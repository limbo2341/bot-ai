"""
handlers/bonuses.py — раздел «🎁 Бонусы»: реферальная система и ввод промокодов.
Создание промокодов — в handlers/admin.py (доступно только главному админу).
"""
import datetime
import random
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from db import get_db, has_garage_space, add_user_exp, is_user_premium
from keyboards import bonuses_menu_kb
from config import REFERRAL_THRESHOLD, PREMIUM_DAILY_BONUS_MULT, WEEKLY_STREAK_GOLD

router = Router(name="bonuses")

DAILY_BONUS_COOLDOWN_SECONDS = 24 * 60 * 60
# Порог суммарной ценности гаража (в серебре) -> диапазон награды и шанс контейнера.
DAILY_BONUS_TIERS = [
    (0, (500, 3_000), None),
    (50_000, (3_000, 15_000), "common"),
    (500_000, (15_000, 60_000), "rare"),
]


class PromoRedeemStates(StatesGroup):
    waiting_code = State()


@router.message(F.text == "🎁 Бонусы")
async def show_bonuses_menu(message: Message):
    is_premium = await is_user_premium(message.from_user.id)
    await message.answer(
        "🎁 <b>Бонусы</b>\n━━━━━━━━━━━━━━\nПриглашайте друзей или вводите промокоды, чтобы получать награды.",
        parse_mode="HTML", reply_markup=bonuses_menu_kb(is_premium),
    )


@router.callback_query(F.data == "bonus:premium_container")
async def premium_daily_container(callback: CallbackQuery):
    tg_id = callback.from_user.id
    if not await is_user_premium(tg_id):
        await callback.answer("Доступно только с активным Premium BP", show_alert=True)
        return

    conn = await get_db()
    cur = await conn.execute("SELECT premium_container_claimed_at FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    now = datetime.datetime.utcnow()
    if u["premium_container_claimed_at"]:
        last = datetime.datetime.fromisoformat(u["premium_container_claimed_at"])
        elapsed = (now - last).total_seconds()
        if elapsed < DAILY_BONUS_COOLDOWN_SECONDS:
            remaining = int(DAILY_BONUS_COOLDOWN_SECONDS - elapsed)
            h, rem = divmod(remaining, 3600)
            m = rem // 60
            await callback.answer(f"⏳ Следующий премиум-контейнер через {h}ч {m}м.", show_alert=True)
            return

    from handlers.containers import add_container_to_inventory, CONTAINER_LABELS
    await add_container_to_inventory(tg_id, "common", qty=1)
    await conn.execute("UPDATE users SET premium_container_claimed_at = ? WHERE tg_id = ?", (now.isoformat(), tg_id))
    await conn.commit()
    await callback.message.answer(
        f"💎 Ежедневный подарок Premium BP: {CONTAINER_LABELS['common']} добавлен в «📦 Инвентарь»!"
    )
    await callback.answer()


@router.callback_query(F.data == "bonus:daily")
async def daily_bonus_claim(callback: CallbackQuery):
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT last_daily_bonus_at, daily_streak FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    now = datetime.datetime.utcnow()

    streak = u["daily_streak"] or 0
    if u["last_daily_bonus_at"]:
        last = datetime.datetime.fromisoformat(u["last_daily_bonus_at"])
        elapsed = (now - last).total_seconds()
        if elapsed < DAILY_BONUS_COOLDOWN_SECONDS:
            remaining = int(DAILY_BONUS_COOLDOWN_SECONDS - elapsed)
            h, rem = divmod(remaining, 3600)
            m = rem // 60
            await callback.answer(f"⏳ Следующий ежедневный бонус через {h}ч {m}м.", show_alert=True)
            return
        # Серия не прерывается, если зашёл в течение 48 часов с прошлого бонуса —
        # даёт немного свободы, но всё равно стимулирует заходить каждый день.
        streak = streak + 1 if elapsed <= 48 * 3600 else 1
    else:
        streak = 1
    streak = min(streak, 30)

    cur = await conn.execute(
        """SELECT COALESCE(SUM(c.base_value), 0) as total_value FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ?""",
        (tg_id,),
    )
    garage_value = int((await cur.fetchone())["total_value"])

    tier = DAILY_BONUS_TIERS[0]
    for threshold, reward_range, container_key in DAILY_BONUS_TIERS:
        if garage_value >= threshold:
            tier = (threshold, reward_range, container_key)
    _, (lo, hi), container_key = tier

    streak_bonus_pct = min(streak - 1, 10) * 0.05  # +5%/день серии, максимум +50% с 11-го дня
    is_premium = await is_user_premium(tg_id)
    premium_mult = PREMIUM_DAILY_BONUS_MULT if is_premium else 1.0
    silver_reward = int(random.randint(lo, hi) * (1 + streak_bonus_pct) * premium_mult)

    await conn.execute(
        "UPDATE users SET silver = silver + ?, last_daily_bonus_at = ?, daily_streak = ? WHERE tg_id = ?",
        (silver_reward, now.isoformat(), streak, tg_id),
    )
    await add_user_exp(tg_id, 20)

    weekly_gold = WEEKLY_STREAK_GOLD if streak % 7 == 0 else 0
    if weekly_gold:
        await conn.execute("UPDATE users SET gold = gold + ? WHERE tg_id = ?", (weekly_gold, tg_id))

    bonus_text = (
        f"🎰 <b>Ежедневный бонус!</b>\n━━━━━━━━━━━━━━\n"
        f"💰 +{silver_reward:,} серебра\n⭐ +20 XP профиля\n🔥 Серия: {streak} "
        f"{'день' if streak % 10 == 1 and streak % 100 != 11 else 'дней'}"
    ).replace(",", " ")
    if streak_bonus_pct > 0:
        bonus_text += f" (+{streak_bonus_pct*100:.0f}% за серию)"
    if weekly_gold:
        bonus_text += f"\n🏅 Целая неделя подряд! +{weekly_gold} золота"
    if is_premium:
        bonus_text += f"\n💎 Premium BP: x{PREMIUM_DAILY_BONUS_MULT} к награде"

    # Чем больше активов в гараже — тем выше шанс дополнительно получить контейнер.
    if container_key and random.random() < 0.25:
        from handlers.containers import add_container_to_inventory, CONTAINER_LABELS
        await add_container_to_inventory(tg_id, container_key)
        bonus_text += f"\n🎁 Бонусом: {CONTAINER_LABELS.get(container_key, container_key)} (в инвентаре)"

    await conn.commit()
    await callback.message.answer(bonus_text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "bonus:referral")
async def show_referral(callback: CallbackQuery):
    tg_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE referred_by = ? AND referral_confirmed = 1",
                              (tg_id,))
    count = (await cur.fetchone())["cnt"]
    cur = await conn.execute("SELECT referral_bonus_claimed FROM users WHERE tg_id = ?", (tg_id,))
    claimed = (await cur.fetchone())["referral_bonus_claimed"]

    status = "✅ уже получена" if claimed else f"{min(count, REFERRAL_THRESHOLD)}/{REFERRAL_THRESHOLD}"
    ratio = min(count / REFERRAL_THRESHOLD, 1.0)
    filled = int(ratio * 10)
    bar = "🟩" * filled + "⬜️" * (10 - filled)
    await callback.message.answer(
        f"👥 <b>Реферальная система</b>\n━━━━━━━━━━━━━━\n"
        f"Пригласите {REFERRAL_THRESHOLD} друзей — получите секретную машину!\n\n"
        f"🔗 <code>https://t.me/{bot_info.username}?start=ref_{tg_id}</code>\n━━━━━━━━━━━━━━\n"
        f"{bar}\n📊 Приглашено: {count} | Прогресс: {status}",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "bonus:promo")
