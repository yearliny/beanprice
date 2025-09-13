"""
A source fetching stock prices from EastMoney (东方财富)
which is a chinese securities company.

EastMoney supports stock prices for A-shares, B-shares, and other Chinese stocks.
This script fetches historical stock prices from the EastMoney API.

The API, as far as I know, is undocumented.

Prices are denoted in CNY.
Timezone information: the http API requests GMT+8,
    the function transfers timezone to GMT+8 automatically
"""

import datetime
import json
from decimal import Decimal

import requests

from beanprice import source

CURRENCY = "CNY"

TIMEZONE = datetime.timezone(datetime.timedelta(hours=+8), "Asia/Shanghai")

headers = {
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0"
}

market_mapping = {
    'SZ': '0',  # Shenzhen
    'SH': '1',  # Shanghai
    'HK': '116',  # Hong Kong
}


class EastMoneyQuotaError(ValueError):
    "An error from the EastMoney API."


def get_market_code(ticker: str) -> str:
    """Determine market code based on ticker prefix."""
    if ticker.isdigit() and len(ticker) == 6:
        if ticker.startswith(('0', '1', '2', '3')):
            return market_mapping['SZ']  # Shenzhen
        elif ticker.startswith('6'):
            return market_mapping['SH']  # Shanghai
    elif ticker.isdigit() and len(ticker) == 5:
        return market_mapping['HK']  # Hong Kong
    else:
        raise EastMoneyQuotaError(f"Unsupported ticker format: {ticker}")


def parse_kline_data(data: dict) -> list:
    """Parse kline data from API response."""
    if not data or 'data' not in data or 'klines' not in data['data']:
        raise EastMoneyQuotaError("Invalid API response format")

    klines = data['data']['klines']
    if not klines:
        raise EastMoneyQuotaError("No price data found")

    result = []
    for kline in klines:
        try:
            date_str, close_price = kline.split(',')
            date = datetime.datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=TIMEZONE)
            price = Decimal(close_price)
            result.append((date, price))
        except (ValueError, IndexError):
            continue

    if not result:
        raise EastMoneyQuotaError("No valid price data found")

    return sorted(result, key=lambda x: x[0])


def get_price_series(
    ticker: str, time_begin: datetime.datetime, time_end: datetime.datetime
):
    """Fetch stock price series from EastMoney API."""
    base_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    market_code = get_market_code(ticker)
    secid = f"{market_code}.{ticker}"

    # Calculate the number of days to fetch
    days = (time_end - time_begin).days + 1

    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f53',
        'klt': '101',  # Daily line
        'fqt': '0',  # No adjustment
        'beg': time_begin.strftime('%Y%m%d'),
        'end': time_end.strftime('%Y%m%d'),
        'lmt': str(days),
    }

    try:
        response = requests.get(base_url, params=params, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get('rc') != 0:
            raise EastMoneyQuotaError(f"API error: {data.get('rt', 'Unknown error')}")

        prices = parse_kline_data(data)
        if not prices:
            raise EastMoneyQuotaError(
                f"No price data found for {ticker} between {time_begin.date()} and {time_end.date()}"
            )

        return prices
    except requests.RequestException as e:
        raise EastMoneyQuotaError(f"Network error: {e}")
    except (json.JSONDecodeError, ValueError) as e:
        raise EastMoneyQuotaError(f"Invalid JSON response: {e}")


def generate_secid(ticker: str) -> str:
    """Generate secid from ticker with optional market prefix.

    Supports market prefixes:
    - HK. for Hong Kong stocks (e.g., HK.00700)
    - SZ. for Shenzhen stocks (e.g., SZ.000651)
    - SH. for Shanghai stocks (e.g., SH.600519)

    If no prefix provided, auto-detect market based on ticker code.

    Args:
        ticker: Stock ticker symbol with optional market prefix

    Returns:
        secid string in format "market_code.ticker"

    Raises:
        EastMoneyQuotaError: For invalid ticker format or unsupported market
    """
    # Handle market prefixes
    if '.' in ticker:
        prefix, code = ticker.split('.', 1)
        prefix = prefix.upper()
        if prefix not in market_mapping:
            raise EastMoneyQuotaError(f"Unsupported market prefix: {prefix}")

        market_code = market_mapping[prefix]
        return f"{market_code}.{code}"

    # Auto-detect market based on ticker code
    return f"{get_market_code(ticker)}.{ticker}"


class Source(source.Source):
    def get_latest_price(self, ticker):
        """Get the latest price for a stock."""
        end_time = datetime.datetime.now(TIMEZONE)
        begin_time = end_time - datetime.timedelta(days=10)  # Reduce days to avoid filtering out all data

        prices = get_price_series(ticker, begin_time, end_time)
        if not prices:
            raise EastMoneyQuotaError(f"No price data found for {ticker}")

        # Return the most recent price
        latest_price = prices[-1]
        return source.SourcePrice(latest_price[1], latest_price[0], CURRENCY)

    def get_historical_price(self, ticker, time):
        """Get historical price for a stock on a specific date."""
        # Get prices for the specific date and a few days around it
        begin_time = time - datetime.timedelta(days=10)
        end_time = time + datetime.timedelta(days=10)

        prices = get_price_series(ticker, begin_time, end_time)
        if not prices:
            raise EastMoneyQuotaError(f"No price data found for {ticker} on {time.date()}")

        # Find the closest price to the requested date
        closest_price = min(prices, key=lambda x: abs((x[0] - time).total_seconds()))
        return source.SourcePrice(closest_price[1], closest_price[0], CURRENCY)

    def get_prices_series(self, ticker, time_begin, time_end):
        """Get price series for a stock within a date range."""
        prices = get_price_series(ticker, time_begin, time_end)
        return [
            source.SourcePrice(price, date, CURRENCY)
            for date, price in prices
        ]
