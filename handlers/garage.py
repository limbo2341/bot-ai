"""
handlers/garage.py — фарм серебра, список гаража, продажа машин,
улучшения фарма/ангара/часов накопления.
"""
import datetime
import math
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile

from db import get_db, add_user_exp, send_car_photo, is_user_premium
from handlers.battlepass import increment_quest_progress
from keyboards import (
    garage_list_kb, garage_car_detail_kb, garage_sellmode_kb, upgrades_kb,
    farm_upgrade_kb, storage_upgrade_kb, garage_slot_purchase_kb,
)
from config import (
    BASE_COOLDOWN_SECONDS, FARM_UPGRADE_COSTS, FARM_UPGRADE_STEP_SECONDS,
    STORAGE_UPGRADE_COSTS, GARAGE_SLOT_PRICE_SILVER, RARITY_EMOJI,
    CLAN_MAX_LEVEL, CLAN_INCOME_BONUS_PER_LEVEL,
)

router = Router(name="garage")

PAGE_SIZE = 8
_sell_selection: dict[int, set] = {}  # tg_id -> set(entry_id) — временный выбор машин на продажу


def _current_cooldown_seconds(cooldown_reduction_level: int) -> int:
    return max(
        BASE_COOLDOWN_SECONDS - cooldown_reduction_level * FARM_UPGRADE_STEP_SECONDS,
        BASE_COOLDOWN_SECONDS - 10 * FARM_UPGRADE_STEP_SECONDS,
    )


# ---------------------------------------------------------------- Гараж
@router.message(F.text == "🚗 Гараж")
async def show_garage(message: Message):
    await _render_garage_page(message, message.from_user.id, page=1)


async def _render_garage_page(target: Message, tg_id: int, page: int, edit: bool = False):
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM user_garage WHERE tg_id = ?", (tg_id,))
    total = (await cur.fetchone())["cnt"]
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * PAGE_SIZE

    cur = await conn.execute(
        """SELECT g.id as entry_id, c.car_id, c.name, c.brand, c.rarity, c.tier, c.hourly_income
           FROM user_garage g JOIN cars c ON c.car_id = g.car_id
           WHERE g.tg_id = ? ORDER BY g.id DESC LIMIT ? OFFSET ?""",
        (tg_id, PAGE_SIZE, offset),
    )
    rows = await cur.fetchall()

    if total == 0:
        await target.answer("🚗 Ваш гараж пуст. Откройте контейнеры или купите машину в магазине!")
        return

    cars = [(r["entry_id"], r["car_id"], r["name"], r["brand"], r["rarity"], r["tier"], r["hourly_income"])
            for r in rows]
    cur = await conn.execute(
        """SELECT COALESCE(SUM(c.hourly_income), 0) as income FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ?""",
        (tg_id,),
    )
    total_income = int((await cur.fetchone())["income"])
    text = (
        f"🚗 <b>Ваш гараж</b>\n━━━━━━━━━━━━━━\n"
        f"Машин: {total} | Доход: {total_income:,} серебра/ч\n"
        f"Страница {page}/{total_pages}"
    ).replace(",", " ")
    kb = garage_list_kb(cars, page, total_pages, tg_id)
    if edit:
        try:
            await target.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            pass  # сообщение могло стать фото или устареть — пришлём новое
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


NOT_YOUR_GARAGE_TEXT = ("🚫 Это не ваш гараж. В группе бот показывает каждому только его собственные машины — "
                        "напишите «Гараж», чтобы открыть свой.")


@router.callback_query(F.data.startswith("garage:page:"))
async def garage_page_nav(callback: CallbackQuery):
    _, _, owner_id_str, page_str = callback.data.split(":")
    owner_id, page = int(owner_id_str), int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    await _render_garage_page(callback.message, callback.from_user.id, page, edit=True)
    await callback.answer()


