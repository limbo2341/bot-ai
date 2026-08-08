"""
handlers/auctions.py — аукцион поездов со ставками, доступен с 1 уровня профиля.

Как это работает:
- Продавец выставляет поезд со стартовой ценой и сроком (24/48/72ч), платит
  комиссию серебром за размещение (чем дольше висит лот — тем дороже).
- Покупатели делают ставки. Ставка сразу списывается (эскроу): если тебя
  перебивают — деньги мгновенно возвращаются, и приходит уведомление, кто
  именно перебил и на сколько.
- Если в последние 5 минут до конца кто-то поставил ставку — аукцион
  продлевается на 5 минут (защита от снайпинга в последнюю секунду).
- По истечении времени поезд уходит победителю (деньги — продавцу), либо,
  если ставок не было, возвращается в депо продавца. Комиссия за размещение
  при этом не возвращается — таковы правила аукционного дома.
"""
import datetime
import math
from aiogram import Router, F, Bot
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db import get_db, has_garage_space, add_user_exp
from keyboards import auction_menu_kb, auction_my_lots_kb, auction_duration_kb
from config import (
    AUCTION_UNLOCK_LEVEL, AUCTION_DURATION_OPTIONS, AUCTION_MIN_BID_STEP, AUCTION_MIN_BID_STEP_PERCENT,
    AUCTION_ANTISNIPE_WINDOW_MIN, AUCTION_ANTISNIPE_EXTEND_MIN, RARITY_EMOJI,
)

router = Router(name="auctions")
LOTS_PER_PAGE = 5
MY_LOTS_PER_PAGE = 10

# Живые "зрители" открытых карточек лотов: auction_id -> {(chat_id, message_id), ...}.
# Пока лот открыт хотя бы у одного человека, при каждой новой ставке его карточка
# обновляется сама, без нажатия "Обновить". Реестр в памяти процесса — переживать
# перезапуск бота ему не нужно, это лишь список того, что сейчас на экране у людей.
_LOT_VIEWERS: dict[int, set[tuple[int, int]]] = {}


def discard_lot_viewers(auction_id: int) -> None:
    """Вызывается из фоновой задачи в main.py, когда лот завершается по таймеру —
    чтобы не хранить в памяти ссылки на карточки лотов, которых больше не существует."""
    _LOT_VIEWERS.pop(auction_id, None)


class AuctionStates(StatesGroup):
    choose_car = State()
    price_silver = State()
    entering_bid = State()


def _min_next_bid(current_bid: int) -> int:
    step = max(AUCTION_MIN_BID_STEP, int(current_bid * AUCTION_MIN_BID_STEP_PERCENT))
    return current_bid + step


def _time_left_str(ends_at: str) -> str:
    ends = datetime.datetime.fromisoformat(ends_at)
    delta = ends - datetime.datetime.utcnow()
    if delta.total_seconds() <= 0:
        return "⏳ завершается..."
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60
    if hours >= 24:
        return f"⏱ {hours // 24}д {hours % 24}ч"
    if hours > 0:
        return f"⏱ {hours}ч {minutes}м"
    return f"⏱ {minutes}м"