async def promo_redeem_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🎫 Введите промокод:")
    await state.set_state(PromoRedeemStates.waiting_code)
    await callback.answer()


@router.message(StateFilter(PromoRedeemStates.waiting_code))
async def promo_redeem_check(message: Message, state: FSMContext):
    await state.clear()
    code = message.text.strip().upper()
    tg_id = message.from_user.id
    conn = await get_db()

    cur = await conn.execute("SELECT * FROM promo_codes WHERE code = ?", (code,))
    promo = await cur.fetchone()
    if not promo:
        await message.answer("⚠️ Такого промокода не существует.")
        return

    if promo["expires_at"]:
        if datetime.datetime.utcnow() > datetime.datetime.fromisoformat(promo["expires_at"]):
            await message.answer("⚠️ Срок действия этого промокода истёк.")
            return
    if promo["max_uses"] is not None and promo["uses_count"] >= promo["max_uses"]:
        await message.answer("⚠️ Этот промокод уже исчерпал лимит активаций.")
        return

    cur = await conn.execute("SELECT 1 FROM promo_redemptions WHERE code = ? AND tg_id = ?", (code, tg_id))
    if await cur.fetchone():
        await message.answer("⚠️ Вы уже использовали этот промокод.")
        return

    reward_type = promo["reward_type"]
    reward_value = promo["reward_value"]

    if reward_type in ("silver", "gold", "chips"):
        amount = int(reward_value)
        await conn.execute(f"UPDATE users SET {reward_type} = {reward_type} + ? WHERE tg_id = ?", (amount, tg_id))
        result_text = f"✅ Промокод активирован! Начислено: {amount:,} ({reward_type}).".replace(",", " ")

    elif reward_type == "container":
        from handlers.containers import add_container_to_inventory, CONTAINER_LABELS
        await add_container_to_inventory(tg_id, reward_value)
        result_text = f"✅ Промокод активирован! Получен: {CONTAINER_LABELS.get(reward_value, reward_value)}."

    elif reward_type == "car":
        car_id = int(reward_value)
        if not await has_garage_space(tg_id):
            await message.answer("🚫 Ваш гараж переполнен! Освободите место и введите промокод снова.")
            return
        cur = await conn.execute("SELECT name, brand FROM cars WHERE car_id = ?", (car_id,))
        car = await cur.fetchone()
        if not car:
            await message.answer("⚠️ Машина из этого промокода больше не существует в каталоге.")
            return
        await conn.execute(
            "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
            (tg_id, car_id, datetime.datetime.utcnow().isoformat()),
        )
        result_text = f"✅ Промокод активирован! Получена машина: <b>{car['brand']} {car['name']}</b>."

    else:
        await message.answer("⚠️ Неизвестный тип награды промокода.")
        return

    await conn.execute("UPDATE promo_codes SET uses_count = uses_count + 1 WHERE code = ?", (code,))
    await conn.execute(
        "INSERT INTO promo_redemptions (code, tg_id, redeemed_at) VALUES (?, ?, ?)",
        (code, tg_id, datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()
    await message.answer(result_text, parse_mode="HTML")
