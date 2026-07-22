"""
handlers/battlepass.py — боевой пропуск: уровни, награды, ежедневные задания.
"""
import datetime
import math
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, LabeledPrice

from db import get_db, add_user_exp, has_garage_space
from keyboards import battle_pass_kb, bp_levels_kb, bp_quests_kb, bp_premium_kb
from config import PREMIUM_BP_OPTIONS, STARS_CURRENCY

router = Router(name="battlepass")

MAX_BP_LEVEL = 50
XP_PER_LEVEL = 20
LEVELS_PER_PAGE = 5
QUESTS_PER_PAGE = 3

DAILY_QUEST_TEMPLATES = [
    ("spend_silver", "Потратить 2,000,000 серебра", 2_000_000),
    ("claim_income", "Собрать доход 4 раза", 4),
    ("play_duels", "Сыграть 3 дуэли", 3),
    ("open_container", "Открыть 1 контейнер", 1),
    ("use_casino", "Сыграть в казино 5 раз", 5),
]

# Премиум-задания — видны ВСЕМ (чтобы мотивировать купить Premium BP), но
# заклеймить их можно только при активном премиуме. Награда выше обычных.
PREMIUM_QUEST_TEMPLATES = [
    ("premium_claim_income", "💎 Собрать доход 8 раз", 8, 15),
    ("premium_open_container", "💎 Открыть 3 контейнера", 3, 20),
]


async def _is_premium_active(bp_row) -> bool:
    if not bp_row["premium_unlocked"]:
        return False
    expires_at = bp_row["premium_expires_at"] if "premium_expires_at" in bp_row.keys() else None
    if not expires_at:
        return True  # бессрочный премиум
    try:
        return datetime.datetime.fromisoformat(expires_at) > datetime.datetime.utcnow()
    except ValueError:
        return True


async def _ensure_daily_quests(tg_id: int) -> None:
    """Гарантирует, что на сегодня у игрока уже созданы записи заданий —
    вызывается и при просмотре вкладки, и при любом прогрессе (сбор дохода,
    дуэли и т.д.), чтобы прогресс не терялся, если игрок ещё не открывал
    вкладку «Задания» сегодня."""
    today = datetime.date.today().isoformat()
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM quests WHERE tg_id = ? AND day_stamp = ?", (tg_id, today))
    if (await cur.fetchone())["cnt"] == 0:
        for key, desc, target in DAILY_QUEST_TEMPLATES:
            await conn.execute(
                """INSERT INTO quests (tg_id, quest_key, description, target, progress, bp_xp_reward, claimed, day_stamp, is_premium)
                   VALUES (?, ?, ?, ?, 0, 5, 0, ?, 0)""",
                (tg_id, key, desc, target, today),
            )
        for key, desc, target, xp in PREMIUM_QUEST_TEMPLATES:
            await conn.execute(
                """INSERT INTO quests (tg_id, quest_key, description, target, progress, bp_xp_reward, claimed, day_stamp, is_premium)
                   VALUES (?, ?, ?, ?, 0, ?, 0, ?, 1)""",
                (tg_id, key, desc, target, xp, today),
            )
        await conn.commit()


async def _reward_for_level(level: int) -> str:
    if level % 10 == 0:
        return "5 000 золота + случайная машина (Rare+)"
    if level % 5 == 0:
        return "1 500 золота + бустер фарма"
    return "500 000 серебра + XP бустер"


async def _grant_level_reward(tg_id: int, level: int) -> str:
    """Выдаёт награду уровня. Золото/серебро — сразу на баланс, всё остальное
    (машины, бустеры) — в «📦 Инвентарь», чтобы игрок мог использовать когда захочет."""
    conn = await get_db()
    if level % 10 == 0:
        await conn.execute("UPDATE users SET gold = gold + 5000 WHERE tg_id = ?", (tg_id,))
        await conn.execute(
            """INSERT INTO inventory (tg_id, item_type, item_name, quantity)
               VALUES (?, 'car_token', 'Rare Car Token', 1)
               ON CONFLICT(tg_id, item_type, item_name) DO UPDATE SET quantity = inventory.quantity + 1""",
            (tg_id,),
        )
        await conn.commit()
        return "🎁 +5 000 золота и жетон машины (Rare+) добавлены в инвентарь!"
    if level % 5 == 0:
        await conn.execute("UPDATE users SET gold = gold + 1500 WHERE tg_id = ?", (tg_id,))
        await conn.execute(
            """INSERT INTO inventory (tg_id, item_type, item_name, quantity)
               VALUES (?, 'booster', 'Фарм-бустер', 1)
               ON CONFLICT(tg_id, item_type, item_name) DO UPDATE SET quantity = inventory.quantity + 1""",
            (tg_id,),
        )
        await conn.commit()
        return "🎁 +1 500 золота и бустер фарма добавлены в инвентарь!"
    await conn.execute("UPDATE users SET silver = silver + 500000 WHERE tg_id = ?", (tg_id,))
    await conn.execute(
        """INSERT INTO inventory (tg_id, item_type, item_name, quantity)
           VALUES (?, 'booster', 'XP бустер', 1)
           ON CONFLICT(tg_id, item_type, item_name) DO UPDATE SET quantity = inventory.quantity + 1""",
        (tg_id,),
    )
    await conn.commit()
    return "🎁 +500 000 серебра и XP-бустер добавлены в инвентарь!"


