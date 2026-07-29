"""
handlers/lottery.py — 🎟 Ежедневная лотерея.

Все купленные билеты формируют общий банк. Раз в 24 часа бот случайно выбирает
победителя (шанс пропорционален числу купленных билетов) — тот забирает
основную часть банка. Простая, азартная и полностью автоматическая механика:
никто, включая админов, не выбирает победителя вручную.
"""
import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db import get_lottery_state, get_lottery_pot_and_tickets, buy_lottery_tickets
from config import LOTTERY_TICKET_PRICE

router = Router(name="lottery")


def _time_left_str(draws_at: str) -> str:
    ends = datetime.datetime.fromisoformat(draws_at)
    delta = ends - datetime.datetime.utcnow()
    if delta.total_seconds() <= 0:
        return "розыгрыш вот-вот начнётся..."
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60
    return f"{hours}ч {minutes}м"


def _lottery_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎟 Купить 1 билет ({LOTTERY_TICKET_PRICE:,})".replace(",", " "),
                               callback_data="lottery:buy:1")],
        [InlineKeyboardButton(text=f"🎟 Купить 5 билетов ({LOTTERY_TICKET_PRICE*5:,})".replace(",", " "),
                               callback_data="lottery:buy:5")],
        [InlineKeyboardButton(text=f"🎟 Купить 10 билетов ({LOTTERY_TICKET_PRICE*10:,})".replace(",", " "),
                               callback_data="lottery:buy:10")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="lottery:refresh")],
    ])


async def _render_lottery(tg_id: int) -> str:
    state = await get_lottery_state()
    pot, total_tickets, my_tickets = await get_lottery_pot_and_tickets(tg_id)
    chance = f"{(my_tickets / total_tickets * 100):.1f}%" if total_tickets else "0%"

    last_winner_line = ""
    if state["last_winner_tg_id"]:
        last_winner_line = f"\n🏆 Прошлый победитель выиграл {state['last_winner_prize']:,} серебра!".replace(",", " ")

    return (
        f"🎟 <b>Ежедневная лотерея</b>\n━━━━━━━━━━━━━━\n"
        f"💰 Банк: <b>{pot:,}</b> серебра\n"
        f"🎫 Всего билетов: {total_tickets}\n"
        f"⏳ До розыгрыша: {_time_left_str(state['draws_at'])}\n"
        f"━━━━━━━━━━━━━━\n"
        f"Ваши билеты: <b>{my_tickets}</b> (шанс на победу: {chance})"
        f"{last_winner_line}"
    ).replace(",", " ")


@router.message(F.text == "🎟 Лотерея")
async def show_lottery(message: Message):
    text = await _render_lottery(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=_lottery_kb())


@router.callback_query(F.data == "lottery:refresh")
async def refresh_lottery(callback: CallbackQuery):
    text = await _render_lottery(callback.from_user.id)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_lottery_kb())
    except Exception:
        pass
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("lottery:buy:"))
async def buy_tickets(callback: CallbackQuery):
    count = int(callback.data.split(":")[2])
    ok = await buy_lottery_tickets(callback.from_user.id, count)
    if not ok:
        await callback.answer("Недостаточно серебра", show_alert=True)
        return
    await callback.answer(f"✅ Куплено билетов: {count}!")
    text = await _render_lottery(callback.from_user.id)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_lottery_kb())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=_lottery_kb())
