import datetime
import unittest
from decimal import Decimal

from unittest import mock
from dateutil import tz

import requests

from beanprice.sources import eastmoneyquota
from beanprice import source


# 测试用的股票数据
STOCK_RESPONSE = {
    "rc": 0,
    "rt": 17,
    "svr": 177617938,
    "lt": 1,
    "full": 0,
    "dlmkts": "",
    "data": {
        "code": "000651",
        "market": 0,
        "name": "格力电器",
        "decimal": 2,
        "dktotal": 6768,
        "preKPrice": 41.34,
        "klines": [
            "2024-12-20,41.16",
            "2024-12-19,41.37",
            "2024-12-18,41.05",
            "2024-12-17,40.89",
            "2024-12-16,41.23",
            "2024-12-13,40.98",
            "2024-12-12,40.75",
            "2024-12-11,40.62",
            "2024-12-10,40.45",
            "2024-12-09,40.33"
        ]
    }
}

EMPTY_RESPONSE = {
    "rc": 0,
    "rt": 17,
    "svr": 177617938,
    "lt": 1,
    "full": 0,
    "dlmkts": "",
    "data": {
        "code": "000651",
        "market": 0,
        "name": "格力电器",
        "decimal": 2,
        "dktotal": 0,
        "preKPrice": 41.34,
        "klines": []
    }
}

ERROR_RESPONSE = {
    "rc": 1,
    "rt": "参数错误",
    "svr": 177617938,
    "lt": 1,
    "full": 0,
    "dlmkts": ""
}


def response_json(data, status_code=requests.codes.ok):
    """Return a context manager to patch a JSON response."""
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = data
    response.raise_for_status = mock.Mock()
    return mock.patch("requests.get", return_value=response)


