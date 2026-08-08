"""
handlers/fusion.py — 🧬 Слияние поездов: новая механика крафта.

Сдаёте N дубликатов поездов одной редкости (плюс небольшую комиссию серебром) —
получаете взамен ГАРАНТИРОВАННУЮ случайный поезд следующей редкости. Даёт
дубликатам смысл существовать, кроме продажи за серебро, и даёт игрокам
управляемый путь наверх по редкости без чистой удачи контейнеров.
"""
import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db import get_db, add_user_exp, send_car_photo
from config import RARITY_EMOJI, FUSION_ORDER, FUSION_REQUIREMENTS, FUSION_NEXT_RARITY

router = Router(name="fusion")


async def _rarity_counts(tg_id: int) -> dict:
    conn = await get_db()
    cur = await conn.execute(
        """SELECT c.rarity, COUNT(*) as cnt FROM user_garage g JOIN cars c ON c.car_id = g.car_id
           WHERE g.tg_id = ? GROUP BY c.rarity""",
        (tg_id,),
    )
    rows = await cur.fetchall()
    return {r["rarity"]: r["cnt"] for r in rows}


def _fusion_menu_kb(counts: dict) -> InlineKeyboardMarkup:
    rows = []
    for rarity in FUSION_ORDER:
        req = FUSION_REQUIREMENTS[rarity]
        have = counts.get(rarity, 0)
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        next_emoji = RARITY_EMOJI.get(FUSION_NEXT_RARITY[rarity], "⚪")
        label = f"{emoji}×{req['count']} → {next_emoji} ({have}/{req['count']}, {req['fee_silver']:,}🪙)".replace(",", " ")
        if have >= req["count"]:
            rows.append([InlineKeyboardButton(text=f"✅ {label}", callback_data=f"fusion:do:{rarity}")])
        else:
            rows.append([InlineKeyboardButton(text=f"🔒 {label}", callback_data="fusion:locked")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:economy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "🧬 Слияние поездов")
async def show_fusion_menu(message: Message):
    counts = await _rarity_counts(message.from_user.id)
    await message.answer(
        "🧬 <b>Слияние поездов</b>\n━━━━━━━━━━━━━━\n"
        "Сдайте несколько поездов одной редкости (+ комиссия серебром) — получите взамен "
        "ГАРАНТИРОВАННУЮ случайный поезд следующей редкости. Никакой удачи — чистый расчёт.\n\n"
        "Какие поезда сольются — выбирает бот случайно среди дубликатов подходящей редкости.",
        parse_mode="HTML", reply_markup=_fusion_menu_kb(counts),
    )


@router.callback_query(F.data == "fusion:locked")
async def fusion_locked(callback: CallbackQuery):
    await callback.answer("Недостаточно поездов этой редкости для слияния", show_alert=True)


@router.callback_query(F.data.startswith("fusion:do:"))
async def do_fusion(callback: CallbackQuery):
    rarity = callback.data.split(":")[2]
    req = FUSION_REQUIREMENTS[rarity]
    tg_id = callback.from_user.id

    conn = await get_db()
    cur = await conn.execute(
        """SELECT g.id FROM user_garage g JOIN cars c ON c.car_id = g.car_id
           WHERE g.tg_id = ? AND c.rarity = ? LIMIT ?""",
        (tg_id, rarity, req["count"]),
    )
    entries = await cur.fetchall()
    if len(entries) < req["count"]:
        await callback.answer("Недостаточно поездов этой редкости", show_alert=True)
        return

    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if u["silver"] < req["fee_silver"]:
        await callback.answer("Недостаточно серебра на комиссию слияния", show_alert=True)
        return

    next_rarity = FUSION_NEXT_RARITY[rarity]
    cur = await conn.execute(
        "SELECT car_id, name, brand, image_url, telegram_file_id FROM cars WHERE rarity = ? ORDER BY RANDOM() LIMIT 1",
        (next_rarity,),
    )
    new_car = await cur.fetchone()
    if not new_car:
        await callback.answer("В каталоге пока нет поездов этой редкости — попробуйте позже", show_alert=True)
        return

    for entry in entries:
        await conn.execute("DELETE FROM user_garage WHERE id = ?", (entry["id"],))
    await conn.execute("UPDATE users SET silver = silver - ? WHERE tg_id = ?", (req["fee_silver"], tg_id))
    await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
        (tg_id, new_car["car_id"], datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()
    await add_user_exp(tg_id, 25)

    emoji = RARITY_EMOJI.get(next_rarity, "⚪")
    caption = (
        f"🧬 <b>Слияние успешно!</b>\n━━━━━━━━━━━━━━\n"
        f"Сдано: {req['count']}× {RARITY_EMOJI.get(rarity, '⚪')} {rarity}\n\n"
        f"Получено: {emoji} <b>{new_car['brand']} {new_car['name']}</b> ({next_rarity})"
    )
    sent = await send_car_photo(callback.message, new_car["car_id"], new_car["image_url"],
                                 new_car["telegram_file_id"], caption)
    if not sent:
        await callback.message.answer(caption, parse_mode="HTML")

    counts = await _rarity_counts(tg_id)
    await callback.message.answer("🧬 Слить ещё?", reply_markup=_fusion_menu_kb(counts))
    await callback.answer()
