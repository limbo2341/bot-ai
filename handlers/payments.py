"""
handlers/payments.py — нативные платежи Telegram Stars (XTR).
Обрабатывает создание инвойсов, pre_checkout_query и успешные платежи.
"""
import datetime
import json
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, LabeledPrice,
)

from db import get_db
from keyboards import shop_kb
from config import STAR_PACKS, STARS_CURRENCY, PREMIUM_BP_OPTIONS
from handlers.containers import grant_container_from_payment

router = Router(name="payments")


@router.message(F.text == "🛒 Магазин")
async def show_shop(message: Message):
    await message.answer(
        "🛒 <b>Магазин</b>\n━━━━━━━━━━━━━━\nВыберите набор для покупки за Telegram Stars:",
        parse_mode="HTML",
        reply_markup=shop_kb(),
    )


@router.callback_query(F.data.startswith("shop:buy:"))
async def send_pack_invoice(callback: CallbackQuery, bot: Bot):
    pack_key = callback.data.split(":")[2]
    pack = STAR_PACKS.get(pack_key)
    if not pack:
        await callback.answer("Товар не найден", show_alert=True)
        return

    payload = json.dumps({"pack": pack_key, "tg_id": callback.from_user.id})

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=pack["title"],
        description=pack["description"],
        payload=payload,
        provider_token="",  # для Stars provider_token должен быть пустой строкой
        currency=STARS_CURRENCY,
        prices=[LabeledPrice(label=pack["title"], amount=pack["price"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    """Проверяем, что покупатель не забанен, прежде чем подтвердить оплату."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT is_banned FROM users WHERE tg_id = ?", (pre_checkout_query.from_user.id,)
    )
    row = await cur.fetchone()
    if row and row["is_banned"]:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id, ok=False, error_message="Ваш аккаунт заблокирован."
        )
        return
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payment = message.successful_payment
    tg_id = message.from_user.id
    try:
        data = json.loads(payment.invoice_payload)
    except (json.JSONDecodeError, TypeError):
        data = {}
    pack_key = data.get("pack")
    container_key = data.get("container")
    container_qty = int(data.get("qty", 1))
    premium_bp_option = data.get("premium_bp_option")
    pack = STAR_PACKS.get(pack_key)

    conn = await get_db()
    await conn.execute(
        """INSERT INTO payments (tg_id, stars_amount, payload, status, timestamp)
           VALUES (?, ?, ?, 'completed', ?)""",
        (tg_id, payment.total_amount, payment.invoice_payload, datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()

    if container_key:
        result_text = await grant_container_from_payment(tg_id, container_key, qty=container_qty)
        await message.answer(result_text, parse_mode="HTML")
        return

    if premium_bp_option:
        opt = PREMIUM_BP_OPTIONS.get(premium_bp_option)
        if opt:
            if opt["days"] is None:
                new_expiry = None  # бессрочно (до конца сезона)
            else:
                cur = await conn.execute(
                    "SELECT premium_expires_at FROM battle_pass WHERE tg_id = ?", (tg_id,)
                )
                row = await cur.fetchone()
                now = datetime.datetime.utcnow()
                current_expiry = None
                if row and row["premium_expires_at"]:
                    try:
                        current_expiry = datetime.datetime.fromisoformat(row["premium_expires_at"])
                    except ValueError:
                        current_expiry = None
                base = current_expiry if current_expiry and current_expiry > now else now
                new_expiry = (base + datetime.timedelta(days=opt["days"])).isoformat()
            await conn.execute(
                "UPDATE battle_pass SET premium_unlocked = 1, premium_expires_at = ? WHERE tg_id = ?",
                (new_expiry, tg_id),
            )
            await conn.commit()
            when = "бессрочно (до конца сезона)" if opt["days"] is None else f"на {opt['label']}"
            await message.answer(f"🎉 Premium Battle Pass активирован {when}! Наслаждайтесь премиум-наградами.")
        return

    if not pack:
        await conn.commit()
        await message.answer("⚠️ Платёж получен, но пакет не распознан. Обратитесь к администрации.")
        return

    silver = pack.get("silver", 0)
    gold = pack.get("gold", 0)
    await conn.execute(
        "UPDATE users SET silver = silver + ?, gold = gold + ? WHERE tg_id = ?",
        (silver, gold, tg_id),
    )

    async def _grant_tokens(name: str, qty: int):
        await conn.execute(
            """INSERT INTO inventory (tg_id, item_type, item_name, quantity)
               VALUES (?, 'car_token', ?, ?)
               ON CONFLICT(tg_id, item_type, item_name) DO UPDATE SET quantity = inventory.quantity + ?""",
            (tg_id, name, qty, qty),
        )

    if pack_key == "starter":
        await _grant_tokens("Common Car Token", pack.get("common_packs", 0))
    elif pack_key == "pro":
        await _grant_tokens("Uncommon Car Token", pack.get("uncommon_cars", 0))
        await _grant_tokens("Rare Car Token", pack.get("rare_cars", 0))

    await conn.commit()

    await message.answer(
        f"🎉 Спасибо за покупку <b>{pack['title']}</b>!\n"
        f"Начислено: {silver:,} серебра, {gold:,} золота.".replace(",", " "),
        parse_mode="HTML",
    )
