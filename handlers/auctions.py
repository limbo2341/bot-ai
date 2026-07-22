"""
handlers/auctions.py — аукцион машин, доступен с 5 уровня профиля.
"""
import datetime
import math
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db import get_db, has_garage_space, add_user_exp
from keyboards import auction_menu_kb, auction_my_lots_kb
from config import AUCTION_UNLOCK_LEVEL

router = Router(name="auctions")
LOTS_PER_PAGE = 5
MY_LOTS_PER_PAGE = 10


class AuctionStates(StatesGroup):
    choose_car = State()
    price_silver = State()
    price_gold = State()


@router.message(F.text == "🔨 Аукцион")
async def show_auction_menu(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT level FROM users WHERE tg_id = ?", (message.from_user.id,))
    u = await cur.fetchone()
    if u["level"] < AUCTION_UNLOCK_LEVEL:
        await message.answer(f"🔒 Аукцион открывается с {AUCTION_UNLOCK_LEVEL} уровня профиля.")
        return
    await message.answer("🔨 <b>Аукцион</b>\n━━━━━━━━━━━━━━\nВыберите действие:", parse_mode="HTML",
                          reply_markup=auction_menu_kb())


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
        """SELECT a.auction_id, a.price_silver, a.price_gold, c.name, c.brand, c.rarity
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
    lines = [f"📋 <b>Активные лоты</b> (стр. {page}/{total_pages})\n"]
    for lot in lots:
        lines.append(
            f"#{lot['auction_id']} {lot['brand']} {lot['name']} ({lot['rarity']}) — "
            f"{lot['price_silver']:,} серебра / {lot['price_gold']} золота".replace(",", " ")
        )
        rows.append([InlineKeyboardButton(text=f"Купить лот #{lot['auction_id']}",
                                           callback_data=f"auc:buy:{lot['auction_id']}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"auc:list:{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"auc:list:{page+1}"))
    if nav:
        rows.append(nav)

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("auc:buy:"))
async def buy_auction_lot(callback: CallbackQuery):
    auction_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM auctions WHERE auction_id = ?", (auction_id,))
    lot = await cur.fetchone()
    if not lot:
        await callback.answer("Лот уже продан или не найден", show_alert=True)
        return
    if lot["seller_id"] == tg_id:
        await callback.answer("Нельзя купить собственный лот", show_alert=True)
        return

    cur = await conn.execute("SELECT silver, gold FROM users WHERE tg_id = ?", (tg_id,))
    buyer = await cur.fetchone()
    if buyer["silver"] < lot["price_silver"] or buyer["gold"] < lot["price_gold"]:
        await callback.answer("Недостаточно средств", show_alert=True)
        return
    if not await has_garage_space(tg_id):
        await callback.answer("🚫 Гараж переполнен! Расширьте его в «⚙️ Улучшения».", show_alert=True)
        return

    await conn.execute("UPDATE users SET silver = silver - ?, gold = gold - ? WHERE tg_id = ?",
                        (lot["price_silver"], lot["price_gold"], tg_id))
    await conn.execute("UPDATE users SET silver = silver + ?, gold = gold + ? WHERE tg_id = ?",
                        (lot["price_silver"], lot["price_gold"], lot["seller_id"]))
    await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
        (tg_id, lot["car_id"], datetime.datetime.utcnow().isoformat()),
    )
    await conn.execute("DELETE FROM auctions WHERE auction_id = ?", (auction_id,))
    await conn.commit()
    await add_user_exp(tg_id, 15)
    await callback.message.answer("✅ Лот куплен и добавлен в ваш гараж!")
    await callback.answer()


@router.callback_query(F.data == "auc:back")
async def auction_back(callback: CallbackQuery):
    await callback.message.answer("🔨 <b>Аукцион</b>\n━━━━━━━━━━━━━━\nВыберите действие:", parse_mode="HTML",
                                   reply_markup=auction_menu_kb())
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
        """SELECT a.auction_id, a.price_silver, a.price_gold, c.name, c.brand, c.rarity
           FROM auctions a JOIN cars c ON c.car_id = a.car_id
           WHERE a.seller_id = ? ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
        (tg_id, MY_LOTS_PER_PAGE, offset),
    )
    lots = await cur.fetchall()
    if not lots:
        await callback.message.answer("🗂 У вас нет активных лотов на аукционе.")
        await callback.answer()
        return

    lines = [f"🗂 <b>Ваши лоты</b> (стр. {page}/{total_pages})\n"]
    for lot in lots:
        lines.append(
            f"#{lot['auction_id']} {lot['brand']} {lot['name']} ({lot['rarity']}) — "
            f"{lot['price_silver']:,} серебра / {lot['price_gold']} золота".replace(",", " ")
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
async def cancel_my_lot(callback: CallbackQuery):
    auction_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM auctions WHERE auction_id = ? AND seller_id = ?", (auction_id, tg_id))
    lot = await cur.fetchone()
    if not lot:
        await callback.answer("Лот не найден или это не ваш лот", show_alert=True)
        return

    await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
        (tg_id, lot["car_id"], datetime.datetime.utcnow().isoformat()),
    )
    await conn.execute("DELETE FROM auctions WHERE auction_id = ?", (auction_id,))
    await conn.commit()
    await callback.message.answer("✅ Лот снят с аукциона, машина возвращена в ваш гараж.")
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
        await callback.answer("В гараже нет машин для продажи", show_alert=True)
        return

    rows = [[InlineKeyboardButton(text=f"{c['brand']} {c['name']}", callback_data=f"auc:pick:{c['entry_id']}")]
             for c in cars]
    await callback.message.answer("🚗 Выберите машину для выставления на аукцион:",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await state.set_state(AuctionStates.choose_car)
    await callback.answer()


@router.callback_query(StateFilter(AuctionStates.choose_car), F.data.startswith("auc:pick:"))
async def auction_pick_car(callback: CallbackQuery, state: FSMContext):
    entry_id = int(callback.data.split(":")[2])
    await state.update_data(entry_id=entry_id)
    await callback.message.answer("💰 Введите стартовую цену в серебре (0, если не нужно):")
    await state.set_state(AuctionStates.price_silver)
    await callback.answer()


@router.message(StateFilter(AuctionStates.price_silver))
async def auction_price_silver(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    await state.update_data(price_silver=int(message.text.strip()))
    await message.answer("🥇 Введите цену в золоте (0, если не нужно):")
    await state.set_state(AuctionStates.price_gold)


@router.message(StateFilter(AuctionStates.price_gold))
async def auction_price_gold(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    data = await state.get_data()
    price_gold = int(message.text.strip())
    tg_id = message.from_user.id
    entry_id = data["entry_id"]

    conn = await get_db()
    cur = await conn.execute("SELECT car_id FROM user_garage WHERE id = ? AND tg_id = ?", (entry_id, tg_id))
    entry = await cur.fetchone()
    if not entry:
        await message.answer("⚠️ Машина не найдена в гараже.")
        await state.clear()
        return

    await conn.execute("DELETE FROM user_garage WHERE id = ?", (entry_id,))
    await conn.execute(
        """INSERT INTO auctions (seller_id, car_id, price_silver, price_gold, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (tg_id, entry["car_id"], data["price_silver"], price_gold, datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()
    await state.clear()
    await add_user_exp(tg_id, 15)
    await message.answer("✅ Лот выставлен на аукцион!")
