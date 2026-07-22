"""
handlers/duels.py — дуэли между игроками: состав из машин, ставки, расчёт мощи.
Power = sum(car_income * rarity_multiplier) + random(-15%, +15%)
"""
import random
import asyncio
import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery

from db import get_db, add_user_exp
from handlers.battlepass import increment_quest_progress
from keyboards import duel_menu_kb, duel_squad_kb
from config import RARITY_MULTIPLIERS, DUEL_WIN_STREAK_GOLD, DUEL_WIN_STREAK_TARGET

router = Router(name="duels")

MAX_SQUAD_SIZE = 7
DUEL_STAKE_SILVER = 5000
DUEL_RESOLVE_DELAY_SECONDS = 60  # результат приходит не мгновенно, а как будто идёт гонка
_squad_selection: dict[int, set] = {}  # tg_id -> set(entry_id) — временный кэш выбора состава

RACE_STAGES = [
    "🏁 Старт! Машины срываются с места...",
    "🚗💨 Первый круг позади, соперники идут почти вровень...",
    "🌪 Кто-то жмёт на газ на последнем повороте...",
    "🏆 Финишная прямая!",
]


@router.message(F.text == "⚔️ Дуэли")
async def show_duel_menu(message: Message):
    await message.answer(
        (
            "⚔️ <b>Дуэли</b>\n━━━━━━━━━━━━━━\n"
            f"Соберите состав из до {MAX_SQUAD_SIZE} машин и найдите соперника.\n"
            f"💰 Ставка за бой: {DUEL_STAKE_SILVER:,} серебра\n"
            f"⚡ Мощь = сумма (доход × множитель редкости) ± 15%"
        ).replace(",", " "),
        parse_mode="HTML", reply_markup=duel_menu_kb(),
    )


@router.callback_query(F.data == "duel:back")
async def duel_back(callback: CallbackQuery):
    await callback.message.answer(
        (
            "⚔️ <b>Дуэли</b>\n━━━━━━━━━━━━━━\n"
            f"Соберите состав из до {MAX_SQUAD_SIZE} машин и найдите соперника.\n"
            f"💰 Ставка за бой: {DUEL_STAKE_SILVER:,} серебра\n"
            f"⚡ Мощь = сумма (доход × множитель редкости) ± 15%"
        ).replace(",", " "),
        parse_mode="HTML", reply_markup=duel_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "duel:squad")
async def show_squad_builder(callback: CallbackQuery):
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        """SELECT g.id as entry_id, c.name, c.brand, c.rarity FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ? LIMIT 30""",
        (tg_id,),
    )
    cars = [(r["entry_id"], r["name"], r["brand"], r["rarity"]) for r in await cur.fetchall()]
    if not cars:
        await callback.answer("В вашем гараже нет машин", show_alert=True)
        return

    selected = _squad_selection.setdefault(tg_id, set())
    await callback.message.answer(
        f"🛡 Выберите до {MAX_SQUAD_SIZE} машин для состава:",
        reply_markup=duel_squad_kb(cars, selected, tg_id),
    )
    await callback.answer()


NOT_YOUR_SQUAD_TEXT = "🚫 Это не ваш состав — в группе у каждого свой набор машин для дуэли."


@router.callback_query(F.data.startswith("duel:toggle:"))
async def toggle_squad_member(callback: CallbackQuery):
    _, _, owner_id_str, entry_id_str = callback.data.split(":")
    owner_id, entry_id = int(owner_id_str), int(entry_id_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_SQUAD_TEXT, show_alert=True)
        return
    tg_id = owner_id
    selected = _squad_selection.setdefault(tg_id, set())

    if entry_id in selected:
        selected.remove(entry_id)
    elif len(selected) < MAX_SQUAD_SIZE:
        selected.add(entry_id)
    else:
        await callback.answer(f"Максимум {MAX_SQUAD_SIZE} машин в составе", show_alert=True)
        return

    conn = await get_db()
    cur = await conn.execute(
        """SELECT g.id as entry_id, c.name, c.brand, c.rarity FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ? LIMIT 30""",
        (tg_id,),
    )
    cars = [(r["entry_id"], r["name"], r["brand"], r["rarity"]) for r in await cur.fetchall()]
    await callback.message.edit_reply_markup(reply_markup=duel_squad_kb(cars, selected, owner_id))
    await callback.answer()