async def _render_lot_detail(auction_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    conn = await get_db()
    cur = await conn.execute(
        """SELECT a.*, c.name, c.brand, c.rarity, c.hourly_income
           FROM auctions a JOIN cars c ON c.car_id = a.car_id WHERE a.auction_id = ?""",
        (auction_id,),
    )
    lot = await cur.fetchone()
    if not lot:
        return None

    current = lot["current_bid"] or lot["start_price"]
    leader_line = f"🔥 Ставок сделано: <b>{lot['bid_count']}</b>" if lot["bid_count"] else "🆕 Ставок пока не было — станьте первым"
    min_bid = _min_next_bid(current) if lot["bid_count"] else lot["start_price"]
    emoji = RARITY_EMOJI.get(lot["rarity"], "⚪")

    text = (
        f"🔨 <b>ЛОТ #{auction_id}</b>\n━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{lot['brand']} {lot['name']}</b>\n"
        f"Редкость: <b>{lot['rarity']}</b>\n"
        f"💵 Доход: {lot['hourly_income']:,} серебра/час\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Текущая цена: <b>{current:,} серебра</b>\n"
        f"{leader_line}\n"
        f"{_time_left_str(lot['ends_at'])}\n"
        f"━━━━━━━━━━━━━━\n"
        f"➡️ Минимальная ставка: <b>{min_bid:,} серебра</b>\n"
        f"🔴 <i>Обновляется в реальном времени, пока лот открыт</i>"
    ).replace(",", " ")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Сделать ставку", callback_data=f"auc:bid:{auction_id}")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"auc:refresh:{auction_id}")],
        [InlineKeyboardButton(text="⬅️ К списку лотов", callback_data="auc:list:1")],
    ])
    return text, kb


async def _push_live_update(bot: Bot, auction_id: int) -> None:
    """Обновляет карточку лота у всех, кто держит её открытой на экране, сразу
    после новой ставки — без перезагрузки с их стороны."""
    viewers = _LOT_VIEWERS.get(auction_id)
    if not viewers:
        return
    rendered = await _render_lot_detail(auction_id)
    stale = set()
    for chat_id, message_id in viewers:
        if rendered is None:
            stale.add((chat_id, message_id))
            continue
        text, kb = rendered
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                         parse_mode="HTML", reply_markup=kb)
        except Exception:
            stale.add((chat_id, message_id))
    viewers -= stale


@router.callback_query(F.data.startswith("auc:view:"))
async def view_lot_detail(callback: CallbackQuery):
    auction_id = int(callback.data.split(":")[2])
    rendered = await _render_lot_detail(auction_id)
    if rendered is None:
        await callback.answer("Лот уже завершён или не найден", show_alert=True)
        return
    text, kb = rendered
    sent = await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    _LOT_VIEWERS.setdefault(auction_id, set()).add((sent.chat.id, sent.message_id))
    await callback.answer()


@router.callback_query(F.data.startswith("auc:refresh:"))
async def refresh_lot_detail(callback: CallbackQuery):
    auction_id = int(callback.data.split(":")[2])
    rendered = await _render_lot_detail(auction_id)
    if rendered is None:
        await callback.answer("Лот уже завершён", show_alert=True)
        return
    text, kb = rendered
    _LOT_VIEWERS.setdefault(auction_id, set()).add((callback.message.chat.id, callback.message.message_id))
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass
    await callback.answer("Обновлено")


