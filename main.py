"""
main.py — точка входа Carcollection bot.
Собирает диспетчер, регистрирует роутеры, инициализирует БД и запускает polling.
Для деплоя на Railway: Procfile должен содержать `worker: python main.py`.
"""
import asyncio
import datetime
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
    fusion, lottery,
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


async def _income_notifier_loop(bot: Bot) -> None:
    """Раз в несколько минут проверяет, у кого фарм уже накопился, и шлёт
    напоминание — простой, но эффективный способ поднять активность (DAU),
    возвращая игроков в бота, когда им реально есть что забрать."""
    from handlers.garage import _current_cooldown_seconds
    from aiogram.exceptions import TelegramForbiddenError
    from db import set_user_blocked
    while True:
        try:
            conn = await get_db()
            cur = await conn.execute(
                """SELECT tg_id, last_claim_at, cooldown_reduction, income_notified_at FROM users
                   WHERE last_claim_at IS NOT NULL AND blocked_bot = 0 AND is_banned = 0"""
            )
            rows = await cur.fetchall()
            now = datetime.datetime.utcnow()
            for row in rows:
                try:
                    last_claim = datetime.datetime.fromisoformat(row["last_claim_at"])
                except (ValueError, TypeError):
                    continue
                cooldown = _current_cooldown_seconds(row["cooldown_reduction"])
                if now < last_claim + datetime.timedelta(seconds=cooldown):
                    continue
                notified_at = row["income_notified_at"]
                if notified_at:
                    try:
                        if datetime.datetime.fromisoformat(notified_at) >= last_claim:
                            continue  # уже уведомляли об этом цикле накопления
                    except ValueError:
                        pass
                try:
                    await bot.send_message(
                        row["tg_id"],
                        "💰 Ваш доход с депо накопился и готов к сбору! "
                        "Загляните в «🚂 Депо» → «💰 Собрать».",
                    )
                except TelegramForbiddenError:
                    await set_user_blocked(row["tg_id"], True)
                    continue
                except Exception:
                    pass
                await conn.execute(
                    "UPDATE users SET income_notified_at = ? WHERE tg_id = ?", (now.isoformat(), row["tg_id"])
                )
                await conn.commit()
                await asyncio.sleep(0.05)
        except Exception:
            logging.exception("income notifier loop failed")
        await asyncio.sleep(180)


async def _ad_campaign_loop(bot: Bot) -> None:
    """Раз в минуту проверяет, не пора ли снова разослать рекламный пост по группам,
    выбранным главным админом — интервал полностью автоматический, без ручных действий."""
    from db import get_ad_campaign, get_ad_target_groups, touch_ad_campaign_sent
    while True:
        try:
            campaign = await get_ad_campaign()
            if campaign and campaign["is_active"] and campaign["source_message_id"]:
                now = datetime.datetime.utcnow()
                last_sent = None
                if campaign["last_sent_at"]:
                    try:
                        last_sent = datetime.datetime.fromisoformat(campaign["last_sent_at"])
                    except ValueError:
                        last_sent = None
                interval = datetime.timedelta(minutes=campaign["interval_minutes"] or 60)
                if not last_sent or now >= last_sent + interval:
                    groups = await get_ad_target_groups()
                    sent_this_round = 0
                    for chat_id, title in groups:
                        try:
                            await bot.copy_message(
                                chat_id=chat_id,
                                from_chat_id=campaign["source_chat_id"],
                                message_id=campaign["source_message_id"],
                            )
                            sent_this_round += 1
                        except Exception:
                            pass
                        await asyncio.sleep(0.1)
                    await touch_ad_campaign_sent(sent_this_round)
        except Exception:
            logging.exception("ad campaign loop failed")
        await asyncio.sleep(60)


async def _auction_expiry_loop(bot: Bot) -> None:
    """Раз в минуту закрывает истёкшие лоты аукциона: поезд уходит победителю
    (деньги — продавцу), либо, если ставок не было, возвращается продавцу."""
    from db import get_db, has_garage_space
    while True:
        try:
            conn = await get_db()
            now = datetime.datetime.utcnow()
            cur = await conn.execute(
                "SELECT * FROM auctions WHERE ends_at IS NOT NULL AND ends_at <= ?", (now.isoformat(),)
            )
            expired = await cur.fetchall()
            for lot in expired:
                cur2 = await conn.execute("SELECT name, brand FROM cars WHERE car_id = ?", (lot["car_id"],))
                car = await cur2.fetchone()
                car_label = f"{car['brand']} {car['name']}" if car else "поезд"

                if lot["current_bidder_id"]:
                    winner_id = lot["current_bidder_id"]
                    price = lot["current_bid"]
                    if await has_garage_space(winner_id):
                        await conn.execute(
                            "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
                            (winner_id, lot["car_id"], now.isoformat()),
                        )
                        await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?",
                                            (price, lot["seller_id"]))
                        await conn.commit()
                        try:
                            await bot.send_message(winner_id, f"🏆 Вы выиграли аукцион! {car_label} добавлена в ваше депо.")
                        except Exception:
                            pass
                        try:
                            await bot.send_message(
                                lot["seller_id"],
                                f"💰 Ваш лот #{lot['auction_id']} ({car_label}) продан за {price:,} серебра!".replace(",", " "),
                            )
                        except Exception:
                            pass
                    else:
                        # Депо победителя переполнено — возвращаем деньги, поезд продавцу.
                        await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (price, winner_id))
                        await conn.execute(
                            "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
                            (lot["seller_id"], lot["car_id"], now.isoformat()),
                        )
                        await conn.commit()
                        try:
                            await bot.send_message(
                                winner_id,
                                f"⚠️ Ваше депо переполнено — выигрыш лота #{lot['auction_id']} отменён, деньги возвращены.",
                            )
                        except Exception:
                            pass
                        try:
                            await bot.send_message(
                                lot["seller_id"],
                                f"⚠️ Победитель лота #{lot['auction_id']} не смог принять поезд (депо переполнено) — поезд возвращён вам.",
                            )
                        except Exception:
                            pass
                else:
                    await conn.execute(
                        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
                        (lot["seller_id"], lot["car_id"], now.isoformat()),
                    )
                    await conn.commit()
                    try:
                        await bot.send_message(
                            lot["seller_id"],
                            f"ℹ️ Лот #{lot['auction_id']} ({car_label}) не был продан — ставок не было. "
                            f"Поезд возвращён в депо.",
                        )
                    except Exception:
                        pass

                await conn.execute("DELETE FROM auctions WHERE auction_id = ?", (lot["auction_id"],))
                await conn.commit()
                from handlers.auctions import discard_lot_viewers
                discard_lot_viewers(lot["auction_id"])
        except Exception:
            logging.exception("auction expiry loop failed")
        await asyncio.sleep(60)