@router.callback_query(F.data.startswith("duel:save:"))
async def save_squad(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[2])
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_SQUAD_TEXT, show_alert=True)
        return
    selected = _squad_selection.get(owner_id, set())
    if not selected:
        await callback.answer("Состав пуст", show_alert=True)
        return
    await callback.message.answer(f"💾 Состав сохранён: {len(selected)} машин. Теперь найдите соперника!")
    await callback.answer()


async def _calculate_power(tg_id: int, entry_ids: set) -> float:
    if not entry_ids:
        return 0.0
    conn = await get_db()
    placeholders = ",".join("?" * len(entry_ids))
    cur = await conn.execute(
        f"""SELECT c.hourly_income, c.rarity FROM user_garage g
            JOIN cars c ON c.car_id = g.car_id
            WHERE g.id IN ({placeholders}) AND g.tg_id = ?""",
        (*entry_ids, tg_id),
    )
    rows = await cur.fetchall()
    total = sum(r["hourly_income"] * RARITY_MULTIPLIERS.get(r["rarity"], 1.0) for r in rows)
    variance = random.uniform(-0.15, 0.15)
    return total * (1 + variance)


@router.callback_query(F.data == "duel:cancel_search")
async def cancel_duel_search(callback: CallbackQuery):
    tg_id = callback.from_user.id
    conn = await get_db()
    await conn.execute("DELETE FROM duels WHERE player_a = ? AND status = 'waiting'", (tg_id,))
    await conn.commit()
    await callback.message.answer("🚫 Поиск соперника отменён.")
    await callback.answer()