async def _premium_status_line(bp) -> str:
    if not bp["premium_unlocked"]:
        return "💎 Premium BP: не куплен ❌"
    expires_at = bp["premium_expires_at"] if "premium_expires_at" in bp.keys() else None
    if not expires_at:
        return "💎 Premium BP: <b>активен навсегда</b> ✅"
    try:
        dt = datetime.datetime.fromisoformat(expires_at)
    except ValueError:
        return "💎 Premium BP: <b>активен</b> ✅"
    if dt <= datetime.datetime.utcnow():
        return "💎 Premium BP: <b>истёк</b> ⏱ — продлите в разделе Premium"
    return f"💎 Premium BP: <b>активен</b> ✅ до {dt.strftime('%d.%m.%Y')}"


@router.message(F.text == "🎫 Боевой пропуск")
async def show_battle_pass(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT current_level, xp, premium_unlocked, premium_expires_at FROM battle_pass WHERE tg_id = ?",
                              (message.from_user.id,))
    bp = await cur.fetchone()
    cur = await conn.execute("SELECT title, duration_days, image_url, start_date FROM active_season WHERE is_active = 1")
    season = await cur.fetchone()

    started = datetime.datetime.fromisoformat(season["start_date"])
    days_left = max(0, season["duration_days"] - (datetime.datetime.utcnow() - started).days)

    progress_ratio = min(bp["xp"] / XP_PER_LEVEL, 1.0)
    filled = int(progress_ratio * 10)
    progress_bar = "🟩" * filled + "⬜️" * (10 - filled)
    premium_line = await _premium_status_line(bp)

    caption = (
        f"🎫 <b>{season['title']}</b>\n"
        f"⏳ Осталось дней сезона: {days_left}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏅 Уровень {bp['current_level']}/{MAX_BP_LEVEL}\n"
        f"{progress_bar}\n"
        f"{bp['xp']}/{XP_PER_LEVEL} XP до следующего уровня\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{premium_line}"
    )

    if season["image_url"]:
        try:
            await message.answer_photo(season["image_url"], caption=caption, parse_mode="HTML",
                                        reply_markup=battle_pass_kb(1, math.ceil(MAX_BP_LEVEL / LEVELS_PER_PAGE)))
            return
        except Exception:
            pass
    await message.answer(caption, parse_mode="HTML",
                          reply_markup=battle_pass_kb(1, math.ceil(MAX_BP_LEVEL / LEVELS_PER_PAGE)))


@router.callback_query(F.data == "bp:back")
async def bp_back(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT current_level, xp, premium_unlocked, premium_expires_at FROM battle_pass WHERE tg_id = ?",
                              (callback.from_user.id,))
    bp = await cur.fetchone()
    cur = await conn.execute("SELECT title, duration_days, start_date FROM active_season WHERE is_active = 1")
    season = await cur.fetchone()

    started = datetime.datetime.fromisoformat(season["start_date"])
    days_left = max(0, season["duration_days"] - (datetime.datetime.utcnow() - started).days)
    progress_ratio = min(bp["xp"] / XP_PER_LEVEL, 1.0)
    filled = int(progress_ratio * 10)
    progress_bar = "🟩" * filled + "⬜️" * (10 - filled)
    premium_line = await _premium_status_line(bp)

    caption = (
        f"🎫 <b>{season['title']}</b>\n"
        f"⏳ Осталось дней сезона: {days_left}\n━━━━━━━━━━━━━━━\n"
        f"🏅 Уровень {bp['current_level']}/{MAX_BP_LEVEL}\n{progress_bar}\n"
        f"{bp['xp']}/{XP_PER_LEVEL} XP до следующего уровня\n━━━━━━━━━━━━━━━\n{premium_line}"
    )
    await callback.message.answer(caption, parse_mode="HTML",
                                   reply_markup=battle_pass_kb(1, math.ceil(MAX_BP_LEVEL / LEVELS_PER_PAGE)))
    await callback.answer()


