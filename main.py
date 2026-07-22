"""
main.py — точка входа Carcollection bot.
Собирает диспетчер, регистрирует роутеры, инициализирует БД и запускает polling.
Для деплоя на Railway: Procfile должен содержать `worker: python main.py`.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent, BotCommand

from config import BOT_TOKEN, ADMIN_IDS, HEAD_ADMIN_ID, DATABASE_URL
from db import init_db, get_db

from handlers import (
    common, garage, casino, payments, admin, battlepass, duels, auctions, containers, freecar, bonuses, groupcmds,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("carcollection")


def _check_config() -> None:
    """Проверяет, что обязательные переменные окружения заданы, и завершает
    процесс с понятным сообщением, если что-то забыли настроить в Variables."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not ADMIN_IDS:
        missing.append("ADMIN_IDS")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if missing:
        logger.error(
            "Не заданы обязательные переменные окружения: %s. "
            "Локально: задайте их в файле .env (см. .env.example). "
            "На Railway: вкладка сервиса -> Variables.",
            ", ".join(missing),
        )
        raise SystemExit(1)


async def main() -> None:
    _check_config()

    await init_db()
    logger.info("База данных инициализирована.")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать / открыть меню"),
        BotCommand(command="garage", description="🚗 Гараж"),
        BotCommand(command="collect", description="💰 Собрать доход"),
        BotCommand(command="freecar", description="🎁 Бесплатная машина"),
        BotCommand(command="shop", description="🛒 Магазин"),
        BotCommand(command="inventory", description="📦 Инвентарь"),
        BotCommand(command="profile", description="👤 Профиль"),
        BotCommand(command="upgrades", description="⚙️ Улучшения"),
        BotCommand(command="battlepass", description="🎫 Боевой пропуск"),
        BotCommand(command="casino", description="🎰 Казино"),
        BotCommand(command="duels", description="⚔️ Дуэли"),
        BotCommand(command="clan", description="🏛 Клан"),
        BotCommand(command="auction", description="🔨 Аукцион"),
        BotCommand(command="containers", description="📥 Контейнеры"),
        BotCommand(command="bonuses", description="🎁 Бонусы (рефералка/промокоды)"),
        BotCommand(command="pay", description="💸 Перевести серебро (ответом на сообщение)"),
    ])
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware: гарантирует, что пользователь существует в БД перед обработкой любого апдейта.
    # /start пропускается здесь намеренно — cmd_start сам вызывает ensure_user с учётом
    # реферальной ссылки (?start=ref_123); если бы middleware регистрировал пользователя
    # первым, реферал никогда бы не сохранялся (пользователь уже существовал бы к этому моменту).
    @dp.message.outer_middleware()
    async def ensure_user_middleware(handler, event, data):
        from db import ensure_user, touch_user_activity
        is_start_command = bool(event.text) and event.text.split()[0].split("@")[0] == "/start"
        if event.from_user and not event.from_user.is_bot and not is_start_command:
            await ensure_user(event.from_user.id, event.from_user.username)
            await touch_user_activity(event.from_user.id)
        return await handler(event, data)

    @dp.callback_query.outer_middleware()
    async def ensure_user_cb_middleware(handler, event, data):
        from db import ensure_user, touch_user_activity
        if event.from_user and not event.from_user.is_bot:
            await ensure_user(event.from_user.id, event.from_user.username)
            await touch_user_activity(event.from_user.id)
        return await handler(event, data)

    # Middleware обязательной подписки: если в /admin настроены каналы/группы,
    # блокирует любое действие в личке для тех, кто на них не подписан (кроме /start
    # и самой кнопки проверки), и просит подписаться. От проверки освобождён ТОЛЬКО
    # главный админ (HEAD_ADMIN_ID) — чтобы не заблокировать себе доступ к /admin и
    # возможность всё убрать; обычные админы подписываться обязаны наравне со всеми.
    @dp.message.outer_middleware()
    async def fsub_middleware(handler, event, data):
        from db import get_not_subscribed_channels
        from keyboards import fsub_check_kb
        is_start_command = bool(event.text) and event.text.split()[0].split("@")[0] == "/start"
        if (event.from_user and not event.from_user.is_bot and not is_start_command
                and event.chat.type == "private" and event.from_user.id != HEAD_ADMIN_ID):
            not_subscribed = await get_not_subscribed_channels(bot, event.from_user.id)
            if not_subscribed:
                await event.answer(
                    "🔔 Чтобы пользоваться ботом, подпишитесь на каналы/группы ниже, "
                    "затем нажмите «✅ Я подписался»:",
                    reply_markup=fsub_check_kb(not_subscribed),
                )
                return
        return await handler(event, data)

    @dp.callback_query.outer_middleware()
    async def fsub_cb_middleware(handler, event, data):
        from db import get_not_subscribed_channels
        from keyboards import fsub_check_kb
        if (event.data != "fsub:check" and event.from_user and not event.from_user.is_bot
                and event.message and event.message.chat.type == "private"
                and event.from_user.id != HEAD_ADMIN_ID):
            not_subscribed = await get_not_subscribed_channels(bot, event.from_user.id)
            if not_subscribed:
                await event.answer("🔔 Сначала подпишитесь на обязательные каналы/группы", show_alert=True)
                try:
                    await event.message.answer(
                        "🔔 Чтобы пользоваться ботом, подпишитесь на каналы/группы ниже, "
                        "затем нажмите «✅ Я подписался»:",
                        reply_markup=fsub_check_kb(not_subscribed),
                    )
                except Exception:
                    pass
                return
        return await handler(event, data)

    # Порядок регистрации роутеров важен: более специфичные FSM-хендлеры — раньше.
    dp.include_router(admin.router)
    dp.include_router(payments.router)
    dp.include_router(common.router)
    dp.include_router(garage.router)
    dp.include_router(battlepass.router)
    dp.include_router(casino.router)
    dp.include_router(duels.router)
    dp.include_router(auctions.router)
    dp.include_router(containers.router)
    dp.include_router(freecar.router)
    dp.include_router(bonuses.router)
    dp.include_router(groupcmds.router)  # ВАЖНО: должен быть последним (см. docstring файла)

    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        """Ловит любые необработанные исключения в хендлерах: пишет полный traceback в
        логи (для диагностики) и показывает пользователю понятное сообщение вместо
        полной тишины — раньше упавший хендлер выглядел как «кнопка не работает»."""
        logger.exception("Необработанная ошибка при обработке апдейта %s", event.update.update_id,
                          exc_info=event.exception)
        try:
            if event.update.message:
                await event.update.message.answer("⚠️ Произошла ошибка. Попробуйте ещё раз или напишите /start.")
            elif event.update.callback_query:
                await event.update.callback_query.answer(
                    "⚠️ Произошла ошибка. Попробуйте ещё раз.", show_alert=True
                )
        except Exception:
            pass
        return True

    logger.info("Запуск polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
