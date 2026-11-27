"""Arabic Telegram text for paper-trading events and summaries."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading.live.store import StoredFill

_REASONS = {
    "ENTRY_FILLED": "دخول",
    "EXIT_FILLED": "خروج بإشارة",
    "STOP_FILLED": "خروج بوقف الخسارة",
    "TARGET_FILLED": "خروج بالهدف",
}


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def format_fill_alert(item: StoredFill, equity: Decimal) -> str:
    fill = item.fill
    label = _REASONS.get(item.reason, item.reason)
    side = "شراء" if fill.side.value == "BUY" else "بيع"
    return (
        f"📌 صفقة تجريبية: {label}\n"
        f"{fill.instrument} | {side} {fill.quantity:.6f} @ {_money(fill.price)}\n"
        f"الرسوم: {_money(fill.fee)} | قيمة المحفظة: {_money(equity)} USDT\n"
        "محاكاة فقط، لا توجد أوامر حقيقية."
    )


def format_summary(summary: dict[str, Any], initial_cash: Decimal) -> str:
    latest = summary.get("latest")
    if not latest:
        return (
            "💼 المحفظة التجريبية\n"
            f"رأس المال الافتراضي: {_money(initial_cash)} USDT\n"
            "لسه مفيش صفقات ولا قياسات مسجلة. اللوب بيستنى أول شمعة جديدة، "
            "ولازم تضغط «▶️ السماح بالدخول» عشان يفتح صفقات تجريبية."
        )
    equity: Decimal = latest["equity"]
    change = (equity - initial_cash) / initial_cash * Decimal("100")
    peak: Decimal = summary.get("peak_equity") or equity
    drawdown = (peak - equity) / peak * Decimal("100") if peak > 0 else Decimal("0")
    lines = [
        "💼 المحفظة التجريبية (محاكاة)",
        f"القيمة: {_money(equity)} USDT ({change:+.2f}%)",
        f"الكاش: {_money(latest['cash'])} | مربح محقق: {_money(latest['realized_pnl'])}"
        f" | غير محقق: {_money(latest['unrealized_pnl'])}",
        f"الرسوم: {_money(latest['total_fees'])} | أقصى تراجع من القمة: {drawdown:.2f}%",
        f"عدد التنفيذات: {summary['fill_count']}",
        "مراكز مفتوحة: " + (", ".join(summary["open_symbols"]) or "لا يوجد"),
    ]
    recent = summary.get("recent_fills") or []
    if recent:
        lines.append("\nآخر التنفيذات:")
        for row in recent:
            side = "شراء" if row["side"] == "BUY" else "بيع"
            lines.append(
                f"• {row['symbol']} {side} {row['quantity']:.6f} @ {_money(row['price'])}"
                f" ({_REASONS.get(row['reason'], row['reason'])})"
            )
    return "\n".join(lines)
