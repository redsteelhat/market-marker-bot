"""Download historical market data from Binance for backtesting.

This script downloads klines (OHLCV) data from Binance and converts it
to orderbook snapshot format for backtesting.

Usage:
    python scripts/download_backtest_data.py --symbol BTCUSDT --start-date 2024-01-01 --end-date 2024-01-07
    python scripts/download_backtest_data.py --symbol BTCUSDT --start-date 2024-01-01 --end-date 2024-01-07 --interval 1m
"""

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import httpx
import time

# Binance Futures public API (no API key required)
BASE_URL = "https://fapi.binance.com"


def timestamp_to_datetime(ts: int) -> datetime:
    """Convert Unix timestamp (ms) to datetime."""
    return datetime.fromtimestamp(ts / 1000.0)


def datetime_to_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp (ms)."""
    return int(dt.timestamp() * 1000)


def fetch_klines(
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    limit: int = 1000,
) -> list:
    """Fetch klines from Binance Futures API.
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        interval: Kline interval (1m, 5m, 1h, etc.)
        start_time: Start timestamp (ms)
        end_time: End timestamp (ms)
        limit: Maximum number of klines per request (max 1000)
    
    Returns:
        List of kline arrays
    """
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_time,
        "endTime": end_time,
        "limit": limit,
    }
    
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def kline_to_orderbook_snapshot(kline: list, symbol: str) -> dict:
    """Convert a kline to orderbook snapshot format.
    
    Binance kline format:
    [
        open_time,      # 0
        open,           # 1
        high,           # 2
        low,            # 3
        close,          # 4
        volume,         # 5
        close_time,     # 6
        quote_volume,   # 7
        trades,         # 8
        taker_buy_base, # 9
        taker_buy_quote,# 10
        ignore          # 11
    ]
    
    We use OHLC to estimate bid/ask:
    - bid_price = low (conservative)
    - ask_price = high (conservative)
    - Or use mid = (open + close) / 2, spread = (high - low)
    
    For orderbook format, we'll use:
    - mid_price = (open + close) / 2
    - spread = (high - low) / mid_price
    - bid_price = mid_price - (spread / 2)
    - ask_price = mid_price + (spread / 2)
    - bid_size = volume * 0.5 (estimate)
    - ask_size = volume * 0.5 (estimate)
    """
    open_time = int(kline[0])
    open_price = float(kline[1])
    high_price = float(kline[2])
    low_price = float(kline[3])
    close_price = float(kline[4])
    volume = float(kline[5])
    
    # Calculate mid price and spread
    mid_price = (open_price + close_price) / 2.0
    spread = high_price - low_price
    
    # Estimate bid/ask from OHLC
    # Use low as bid, high as ask (conservative)
    bid_price = low_price
    ask_price = high_price
    
    # Or use mid ± spread/2
    # bid_price = mid_price - (spread / 2.0)
    # ask_price = mid_price + (spread / 2.0)
    
    # Estimate sizes (50/50 split, or use taker buy ratio if available)
    bid_size = volume * 0.5
    ask_size = volume * 0.5
    
    return {
        "timestamp": timestamp_to_datetime(open_time).isoformat(),
        "bid_price": f"{bid_price:.8f}",
        "bid_size": f"{bid_size:.8f}",
        "ask_price": f"{ask_price:.8f}",
        "ask_size": f"{ask_size:.8f}",
    }


def download_data(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    interval: str = "1m",
    output_dir: str = "data/backtest",
) -> Path:
    """Download historical data and save to CSV.
    
    Args:
        symbol: Trading symbol
        start_date: Start date
        end_date: End date
        interval: Kline interval (1m, 5m, 1h, etc.)
        output_dir: Output directory
    
    Returns:
        Path to output CSV file
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    output_file = output_path / f"{symbol}_orderbook.csv"
    
    start_ts = datetime_to_timestamp(start_date)
    end_ts = datetime_to_timestamp(end_date)
    
    print(f"Downloading {symbol} data from {start_date.date()} to {end_date.date()}")
    print(f"Interval: {interval}")
    print(f"Output: {output_file}")
    
    all_snapshots = []
    current_start = start_ts
    batch_count = 0
    
    while current_start < end_ts:
        batch_count += 1
        current_end = min(current_start + (1000 * 60 * 1000), end_ts)  # 1000 minutes max per request
        
        print(f"Fetching batch {batch_count}... ({timestamp_to_datetime(current_start).strftime('%Y-%m-%d %H:%M')} to {timestamp_to_datetime(current_end).strftime('%Y-%m-%d %H:%M')})")
        
        try:
            klines = fetch_klines(symbol, interval, current_start, current_end)
            
            if not klines:
                print("  No data returned, moving to next batch")
                current_start = current_end + 1
                continue
            
            # Convert to orderbook snapshots
            for kline in klines:
                snapshot = kline_to_orderbook_snapshot(kline, symbol)
                all_snapshots.append(snapshot)
            
            # Update start time to last kline's close time + 1
            last_close_time = int(klines[-1][6])  # close_time
            current_start = last_close_time + 1
            
            # Rate limiting (Binance allows 1200 requests per minute)
            time.sleep(0.1)
            
        except Exception as e:
            print(f"  Error fetching batch: {e}")
            # Skip this batch and continue
            current_start = current_end + 1
            continue
    
    # Write to CSV
    print(f"\nWriting {len(all_snapshots)} snapshots to {output_file}...")
    
    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "bid_price", "bid_size", "ask_price", "ask_size"])
        writer.writeheader()
        writer.writerows(all_snapshots)
    
    print(f"✓ Saved {len(all_snapshots)} snapshots to {output_file}")
    
    return output_file


def main():
    parser = argparse.ArgumentParser(description="Download historical market data for backtesting")
    parser.add_argument("--symbol", "-s", required=True, help="Trading symbol (e.g., BTCUSDT)")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", "-i", default="1m", help="Kline interval (1m, 5m, 1h, 1d, etc.)")
    parser.add_argument("--output-dir", "-o", default="data/backtest", help="Output directory")
    
    args = parser.parse_args()
    
    # Parse dates
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    # Add one day to end_date to include the full day
    end_date = end_date + timedelta(days=1)
    
    symbol = args.symbol.upper()
    
    try:
        output_file = download_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=args.interval,
            output_dir=args.output_dir,
        )
        print(f"\n✓ Success! Data saved to: {output_file}")
        print(f"\nTo run backtest:")
        print(f"  python -m src.apps.main run --mode backtest --symbol {symbol}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