@router.callback_query(F.data.startswith("bp:levels:"))
async def show_bp_levels(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    total_pages = math.ceil(MAX_BP_LEVEL / LEVELS_PER_PAGE)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * LEVELS_PER_PAGE + 1
    end = min(start + LEVELS_PER_PAGE - 1, MAX_BP_LEVEL)

    conn = await get_db()
    cur = await conn.execute("SELECT current_level FROM battle_pass WHERE tg_id = ?", (callback.from_user.id,))
    bp = await cur.fetchone()
    cur = await conn.execute("SELECT level FROM bp_claimed_levels WHERE tg_id = ?", (callback.from_user.id,))
    claimed_levels = {r["level"] for r in await cur.fetchall()}

    lines = [f"🎁 <b>Награды {start}/{end}</b> (стр. {page}/{total_pages})\n"]
    claimable = []
    for lvl in range(start, end + 1):
        reward = await _reward_for_level(lvl)
        if lvl in claimed_levels:
            status = "✅ получено"
        elif lvl <= bp["current_level"]:
            status = "🎁 доступно"
            claimable.append(lvl)
        else:
            status = "🔒 заблокировано"
        lines.append(f"Ур.{lvl}: {reward} — {status}")

    text = "\n".join(lines)
    kb = bp_levels_kb(page, total_pages, claimable)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("bp:claim:"))
async def claim_bp_level(callback: CallbackQuery):
    level = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT current_level FROM battle_pass WHERE tg_id = ?", (tg_id,))
    bp = await cur.fetchone()
    if level > bp["current_level"]:
        await callback.answer("Уровень ещё не открыт", show_alert=True)
        return

    cur = await conn.execute("SELECT 1 FROM bp_claimed_levels WHERE tg_id = ? AND level = ?", (tg_id, level))
    if await cur.fetchone():
        await callback.answer("Награда за этот уровень уже получена", show_alert=True)
        return

    reward_text = await _grant_level_reward(tg_id, level)
    await conn.execute("INSERT INTO bp_claimed_levels (tg_id, level) VALUES (?, ?)", (tg_id, level))
    await conn.commit()
    await callback.message.answer(f"🎉 Награда за уровень {level} получена!\n{reward_text}")
    await callback.answer()


@router.callback_query(F.data.startswith("bp:quests:"))
async def show_bp_quests(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    today = datetime.date.today().isoformat()

    await _ensure_daily_quests(tg_id)
    conn = await get_db()

    cur = await conn.execute("SELECT premium_unlocked, premium_expires_at FROM battle_pass WHERE tg_id = ?", (tg_id,))
    bp_row = await cur.fetchone()
    premium_active = await _is_premium_active(bp_row) if bp_row else False

    cur = await conn.execute(
        "SELECT quest_id, quest_key, description, target, progress, claimed, is_premium FROM quests "
        "WHERE tg_id = ? AND day_stamp = ? ORDER BY is_premium, quest_id", (tg_id, today))
    quests = await cur.fetchall()

    total_pages = math.ceil(len(quests) / QUESTS_PER_PAGE)
    page = min(max(page, 1), max(total_pages, 1))
    start = (page - 1) * QUESTS_PER_PAGE
    page_quests = quests[start:start + QUESTS_PER_PAGE]

    lines = [f"📜 <b>Задания дня</b> (стр. {page}/{total_pages})\n"]
    claimable = []
    for q in page_quests:
        if q["is_premium"] and not premium_active:
            state = "🔒 Только Premium BP"
        elif q["claimed"]:
            state = "Claimed ✅"
        elif q["progress"] >= q["target"]:
            state = "Готово! 🟢"
        else:
            state = "Active 🔵"
        lines.append(f"{q['description']} [{q['progress']}/{q['target']}] — {state}")
        if q["progress"] >= q["target"] and not q["claimed"] and (not q["is_premium"] or premium_active):
            claimable.append(q["quest_key"])
    if any(q["is_premium"] for q in quests) and not premium_active:
        lines.append("\n💎 Купите Premium BP, чтобы получать награды за задания с 🔒.")

    text = "\n".join(lines)
    kb = bp_quests_kb(page, max(total_pages, 1), claimable)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("bp:questclaim:"))
async def claim_bp_quest(callback: CallbackQuery):
    quest_key = callback.data.split(":")[2]
    tg_id = callback.from_user.id
    today = datetime.date.today().isoformat()

    conn = await get_db()
    cur = await conn.execute(
        "SELECT quest_id, progress, target, claimed, bp_xp_reward, is_premium FROM quests "
        "WHERE tg_id = ? AND quest_key = ? AND day_stamp = ?",
        (tg_id, quest_key, today),
    )
    quest = await cur.fetchone()
    if not quest or quest["claimed"] or quest["progress"] < quest["target"]:
        await callback.answer("Задание ещё не выполнено", show_alert=True)
        return

    if quest["is_premium"]:
        cur = await conn.execute("SELECT premium_unlocked, premium_expires_at FROM battle_pass WHERE tg_id = ?", (tg_id,))
        bp_row = await cur.fetchone()
        if not await _is_premium_active(bp_row):
            await callback.answer("🔒 Это задание доступно только с Premium BP", show_alert=True)
            return

    await conn.execute("UPDATE quests SET claimed = 1 WHERE quest_id = ?", (quest["quest_id"],))
    await _add_bp_xp(tg_id, quest["bp_xp_reward"])
    await conn.commit()
    await add_user_exp(tg_id, 30)
    await callback.message.answer(f"✅ Задание выполнено! +{quest['bp_xp_reward']} XP боевого пропуска.")
    await callback.answer()