async def _render_sellmode_page(callback: CallbackQuery, owner_id: int, page: int):
    tg_id = owner_id
    conn = await get_db()
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM user_garage WHERE tg_id = ?", (tg_id,))
    total = (await cur.fetchone())["cnt"]
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * PAGE_SIZE

    cur = await conn.execute(
        """SELECT g.id as entry_id, c.car_id, c.name, c.brand, c.rarity, c.tier, c.hourly_income
           FROM user_garage g JOIN cars c ON c.car_id = g.car_id
           WHERE g.tg_id = ? ORDER BY g.id DESC LIMIT ? OFFSET ?""",
        (tg_id, PAGE_SIZE, offset),
    )
    rows = await cur.fetchall()
    if total == 0:
        await callback.message.answer("🚗 Ваш гараж пуст.")
        return

    cars = [(r["entry_id"], r["car_id"], r["name"], r["brand"], r["rarity"], r["tier"], r["hourly_income"])
            for r in rows]
    selected = _sell_selection.setdefault(tg_id, set())
    text = "🗑 <b>Режим продажи</b>\nОтметьте машины, которые хотите продать, затем нажмите «Продать выбранные»."
    kb = garage_sellmode_kb(cars, selected, page, total_pages, owner_id)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("garage:sellmode:"))
async def garage_sellmode(callback: CallbackQuery):
    _, _, owner_id_str, page_str = callback.data.split(":")
    owner_id, page = int(owner_id_str), int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    await _render_sellmode_page(callback, owner_id, page)
    await callback.answer()


@router.callback_query(F.data.startswith("garage:selltoggle:"))
async def garage_selltoggle(callback: CallbackQuery):
    _, _, owner_id_str, entry_id_str, page_str = callback.data.split(":")
    owner_id, entry_id, page = int(owner_id_str), int(entry_id_str), int(page_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    selected = _sell_selection.setdefault(owner_id, set())
    if entry_id in selected:
        selected.remove(entry_id)
    else:
        selected.add(entry_id)
    await _render_sellmode_page(callback, owner_id, page)
    await callback.answer()


@router.callback_query(F.data.startswith("garage:sellclear:"))
async def garage_sellclear(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[2])
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    _sell_selection.pop(owner_id, None)
    await _render_sellmode_page(callback, owner_id, 1)
    await callback.answer("Выбор сброшен")


@router.callback_query(F.data.startswith("garage:sellconfirm:"))
async def garage_sellconfirm(callback: CallbackQuery):
    owner_id = int(callback.data.split(":")[2])
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    tg_id = owner_id
    selected = _sell_selection.get(tg_id, set())
    if not selected:
        await callback.answer("Вы ничего не выбрали", show_alert=True)
        return

    conn = await get_db()
    placeholders = ",".join("?" * len(selected))
    cur = await conn.execute(
        f"""SELECT g.id as entry_id, c.base_value, c.brand, c.name FROM user_garage g
            JOIN cars c ON c.car_id = g.car_id
            WHERE g.id IN ({placeholders}) AND g.tg_id = ?""",
        (*selected, tg_id),
    )
    rows = await cur.fetchall()
    if not rows:
        await callback.answer("Эти машины уже не найдены в гараже", show_alert=True)
        _sell_selection.pop(tg_id, None)
        return

    total_value = sum(r["base_value"] for r in rows)
    entry_ids = [r["entry_id"] for r in rows]
    placeholders2 = ",".join("?" * len(entry_ids))
    await conn.execute(
        f"DELETE FROM user_garage WHERE id IN ({placeholders2}) AND tg_id = ?", (*entry_ids, tg_id)
    )
    await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (total_value, tg_id))
    await conn.commit()
    _sell_selection.pop(tg_id, None)

    await callback.message.answer(
        f"💵 Продано {len(rows)} машин(ы) за {total_value:,} серебра.".replace(",", " ")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("garage:view:"))
async def garage_view_car(callback: CallbackQuery):
    _, _, owner_id_str, entry_id_str = callback.data.split(":")
    owner_id, entry_id = int(owner_id_str), int(entry_id_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    conn = await get_db()
    cur = await conn.execute(
        """SELECT g.is_favorite, c.car_id, c.name, c.brand, c.rarity, c.tier, c.hourly_income,
                  c.base_value, c.image_url, c.telegram_file_id
           FROM user_garage g JOIN cars c ON c.car_id = g.car_id
           WHERE g.id = ? AND g.tg_id = ?""",
        (entry_id, owner_id),
    )
    car = await cur.fetchone()
    if not car:
        await callback.answer("🚫 Машина не найдена.", show_alert=True)
        return
    emoji = RARITY_EMOJI.get(car["rarity"], "⚪")
    fav_note = "❤️ В избранном" if car["is_favorite"] else ""
    text = (
        f"{emoji} <b>{car['brand']} {car['name']}</b>\n━━━━━━━━━━━━━━\n"
        f"Редкость: <b>{car['rarity']}</b> | Тир: <b>{car['tier']}</b>\n"
        f"💵 Доход: {car['hourly_income']:,} серебра/ч\n"
        f"🏷 Цена продажи: {car['base_value']:,} серебра" + (f"\n{fav_note}" if fav_note else "")
    ).replace(",", " ")
    kb = garage_car_detail_kb(entry_id, bool(car["is_favorite"]), owner_id)
    sent_photo = await send_car_photo(
        callback.message, car["car_id"], car["image_url"], car["telegram_file_id"],
        caption=text, parse_mode="HTML", reply_markup=kb,
    )
    if not sent_photo:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("garage:fav:"))