@router.message(F.text == "🔨 Аукцион")
async def show_auction_menu(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT level FROM users WHERE tg_id = ?", (message.from_user.id,))
    u = await cur.fetchone()
    if u["level"] < AUCTION_UNLOCK_LEVEL:
        await message.answer(f"🔒 Аукцион открывается с {AUCTION_UNLOCK_LEVEL} уровня профиля.")
        return
    await message.answer(
        "🔨 <b>АУКЦИОН</b>\n━━━━━━━━━━━━━━\n"
        "Делайте ставки на поезда других игроков или выставляйте свои — "
        "лот уходит тому, кто предложит больше к моменту окончания времени.",
        parse_mode="HTML", reply_markup=auction_menu_kb(),
    )


@router.callback_query(F.data.startswith("auc:list:"))
async def list_auction_lots(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM auctions")
    total = (await cur.fetchone())["cnt"]
    total_pages = max(1, math.ceil(total / LOTS_PER_PAGE))
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * LOTS_PER_PAGE

    cur = await conn.execute(
        """SELECT a.auction_id, a.start_price, a.current_bid, a.current_bidder_id, a.bid_count, a.ends_at,
                  c.name, c.brand, c.rarity
           FROM auctions a JOIN cars c ON c.car_id = a.car_id
           ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
        (LOTS_PER_PAGE, offset),
    )
    lots = await cur.fetchall()
    if not lots:
        await callback.message.answer("📋 На аукционе пока нет лотов.")
        await callback.answer()
        return

    rows = []
    lines = [f"🔨 <b>АУКЦИОН</b> · лоты (стр. {page}/{total_pages})\n━━━━━━━━━━━━━━"]
    for lot in lots:
        current = lot["current_bid"] or lot["start_price"]
        leader = "🔥 в торге" if lot["bid_count"] else "🆕 стартовая цена"
        emoji = RARITY_EMOJI.get(lot["rarity"], "⚪")
        lines.append(
            f"\n{emoji} <b>{lot['brand']} {lot['name']}</b>  ·  #{lot['auction_id']}\n"
            f"💰 <b>{current:,}</b> серебра  ·  {leader}\n"
            f"{_time_left_str(lot['ends_at'])}\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈".replace(",", " ")
        )
        rows.append([InlineKeyboardButton(text=f"🔍 #{lot['auction_id']} · {lot['brand']} {lot['name']} — {current:,}".replace(",", " "),
                                           callback_data=f"auc:view:{lot['auction_id']}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"auc:list:{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"auc:list:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ В меню аукциона", callback_data="auc:back")])

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("auc:bid:"))
async def auction_bid_prompt(callback: CallbackQuery, state: FSMContext):
    auction_id = int(callback.data.split(":")[2])
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM auctions WHERE auction_id = ?", (auction_id,))
    lot = await cur.fetchone()
    if not lot:
        await callback.answer("Лот уже завершён или не найден", show_alert=True)
        return
    if lot["seller_id"] == callback.from_user.id:
        await callback.answer("Нельзя делать ставку на собственный лот", show_alert=True)
        return

    current = lot["current_bid"] or lot["start_price"]
    min_bid = _min_next_bid(current) if lot["bid_count"] else lot["start_price"]
    await state.update_data(auction_id=auction_id, min_bid=min_bid)
    await state.set_state(AuctionStates.entering_bid)
    await callback.message.answer(
        f"💸 Лот #{auction_id}. Текущая цена: {current:,} серебра.\n"
        f"Минимальная ставка: <b>{min_bid:,}</b> серебра. Введите вашу ставку:".replace(",", " "),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(AuctionStates.entering_bid))
async def auction_bid_submit(message: Message, state: FSMContext, bot: Bot):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    bid_amount = int(message.text.strip())
    data = await state.get_data()
    auction_id = data["auction_id"]
    tg_id = message.from_user.id

    conn = await get_db()
    cur = await conn.execute("SELECT * FROM auctions WHERE auction_id = ?", (auction_id,))
    lot = await cur.fetchone()
    if not lot:
        await state.clear()
        await message.answer("⚠️ Лот уже завершён.")
        return

    current = lot["current_bid"] or lot["start_price"]
    min_bid = _min_next_bid(current) if lot["bid_count"] else lot["start_price"]
    if bid_amount < min_bid:
        await message.answer(f"⚠️ Ставка должна быть не меньше {min_bid:,} серебра.".replace(",", " "))
        return

    cur = await conn.execute("SELECT silver, username FROM users WHERE tg_id = ?", (tg_id,))
    bidder = await cur.fetchone()
    if bidder["silver"] < bid_amount:
        await message.answer("⚠️ Недостаточно серебра для такой ставки.")
        return

    await state.clear()

    # Списываем ставку сразу (эскроу), возвращаем предыдущему лидеру его деньги.
    await conn.execute("UPDATE users SET silver = silver - ? WHERE tg_id = ?", (bid_amount, tg_id))
    prev_bidder_id = lot["current_bidder_id"]
    prev_bid = lot["current_bid"]
    if prev_bidder_id:
        await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (prev_bid, prev_bidder_id))

    # Анти-снайпинг: если ставка в последние N минут — продлеваем лот.
    ends_at = datetime.datetime.fromisoformat(lot["ends_at"])
    now = datetime.datetime.utcnow()
    extended = False
    if (ends_at - now).total_seconds() <= AUCTION_ANTISNIPE_WINDOW_MIN * 60:
        ends_at = now + datetime.timedelta(minutes=AUCTION_ANTISNIPE_EXTEND_MIN)
        extended = True

    await conn.execute(
        """UPDATE auctions SET current_bid = ?, current_bidder_id = ?, bid_count = bid_count + 1, ends_at = ?
           WHERE auction_id = ?""",
        (bid_amount, tg_id, ends_at.isoformat(), auction_id),
    )
    await conn.commit()
    await add_user_exp(tg_id, 15)

    extend_note = f"\n⏳ Времени было мало — лот продлён ещё на {AUCTION_ANTISNIPE_EXTEND_MIN} мин.!" if extended else ""
    await message.answer(f"✅ Ставка {bid_amount:,} серебра принята на лот #{auction_id}!{extend_note}".replace(",", " "))

    if prev_bidder_id:
        try:
            outbidder_name = message.from_user.username or message.from_user.full_name
            await bot.send_message(
                prev_bidder_id,
                f"⚡ Вашу ставку {prev_bid:,} серебра на лот #{auction_id} перебил @{outbidder_name}!\n"
                f"Новая цена: {bid_amount:,} серебра. Ваши деньги возвращены на баланс — "
                f"можете перебить ставку снова.".replace(",", " "),
            )
        except Exception:
            pass

    await _push_live_update(bot, auction_id)


@router.callback_query(F.data == "auc:back")
async def auction_back(callback: CallbackQuery):
    await callback.message.answer(
        "🔨 <b>Аукцион</b>\n━━━━━━━━━━━━━━\nВыберите действие:", parse_mode="HTML",
        reply_markup=auction_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("auc:mylots:"))
async def list_my_lots(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM auctions WHERE seller_id = ?", (tg_id,))
    total = (await cur.fetchone())["cnt"]
    total_pages = max(1, math.ceil(total / MY_LOTS_PER_PAGE))
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * MY_LOTS_PER_PAGE

    cur = await conn.execute(
        """SELECT a.auction_id, a.start_price, a.current_bid, a.bid_count, a.ends_at, c.name, c.brand, c.rarity
           FROM auctions a JOIN cars c ON c.car_id = a.car_id
           WHERE a.seller_id = ? ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
        (tg_id, MY_LOTS_PER_PAGE, offset),
    )
    lots = await cur.fetchall()
    if not lots:
        await callback.message.answer("🗂 У вас нет активных лотов на аукционе.")
        await callback.answer()
        return

    lines = [f"🗂 <b>Ваши лоты</b> (стр. {page}/{total_pages})\n━━━━━━━━━━━━━━"]
    for lot in lots:
        current = lot["current_bid"] or lot["start_price"]
        status = f"🔥 {lot['bid_count']} ставок" if lot["bid_count"] else "нет ставок"
        lines.append(
            f"\n#{lot['auction_id']} {lot['brand']} {lot['name']} ({lot['rarity']})\n"
            f"💰 {current:,} серебра — {status} — {_time_left_str(lot['ends_at'])}".replace(",", " ")
        )
    kb_lots = [(lot["auction_id"], lot["brand"], lot["name"]) for lot in lots]
    text = "\n".join(lines)
    kb = auction_my_lots_kb(kb_lots, page, total_pages)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("auc:cancel:"))
async def cancel_my_lot(callback: CallbackQuery, bot: Bot):
    auction_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM auctions WHERE auction_id = ? AND seller_id = ?", (auction_id, tg_id))
    lot = await cur.fetchone()
    if not lot:
        await callback.answer("Лот не найден или это не ваш лот", show_alert=True)
        return

    # Если уже есть ставка — возвращаем деньги лидеру и уведомляем его.
    if lot["current_bidder_id"]:
        await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?",
                            (lot["current_bid"], lot["current_bidder_id"]))
        try:
            await bot.send_message(
                lot["current_bidder_id"],
                f"ℹ️ Продавец снял лот #{auction_id} с аукциона. Ваша ставка "
                f"{lot['current_bid']:,} серебра возвращена на баланс.".replace(",", " "),
            )
        except Exception:
            pass

    await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
        (tg_id, lot["car_id"], datetime.datetime.utcnow().isoformat()),
    )
    await conn.execute("DELETE FROM auctions WHERE auction_id = ?", (auction_id,))
    await conn.commit()
    discard_lot_viewers(auction_id)
    await callback.message.answer("✅ Лот снят с аукциона, поезд возвращён в ваше депо. "
                                   "Комиссия за размещение не возвращается.")
    await callback.answer()