async def _add_bp_xp(tg_id: int, xp_amount: int):
    conn = await get_db()
    cur = await conn.execute("SELECT current_level, xp FROM battle_pass WHERE tg_id = ?", (tg_id,))
    bp = await cur.fetchone()
    new_xp = bp["xp"] + xp_amount
    new_level = bp["current_level"]
    while new_xp >= XP_PER_LEVEL and new_level < MAX_BP_LEVEL:
        new_xp -= XP_PER_LEVEL
        new_level += 1
    await conn.execute("UPDATE battle_pass SET xp = ?, current_level = ? WHERE tg_id = ?",
                        (new_xp, new_level, tg_id))
    await conn.commit()


async def increment_quest_progress(tg_id: int, quest_key: str, amount: int = 1):
    """Вызывается из других модулей (гараж, казино, дуэли, контейнеры) для обновления
    прогресса заданий. Сама создаёт задания дня, если их ещё нет (игрок мог ни разу не
    открывать вкладку «Задания» сегодня) — иначе прогресс терялся."""
    await _ensure_daily_quests(tg_id)
    today = datetime.date.today().isoformat()
    conn = await get_db()
    await conn.execute(
        """UPDATE quests SET progress = LEAST(progress + ?, target)
           WHERE tg_id = ? AND quest_key = ? AND day_stamp = ? AND claimed = 0""",
        (amount, tg_id, quest_key, today),
    )
    # Обновляем и премиум-версию того же действия (если она сегодня есть) —
    # например claim_income также продвигает premium_claim_income.
    premium_key = f"premium_{quest_key}"
    await conn.execute(
        """UPDATE quests SET progress = LEAST(progress + ?, target)
           WHERE tg_id = ? AND quest_key = ? AND day_stamp = ? AND claimed = 0""",
        (amount, tg_id, premium_key, today),
    )
    await conn.commit()


@router.callback_query(F.data.startswith("bp:buyprem:"))
async def buy_premium_bp(callback: CallbackQuery, bot: Bot):
    option = callback.data.split(":")[2]
    opt = PREMIUM_BP_OPTIONS.get(option)
    if not opt:
        await callback.answer("Вариант не найден", show_alert=True)
        return
    import json
    payload = json.dumps({"premium_bp_option": option, "tg_id": callback.from_user.id})
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Premium Battle Pass — {opt['label']}",
        description="Открывает премиум-награды и премиум-задания текущего сезона.",
        payload=payload,
        provider_token="",
        currency=STARS_CURRENCY,
        prices=[LabeledPrice(label=f"Premium BP ({opt['label']})", amount=opt["price"])],
    )
    await callback.answer()


@router.callback_query(F.data == "bp:premium")
async def bp_premium_menu(callback: CallbackQuery):
    await callback.message.answer(
        "💎 <b>Premium Battle Pass</b>\nОткройте премиум-награды или купите уровни напрямую.",
        parse_mode="HTML", reply_markup=bp_premium_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bp:buy:"))
async def bp_buy_levels(callback: CallbackQuery):
    option = callback.data.split(":")[2]
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT current_level, gold FROM battle_pass bp JOIN users u ON u.tg_id = bp.tg_id WHERE bp.tg_id = ?",
                              (tg_id,))
    row = await cur.fetchone()

    cost_per_level_gold = 50
    if option == "max":
        levels_to_buy = min(MAX_BP_LEVEL - row["current_level"], row["gold"] // cost_per_level_gold)
    else:
        levels_to_buy = min(int(option), MAX_BP_LEVEL - row["current_level"])

    total_cost = levels_to_buy * cost_per_level_gold
    if levels_to_buy <= 0 or row["gold"] < total_cost:
        await callback.answer("Недостаточно золота или максимальный уровень достигнут", show_alert=True)
        return

    await conn.execute("UPDATE users SET gold = gold - ? WHERE tg_id = ?", (total_cost, tg_id))
    await conn.execute("UPDATE battle_pass SET current_level = current_level + ? WHERE tg_id = ?",
                        (levels_to_buy, tg_id))
    await conn.commit()
    await callback.message.answer(f"✅ Куплено {levels_to_buy} уровень(ей) боевого пропуска за {total_cost} золота.")
    await callback.answer()
