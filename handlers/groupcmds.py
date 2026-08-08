"""
handlers/groupcmds.py — поддержка бота в группах:
  1) те же действия можно вызвать обычным словом без эмодзи и без нажатия
     кнопки (например написать в чат "Депо" или "Собрать");
  2) слэш-команды-алиасы для тех же разделов (/garage, /casino, ...);
  3) /pay — перевод серебра игроку, на сообщение которого вы ответили (reply).

Этот роутер должен быть подключён ПОСЛЕДНИМ в main.py, чтобы не перехватывать
текст, ожидаемый другими хендлерами в состояниях FSM (ввод сумм, названий и т.д.).
"""
import inspect
import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db import get_db
from handlers import auctions, battlepass, casino, common, containers, duels, freecar, garage, payments, bonuses

router = Router(name="groupcmds")

# Текстовые алиасы (без эмодзи, регистр не важен) -> обработчик из соответствующего модуля.
# "Ангар" добавлен как синоним "Депо" (термин из другого популярного бота — для привычки игроков).
ALIAS_HANDLERS = {
    "депо": garage.show_garage,
    "ангар": garage.show_garage,
    "собрать": garage.claim_silver,
    "забрать": garage.claim_silver,
    "улучшения": garage.show_upgrades_menu,
    "бесплатный поезд": freecar.claim_free_car,
    "бесплатный поезд": freecar.claim_free_car,
    "поезд": freecar.claim_free_car,
    "магазин": payments.show_shop,
    "инвентарь": common.show_inventory,
    "профиль": common.show_profile,
    "боевой пропуск": battlepass.show_battle_pass,
    "казино": casino.show_casino_menu,
    "дуэли": duels.show_duel_menu,
    "клан": common.show_clan_menu,
    "аукцион": auctions.show_auction_menu,
    "контейнеры": containers.show_containers_menu,
    "бонусы": bonuses.show_bonuses_menu,
    "сообщить о баге": common.bug_report_start,
    "баг": common.bug_report_start,
}

# Те же самые разделы, но как обычные слэш-команды — привычнее для групповых чатов.
COMMAND_ALIASES = {
    "garage": garage.show_garage,
    "collect": garage.claim_silver,
    "upgrades": garage.show_upgrades_menu,
    "freecar": freecar.claim_free_car,
    "shop": payments.show_shop,
    "inventory": common.show_inventory,
    "profile": common.show_profile,
    "battlepass": battlepass.show_battle_pass,
    "casino": casino.show_casino_menu,
    "duels": duels.show_duel_menu,
    "clan": common.show_clan_menu,
    "auction": auctions.show_auction_menu,
    "containers": containers.show_containers_menu,
    "bonuses": bonuses.show_bonuses_menu,
}


async def _call(handler, message: Message, state: FSMContext):
    """Вызывает обработчик, подставляя state только если он ему реально нужен."""
    if "state" in inspect.signature(handler).parameters:
        await handler(message, state)
    else:
        await handler(message)


