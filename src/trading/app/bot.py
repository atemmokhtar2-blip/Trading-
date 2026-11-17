from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from trading.app.config import Settings
from trading.app.database import Database
from trading.research.binance_account import (
    BinanceAccountError,
    BinanceReadOnlyAccountClient,
)
from trading.research.binance_public import BinanceDataError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 حالة النظام"), KeyboardButton(text="💼 المحفظة التجريبية")],
        [KeyboardButton(text="🏦 حساب Binance")],
        [KeyboardButton(text="⏸ إيقاف الدخول"), KeyboardButton(text="▶️ السماح بالدخول")],
    ], resize_keyboard=True,
)


def build_dispatcher(db: Database, settings: Settings) -> Dispatcher:
    dp = Dispatcher()

    def is_admin(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id == settings.admin_telegram_id)

    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        if not message.from_user:
            return
        await db.register_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
        await message.answer(
            "أهلاً بيك في بوت التداول التجريبي 📈\n\n"
            "الوضع الحالي محاكاة فقط؛ لا توجد أوامر شراء أو بيع حقيقية.\n"
            "إدارة المخاطر تظل مستقلة عن أي تحليل أو توصيات.",
            reply_markup=MENU if is_admin(message) else None,
        )

    @dp.message(F.text == "📊 حالة النظام")
    async def status(message: Message) -> None:
        if not is_admin(message):
            return
        data = await db.dashboard()
        paused = data.get("entries_paused", True)
        heartbeat = data.get("worker_heartbeat")
        worker = heartbeat.strftime("%Y-%m-%d %H:%M UTC") if heartbeat else "لم يبدأ بعد"
        await message.answer(
            f"📊 حالة النظام\nالوضع: PAPER فقط\nالدخول: {'متوقف' if paused else 'مسموح تجريبياً'}\n"
            f"المستخدمون: {data.get('users', 0)}\nعمليات اليوم: {data.get('events_today', 0)}\n"
            f"آخر نبضة Worker: {worker}"
        )

    @dp.message(F.text == "💼 المحفظة التجريبية")
    async def portfolio(message: Message) -> None:
        if is_admin(message):
            await message.answer(
                "المحفظة الافتراضية ستظهر هنا بعد ربط سجل التنفيذ الدائم. "
                "لا يتم احتساب أرباح قبل وجود صفقات محاكاة مسجلة."
            )


    @dp.message(F.text == "🏦 حساب Binance")
    async def binance_account(message: Message) -> None:
        if not is_admin(message):
            return
        if not settings.binance_api_key or not settings.binance_api_secret:
            await message.answer(
                "🔐 ربط حساب Binance غير مكتمل. أضف BINANCE_API_KEY و"
                "BINANCE_API_SECRET في Railway Variables بصلاحية Read Only فقط."
            )
            return
        client = BinanceReadOnlyAccountClient(
            settings.binance_api_key, settings.binance_api_secret
        )
        try:
            snapshot = await asyncio.to_thread(client.account_snapshot)
        except BinanceAccountError as exc:
            logger.warning(
                "Binance account read failed stage=%s category=%s code=%s "
                "host=%s exception=%s reason_type=%s errno=%s http_status=%s elapsed_ms=%s",
                exc.stage,
                exc.category,
                exc.code,
                exc.host,
                exc.exception_type,
                exc.reason_type,
                exc.errno,
                exc.http_status,
                exc.elapsed_ms,
            )
            await message.answer(
                "❌ فشل الاتصال بحساب Binance\n\n"
                f"السبب: {exc.user_message}\n"
                f"كود التشخيص: {exc.code if exc.code is not None else 'غير متاح'}\n\n"
                "🔐 لم يتم عرض أو تسجيل أي مفتاح أو Secret."
            )
            return
        except (BinanceDataError, ValueError) as exc:
            logger.warning(
                "Binance account read failed: category=unexpected error=%s",
                type(exc).__name__,
            )
            await message.answer(
                "⚠️ حدث خطأ غير متوقع أثناء قراءة حساب Binance. "
                "راجع سجلات Railway وأرسل وقت المحاولة للدعم."
            )
            return
        nonzero = [
            item for item in snapshot.balances
            if item.free != Decimal("0") or item.locked != Decimal("0")
        ]
        if not nonzero:
            balances_text = "لا توجد أرصدة ظاهرة في حساب Spot."
        else:
            balances_text = "\n".join(
                f"• {item.asset}: متاح {item.free:f} | محجوز {item.locked:f}"
                for item in nonzero[:30]
            )
        await message.answer(
            "🏦 قراءة حساب Binance (Read Only)\n"
            "هذه بيانات الحساب الحقيقي وليست رأس مال المحفظة التجريبية.\n\n"
            f"{balances_text}\n\n"
            "🔒 لا توجد أوامر تداول أو سحب مفعّلة في هذا النظام."
        )

    @dp.message(F.text == "⏸ إيقاف الدخول")
    async def pause(message: Message) -> None:
        if not is_admin(message) or not message.from_user:
            return
        await db.set_paused(True, message.from_user.id)
        await message.answer(
            "⏸ تم إيقاف فتح صفقات جديدة. "
            "يظل الخروج وإدارة المراكز متاحين داخل المحاكاة."
        )

    @dp.message(F.text == "▶️ السماح بالدخول")
    async def resume(message: Message) -> None:
        if not is_admin(message) or not message.from_user:
            return
        await db.set_paused(False, message.from_user.id)
        await message.answer("▶️ تم السماح بإشارات دخول تجريبية فقط. لا يوجد تداول حقيقي.")

    @dp.message()
    async def fallback(message: Message) -> None:
        if is_admin(message):
            await message.answer(
                "استخدم أزرار القائمة للتحكم في الوضع التجريبي.", reply_markup=MENU
            )

    return dp


async def main() -> None:
    settings = Settings.from_env(require_telegram=True)
    assert settings.telegram_bot_token is not None
    assert settings.admin_telegram_id is not None
    db = await Database.connect(settings.database_url)
    bot = Bot(token=settings.telegram_bot_token)
    dp = build_dispatcher(db, settings)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
