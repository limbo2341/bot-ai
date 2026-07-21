"""
handlers/casino.py — обменник (полностью на кнопках, без слэш-команд для сумм),
мини-игры (баскетбол, слоты, кости).
Мини-игры используют встроенные Telegram dice-анимации (message.dice)
для честной и прозрачной механики.
"""
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from db import get_db, add_user_exp
from handlers.battlepass import increment_quest_progress
from keyboards import casino_kb, exchange_kb, exchange_amount_kb
from config import SILVER_TO_CHIP_RATE, CHIP_TO_SILVER_COMMISSION, EXCHANGE_QUICK_SILVER, EXCHANGE_QUICK_CHIPS

router = Router(name="casino")


class ExchangeStates(StatesGroup):
    waiting_custom_amount = State()

CASINO_XP_PER_PLAY = 5  # небольшой опыт профиля за каждую игру — стимул быть активным


@router.message(F.text == "🎰 Казино")
async def show_casino_menu(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT chips, silver FROM users WHERE tg_id = ?", (message.from_user.id,))
    u = await cur.fetchone()
    await message.answer(
        (
            f"🎰 <b>Казино</b>\n━━━━━━━━━━━━━━\n"
            f"🎟 Фишки: {u['chips']:,}\n💰 Серебро: {u['silver']:,}\n━━━━━━━━━━━━━━\n"
            f"Мини-игры: <code>/basket [ставка]</code>, <code>/slot [ставка]</code>, "
            f"<code>/dice [ставка]</code>"
        ).replace(",", " "),
        parse_mode="HTML",
        reply_markup=casino_kb(),
    )


@router.callback_query(F.data == "casino:back")
async def casino_back(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT chips, silver FROM users WHERE tg_id = ?", (callback.from_user.id,))
    u = await cur.fetchone()
    await callback.message.answer(
        (
            f"🎰 <b>Казино</b>\n━━━━━━━━━━━━━━\n"
            f"🎟 Фишки: {u['chips']:,}\n💰 Серебро: {u['silver']:,}\n━━━━━━━━━━━━━━\n"
            f"Мини-игры: <code>/basket [ставка]</code>, <code>/slot [ставка]</code>, "
            f"<code>/dice [ставка]</code>"
        ).replace(",", " "),
        parse_mode="HTML",
        reply_markup=casino_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "casino:exchange")
async def show_exchange(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT chips, silver FROM users WHERE tg_id = ?", (callback.from_user.id,))
    u = await cur.fetchone()
    await callback.message.answer(
        f"💱 <b>Обменник</b>\n{SILVER_TO_CHIP_RATE} серебра ➜ 1 фишка\n"
        f"1 фишка ➜ серебро (комиссия {int(CHIP_TO_SILVER_COMMISSION*100)}%)\n\n"
        f"💰 Баланс: {u['silver']:,} серебра, 🎟 {u['chips']:,} фишек".replace(",", " "),
        parse_mode="HTML",
        reply_markup=exchange_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "exch:s2c:menu")
async def exchange_s2c_menu(callback: CallbackQuery):
    await callback.message.answer(
        "💱 <b>Серебро ➜ Фишки</b>\nВыберите сумму серебра для обмена:",
        parse_mode="HTML", reply_markup=exchange_amount_kb("s2c", EXCHANGE_QUICK_SILVER),
    )
    await callback.answer()


@router.callback_query(F.data == "exch:c2s:menu")
async def exchange_c2s_menu(callback: CallbackQuery):
    await callback.message.answer(
        "💱 <b>Фишки ➜ Серебро</b> (комиссия 10%)\nВыберите количество фишек для обмена:",
        parse_mode="HTML", reply_markup=exchange_amount_kb("c2s", EXCHANGE_QUICK_CHIPS),
    )
    await callback.answer()


async def _do_exchange_s2c(tg_id: int, silver_amount: int) -> str:
    conn = await get_db()
    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if silver_amount <= 0 or u["silver"] < silver_amount:
        return "⚠️ Недостаточно серебра для такого обмена."
    chips_gained = silver_amount // SILVER_TO_CHIP_RATE
    if chips_gained <= 0:
        return f"⚠️ Минимум {SILVER_TO_CHIP_RATE} серебра для обмена."
    silver_spent = chips_gained * SILVER_TO_CHIP_RATE
    await conn.execute(
        "UPDATE users SET silver = silver - ?, chips = chips + ? WHERE tg_id = ?",
        (silver_spent, chips_gained, tg_id),
    )
    await conn.commit()
    return f"✅ Обменяно {silver_spent:,} серебра на {chips_gained:,} фишек.".replace(",", " ")


async def _do_exchange_c2s(tg_id: int, chips_amount: int) -> str:
    conn = await get_db()
    cur = await conn.execute("SELECT chips FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if chips_amount <= 0 or u["chips"] < chips_amount:
        return "⚠️ Недостаточно фишек для такого обмена."
    silver_gained = int(chips_amount * SILVER_TO_CHIP_RATE * (1 - CHIP_TO_SILVER_COMMISSION))
    await conn.execute(
        "UPDATE users SET chips = chips - ?, silver = silver + ? WHERE tg_id = ?",
        (chips_amount, silver_gained, tg_id),
    )
    await conn.commit()
    return f"✅ Обменяно {chips_amount:,} фишек на {silver_gained:,} серебра (комиссия 10%).".replace(",", " ")


@router.callback_query(F.data.startswith("exch:s2c:amt:"))
async def exchange_s2c_amount(callback: CallbackQuery):
    tg_id = callback.from_user.id
    value = callback.data.split(":")[3]
    conn = await get_db()
    if value == "max":
        cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (tg_id,))
        amount = (await cur.fetchone())["silver"]
    else:
        amount = int(value)
    text = await _do_exchange_s2c(tg_id, amount)
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith("exch:c2s:amt:"))
async def exchange_c2s_amount(callback: CallbackQuery):
    tg_id = callback.from_user.id
    value = callback.data.split(":")[3]
    conn = await get_db()
    if value == "max":
        cur = await conn.execute("SELECT chips FROM users WHERE tg_id = ?", (tg_id,))
        amount = (await cur.fetchone())["chips"]
    else:
        amount = int(value)
    text = await _do_exchange_c2s(tg_id, amount)
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.in_(["exch:s2c:custom", "exch:c2s:custom"]))
async def exchange_custom_start(callback: CallbackQuery, state: FSMContext):
    direction = callback.data.split(":")[1]
    await state.update_data(direction=direction)
    await state.set_state(ExchangeStates.waiting_custom_amount)
    unit = "серебра" if direction == "s2c" else "фишек"
    await callback.message.answer(f"✏️ Введите количество {unit} для обмена (просто числом):")
    await callback.answer()


@router.message(StateFilter(ExchangeStates.waiting_custom_amount))
async def exchange_custom_amount(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    data = await state.get_data()
    direction = data.get("direction")
    amount = int(message.text.strip())
    await state.clear()
    if direction == "s2c":
        text = await _do_exchange_s2c(message.from_user.id, amount)
    else:
        text = await _do_exchange_c2s(message.from_user.id, amount)
    await message.answer(text)


# ---------------------------------------------------------------- Мини-игры
async def _get_chips(tg_id: int) -> int:
    conn = await get_db()
    cur = await conn.execute("SELECT chips FROM users WHERE tg_id = ?", (tg_id,))
    return (await cur.fetchone())["chips"]


async def _adjust_chips(tg_id: int, delta: int):
    conn = await get_db()
    await conn.execute("UPDATE users SET chips = chips + ? WHERE tg_id = ?", (delta, tg_id))
    await conn.commit()
    await increment_quest_progress(tg_id, "use_casino", 1)


@router.message(Command("basket"))
async def play_basketball(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("⚠️ Формат: /basket [ставка в фишках]")
        return
    bet = int(parts[1])
    chips = await _get_chips(message.from_user.id)
    if bet <= 0 or bet > chips:
        await message.answer("⚠️ Некорректная ставка или недостаточно фишек")
        return

    dice_msg = await message.answer_dice(emoji="🏀")
    await add_user_exp(message.from_user.id, CASINO_XP_PER_PLAY)
    await increment_quest_progress(message.from_user.id, "use_casino", 1)
    # Значения 4 и 5 в Telegram basketball-dice считаются заброшенным мячом
    won = dice_msg.dice.value in (4, 5)
    if won:
        await _adjust_chips(message.from_user.id, bet)
        await message.answer(f"🏀 Гол! Вы выиграли {bet*2:,} фишек (ставка удвоена).".replace(",", " "))
    else:
        await _adjust_chips(message.from_user.id, -bet)
        await message.answer(f"🏀 Мимо! Вы проиграли {bet:,} фишек.".replace(",", " "))


@router.message(Command("slot"))
async def play_slot(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("⚠️ Формат: /slot [ставка в фишках]")
        return
    bet = int(parts[1])
    chips = await _get_chips(message.from_user.id)
    if bet <= 0 or bet > chips:
        await message.answer("⚠️ Некорректная ставка или недостаточно фишек")
        return

    dice_msg = await message.answer_dice(emoji="🎰")
    await add_user_exp(message.from_user.id, CASINO_XP_PER_PLAY)
    await increment_quest_progress(message.from_user.id, "use_casino", 1)
    value = dice_msg.dice.value  # 1..64, кодирует три барабана

    # Раскодируем значение слота Telegram в 3 символа барабана (1..4)
    idx = value - 1
    reel1 = idx % 4
    reel2 = (idx // 4) % 4
    reel3 = (idx // 16) % 4

    if reel1 == reel2 == reel3:
        multiplier = 10 if reel1 == 3 else 5  # индекс 3 = 777 (джекпот Telegram, value=64)
        winnings = bet * multiplier
        await _adjust_chips(message.from_user.id, winnings - bet)
        await message.answer(f"🎰 ДЖЕКПОТ! Три одинаковых символа! Выигрыш: {winnings:,} фишек.".replace(",", " "))
    elif reel1 == reel2 or reel2 == reel3 or reel1 == reel3:
        winnings = bet * 2
        await _adjust_chips(message.from_user.id, winnings - bet)
        await message.answer(f"🎰 Два совпадения! Выигрыш: {winnings:,} фишек.".replace(",", " "))
    else:
        await _adjust_chips(message.from_user.id, -bet)
        await message.answer(f"🎰 Не повезло! Вы проиграли {bet:,} фишек.".replace(",", " "))


@router.message(Command("dice"))
async def play_dice(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("⚠️ Формат: /dice [ставка в фишках]")
        return
    bet = int(parts[1])
    chips = await _get_chips(message.from_user.id)
    if bet <= 0 or bet > chips:
        await message.answer("⚠️ Некорректная ставка или недостаточно фишек")
        return

    player_dice = await message.answer_dice(emoji="🎲")
    dealer_dice = await message.answer_dice(emoji="🎲")
    await add_user_exp(message.from_user.id, CASINO_XP_PER_PLAY)
    await increment_quest_progress(message.from_user.id, "use_casino", 1)
    player_val = player_dice.dice.value
    dealer_val = dealer_dice.dice.value

    if player_val > dealer_val:
        await _adjust_chips(message.from_user.id, bet)
        await message.answer(f"🎲 Вы выиграли! ({player_val} vs {dealer_val}) +{bet*2:,} фишек.".replace(",", " "))
    elif player_val < dealer_val:
        await _adjust_chips(message.from_user.id, -bet)
        await message.answer(f"🎲 Вы проиграли! ({player_val} vs {dealer_val}) -{bet:,} фишек.".replace(",", " "))
    else:
        await message.answer(f"🎲 Ничья! ({player_val} vs {dealer_val}) Ставка возвращена.")


@router.callback_query(F.data.startswith("casino:info:"))
async def casino_info(callback: CallbackQuery):
    game = callback.data.split(":")[2]
    texts = {
        "basket": "🏀 /basket [ставка] — попадание удваивает ставку фишек.",
        "slot": "🎰 /slot [ставка] — совпадения символов приносят x2 или x10.",
        "dice": "🎲 /dice [ставка] — бросок против дилера, больше число побеждает.",
    }
    await callback.answer(texts.get(game, ""), show_alert=True)
