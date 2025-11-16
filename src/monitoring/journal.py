"""Trade journaling and session reporting.

Records trades during a session to CSV and generates a final summary.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from src.core.models import Trade, Position


@dataclass
class JournalConfig:
    run_dir: str  # directory to store artifacts


class TradeJournal:
    def __init__(self, config: JournalConfig, initial_equity: Decimal) -> None:
        self.config = config
        self.initial_equity = initial_equity
        os.makedirs(self.config.run_dir, exist_ok=True)
        self.trades_csv = os.path.join(self.config.run_dir, "trades.csv")
        self.state_json = os.path.join(self.config.run_dir, "state.json")
        self.summary_md = os.path.join(self.config.run_dir, "summary.md")
        self._last_trade_ids: set[str] = set()
        self._init_csv()
        self._save_state({"initial_equity": str(self.initial_equity), "started_at": datetime.utcnow().isoformat()})

    def _init_csv(self) -> None:
        if not os.path.exists(self.trades_csv):
            with open(self.trades_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "trade_id", "order_id", "symbol", "side", "price", "quantity", "fee", "is_maker"])

    def _save_state(self, state: Dict) -> None:
        try:
            with open(self.state_json, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def append_new_trades(self, trades: List[Trade]) -> int:
        """Append only previously unseen trades to CSV."""
        new_count = 0
        with open(self.trades_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for t in trades:
                tid = getattr(t, "trade_id", "") or getattr(t, "id", "")
                if not tid:
                    # derive id from order+ts
                    tid = f"{t.order_id}-{t.timestamp.isoformat()}"
                if tid in self._last_trade_ids:
                    continue
                self._last_trade_ids.add(tid)
                writer.writerow([
                    t.timestamp.isoformat(),
                    tid,
                    t.order_id,
                    t.symbol,
                    t.side if isinstance(t.side, str) else getattr(t.side, "value", str(t.side)),
                    str(t.price),
                    str(t.quantity),
                    str(getattr(t, "fee", Decimal("0"))),
                    str(getattr(t, "is_maker", True)),
                ])
                new_count += 1
        return new_count

    def write_summary(
        self,
        positions: List[Position],
        trades: List[Trade],
        equity: Decimal,
        realized_pnl: Decimal,
        unrealized_pnl: Decimal,
    ) -> None:
        """Write a human-readable session summary."""
        per_symbol: Dict[str, Dict[str, Decimal]] = {}
        for t in trades:
            sym = t.symbol
            if sym not in per_symbol:
                per_symbol[sym] = {
                    "buys": Decimal("0"),
                    "sells": Decimal("0"),
                    "buy_qty": Decimal("0"),
                    "sell_qty": Decimal("0"),
                }
            if (t.side if isinstance(t.side, str) else getattr(t.side, "value", str(t.side))) == "BUY":
                per_symbol[sym]["buys"] += t.price * t.quantity
                per_symbol[sym]["buy_qty"] += t.quantity
            else:
                per_symbol[sym]["sells"] += t.price * t.quantity
                per_symbol[sym]["sell_qty"] += t.quantity

        lines: List[str] = []
        lines.append(f"# Session Summary\n")
        lines.append(f"- Start equity: {self.initial_equity} USDT")
        lines.append(f"- End equity: {equity} USDT")
        lines.append(f"- Total PnL: {realized_pnl + unrealized_pnl:+.2f} USDT (realized {realized_pnl:+.2f}, unrealized {unrealized_pnl:+.2f})\n")

        lines.append("## Per-symbol activity\n")
        for sym, agg in per_symbol.items():
            lines.append(f"### {sym}")
            lines.append(f"- Total buys: {agg['buys']:.2f} USDT (qty {agg['buy_qty']})")
            lines.append(f"- Total sells: {agg['sells']:.2f} USDT (qty {agg['sell_qty']})")
        lines.append("")

        lines.append("## Open positions\n")
        if positions:
            for p in positions:
                lines.append(f"- {p.symbol}: qty={p.quantity} entry={p.entry_price} mark={p.mark_price} upnl={p.unrealized_pnl:+.2f}")
        else:
            lines.append("- None")

        lines.append("\n## Notes\n- Long/short is implied by trade sides and final positions.\n- Full trade list is available in trades.csv.")

        try:
            with open(self.summary_md, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass


