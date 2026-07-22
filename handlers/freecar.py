"""
handlers/freecar.py — бесплатная машина раз в N часов (по умолчанию 2ч),
кулдаун можно сократить через прокачку (см. upg:freecar в keyboards.py).
"""
import datetime
import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from db import get_db, add_user_exp, has_garage_space, send_car_photo
from keyboards import freecar_upgrade_kb, garage_car_detail_kb
from config import (
    FREE_CAR_BASE_COOLDOWN_SECONDS, FREE_CAR_MIN_COOLDOWN_SECONDS,
    FREE_CAR_UPGRADE_STEP_SECONDS, FREE_CAR_UPGRADE_COSTS, FREE_CAR_MAX_UPGRADE_LEVEL,
    FREE_CAR_ODDS, RARITY_EMOJI,
)

router = Router(name="freecar")


def _current_cooldown_seconds(upgrade_level: int) -> int:
    return max(
        FREE_CAR_BASE_COOLDOWN_SECONDS - upgrade_level * FREE_CAR_UPGRADE_STEP_SECONDS,
        FREE_CAR_MIN_COOLDOWN_SECONDS,
    )


@router.message(F.text == "🎁 Бесплатная машина")
async def claim_free_car(message: Message):
    tg_id = message.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        "SELECT last_free_car_at, free_car_cooldown_reduction FROM users WHERE tg_id = ?", (tg_id,)
    )
    u = await cur.fetchone()

    now = datetime.datetime.utcnow()
    cooldown = _current_cooldown_seconds(u["free_car_cooldown_reduction"])

    if u["last_free_car_at"]:
        last_claim = datetime.datetime.fromisoformat(u["last_free_car_at"])
        elapsed = (now - last_claim).total_seconds()
        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            h, rem = divmod(remaining, 3600)
            m, s = divmod(rem, 60)
            await message.answer(
                f"⏳ Бесплатная машина ещё не готова.\nОсталось: {h}ч {m}м {s}с.\n\n"
                f"💡 Кулдаун можно сократить в разделе «⚙️ Улучшения» → «🎁 Ускорение бесплатной машины»."
            )
            return

    if not await has_garage_space(tg_id):
        await message.answer(
            "🚫 Гараж переполнен! Расширьте его в «⚙️ Улучшения» или продайте машины — "
            "кулдаун бесплатной машины не потрачен, попробуйте снова после этого."
        )
        return

    rarities = list(FREE_CAR_ODDS.keys())
    weights = list(FREE_CAR_ODDS.values())
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    cur = await conn.execute(
        "SELECT car_id, name, brand, tier, hourly_income, image_url, telegram_file_id FROM cars "
        "WHERE rarity = ? ORDER BY RANDOM() LIMIT 1",
        (chosen_rarity,),
    )
    car = await cur.fetchone()
    if not car:
        await message.answer("⚠️ Не удалось подобрать машину. Попробуйте чуть позже.")
        return

    cur = await conn.execute(
        "SELECT COUNT(*) as cnt FROM user_garage WHERE tg_id = ? AND car_id = ?", (tg_id, car["car_id"])
    )
    is_duplicate = (await cur.fetchone())["cnt"] > 0

    cur = await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?) RETURNING id",
        (tg_id, car["car_id"], now.isoformat()),
    )
    entry_id = cur.lastrowid
    await conn.execute("UPDATE users SET last_free_car_at = ? WHERE tg_id = ?", (now.isoformat(), tg_id))
    await conn.commit()
    await add_user_exp(tg_id, 10)

    emoji = RARITY_EMOJI.get(chosen_rarity, "⚪")
    duplicate_note = "\n♻️ Такая машина уже есть в гараже — можно продать эту копию." if is_duplicate else ""
    text = (
        f"🎁 <b>Бесплатная машина получена!</b>\n━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{car['brand']} {car['name']}</b>\nТир {car['tier']} | {chosen_rarity}\n"
        f"⚡ Доход: {car['hourly_income']:,} серебра/ч{duplicate_note}\n━━━━━━━━━━━━━━\n"
        f"Следующая через {_current_cooldown_seconds(u['free_car_cooldown_reduction']) // 60} мин."
    ).replace(",", " ")
    kb = garage_car_detail_kb(entry_id, False, tg_id)
    sent_photo = await send_car_photo(
        message, car["car_id"], car["image_url"], car["telegram_file_id"], caption=text, parse_mode="HTML",
        reply_markup=kb,
    )
    if not sent_photo:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "upg:freecar")
async def upg_freecar_menu(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute(
        "SELECT free_car_cooldown_reduction, silver, gold FROM users WHERE tg_id = ?", (callback.from_user.id,)
    )
    u = await cur.fetchone()
    current_level = u["free_car_cooldown_reduction"]
    cooldown = _current_cooldown_seconds(current_level)
    h, rem = divmod(cooldown, 3600)
    m = rem // 60

    if current_level >= FREE_CAR_MAX_UPGRADE_LEVEL:
        await callback.message.answer(
            f"🎁 <b>Ускорение бесплатной машины</b>\n━━━━━━━━━━━━━━\n"
            f"🟩🟩🟩🟩🟩\nКулдаун: {h}ч {m}м (МАКСИМУМ {FREE_CAR_MAX_UPGRADE_LEVEL}/{FREE_CAR_MAX_UPGRADE_LEVEL})",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    next_level = current_level + 1
    cost_silver, cost_gold = FREE_CAR_UPGRADE_COSTS[next_level]
    can_afford = u["silver"] >= cost_silver and u["gold"] >= cost_gold
    bar = "🟩" * current_level + "⬜️" * (FREE_CAR_MAX_UPGRADE_LEVEL - current_level)
    await callback.message.answer(
        f"🎁 <b>Ускорение бесплатной машины</b>\n━━━━━━━━━━━━━━\n"
        f"Уровень {current_level}/{FREE_CAR_MAX_UPGRADE_LEVEL}\n{bar}\n"
        f"Текущий кулдаун: {h}ч {m}м\n━━━━━━━━━━━━━━\n"
        f"Ур. {next_level}: {cost_silver:,} серебра + {cost_gold} золота".replace(",", " "),
        parse_mode="HTML",
        reply_markup=freecar_upgrade_kb(next_level, can_afford),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("upg:freecar:buy:"))
async def upg_freecar_buy(callback: CallbackQuery):
    level = int(callback.data.split(":")[3])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT free_car_cooldown_reduction, silver, gold FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if u["free_car_cooldown_reduction"] + 1 != level:
        await callback.answer("Некорректный уровень улучшения", show_alert=True)
        return
    cost_silver, cost_gold = FREE_CAR_UPGRADE_COSTS[level]
    if u["silver"] < cost_silver or u["gold"] < cost_gold:
        await callback.answer("Недостаточно средств", show_alert=True)
        return
    await conn.execute(
        "UPDATE users SET silver = silver - ?, gold = gold - ?, free_car_cooldown_reduction = ? WHERE tg_id = ?",
        (cost_silver, cost_gold, level, tg_id),
    )
    await conn.commit()
    await callback.message.answer(
        f"✅ <b>Ускорение улучшено до уровня {level}/{FREE_CAR_MAX_UPGRADE_LEVEL}!</b>", parse_mode="HTML"
    )
    await callback.answer()