def _normalize(text: str) -> str:
    return text.strip().lower().lstrip("!/.")


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and t.strip().lower().lstrip("/") in ("хелп", "help", "команды", "команда")),
)
async def group_help(message: Message):
    text_cmds = ", ".join(f"«{w.capitalize()}»" for w in sorted(ALIAS_HANDLERS.keys()))
    slash_cmds = ", ".join(f"/{c}" for c in sorted(COMMAND_ALIASES.keys()))
    lines = [
        "🤖 <b>Команды бота в этом чате</b>\n━━━━━━━━━━━━━━",
        "Просто напишите слово (без /) — сработает как кнопка:",
        text_cmds,
        "\nТе же разделы через слэш-команды:",
        slash_cmds,
        "\n🎰 Мини-игры казино: /basket, /slot, /dice [ставка]",
        "💸 Перевод серебра: /pay {сумма} — ответом на сообщение игрока",
        "🎫 Активировать промокод: напишите слово «Промокод»",
        "🚀 Открыть бота в личке: /start",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.reply_to_message,
    F.text.func(lambda t: bool(t) and t.strip().lower() in ("дуэль", "дуель")),
)
async def group_duel_challenge(message: Message):
    challenger = message.from_user
    challenged = message.reply_to_message.from_user
    if challenger.is_bot:
        return
    if not challenged or challenged.is_bot:
        await message.reply("⚠️ Нельзя вызвать на дуэль бота.")
        return
    if challenged.id == challenger.id:
        await message.reply("⚠️ Нельзя вызвать на дуэль самого себя.")
        return

    conn = await get_db()
    cur = await conn.execute(
        """INSERT INTO group_duel_challenges (chat_id, challenger_id, challenged_id, status, created_at)
           VALUES (?, ?, ?, 'pending', ?) RETURNING challenge_id""",
        (message.chat.id, challenger.id, challenged.id, datetime.datetime.utcnow().isoformat()),
    )
    row = await cur.fetchone()
    challenge_id = row["challenge_id"]
    await conn.commit()

    challenger_name = f"@{challenger.username}" if challenger.username else challenger.full_name
    challenged_name = f"@{challenged.username}" if challenged.username else challenged.full_name
    await message.reply(
        f"⚔️ {challenger_name} предлагает устроить дуэль {challenged_name}!\n"
        f"🔥 Погнали? (принять может только {challenged_name})",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Принять", callback_data=f"gduel:accept:{challenge_id}"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data=f"gduel:decline:{challenge_id}"),
        ]]),
    )


@router.callback_query(F.data.startswith("gduel:"))
async def group_duel_response(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    action, challenge_id = parts[1], int(parts[2])

    conn = await get_db()
    cur = await conn.execute("SELECT * FROM group_duel_challenges WHERE challenge_id = ?", (challenge_id,))
    challenge = await cur.fetchone()
    if not challenge or challenge["status"] != "pending":
        await callback.answer("Этот вызов уже неактуален", show_alert=True)
        return
    # Только тот, кого вызвали, может нажимать эти кнопки — остальным, включая
    # самого вызывающего, бот вежливо отказывает без каких-либо действий.
    if callback.from_user.id != challenge["challenged_id"]:
        await callback.answer("🚫 Эта кнопка не для вас — вызов адресован другому игроку", show_alert=True)
        return

    if action == "decline":
        await conn.execute("UPDATE group_duel_challenges SET status = 'declined' WHERE challenge_id = ?",
                            (challenge_id,))
        await conn.commit()
        try:
            await callback.message.edit_text("❌ Дуэль отклонена.")
        except Exception:
            pass
        await callback.answer()
        return

    conn2 = await get_db()
    cur = await conn2.execute("SELECT silver FROM users WHERE tg_id IN (?, ?)",
                               (challenge["challenger_id"], challenge["challenged_id"]))
    both = await cur.fetchall()
    if len(both) < 2 or any(r["silver"] < duels.DUEL_STAKE_SILVER for r in both):
        await callback.answer(f"У одного из игроков не хватает {duels.DUEL_STAKE_SILVER:,} серебра на ставку"
                               .replace(",", " "), show_alert=True)
        return

    await conn2.execute("UPDATE group_duel_challenges SET status = 'accepted' WHERE challenge_id = ?",
                         (challenge_id,))
    await conn2.commit()
    try:
        await callback.message.edit_text("⚔️ Дуэль принята! Считаем мощь составов...")
    except Exception:
        pass
    await callback.answer()

    await _resolve_group_duel(bot, callback.message, challenge["challenger_id"], challenge["challenged_id"])


async def _resolve_group_duel(bot: Bot, message: Message, challenger_id: int, challenged_id: int):
    """Дуэль по вызову в группе — состав каждый использует свой лучший автоматически
    (без ручного набора), результат публикуется прямо в группе."""
    from handlers.battlepass import increment_quest_progress
    from db import add_user_exp

    power_a = await duels.calculate_power_auto(challenger_id)
    power_b = await duels.calculate_power_auto(challenged_id)
    winner_id = challenger_id if power_a >= power_b else challenged_id
    loser_id = challenged_id if winner_id == challenger_id else challenger_id

    conn = await get_db()
    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (loser_id,))
    loser_silver = (await cur.fetchone())["silver"]
    stake = min(duels.DUEL_STAKE_SILVER, loser_silver)

    await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (stake, winner_id))
    await conn.execute("UPDATE users SET silver = GREATEST(silver - ?, 0) WHERE tg_id = ?", (stake, loser_id))
    await conn.commit()
    await add_user_exp(winner_id, 150)
    await add_user_exp(loser_id, 40)
    await increment_quest_progress(winner_id, "play_duels", 1)
    await increment_quest_progress(loser_id, "play_duels", 1)

    total = power_a + power_b
    a_share = round((power_a / total) * 10) if total > 0 else 5
    bar = "🟦" * a_share + "🟥" * (10 - a_share)

    winner_name = f"tg://user?id={winner_id}"
    try:
        winner_user = await bot.get_chat(winner_id)
        winner_label = f"@{winner_user.username}" if winner_user.username else winner_user.full_name
    except Exception:
        winner_label = "Победитель"

    await message.answer(
        (
            f"🏁 <b>ГОНКА ФИНИШИРОВАНА!</b>\n━━━━━━━━━━━━━━\n"
            f"🟦 Игрок 1: <b>{power_a:,.0f}</b>\n🟥 Игрок 2: <b>{power_b:,.0f}</b>\n"
            f"{bar}\n━━━━━━━━━━━━━━\n"
            f"🏆 Победил: <b>{winner_label}</b>!\n💰 Забрал: {stake:,} серебра"
        ).replace(",", " "),
        parse_mode="HTML",
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and t.strip().lower() == "промокод"),
)
async def promo_word_redirect(message: Message, bot: Bot):
    if message.from_user and message.from_user.is_bot:
        return
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=promo"
    await message.reply(
        "🎫 Для активации промокода перейдите в бота:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🎫 Активировать промокод", url=link),
        ]]),
    )


