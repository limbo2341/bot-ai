"""
handlers/containers.py — контейнеры (гача-механика): покупка за серебро/золото/Stars,
взвешенные шансы дропа машин по редкости, бустеров, XP и фишек.
"""
import datetime
import random
import json
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice

import asyncio

from db import get_db, add_user_exp, has_garage_space, send_car_photo, is_user_premium
from handlers.battlepass import increment_quest_progress
from keyboards import container_menu_kb, premium_container_qty_kb
from config import (
    RARITY_EMOJI, STARS_CURRENCY, PREMIUM_CONTAINER_BASE_PRICE, PREMIUM_CONTAINER_QTY_OPTIONS,
    PREMIUM_CONTAINER_DISCOUNT,
)

router = Router(name="containers")

# Веса выпадения по редкости для каждого типа контейнера.
# В common/rare контейнерах добавлены крошечные шансы более высокой редкости —
# для интриги ("а вдруг именно мне повезёт"), Ultra-Rare остаётся эксклюзивом premium.
CONTAINER_ODDS = {
    "common": {"Common": 55, "Uncommon": 30, "Rare": 12, "Epic": 2.9, "Legendary": 0.1},
    "rare": {"Uncommon": 35, "Rare": 40, "Epic": 19.95, "Legendary": 5, "Secret": 0.05},
    "premium": {"Rare": 25, "Epic": 40, "Legendary": 25, "Ultra-Rare": 9, "Secret": 1},
}

CONTAINER_COSTS = {
    "common": {"currency": "silver", "amount": 5000},
    "rare": {"currency": "gold", "amount": 50},
    "premium": {"currency": "stars", "amount": PREMIUM_CONTAINER_BASE_PRICE},
}


async def _premium_price_for_qty(qty: int, tg_id: int | None = None) -> int:
    opt = PREMIUM_CONTAINER_QTY_OPTIONS.get(qty, {"discount": 0.0})
    extra_discount = PREMIUM_CONTAINER_DISCOUNT if (tg_id and await is_user_premium(tg_id)) else 0.0
    return max(1, round(PREMIUM_CONTAINER_BASE_PRICE * qty * (1 - opt["discount"]) * (1 - extra_discount)))


@router.message(F.text == "📥 Контейнеры")
async def show_containers_menu(message: Message):
    await message.answer(
        "📥 <b>Контейнеры</b>\n━━━━━━━━━━━━━━\n"
        "Откройте контейнер и получите случайную машину! Чем реже контейнер — "
        "тем выше шансы на топовые машины.",
        parse_mode="HTML", reply_markup=container_menu_kb(),
    )


@router.callback_query(F.data == "cont:back")
async def containers_back(callback: CallbackQuery):
    await callback.message.answer(
        "📥 <b>Контейнеры</b>\n━━━━━━━━━━━━━━\n"
        "Откройте контейнер и получите случайную машину! Чем реже контейнер — "
        "тем выше шансы на топовые машины.",
        parse_mode="HTML", reply_markup=container_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "cont:premmenu")
async def premium_container_menu(callback: CallbackQuery):
    is_premium = await is_user_premium(callback.from_user.id)
    extra_note = "\n💎 У вас Premium BP — дополнительная скидка уже применена!" if is_premium else ""
    await callback.message.answer(
        "💎 <b>Премиум контейнер</b>\n━━━━━━━━━━━━━━\n"
        f"Самые высокие шансы на Ultra-Rare и Secret машины. Берите пачкой — дешевле за штуку!{extra_note}",
        parse_mode="HTML", reply_markup=premium_container_qty_kb(is_premium),
    )
    await callback.answer()


@router.callback_query(F.data == "cont:odds")
async def show_odds(callback: CallbackQuery):
    lines = ["📊 <b>Таблица шансов</b>\n"]
    names = {"common": "Обычный", "rare": "Редкий", "premium": "Премиум"}
    for key, odds in CONTAINER_ODDS.items():
        lines.append(f"<b>{names[key]} контейнер:</b>")
        for rarity, weight in odds.items():
            emoji = RARITY_EMOJI.get(rarity, "⚪")
            lines.append(f"  {emoji} {rarity}: {weight}%")
        lines.append("")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


CONTAINER_LABELS = {"common": "Обычный контейнер", "rare": "Редкий контейнер", "premium": "Премиум контейнер"}