@router.callback_query(F.data == "auc:create")
async def auction_create_start(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        """SELECT g.id as entry_id, c.name, c.brand FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ? LIMIT 30""",
        (tg_id,),
    )
    cars = await cur.fetchall()
    if not cars:
        await callback.answer("В депо нет поездов для продажи", show_alert=True)
        return

    rows = [[InlineKeyboardButton(text=f"{c['brand']} {c['name']}", callback_data=f"auc:pick:{c['entry_id']}")]
             for c in cars]
    await callback.message.answer("🚂 Выберите поезд для выставления на аукцион:",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await state.set_state(AuctionStates.choose_car)
    await callback.answer()


@router.callback_query(StateFilter(AuctionStates.choose_car), F.data.startswith("auc:pick:"))
async def auction_pick_car(callback: CallbackQuery, state: FSMContext):
    entry_id = int(callback.data.split(":")[2])
    await state.update_data(entry_id=entry_id)
    await callback.message.answer("💰 Введите стартовую цену лота в серебре:")
    await state.set_state(AuctionStates.price_silver)
    await callback.answer()


@router.message(StateFilter(AuctionStates.price_silver))
async def auction_price_silver(message: Message, state: FSMContext):
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer("⚠️ Введите целое число больше нуля.")
        return
    await state.update_data(price_silver=int(message.text.strip()))
    await message.answer(
        "⏱ На сколько выставить лот? Комиссия списывается сразу и не возвращается "
        "(это плата за размещение, а не залог):",
        reply_markup=auction_duration_kb(),
    )


@router.callback_query(F.data.startswith("auc:duration:"))
async def auction_finalize(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    hours, fee = int(parts[2]), int(parts[3])
    data = await state.get_data()
    if "price_silver" not in data or "entry_id" not in data:
        await callback.answer("Сессия истекла, начните заново", show_alert=True)
        await state.clear()
        return

    tg_id = callback.from_user.id
    entry_id = data["entry_id"]
    start_price = data["price_silver"]

    conn = await get_db()
    cur = await conn.execute("SELECT car_id FROM user_garage WHERE id = ? AND tg_id = ?", (entry_id, tg_id))
    entry = await cur.fetchone()
    if not entry:
        await callback.message.answer("⚠️ Поезд не найден в депо.")
        await state.clear()
        await callback.answer()
        return

    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if u["silver"] < fee:
        await callback.answer("Недостаточно серебра на комиссию за размещение", show_alert=True)
        return

    await state.clear()
    ends_at = datetime.datetime.utcnow() + datetime.timedelta(hours=hours)

    await conn.execute("UPDATE users SET silver = silver - ? WHERE tg_id = ?", (fee, tg_id))
    await conn.execute("DELETE FROM user_garage WHERE id = ?", (entry_id,))
    await conn.execute(
        """INSERT INTO auctions (seller_id, car_id, start_price, current_bid, ends_at, created_at)
           VALUES (?, ?, ?, 0, ?, ?)""",
        (tg_id, entry["car_id"], start_price, ends_at.isoformat(), datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()
    await add_user_exp(tg_id, 15)
    await callback.message.answer(
        f"✅ Лот выставлен на аукцион на {hours} ч.! Комиссия {fee:,} серебра списана.\n"
        f"Стартовая цена: {start_price:,} серебра.".replace(",", " ")
    )
    await callback.answer()