async def garage_toggle_fav(callback: CallbackQuery):
    _, _, owner_id_str, entry_id_str = callback.data.split(":")
    owner_id, entry_id = int(owner_id_str), int(entry_id_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    conn = await get_db()
    cur = await conn.execute("SELECT is_favorite FROM user_garage WHERE id = ? AND tg_id = ?",
                              (entry_id, owner_id))
    row = await cur.fetchone()
    if not row:
        await callback.answer("🚫 Машина не найдена.", show_alert=True)
        return
    new_val = 0 if row["is_favorite"] else 1
    await conn.execute("UPDATE user_garage SET is_favorite = ? WHERE id = ?", (new_val, entry_id))
    await conn.commit()
    await callback.answer("Обновлено!")


@router.callback_query(F.data.startswith("garage:sell:"))
async def garage_sell_car(callback: CallbackQuery):
    _, _, owner_id_str, entry_id_str = callback.data.split(":")
    owner_id, entry_id = int(owner_id_str), int(entry_id_str)
    if callback.from_user.id != owner_id:
        await callback.answer(NOT_YOUR_GARAGE_TEXT, show_alert=True)
        return
    tg_id = owner_id
    conn = await get_db()
    cur = await conn.execute(
        """SELECT c.base_value, c.name, c.brand FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.id = ? AND g.tg_id = ?""",
        (entry_id, tg_id),
    )
    car = await cur.fetchone()
    if not car:
        await callback.answer("🚫 Машина не найдена.", show_alert=True)
        return
    await conn.execute("DELETE FROM user_garage WHERE id = ?", (entry_id,))
    await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (car["base_value"], tg_id))
    await conn.commit()
    await callback.message.answer(
        f"💵 <b>Продано!</b>\n{car['brand']} {car['name']} → +{car['base_value']:,} серебра".replace(",", " "),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------- Фарм / Клейм
@router.message(F.text == "💰 Собрать")
async def claim_silver(message: Message):
    tg_id = message.from_user.id
    conn = await get_db()
    cur = await conn.execute(
        """SELECT last_claim_at, cooldown_reduction, max_farming_hours, silver, clan_id FROM users
           WHERE tg_id = ?""",
        (tg_id,),
    )
    u = await cur.fetchone()

    cur = await conn.execute(
        """SELECT COALESCE(SUM(c.hourly_income), 0) as income
           FROM user_garage g JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ?""",
        (tg_id,),
    )
    income = int((await cur.fetchone())["income"])

    if income == 0:
        await message.answer("⚠️ У вас нет машин в гараже, приносящих доход.")
        return

    now = datetime.datetime.utcnow()
    last_claim = datetime.datetime.fromisoformat(u["last_claim_at"]) if u["last_claim_at"] else now
    elapsed_seconds = max((now - last_claim).total_seconds(), 0)
    cooldown = _current_cooldown_seconds(u["cooldown_reduction"])

    if elapsed_seconds < cooldown:
        remaining = int(cooldown - elapsed_seconds)
        h, rem = divmod(remaining, 3600)
        m, s = divmod(rem, 60)
        await message.answer(f"⏳ <b>Фарм ещё не готов</b>\nОсталось: {h}ч {m}м {s}с.", parse_mode="HTML")
        return

    capped_hours = min(elapsed_seconds / 3600, u["max_farming_hours"])
    earned = int(income * capped_hours)

    clan_bonus_pct = 0.0
    if u["clan_id"]:
        cur = await conn.execute("SELECT clan_level FROM clans WHERE clan_id = ?", (u["clan_id"],))
        clan_row = await cur.fetchone()
        if clan_row:
            clan_bonus_pct = min(clan_row["clan_level"], CLAN_MAX_LEVEL) * CLAN_INCOME_BONUS_PER_LEVEL

    premium_bonus_pct = PREMIUM_INCOME_BONUS if await is_user_premium(tg_id) else 0.0
    earned = int(earned * (1 + clan_bonus_pct + premium_bonus_pct))

    await conn.execute(
        "UPDATE users SET silver = silver + ?, last_claim_at = ? WHERE tg_id = ?",
        (earned, now.isoformat(), tg_id),
    )
    await conn.commit()
    await increment_quest_progress(tg_id, "claim_income", 1)

    exp_gained = max(earned // 200, 1)
    new_level, leveled_up = await add_user_exp(tg_id, exp_gained)

    text = (
        f"💰 <b>Доход собран!</b>\n━━━━━━━━━━━━━━\n"
        f"+{earned:,} серебра\n"
        f"Баланс: {u['silver'] + earned:,} серебра"
    ).replace(",", " ")
    if clan_bonus_pct > 0:
        text += f"\n🏛 Бонус клана: +{clan_bonus_pct*100:.0f}%"
    if premium_bonus_pct > 0:
        text += f"\n💎 Бонус Premium BP: +{premium_bonus_pct*100:.0f}%"
    if leveled_up:
        text += f"\n\n🆙 <b>Новый уровень профиля: {new_level}!</b>"
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------- Улучшения
@router.message(F.text == "⚙️ Улучшения")
async def show_upgrades_menu(message: Message):
    await message.answer("⚙️ <b>Меню улучшений</b>\n━━━━━━━━━━━━━━\nВыберите категорию:", parse_mode="HTML",
                          reply_markup=upgrades_kb())


@router.callback_query(F.data == "upg:back")
async def upg_back(callback: CallbackQuery):
    await callback.message.answer("⚙️ <b>Меню улучшений</b>\n━━━━━━━━━━━━━━\nВыберите категорию:",
                                   parse_mode="HTML", reply_markup=upgrades_kb())
    await callback.answer()


@router.callback_query(F.data == "upg:farm")
async def upg_farm_menu(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT cooldown_reduction, silver, gold FROM users WHERE tg_id = ?",
                              (callback.from_user.id,))
    u = await cur.fetchone()
    current_level = u["cooldown_reduction"]
    cooldown = _current_cooldown_seconds(current_level)
    h, rem = divmod(cooldown, 3600)
    m = rem // 60

    if current_level >= 10:
        await callback.message.answer(
            f"⚡ <b>Улучшение фарма</b>\n━━━━━━━━━━━━━━\n"
            f"🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n"
            f"Кулдаун: {h}ч {m}м (МАКСИМУМ 10/10)",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    next_level = current_level + 1
    cost_silver, cost_gold = FARM_UPGRADE_COSTS[next_level]
    can_afford = u["silver"] >= cost_silver and u["gold"] >= cost_gold
    bar = "🟩" * current_level + "⬜️" * (10 - current_level)
    await callback.message.answer(
        f"⚡ <b>Улучшение фарма</b>\n━━━━━━━━━━━━━━\n"
        f"Уровень {current_level}/10\n{bar}\n"
        f"Текущий кулдаун: {h}ч {m}м\n━━━━━━━━━━━━━━\n"
        f"Ур. {next_level}: {cost_silver:,} серебра + {cost_gold} золота".replace(",", " "),
        parse_mode="HTML",
        reply_markup=farm_upgrade_kb(next_level, can_afford),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("upg:farm:buy:"))
async def upg_farm_buy(callback: CallbackQuery):
    level = int(callback.data.split(":")[3])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT cooldown_reduction, silver, gold FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if u["cooldown_reduction"] + 1 != level:
        await callback.answer("Некорректный уровень улучшения", show_alert=True)
        return
    cost_silver, cost_gold = FARM_UPGRADE_COSTS[level]
    if u["silver"] < cost_silver or u["gold"] < cost_gold:
        await callback.answer("Недостаточно средств", show_alert=True)
        return
    await conn.execute(
        "UPDATE users SET silver = silver - ?, gold = gold - ?, cooldown_reduction = ? WHERE tg_id = ?",
        (cost_silver, cost_gold, level, tg_id),
    )
    await conn.commit()
    if cost_silver:
        await increment_quest_progress(tg_id, "spend_silver", cost_silver)
    await callback.message.answer(f"✅ <b>Фарм улучшен до уровня {level}/10!</b>", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "upg:garage")
async def upg_garage_menu(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT slots_limit, silver FROM users WHERE tg_id = ?", (callback.from_user.id,))
    u = await cur.fetchone()
    await callback.message.answer(
        f"🏠 <b>Улучшение ангара</b>\n━━━━━━━━━━━━━━\n"
        f"Текущий размер: {u['slots_limit']} слотов\n"
        f"Цена 1 слота: {GARAGE_SLOT_PRICE_SILVER:,} серебра\n"
        f"Ваш баланс: {u['silver']:,} серебра".replace(",", " "),
        parse_mode="HTML",
        reply_markup=garage_slot_purchase_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("upg:garage:buy:"))
async def upg_garage_buy(callback: CallbackQuery):
    option = callback.data.split(":")[3]
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()

    if option == "max":
        slots_affordable = u["silver"] // GARAGE_SLOT_PRICE_SILVER
        slots_to_buy = slots_affordable
    else:
        slots_to_buy = int(option)

    total_cost = slots_to_buy * GARAGE_SLOT_PRICE_SILVER
    if slots_to_buy <= 0 or u["silver"] < total_cost:
        await callback.answer("Недостаточно серебра", show_alert=True)
        return

    await conn.execute(
        "UPDATE users SET silver = silver - ?, slots_limit = slots_limit + ? WHERE tg_id = ?",
        (total_cost, slots_to_buy, tg_id),
    )
    await conn.commit()
    await increment_quest_progress(tg_id, "spend_silver", total_cost)
    await callback.message.answer(f"✅ <b>Ангар расширен на {slots_to_buy} слот(ов)!</b>", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "upg:hours")
async def upg_hours_menu(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute(
        "SELECT max_farming_hours, silver, gold FROM users WHERE tg_id = ?", (callback.from_user.id,)
    )
    u = await cur.fetchone()

    current_level = 0
    for lvl, (_, _, hours) in STORAGE_UPGRADE_COSTS.items():
        if u["max_farming_hours"] >= hours:
            current_level = lvl

    if current_level >= 7:
        await callback.message.answer(
            f"⏳ <b>Улучшение часов фарма</b>\n━━━━━━━━━━━━━━\n"
            f"🟩🟩🟩🟩🟩🟩🟩\nМаксимум накопления: {u['max_farming_hours']}ч (МАКСИМУМ)",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    next_level = current_level + 1
    cost_silver, cost_gold, new_hours = STORAGE_UPGRADE_COSTS[next_level]
    can_afford = u["silver"] >= cost_silver and u["gold"] >= cost_gold
    bar = "🟩" * current_level + "⬜️" * (7 - current_level)
    await callback.message.answer(
        f"⏳ <b>Улучшение часов фарма</b>\n━━━━━━━━━━━━━━\n"
        f"Уровень {current_level}/7\n{bar}\n"
        f"Текущий максимум: {u['max_farming_hours']}ч\n━━━━━━━━━━━━━━\n"
        f"Ур. {next_level}: {cost_silver:,} серебра + {cost_gold} золота ➜ {new_hours}ч".replace(",", " "),
        parse_mode="HTML",
        reply_markup=storage_upgrade_kb(next_level, can_afford),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("upg:hours:buy:"))
async def upg_hours_buy(callback: CallbackQuery):
    level = int(callback.data.split(":")[3])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT silver, gold FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    cost_silver, cost_gold, new_hours = STORAGE_UPGRADE_COSTS[level]
    if u["silver"] < cost_silver or u["gold"] < cost_gold:
        await callback.answer("Недостаточно средств", show_alert=True)
        return
    await conn.execute(
        "UPDATE users SET silver = silver - ?, gold = gold - ?, max_farming_hours = ? WHERE tg_id = ?",
        (cost_silver, cost_gold, new_hours, tg_id),
    )
    await conn.commit()
    if cost_silver:
        await increment_quest_progress(tg_id, "spend_silver", cost_silver)
    await callback.message.answer(f"✅ <b>Лимит накопления увеличен до {new_hours}ч!</b>", parse_mode="HTML")
    await callback.answer()