@router.message(F.text.func(lambda t: bool(t) and _normalize(t) in ALIAS_HANDLERS))
async def alias_text_dispatch(message: Message, state: FSMContext):
    handler = ALIAS_HANDLERS[_normalize(message.text)]
    await _call(handler, message, state)


@router.message(F.text.func(lambda t: bool(t) and t.startswith("/") and t[1:].split("@")[0].lower() in COMMAND_ALIASES))
async def command_alias_dispatch(message: Message, state: FSMContext):
    cmd = message.text[1:].split("@")[0].lower().split()[0]
    handler = COMMAND_ALIASES[cmd]
    await _call(handler, message, state)


@router.message(Command("pay"))
async def pay_transfer(message: Message, command: CommandObject):
    """Перевод серебра игроку, чьё сообщение процитировано (reply).
    Использование: ответьте на сообщение получателя командой /pay 5000"""
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("⚠️ Ответьте (reply) на сообщение игрока, которому хотите перевести серебро, "
                              "и напишите /pay {сумма}.")
        return
    recipient = message.reply_to_message.from_user
    if recipient.is_bot:
        await message.answer("⚠️ Нельзя переводить серебро боту.")
        return
    if recipient.id == message.from_user.id:
        await message.answer("⚠️ Нельзя перевести серебро самому себе.")
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("⚠️ Формат: /pay {сумма серебра}, ответом на сообщение получателя.")
        return
    amount = int(command.args.strip())
    if amount <= 0:
        await message.answer("⚠️ Сумма должна быть положительной.")
        return

    conn = await get_db()
    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (message.from_user.id,))
    sender = await cur.fetchone()
    if not sender or sender["silver"] < amount:
        await message.answer("⚠️ Недостаточно серебра для перевода.")
        return
    cur = await conn.execute("SELECT tg_id FROM users WHERE tg_id = ?", (recipient.id,))
    if not await cur.fetchone():
        await message.answer("⚠️ Получатель ещё не запускал бота (нужен хотя бы один /start).")
        return

    await conn.execute("UPDATE users SET silver = silver - ? WHERE tg_id = ?", (amount, message.from_user.id))
    await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (amount, recipient.id))
    await conn.commit()

    sender_name = message.from_user.username or message.from_user.first_name
    recipient_name = recipient.username or recipient.first_name
    await message.answer(
        f"💸 {sender_name} перевёл {amount:,} серебра игроку {recipient_name}.".replace(",", " ")
    )
