"""Historical data loader for backtesting.

This module provides functionality to load historical market data
from various sources (CSV, Parquet, etc.) for backtesting.
"""

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Optional
from src.core.models import OrderBookSnapshot, OrderBookLevel


class HistoricalDataLoader:
    """Load historical market data for backtesting."""

    def __init__(self, data_path: str):
        """Initialize data loader.

        Args:
            data_path: Path to data directory or file
        """
        self.data_path = Path(data_path)

    def load_orderbook_snapshots(
        self, symbol: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> Iterator[OrderBookSnapshot]:
        """Load order book snapshots from CSV.

        Expected CSV format:
        timestamp,bid_price,bid_size,ask_price,ask_size

        Args:
            symbol: Trading symbol
            start_date: Optional start date filter
            end_date: Optional end date filter

        Yields:
            OrderBookSnapshot objects
        """
        data_file = self.data_path / f"{symbol}_orderbook.csv"
        
        if not data_file.exists():
            raise FileNotFoundError(f"Data file not found: {data_file}")

        with open(data_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    timestamp = datetime.fromisoformat(row["timestamp"])
                    
                    # Apply date filters
                    if start_date and timestamp < start_date:
                        continue
                    if end_date and timestamp > end_date:
                        break
                    
                    # Create order book snapshot
                    bids = [OrderBookLevel(
                        price=Decimal(str(row["bid_price"])),
                        quantity=Decimal(str(row["bid_size"])),
                    )]
                    asks = [OrderBookLevel(
                        price=Decimal(str(row["ask_price"])),
                        quantity=Decimal(str(row["ask_size"])),
                    )]
                    
                    snapshot = OrderBookSnapshot(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=timestamp,
                    )
                    
                    yield snapshot
                except (KeyError, ValueError) as e:
                    # Skip invalid rows
                    continue

    def load_trades(
        self, symbol: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> Iterator[dict]:
        """Load trade data from CSV.

        Expected CSV format:
        timestamp,price,quantity,side

        Args:
            symbol: Trading symbol
            start_date: Optional start date filter
            end_date: Optional end date filter

        Yields:
            Trade dictionaries
        """
        data_file = self.data_path / f"{symbol}_trades.csv"
        
        if not data_file.exists():
            return  # No trades file, that's OK

        with open(data_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    timestamp = datetime.fromisoformat(row["timestamp"])
                    
                    # Apply date filters
                    if start_date and timestamp < start_date:
                        continue
                    if end_date and timestamp > end_date:
                        break
                    
                    yield {
                        "timestamp": timestamp,
                        "price": Decimal(str(row["price"])),
                        "quantity": Decimal(str(row["quantity"])),
                        "side": row["side"],
                    }
                except (KeyError, ValueError):
                    continue