async def _resolve_duel_later(bot: Bot, duel_id: int, tg_id: int, squad: set, opponent_id: int, opponent_squad: set):
    """Считает и объявляет результат боя спустя DUEL_RESOLVE_DELAY_SECONDS — вместо
    мгновенного вердикта, чтобы бой ощущался как настоящая гонка, а не как бросок монетки."""
    await asyncio.sleep(DUEL_RESOLVE_DELAY_SECONDS)

    conn = await get_db()
    my_power = await _calculate_power(tg_id, squad)
    opp_power = await _calculate_power(opponent_id, opponent_squad)

    winner_id = tg_id if my_power >= opp_power else opponent_id
    loser_id = opponent_id if winner_id == tg_id else tg_id

    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (loser_id,))
    row = await cur.fetchone()
    loser_silver = row["silver"] if row else 0
    actual_stake = min(DUEL_STAKE_SILVER, loser_silver)

    await conn.execute(
        "UPDATE duels SET status = 'finished', player_b = ?, winner_id = ? WHERE duel_id = ?",
        (tg_id, winner_id, duel_id),
    )
    await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (actual_stake, winner_id))
    await conn.execute("UPDATE users SET silver = GREATEST(silver - ?, 0) WHERE tg_id = ?",
                        (actual_stake, loser_id))

    # Золото за серию побед подряд — сбрасывается при поражении, так что легко не достанется.
    cur = await conn.execute("SELECT duel_win_streak FROM users WHERE tg_id = ?", (winner_id,))
    row = await cur.fetchone()
    win_streak = (row["duel_win_streak"] if row else 0) + 1
    streak_gold = 0
    if win_streak % DUEL_WIN_STREAK_TARGET == 0:
        streak_gold = DUEL_WIN_STREAK_GOLD
        await conn.execute("UPDATE users SET gold = gold + ? WHERE tg_id = ?", (streak_gold, winner_id))
    await conn.execute("UPDATE users SET duel_win_streak = ? WHERE tg_id = ?", (win_streak, winner_id))
    await conn.execute("UPDATE users SET duel_win_streak = 0 WHERE tg_id = ?", (loser_id,))
    await conn.commit()

    await add_user_exp(winner_id, 150)
    await add_user_exp(loser_id, 40)
    await increment_quest_progress(winner_id, "play_duels", 1)
    await increment_quest_progress(loser_id, "play_duels", 1)

    result_text = (
        f"🏁 <b>Гонка финиширована!</b>\n━━━━━━━━━━━━━━\n"
        f"Ваша мощь: {my_power:,.0f}\nМощь соперника: {opp_power:,.0f}\n━━━━━━━━━━━━━━\n"
        f"{{result}}\n💰 Ставка: {actual_stake:,} серебра".replace(",", " ")
    )
    winner_extra = f"\n🥇 Серия побед: {win_streak}"
    if streak_gold:
        winner_extra += f" — бонус +{streak_gold} золота! 🔥"
    try:
        await bot.send_message(
            tg_id,
            result_text.format(result="🏆 Вы победили!" if winner_id == tg_id else "💀 Вы проиграли.")
            + (winner_extra if winner_id == tg_id else ""),
            parse_mode="HTML",
        )
    except Exception:
        pass
    try:
        await bot.send_message(
            opponent_id,
            result_text.format(result="🏆 Вы победили!" if winner_id == opponent_id else "💀 Вы проиграли.")
            + (winner_extra if winner_id == opponent_id else ""),
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _send_race_narration(bot: Bot, chat_id: int):
    """Отправляет пару сообщений 'по ходу гонки' для атмосферы, не влияя на результат."""
    try:
        msg = await bot.send_message(chat_id, RACE_STAGES[0])
        for stage in RACE_STAGES[1:3]:
            await asyncio.sleep(DUEL_RESOLVE_DELAY_SECONDS / 3)
            try:
                await msg.edit_text(stage)
            except Exception:
                pass
    except Exception:
        pass


@router.callback_query(F.data == "duel:find")
async def find_opponent(callback: CallbackQuery, bot: Bot):
    tg_id = callback.from_user.id
    squad = _squad_selection.get(tg_id, set())
    if not squad:
        await callback.answer("Сначала соберите состав (кнопка «🛡 Собрать состав»)", show_alert=True)
        return

    conn = await get_db()

    # Убираем возможные "зависшие" собственные заявки, чтобы не матчиться самому с собой.
    cur = await conn.execute(
        "SELECT duel_id, player_a FROM duels WHERE status = 'waiting' AND player_a != ? ORDER BY duel_id LIMIT 1",
        (tg_id,),
    )
    waiting_duel = await cur.fetchone()

    if waiting_duel:
        opponent_id = waiting_duel["player_a"]
        opponent_squad = _squad_selection.get(opponent_id, set())

        if not opponent_squad:
            # На всякий случай: если состав соперника потерялся (например, рестарт бота),
            # не даём бою пройти вничью без машин — отменяем его старую заявку и ставим свою.
            await conn.execute("DELETE FROM duels WHERE duel_id = ?", (waiting_duel["duel_id"],))
            await conn.execute(
                "INSERT INTO duels (player_a, stake_silver, status, created_at) VALUES (?, ?, 'waiting', ?)",
                (tg_id, DUEL_STAKE_SILVER, datetime.datetime.utcnow().isoformat()),
            )
            await conn.commit()
            await callback.message.answer("🔎 Ищем соперника... Вы будете уведомлены, когда найдётся противник.")
            await callback.answer()
            return

        await conn.execute("UPDATE duels SET status = 'racing' WHERE duel_id = ?", (waiting_duel["duel_id"],))
        await conn.commit()

        # Составы очищаем сразу — следующий бой нужно собирать заново.
        my_squad = set(squad)
        opp_squad = set(opponent_squad)
        _squad_selection.pop(tg_id, None)
        _squad_selection.pop(opponent_id, None)

        eta = DUEL_RESOLVE_DELAY_SECONDS
        await callback.message.answer(
            f"⚔️ Соперник найден! Гонка началась 🏁\nРезультат придёт примерно через {eta} сек.",
        )
        try:
            await bot.send_message(
                opponent_id,
                f"⚔️ Соперник найден! Гонка началась 🏁\nРезультат придёт примерно через {eta} сек.",
            )
        except Exception:
            pass

        asyncio.create_task(_send_race_narration(bot, tg_id))
        asyncio.create_task(_send_race_narration(bot, opponent_id))
        asyncio.create_task(_resolve_duel_later(
            bot, waiting_duel["duel_id"], tg_id, my_squad, opponent_id, opp_squad,
        ))
    else:
        await conn.execute(
            "INSERT INTO duels (player_a, stake_silver, status, created_at) VALUES (?, ?, 'waiting', ?)",
            (tg_id, DUEL_STAKE_SILVER, datetime.datetime.utcnow().isoformat()),
        )
        await conn.commit()
        await callback.message.answer(
            "🔎 Ищем соперника... Вы будете уведомлены, когда найдётся противник.\n"
            "Можно отменить поиск кнопкой «🚫 Отменить поиск»."
        )
    await callback.answer()