@router.callback_query(F.data.startswith("cont:buy:"))
async def buy_container(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    container_key = parts[2]
    qty = int(parts[3]) if len(parts) > 3 else 1
    cost = CONTAINER_COSTS[container_key]
    tg_id = callback.from_user.id

    if cost["currency"] == "stars":
        price = await _premium_price_for_qty(qty, tg_id)
        payload = json.dumps({"container": container_key, "qty": qty, "tg_id": tg_id})
        label = f"Премиум контейнер x{qty}" if qty > 1 else "Премиум контейнер"
        await bot.send_invoice(
            chat_id=tg_id,
            title=label,
            description="Открывает шанс на редчайшие машины из каталога.",
            payload=payload,
            provider_token="",
            currency=STARS_CURRENCY,
            prices=[LabeledPrice(label=label, amount=price)],
        )
        await callback.answer()
        return

    conn = await get_db()
    cur = await conn.execute(f"SELECT {cost['currency']} as bal FROM users WHERE tg_id = ?", (tg_id,))
    balance = (await cur.fetchone())["bal"]
    if balance < cost["amount"]:
        await callback.answer("Недостаточно средств", show_alert=True)
        return

    await conn.execute(f"UPDATE users SET {cost['currency']} = {cost['currency']} - ? WHERE tg_id = ?",
                        (cost["amount"], tg_id))
    await conn.commit()
    if cost["currency"] == "silver":
        await increment_quest_progress(tg_id, "spend_silver", cost["amount"])

    await add_container_to_inventory(tg_id, container_key, qty=1)
    await callback.message.answer(
        f"📦 {CONTAINER_LABELS[container_key]} добавлен в «📦 Инвентарь». "
        f"Откройте его оттуда в любое удобное время!"
    )
    await callback.answer()


async def add_container_to_inventory(tg_id: int, container_key: str, qty: int = 1) -> None:
    conn = await get_db()
    await conn.execute(
        """INSERT INTO inventory (tg_id, item_type, item_name, quantity)
           VALUES (?, 'container', ?, ?)
           ON CONFLICT(tg_id, item_type, item_name) DO UPDATE SET quantity = inventory.quantity + ?""",
        (tg_id, container_key, qty, qty),
    )
    await conn.commit()


ANIMATION_FRAMES = [
    "📦 Открываем контейнер...",
    "📦 Открываем контейнер.\n🔄 Крутим барабан... ⚪🟢🔵",
    "📦 Открываем контейнер..\n🔄 Крутим барабан... 🔵🟣🟡",
    "📦 Открываем контейнер...\n🔄 Крутим барабан... 🟡🔴👑",
    "📦 Почти готово... 🎉",
]


async def animate_container_opening(message: Message):
    """Отправляет короткую анимацию 'спина' перед показом результата открытия
    контейнера — покупает эффект ожидания без реального GIF-файла (см. ниже)."""
    anim_msg = await message.answer(ANIMATION_FRAMES[0])
    for frame in ANIMATION_FRAMES[1:]:
        await asyncio.sleep(0.6)
        try:
            await anim_msg.edit_text(frame)
        except Exception:
            pass
    return anim_msg


async def _open_container(tg_id: int, container_key: str):
    odds = CONTAINER_ODDS[container_key]
    rarities = list(odds.keys())
    weights = list(odds.values())
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    conn = await get_db()
    cur = await conn.execute(
        "SELECT car_id, name, brand, tier, image_url, telegram_file_id FROM cars WHERE rarity = ? ORDER BY RANDOM() LIMIT 1",
        (chosen_rarity,),
    )
    car = await cur.fetchone()
    if not car:
        return None, "⚠️ Не удалось подобрать машину для этого контейнера."

    if not await has_garage_space(tg_id):
        # Гараж уже полон (актуально для оплаты Stars — деньги списаны заранее,
        # отказать в машине нельзя). Продаём её сразу за серебро вместо потери.
        cur2 = await conn.execute("SELECT base_value FROM cars WHERE car_id = ?", (car["car_id"],))
        base_value = (await cur2.fetchone())["base_value"]
        await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (base_value, tg_id))
        await conn.commit()
        emoji = RARITY_EMOJI.get(chosen_rarity, "⚪")
        text = (f"📦 <b>Контейнер открыт!</b>\n\n{emoji} Вам выпала: <b>{car['brand']} {car['name']}</b>, но "
                f"гараж переполнен — машина автоматически продана за {base_value:,} серебра.".replace(",", " "))
        return car, text

    await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
        (tg_id, car["car_id"], datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()
    await add_user_exp(tg_id, 25)
    await increment_quest_progress(tg_id, "open_container", 1)

    emoji = RARITY_EMOJI.get(chosen_rarity, "⚪")
    text = (f"📦 <b>Контейнер открыт!</b>\n\n{emoji} Вы получили: <b>{car['brand']} {car['name']}</b> "
            f"(Тир {car['tier']}, {chosen_rarity})")
    return car, text


async def grant_container_from_payment(tg_id: int, container_key: str, qty: int = 1) -> str:
    """Вызывается из payments.py после успешной оплаты Stars за премиум контейнер(ы)."""
    await add_container_to_inventory(tg_id, container_key, qty=qty)
    label = CONTAINER_LABELS[container_key]
    if qty > 1:
        return f"📦 {label} x{qty} добавлены в «📦 Инвентарь». Открывайте их оттуда, когда захотите!"
    return f"📦 {label} добавлен в «📦 Инвентарь». Откройте его оттуда, когда захотите!"
