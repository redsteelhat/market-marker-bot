import logging
from typing import Optional

from rich.logging import RichHandler


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(symbol)s | %(name)s | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


class SymbolFilter(logging.Filter):
    """Ensures %(symbol)s is always present in log records to avoid KeyError in format."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "symbol"):
            record.symbol = "-"  # default when symbol context is unknown
        return True


def setup_logging(level: int = logging.INFO, rich_tracebacks: bool = True) -> None:
    """Initialize rich-based logging with a safe format that includes symbol field."""
    handler = RichHandler(rich_tracebacks=rich_tracebacks, markup=True)
    handler.addFilter(SymbolFilter())

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FMT,
        handlers=[handler],
    )


