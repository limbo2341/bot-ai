"""
handlers/groupcmds.py — поддержка бота в группах:
  1) те же действия можно вызвать обычным словом без эмодзи и без нажатия
     кнопки (например написать в чат "Гараж" или "Собрать");
  2) слэш-команды-алиасы для тех же разделов (/garage, /casino, ...);
  3) /pay — перевод серебра игроку, на сообщение которого вы ответили (reply).

Этот роутер должен быть подключён ПОСЛЕДНИМ в main.py, чтобы не перехватывать
текст, ожидаемый другими хендлерами в состояниях FSM (ввод сумм, названий и т.д.).
"""
import inspect
from aiogram import Router, F
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import get_db
from handlers import auctions, battlepass, casino, common, containers, duels, freecar, garage, payments, bonuses

router = Router(name="groupcmds")

# Текстовые алиасы (без эмодзи, регистр не важен) -> обработчик из соответствующего модуля.
# "Ангар" добавлен как синоним "Гараж" (термин из другого популярного бота — для привычки игроков).
ALIAS_HANDLERS = {
    "гараж": garage.show_garage,
    "ангар": garage.show_garage,
    "собрать": garage.claim_silver,
    "забрать": garage.claim_silver,
    "улучшения": garage.show_upgrades_menu,
    "бесплатная машина": freecar.claim_free_car,
    "бесплатную машину": freecar.claim_free_car,
    "машина": freecar.claim_free_car,
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