async def _lottery_draw_loop(bot: Bot) -> None:
    """Раз в пару минут проверяет, не пора ли провести розыгрыш лотереи (раз в 24ч),
    и объявляет победителя всем игрокам."""
    from db import get_lottery_state, draw_lottery, broadcast_message
    while True:
        try:
            state = await get_lottery_state()
            draws_at = datetime.datetime.fromisoformat(state["draws_at"])
            if datetime.datetime.utcnow() >= draws_at:
                result = await draw_lottery()
                if result:
                    winner_id, prize = result
                    text = (
                        f"🎉 <b>Розыгрыш лотереи завершён!</b>\n"
                        f"Победитель забрал <b>{prize:,} серебра</b>! Поздравляем!\n"
                        f"Новый раунд уже начался — жмите «🎟 Лотерея» в разделе бонусов.".replace(",", " ")
                    )
                    try:
                        await bot.send_message(winner_id, f"🏆 Вы выиграли в лотерее {prize:,} серебра! 🎉".replace(",", " "))
                    except Exception:
                        pass
                    await broadcast_message(bot, text)
        except Exception:
            logging.exception("lottery draw loop failed")
        await asyncio.sleep(120)


async def _lottery_reminder_loop(bot: Bot) -> None:
    """Раз в час напоминает игрокам, у которых ещё нет билета в ТЕКУЩЕМ раунде
    лотереи, поучаствовать — но только один раз за раунд, без спама."""
    from db import get_db, get_lottery_state
    from aiogram.exceptions import TelegramForbiddenError
    from db import set_user_blocked
    while True:
        try:
            state = await get_lottery_state()
            current_round = state["draws_at"]
            conn = await get_db()
            cur = await conn.execute(
                """SELECT tg_id FROM users
                   WHERE is_banned = 0 AND blocked_bot = 0
                     AND (lottery_last_reminder_round IS NULL OR lottery_last_reminder_round != ?)
                     AND tg_id NOT IN (SELECT tg_id FROM lottery_tickets WHERE ticket_count > 0)""",
                (current_round,),
            )
            rows = await cur.fetchall()
            for row in rows:
                try:
                    await bot.send_message(
                        row["tg_id"],
                        "🎟 Участвуй в лотерее! Купи билет — раз в сутки случайный игрок "
                        "забирает весь банк. Загляни в «🎀 Бонусы и ещё» → «🎟 Лотерея».",
                    )
                except TelegramForbiddenError:
                    await set_user_blocked(row["tg_id"], True)
                except Exception:
                    pass
                await conn.execute(
                    "UPDATE users SET lottery_last_reminder_round = ? WHERE tg_id = ?",
                    (current_round, row["tg_id"]),
                )
                await conn.commit()
                await asyncio.sleep(0.05)
        except Exception:
            logging.exception("lottery reminder loop failed")
        await asyncio.sleep(3600)


async def main() -> None:
    _check_config()

    await init_db()

    from db import get_dynamic_admins
    from handlers.admin import DYNAMIC_ADMIN_IDS
    DYNAMIC_ADMIN_IDS.update(tg_id for tg_id, _ in await get_dynamic_admins())
    logger.info("База данных инициализирована.")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать / открыть меню"),
        BotCommand(command="garage", description="🚂 Депо"),
        BotCommand(command="collect", description="💰 Собрать доход"),
        BotCommand(command="freecar", description="🎁 Бесплатный поезд"),
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
        from db import ensure_user, touch_user_activity, upsert_bot_group
        is_start_command = bool(event.text) and event.text.split()[0].split("@")[0] == "/start"
        if event.from_user and not event.from_user.is_bot and not is_start_command:
            await ensure_user(event.from_user.id, event.from_user.username)
            await touch_user_activity(event.from_user.id)
        if event.chat.type in ("group", "supergroup"):
            # my_chat_member фиксирует только НОВОЕ добавление бота в группу — группы,
            # в которых бот уже состоял до этого обновления, подхватываем так, пассивно,
            # при любом сообщении в группе.
            await upsert_bot_group(event.chat.id, event.chat.title or str(event.chat.id))
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
    dp.include_router(fusion.router)
    dp.include_router(lottery.router)
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
    asyncio.create_task(_income_notifier_loop(bot))
    asyncio.create_task(_ad_campaign_loop(bot))
    asyncio.create_task(_auction_expiry_loop(bot))
    asyncio.create_task(_lottery_draw_loop(bot))
    asyncio.create_task(_lottery_reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