class EastMoneyQuotaFetcher(unittest.TestCase):

    def test_get_market_code_shenzhen(self):
        """Test market code detection for Shenzhen stocks."""
        self.assertEqual(eastmoneyquota.get_market_code("000651"), "0")
        self.assertEqual(eastmoneyquota.get_market_code("002415"), "0")
        self.assertEqual(eastmoneyquota.get_market_code("300750"), "0")

    def test_get_market_code_shanghai(self):
        """Test market code detection for Shanghai stocks."""
        self.assertEqual(eastmoneyquota.get_market_code("600519"), "1")
        self.assertEqual(eastmoneyquota.get_market_code("601318"), "1")
        self.assertEqual(eastmoneyquota.get_market_code("688981"), "1")

    def test_get_market_code_hongkong(self):
        """Test market code detection for Hong Kong stocks."""
        self.assertEqual(eastmoneyquota.get_market_code("00700"), "116")

    def test_get_market_code_invalid(self):
        """Test market code detection for invalid tickers."""
        with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
            eastmoneyquota.get_market_code("ABC123")

    def test_parse_kline_data(self):
        """Test parsing kline data from API response."""
        result = eastmoneyquota.parse_kline_data(STOCK_RESPONSE)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 10)

        # Check first entry
        date, price = result[0]
        self.assertEqual(date.date(), datetime.date(2024, 12, 9))
        self.assertEqual(price, Decimal("40.33"))

        # Check last entry
        date, price = result[-1]
        self.assertEqual(date.date(), datetime.date(2024, 12, 20))
        self.assertEqual(price, Decimal("41.16"))

    def test_parse_kline_data_empty(self):
        """Test parsing empty kline data."""
        with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
            eastmoneyquota.parse_kline_data(EMPTY_RESPONSE)

    def test_parse_kline_data_invalid(self):
        """Test parsing invalid kline data."""
        with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
            eastmoneyquota.parse_kline_data(None)

    def test_error_network(self):
        """Test network error handling."""
        with mock.patch("requests.get", side_effect=requests.RequestException("Network error")):
            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError) as exc:
                eastmoneyquota.get_price_series(
                    "000651", datetime.datetime.now(), datetime.datetime.now()
                )
            self.assertIn("Network error", str(exc.exception))

    def test_error_invalid_json(self):
        """Test JSON parsing error handling."""
        response = mock.Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("Invalid JSON")

        with mock.patch("requests.get", return_value=response):
            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError) as exc:
                eastmoneyquota.get_price_series(
                    "000651", datetime.datetime.now(), datetime.datetime.now()
                )
            self.assertIn("Invalid JSON", str(exc.exception))

    def test_error_api_response(self):
        """Test API error response handling."""
        with response_json(ERROR_RESPONSE):
            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError) as exc:
                eastmoneyquota.get_price_series(
                    "000651", datetime.datetime.now(), datetime.datetime.now()
                )
            self.assertIn("API error", str(exc.exception))

    def test_error_empty_data(self):
        """Test empty data handling."""
        with response_json(EMPTY_RESPONSE):
            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError) as exc:
                eastmoneyquota.get_price_series(
                    "000651", datetime.datetime.now(), datetime.datetime.now()
                )
            self.assertIn("No price data found", str(exc.exception))

    def test_latest_price(self):
        """Test getting latest price."""
        with response_json(STOCK_RESPONSE):
            srcprice = eastmoneyquota.Source().get_latest_price("000651")
            self.assertIsInstance(srcprice, source.SourcePrice)
            self.assertEqual(Decimal("41.16"), srcprice.price)
            self.assertEqual("CNY", srcprice.quote_currency)
            self.assertEqual(
                datetime.datetime(2024, 12, 20, 0, 0, 0, tzinfo=eastmoneyquota.TIMEZONE),
                srcprice.time,
            )

    def test_latest_price_no_data(self):
        """Test getting latest price with no data."""
        with response_json(EMPTY_RESPONSE):
            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
                eastmoneyquota.Source().get_latest_price("000651")

    def test_historical_price(self):
        """Test getting historical price."""
        with response_json(STOCK_RESPONSE):
            target_date = datetime.datetime(2024, 12, 19, 0, 0, 0, tzinfo=datetime.timezone.utc)
            srcprice = eastmoneyquota.Source().get_historical_price("000651", target_date)
            self.assertIsInstance(srcprice, source.SourcePrice)
            self.assertEqual(Decimal("41.37"), srcprice.price)  # 2024-12-19的价格
            self.assertEqual("CNY", srcprice.quote_currency)

    def test_historical_price_no_data(self):
        """Test getting historical price with no data."""
        with response_json(EMPTY_RESPONSE):
            target_date = datetime.datetime(2024, 12, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)
            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
                eastmoneyquota.Source().get_historical_price("000651", target_date)

    def test_get_prices_series(self):
        """Test getting price series."""
        with response_json(STOCK_RESPONSE):
            begin_time = datetime.datetime(2024, 12, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
            end_time = datetime.datetime(2024, 12, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)

            srcprices = eastmoneyquota.Source().get_prices_series("000651", begin_time, end_time)
            self.assertIsInstance(srcprices, list)
            self.assertEqual(len(srcprices), 10)

            # Check first price
            self.assertIsInstance(srcprices[0], source.SourcePrice)
            self.assertEqual(Decimal("40.33"), srcprices[0].price)
            self.assertEqual("CNY", srcprices[0].quote_currency)

            # Check last price
            self.assertIsInstance(srcprices[-1], source.SourcePrice)
            self.assertEqual(Decimal("41.16"), srcprices[-1].price)
            self.assertEqual("CNY", srcprices[-1].quote_currency)

    def test_get_prices_series_empty(self):
        """Test getting empty price series."""
        with response_json(EMPTY_RESPONSE):
            begin_time = datetime.datetime(2024, 12, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
            end_time = datetime.datetime(2024, 12, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)

            with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
                eastmoneyquota.Source().get_prices_series("000651", begin_time, end_time)

    def test_timezone_handling(self):
        """Test timezone handling in price data."""
        with response_json(STOCK_RESPONSE):
            # Test with UTC timezone
            utc_time = datetime.datetime(2024, 12, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)
            srcprice = eastmoneyquota.Source().get_historical_price("000651", utc_time)
            self.assertEqual(srcprice.time.tzinfo, eastmoneyquota.TIMEZONE)


    def test_generate_secid_with_prefix(self):
        """Test generate_secid with market prefixes."""
        # Test Hong Kong
        self.assertEqual(eastmoneyquota.generate_secid("HK.00700"), "116.00700")
        self.assertEqual(eastmoneyquota.generate_secid("hk.00700"), "116.00700")

        # Test Shenzhen
        self.assertEqual(eastmoneyquota.generate_secid("SZ.000651"), "0.000651")
        self.assertEqual(eastmoneyquota.generate_secid("sz.000651"), "0.000651")

        # Test Shanghai
        self.assertEqual(eastmoneyquota.generate_secid("SH.600519"), "1.600519")

    def test_generate_secid_auto_detect(self):
        """Test generate_secid auto-detection without prefix."""
        # Test auto-detection
        self.assertEqual(eastmoneyquota.generate_secid("000651"), "0.000651")  # Shenzhen
        self.assertEqual(eastmoneyquota.generate_secid("600519"), "1.600519")  # Shanghai
        self.assertEqual(eastmoneyquota.generate_secid("002415"), "0.002415")  # Shenzhen
        self.assertEqual(eastmoneyquota.generate_secid("300750"), "0.300750")  # Shenzhen

    def test_generate_secid_invalid_prefix(self):
        """Test generate_secid with invalid market prefix."""
        with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
            eastmoneyquota.generate_secid("US.AAPL")

        with self.assertRaises(eastmoneyquota.EastMoneyQuotaError):
            eastmoneyquota.generate_secid("INVALID.123456")


if __name__ == "__main__":
    unittest.main()
