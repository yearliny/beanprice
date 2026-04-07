"""A source fetching stock prices from East Money (东方财富).

East Money supports A-shares (Shanghai/Shenzhen) and Hong Kong stocks.
This script fetches daily closing prices via the East Money kline API.

The API, as far as I know, is undocumented.

Ticker format:
  - 6-digit code for A-shares: e.g. "600519" (Shanghai), "000858" (Shenzhen)
  - 5-digit code for HK stocks: e.g. "00700"

Prices are denoted in CNY for A-shares and HKD for HK stocks.
Timezone information: the API returns GMT+8 data,
    the function sets timezone to GMT+8 automatically.
"""

import datetime
from decimal import Decimal

import requests

from beanprice import source


TIMEZONE = datetime.timezone(datetime.timedelta(hours=+8), "Asia/Shanghai")

# Market code mapping used by the East Money API.
_MARKET_CODES = {
    "SZ": "0",   # Shenzhen
    "SH": "1",   # Shanghai
    "HK": "116", # Hong Kong
}

_HEADERS = {
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
}


class EastMoneyStockError(ValueError):
    "An error from the East Money stock API."


def _get_market_and_currency(ticker):
    """Determine market code and quote currency from ticker.

    Returns:
        A tuple of (market_code, currency).
    """
    if ticker.isdigit() and len(ticker) == 6:
        if ticker.startswith(("0", "1", "2", "3")):
            return _MARKET_CODES["SZ"], "CNY"
        if ticker.startswith(("5", "6")):
            return _MARKET_CODES["SH"], "CNY"
    if ticker.isdigit() and len(ticker) == 5:
        return _MARKET_CODES["HK"], "HKD"
    raise EastMoneyStockError(f"Unsupported ticker format: {ticker}")


def _parse_kline_data(data):
    """Parse kline data from API response.

    Returns:
        A list of (datetime, Decimal) tuples sorted by date ascending.
    """
    if not data or "data" not in data or not data["data"]:
        return None
    klines = data["data"].get("klines")
    if not klines:
        return None

    result = []
    for kline in klines:
        parts = kline.split(",")
        if len(parts) < 2:
            continue
        try:
            date = datetime.datetime.strptime(
                parts[0], "%Y-%m-%d"
            ).replace(hour=15, tzinfo=TIMEZONE)
            price = Decimal(parts[1])
            result.append((date, price))
        except (ValueError, IndexError):
            continue

    if not result:
        return None
    return sorted(result, key=lambda x: x[0])


def get_price_series(ticker, time_begin, time_end):
    """Fetch stock price series from the East Money API.

    Args:
        ticker: A string, the stock ticker code.
        time_begin: Start of the date range (timezone-aware datetime).
        time_end: End of the date range (timezone-aware datetime).
    Returns:
        A list of (datetime, Decimal) tuples sorted by date ascending.
    """
    base_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    market_code, _ = _get_market_and_currency(ticker)
    secid = f"{market_code}.{ticker}"
    days = (time_end - time_begin).days + 1

    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f53",
        "klt": "101",   # daily
        "fqt": "0",     # unadjusted
        "beg": time_begin.astimezone(TIMEZONE).strftime("%Y%m%d"),
        "end": time_end.astimezone(TIMEZONE).strftime("%Y%m%d"),
        "lmt": str(days),
    }

    response = requests.get(
        base_url, params=params, headers=_HEADERS, timeout=30
    )
    if response.status_code != requests.codes.ok:
        raise EastMoneyStockError(
            f"Invalid response ({response.status_code}): {response.text}"
        )

    data = response.json()
    prices = _parse_kline_data(data)
    if prices is None:
        raise EastMoneyStockError(
            f"No price data for {ticker} between"
            f" {time_begin.date()} and {time_end.date()}"
        )
    return prices


class Source(source.Source):
    "East Money stock price extractor."

    def get_latest_price(self, ticker):
        """See contract in beanprice.source.Source."""
        _, currency = _get_market_and_currency(ticker)
        end_time = datetime.datetime.now(TIMEZONE)
        begin_time = end_time - datetime.timedelta(days=10)
        prices = get_price_series(ticker, begin_time, end_time)
        last = prices[-1]
        return source.SourcePrice(last[1], last[0], currency)

    def get_historical_price(self, ticker, time):
        """See contract in beanprice.source.Source."""
        _, currency = _get_market_and_currency(ticker)
        begin_time = time - datetime.timedelta(days=10)
        prices = get_price_series(ticker, begin_time, time)
        last = prices[-1]
        return source.SourcePrice(last[1], last[0], currency)

    def get_prices_series(self, ticker, time_begin, time_end):
        """See contract in beanprice.source.Source."""
        _, currency = _get_market_and_currency(ticker)
        result = [
            source.SourcePrice(price, date, currency)
            for date, price in get_price_series(ticker, time_begin, time_end)
        ]
        return sorted(result, key=lambda x: x.time)
