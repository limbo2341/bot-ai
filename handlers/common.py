"""
handlers/common.py — /start, профиль, аватар, инвентарь, клан.
"""
import datetime
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, StateFilter, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated

from db import (
    get_db, ensure_user, has_garage_space, send_car_photo, get_setting, get_not_subscribed_channels,
    cumulative_exp_for_level, resolve_player, add_user_exp, set_user_blocked, is_user_premium,
)
from keyboards import (
    main_menu_kb, profile_kb, inventory_kb, inventory_item_kb,
    clan_menu_kb, clan_donate_kb, confirm_kb, bug_report_admin_kb, fsub_check_kb,
    clan_browse_kb, clan_invite_response_kb,
    menu_progress_kb, menu_pvp_kb, menu_economy_kb, menu_more_kb,
)
from config import RARITY_EMOJI, CLAN_CREATION_COST, ADMIN_IDS, HEAD_ADMIN_ID, CLAN_MAX_LEVEL, \
    CLAN_INCOME_BONUS_PER_LEVEL, CLAN_XP_PER_LEVEL, REFERRAL_THRESHOLD, REFERRAL_REWARD_RARITY, \
    AUCTION_UNLOCK_LEVEL

router = Router(name="common")


@router.my_chat_member()
async def track_block_status(event: ChatMemberUpdated):
    """Отслеживает блокировку/разблокировку бота пользователем — статистика в
    админ-панели (сколько реально активных игроков) обновляется автоматически."""
    if event.chat.type != "private":
        return
    new_status = event.new_chat_member.status
    if new_status == "kicked":
        await set_user_blocked(event.from_user.id, True)
    elif new_status == "member":
        await set_user_blocked(event.from_user.id, False)


class AvatarStates(StatesGroup):
    waiting_photo = State()


class ClanStates(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_donation = State()
    waiting_invite_username = State()
    waiting_search_query = State()


class BugReportStates(StatesGroup):
    waiting_text = State()


# ---------------------------------------------------------------- /start
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    referrer_id = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        referrer_id = int(command.args[4:])

    is_new = await ensure_user(message.from_user.id, message.from_user.username, referrer_id)
    is_admin = message.from_user.id in ADMIN_IDS
    is_private = message.chat.type == "private"

    if is_new:
        text = (
            "🚘 <b>Добро пожаловать в Carcollection!</b>\n━━━━━━━━━━━━━━\n"
            "Собирайте суперкары, качайте гараж и зарабатывайте пассивный доход.\n\n"
            "🎁 Стартовый бонус уже у вас на счету\n"
            "⚔️ Бросайте вызов другим игрокам в дуэлях\n"
            "📥 Открывайте контейнеры за шансом на редкие тачки\n"
            "🏛 Создавайте кланы и качайте общий бонус к доходу\n"
            "🎫 Проходите Боевой пропуск за эксклюзивные награды\n\n"
            "Погнали — выберите раздел в меню ниже! 👇"
        )
    else:
        conn = await get_db()
        cur = await conn.execute(
            "SELECT level, silver, daily_streak FROM users WHERE tg_id = ?", (message.from_user.id,)
        )
        u = await cur.fetchone()
        is_premium = await is_user_premium(message.from_user.id)
        badge = " 💎" if is_premium else ""
        streak_hint = f"\n🔥 Серия ежедневных бонусов: {u['daily_streak']}" if u["daily_streak"] else ""
        text = (
            f"🚘 <b>С возвращением{badge}!</b>\n━━━━━━━━━━━━━━\n"
            f"🏅 Уровень {u['level']} · 💰 {u['silver']:,} серебра{streak_hint}"
        ).replace(",", " ")

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb(is_admin) if is_private else None)

    if is_new and referrer_id:
        not_subscribed = await get_not_subscribed_channels(message.bot, message.from_user.id)
        if not not_subscribed:
            # Подписки нет или она уже пройдена — реферал засчитывается сразу.
            await _confirm_referral(message.bot, message.from_user.id)
        # иначе реферал будет зачтён при успешном прохождении fsub:check ниже


# ---------------------------------------------------------------- Разделы компактного меню
@router.callback_query(F.data.startswith("nav:"))
async def nav_shortcut(callback: CallbackQuery):
    """Универсальная кнопка «Назад» на инлайн-экранах — открывает нужный раздел
    компактного меню, не заставляя гравця шукати потрібну кнопку внизу."""
    target = callback.data.split(":")[1]
    is_admin = callback.from_user.id in ADMIN_IDS
    kb_map = {
        "progress": ("📈 Прогресс", menu_progress_kb()),
        "pvp": ("⚔️ PvP и социальное", menu_pvp_kb()),
        "economy": ("🎡 Экономика", menu_economy_kb()),
        "more": ("🎁 Ещё", menu_more_kb()),
        "main": ("🏠 Главное меню", main_menu_kb(is_admin)),
    }
    title, kb = kb_map.get(target, ("🏠 Главное меню", main_menu_kb(is_admin)))
    await callback.message.answer(title, reply_markup=kb)
    await callback.answer()


@router.message(F.text == "📈 Прогресс")
async def menu_progress(message: Message):
    await message.answer("📈 <b>Прогресс</b>\n━━━━━━━━━━━━━━\nВыберите раздел:", parse_mode="HTML",
                          reply_markup=menu_progress_kb())


@router.message(F.text == "⚔️ PvP и соц.")
async def menu_pvp(message: Message):
    await message.answer("⚔️ <b>PvP и социальное</b>\n━━━━━━━━━━━━━━\nВыберите раздел:", parse_mode="HTML",
                          reply_markup=menu_pvp_kb())


@router.message(F.text == "🎡 Экономика")
async def menu_economy(message: Message):
    await message.answer("🎡 <b>Экономика</b>\n━━━━━━━━━━━━━━\nВыберите раздел:", parse_mode="HTML",
                          reply_markup=menu_economy_kb())


@router.message(F.text == "🎁 Ещё")
async def menu_more(message: Message):
    await message.answer("🎁 <b>Ещё</b>\n━━━━━━━━━━━━━━\nВыберите раздел:", parse_mode="HTML",
                          reply_markup=menu_more_kb())


@router.message(F.text == "⬅️ Главное меню")
async def menu_back_to_main(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_kb(is_admin))


@router.callback_query(F.data == "fsub:check")
async def fsub_check(callback: CallbackQuery, bot: Bot):
    not_subscribed = await get_not_subscribed_channels(bot, callback.from_user.id)
    if not_subscribed:
        await callback.answer("❌ Вы всё ещё не подписаны на все каналы/группы ниже", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=fsub_check_kb(not_subscribed))
        except Exception:
            pass
        return
    is_admin = callback.from_user.id in ADMIN_IDS
    await _confirm_referral(bot, callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "✅ Спасибо за подписку! Теперь вам доступны все функции бота.",
        reply_markup=main_menu_kb(is_admin),
    )
    await callback.answer()


async def _confirm_referral(bot, tg_id: int) -> None:
    """Засчитывает реферала пригласившему только теперь — когда приглашённый реально
    начал пользоваться ботом (прошёл обязательную подписку, если она настроена).
    Шлёт владельцу реферальной ссылки уведомление «+1» и проверяет порог на награду."""
    conn = await get_db()
    cur = await conn.execute("SELECT referred_by, referral_confirmed FROM users WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    if not row or not row["referred_by"] or row["referral_confirmed"]:
        return
    referrer_id = row["referred_by"]
    await conn.execute("UPDATE users SET referral_confirmed = 1 WHERE tg_id = ?", (tg_id,))
    await conn.commit()
    try:
        await bot.send_message(
            referrer_id,
            "👥 По вашей реферальной ссылке перешёл новый пользователь! +1 приглашённый.",
        )
    except Exception:
        pass
    await _check_referral_milestone(bot, referrer_id)


async def _check_referral_milestone(bot, referrer_id: int) -> None:
    """Проверяет, не набрал ли пригласивший достаточно подтверждённых рефералов для награды."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE referred_by = ? AND referral_confirmed = 1", (referrer_id,)
    )
    count = (await cur.fetchone())["cnt"]
    if count < REFERRAL_THRESHOLD:
        return
    cur = await conn.execute("SELECT referral_bonus_claimed FROM users WHERE tg_id = ?", (referrer_id,))
    row = await cur.fetchone()
    if not row or row["referral_bonus_claimed"]:
        return

    cur = await conn.execute(
        "SELECT car_id, name, brand, tier FROM cars WHERE rarity = ? ORDER BY RANDOM() LIMIT 1",
        (REFERRAL_REWARD_RARITY,),
    )
    car = await cur.fetchone()
    if not car:
        return
    if not await has_garage_space(referrer_id):
        return  # попробуем выдать при следующем реферале, когда освободится место

    await conn.execute(
        "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
        (referrer_id, car["car_id"], datetime.datetime.utcnow().isoformat()),
    )
    await conn.execute("UPDATE users SET referral_bonus_claimed = 1 WHERE tg_id = ?", (referrer_id,))
    await conn.commit()
    try:
        await bot.send_message(
            referrer_id,
            f"🎉 Вы пригласили {REFERRAL_THRESHOLD} друзей и получили секретную машину: "
            f"<b>{car['brand']} {car['name']}</b>!",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ---------------------------------------------------------------- Профиль
async def _render_profile(tg_id: int) -> tuple[str, str | None]:
    conn = await get_db()
    cur = await conn.execute(
        """SELECT username, level, exp, silver, gold, chips, slots_limit,
                  profile_visits, clan_id, avatar_file_id, daily_streak
           FROM users WHERE tg_id = ?""",
        (tg_id,),
    )
    u = await cur.fetchone()
    is_premium = await is_user_premium(tg_id)

    cur = await conn.execute(
        """SELECT COALESCE(SUM(c.hourly_income), 0) as income
           FROM user_garage g JOIN cars c ON c.car_id = g.car_id
           WHERE g.tg_id = ?""",
        (tg_id,),
    )
    income_row = await cur.fetchone()
    income = int(income_row["income"])

    cur = await conn.execute(
        """SELECT COUNT(*) + 1 as rank FROM users
           WHERE silver + gold * 1000 > (SELECT silver + gold * 1000 FROM users WHERE tg_id = ?)""",
        (tg_id,),
    )
    rank_row = await cur.fetchone()

    clan_name = "нет клана"
    if u["clan_id"]:
        cur = await conn.execute("SELECT clan_name FROM clans WHERE clan_id = ?", (u["clan_id"],))
        clan_row = await cur.fetchone()
        if clan_row:
            clan_name = clan_row["clan_name"]

    level = u["level"]
    level_start = cumulative_exp_for_level(level)
    level_end = cumulative_exp_for_level(level + 1)
    xp_for_level = max(level_end - level_start, 1)
    exp_in_level = u["exp"] - level_start
    progress_ratio = min(exp_in_level / xp_for_level, 1.0) if level < 50 else 1.0
    filled = int(progress_ratio * 10)
    progress_bar = "🟩" * filled + "⬜️" * (10 - filled)

    auction_line = ""
    if level < AUCTION_UNLOCK_LEVEL:
        xp_left = max(cumulative_exp_for_level(AUCTION_UNLOCK_LEVEL) - u["exp"], 0)
        auction_line = (
            f"\n🔨 До открытия аукциона ({AUCTION_UNLOCK_LEVEL} ур.): ещё {xp_left} XP\n"
            f"💡 XP даёт: сбор дохода, дуэли, контейнеры, ежедневный бонус, казино, "
            f"аукцион и взносы в банк клана."
        )

    SEP = "━━━━━━━━━━━━━━"
    badge = " 💎" if is_premium else ""
    streak = u["daily_streak"] or 0
    streak_line = f"🔥 Серия ежедневных бонусов: {streak}\n" if streak > 0 else ""
    premium_line = "💎 <b>Premium BP активен</b> — бонус к доходу и наградам\n" if is_premium else ""
    text = (
        f"👤 <b>Профиль {u['username'] or tg_id}{badge}</b>\n"
        f"{SEP}\n"
        f"🏅 <b>Уровень {level}/50</b>\n"
        f"{progress_bar}\n"
        f"{exp_in_level}/{xp_for_level} XP"
        f"{auction_line}\n"
        f"{SEP}\n"
        f"{premium_line}"
        f"{streak_line}"
        f"💰 Серебро: <b>{u['silver']:,}</b>\n"
        f"🥇 Золото: <b>{u['gold']:,}</b>\n"
        f"🎟 Фишки: <b>{u['chips']:,}</b>\n"
        f"⚡ Доход: <b>{income:,}</b> серебра/ч\n"
        f"{SEP}\n"
        f"🚗 Слотов гаража: {u['slots_limit']}\n"
        f"🏆 Место в топе богачей: #{rank_row['rank']}\n"
        f"🏛 Клан: {clan_name}\n"
        f"👁 Визитов в профиль: {u['profile_visits']}"
    ).replace(",", " ")
    return text, u["avatar_file_id"]


@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    text, avatar_file_id = await _render_profile(message.from_user.id)
    if avatar_file_id:
        try:
            await message.answer_photo(avatar_file_id, caption=text, parse_mode="HTML", reply_markup=profile_kb())
            return
        except Exception:
            pass  # если file_id устарел/недоступен — просто покажем текстовый профиль
    await message.answer(text, parse_mode="HTML", reply_markup=profile_kb())


@router.callback_query(F.data == "profile:leaderboard")
async def leaderboard(callback: CallbackQuery):
    conn = await get_db()
    hide_admins = (await get_setting("hide_admins_from_leaderboard", "0")) == "1"
    if hide_admins and ADMIN_IDS:
        placeholders = ",".join("?" * len(ADMIN_IDS))
        cur = await conn.execute(
            f"SELECT username, silver, gold FROM users WHERE tg_id NOT IN ({placeholders}) "
            f"ORDER BY (silver + gold*1000) DESC LIMIT 10",
            tuple(ADMIN_IDS),
        )
    else:
        cur = await conn.execute(
            "SELECT username, silver, gold FROM users ORDER BY (silver + gold*1000) DESC LIMIT 10"
        )
    rows = await cur.fetchall()
    lines = ["🏆 <b>Топ-10 богачей</b>\n"]
    for i, r in enumerate(rows, start=1):
        lines.append(f"{i}. {r['username'] or 'Игрок'} — {r['silver']:,} серебра, {r['gold']:,} золота".replace(",", " "))
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:set_avatar")
async def ask_avatar(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📸 Отправьте фото, которое станет вашим аватаром.")
    await state.set_state(AvatarStates.waiting_photo)
    await callback.answer()


@router.message(StateFilter(AvatarStates.waiting_photo), F.photo)
async def save_avatar(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    conn = await get_db()
    await conn.execute("UPDATE users SET avatar_file_id = ? WHERE tg_id = ?", (file_id, message.from_user.id))
    await conn.commit()
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("✅ Аватар успешно обновлён!", reply_markup=main_menu_kb(is_admin))


@router.message(StateFilter(AvatarStates.waiting_photo))
async def save_avatar_wrong_type(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте именно фото (не файл и не текст).")


# ---------------------------------------------------------------- Инвентарь
@router.message(F.text == "📦 Инвентарь")
async def show_inventory(message: Message):
    conn = await get_db()
    cur = await conn.execute(
        "SELECT id, item_type, item_name, quantity FROM inventory WHERE tg_id = ? AND quantity > 0",
        (message.from_user.id,),
    )
    items = await cur.fetchall()
    if not items:
        await message.answer("📦 Ваш инвентарь пуст. Покупайте паки и открывайте контейнеры!")
        return
    from handlers.containers import CONTAINER_LABELS
    rows = []
    for i in items:
        display_name = CONTAINER_LABELS.get(i["item_name"], i["item_name"]) if i["item_type"] == "container" \
            else i["item_name"]
        rows.append((i["id"], i["item_type"], display_name, i["quantity"]))
    await message.answer("📦 <b>Ваш инвентарь</b>\n━━━━━━━━━━━━━━\nВыберите предмет для подробностей:",
                          parse_mode="HTML", reply_markup=inventory_kb(rows))


@router.callback_query(F.data.startswith("inv:view:"))
async def view_inventory_item(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[2])
    conn = await get_db()
    cur = await conn.execute("SELECT item_type, item_name, quantity FROM inventory WHERE id = ? AND tg_id = ?",
                              (item_id, callback.from_user.id))
    item = await cur.fetchone()
    if not item:
        await callback.answer("🚫 Это не ваш предмет.", show_alert=True)
        return
    display_name = item["item_name"]
    if item["item_type"] == "container":
        from handlers.containers import CONTAINER_LABELS
        display_name = CONTAINER_LABELS.get(item["item_name"], item["item_name"])
    await callback.message.answer(
        f"🔎 <b>{display_name}</b>\nТип: {item['item_type']}\nКоличество: {item['quantity']}",
        parse_mode="HTML", reply_markup=inventory_item_kb(item_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("inv:use:"))
async def use_inventory_item(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    conn = await get_db()
    cur = await conn.execute("SELECT item_type, item_name, quantity FROM inventory WHERE id = ? AND tg_id = ?",
                              (item_id, tg_id))
    item = await cur.fetchone()
    if not item or item["quantity"] <= 0:
        await callback.answer("Нечего использовать", show_alert=True)
        return

    if item["item_type"] == "container":
        from handlers.containers import _open_container, CONTAINER_LABELS, animate_container_opening
        await callback.answer()
        anim_msg = await animate_container_opening(callback.message)
        car, result_text = await _open_container(tg_id, item["item_name"])
        await conn.execute("UPDATE inventory SET quantity = quantity - 1 WHERE id = ?", (item_id,))
        await conn.commit()
        try:
            await anim_msg.delete()
        except Exception:
            pass
        sent_photo = False
        if car:
            sent_photo = await send_car_photo(
                callback.message, car["car_id"], car["image_url"], car["telegram_file_id"],
                caption=result_text, parse_mode="HTML",
            )
        if not sent_photo:
            await callback.message.answer(result_text, parse_mode="HTML")
        return

    result_text, success = await _apply_item_effect(tg_id, item["item_type"], item["item_name"])
    if success:
        await conn.execute("UPDATE inventory SET quantity = quantity - 1 WHERE id = ?", (item_id,))
        await conn.commit()
    await callback.message.answer(result_text, parse_mode="HTML")
    await callback.answer()


async def _apply_item_effect(tg_id: int, item_type: str, item_name: str) -> tuple[str, bool]:
    """Применяет эффект использования предмета инвентаря."""
    conn = await get_db()
    import random

    if item_type == "car_token":
        rarity_filter = {
            "Random Car Token": None,
            "Common Car Token": "Common",
            "Rare Car Token": "Rare",
        }.get(item_name)
        if rarity_filter:
            cur = await conn.execute("SELECT car_id, name, brand FROM cars WHERE rarity = ? ORDER BY RANDOM() LIMIT 1",
                                      (rarity_filter,))
        else:
            cur = await conn.execute("SELECT car_id, name, brand FROM cars ORDER BY RANDOM() LIMIT 1")
        car = await cur.fetchone()
        if not car:
            return "⚠️ Не удалось подобрать машину.", False
        if not await has_garage_space(tg_id):
            return "🚫 Гараж переполнен! Расширьте его в «⚙️ Улучшения», прежде чем использовать этот предмет.", False
        await conn.execute(
            "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
            (tg_id, car["car_id"], datetime.datetime.utcnow().isoformat()),
        )
        await conn.commit()
        return f"🎉 Вы получили новую машину: <b>{car['brand']} {car['name']}</b>!", True

    if item_type == "booster":
        if item_name == "XP бустер":
            xp_gain = random.randint(150, 400)
            new_level, leveled_up = await add_user_exp(tg_id, xp_gain)
            level_note = f"\n🆙 Новый уровень профиля: {new_level}!" if leveled_up else ""
            return f"⚡ XP-бустер применён! Начислено +{xp_gain} XP профиля.{level_note}", True
        # Остальные бустеры (например «Фарм-бустер») мгновенно добавляют серебро сверх обычного клейма
        bonus = random.randint(2000, 15000)
        await conn.execute("UPDATE users SET silver = silver + ? WHERE tg_id = ?", (bonus, tg_id))
        await conn.commit()
        return f"⚡ Бустер применён! Начислено {bonus:,} серебра.".replace(",", " "), True

    return "✅ Предмет использован.", True


@router.callback_query(F.data == "inv:back")
async def inv_back(callback: CallbackQuery):
    await show_inventory(callback.message)
    await callback.answer()


# ---------------------------------------------------------------- Клан
@router.message(F.text == "🏛 Клан")
async def show_clan_menu(message: Message):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (message.from_user.id,))
    row = await cur.fetchone()
    has_clan = bool(row["clan_id"])
    if has_clan:
        cur = await conn.execute("SELECT clan_name, clan_level, clan_xp, description FROM clans WHERE clan_id = ?",
                                  (row["clan_id"],))
        clan = await cur.fetchone()
        cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE clan_id = ?", (row["clan_id"],))
        members = (await cur.fetchone())["cnt"]
        bonus_pct = min(clan["clan_level"], CLAN_MAX_LEVEL) * CLAN_INCOME_BONUS_PER_LEVEL * 100
        next_level_xp = (clan["clan_level"]) * CLAN_XP_PER_LEVEL
        progress_ratio = min(clan["clan_xp"] / next_level_xp, 1.0) if next_level_xp else 1.0
        filled = int(progress_ratio * 10)
        bar = "🟩" * filled + "⬜️" * (10 - filled)
        text = (
            f"🏛 <b>{clan['clan_name']}</b>\n━━━━━━━━━━━━━━\n"
            f"Уровень {clan['clan_level']} (+{bonus_pct:.0f}% к доходу фермы)\n"
            f"{bar}\n"
            f"Банк: {clan['clan_xp']:,} / {next_level_xp:,}\n━━━━━━━━━━━━━━\n"
            f"👥 Участников: {members}\n"
            f"📝 {clan['description'] or '—'}"
        ).replace(",", " ")
    else:
        text = f"🏛 У вас пока нет клана.\nСоздание клана стоит {CLAN_CREATION_COST:,} серебра.".replace(",", " ")
    await message.answer(text, parse_mode="HTML", reply_markup=clan_menu_kb(has_clan))


@router.callback_query(F.data == "clan:back")
async def clan_back(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    has_clan = bool(row["clan_id"])
    if has_clan:
        cur = await conn.execute("SELECT clan_name, clan_level, clan_xp, description FROM clans WHERE clan_id = ?",
                                  (row["clan_id"],))
        clan = await cur.fetchone()
        cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE clan_id = ?", (row["clan_id"],))
        members = (await cur.fetchone())["cnt"]
        bonus_pct = min(clan["clan_level"], CLAN_MAX_LEVEL) * CLAN_INCOME_BONUS_PER_LEVEL * 100
        next_level_xp = (clan["clan_level"]) * CLAN_XP_PER_LEVEL
        ratio = min(clan["clan_xp"] / next_level_xp, 1.0) if next_level_xp else 1.0
        filled = int(ratio * 10)
        bar = "🟩" * filled + "⬜️" * (10 - filled)
        text = (
            f"🏛 <b>{clan['clan_name']}</b>\n━━━━━━━━━━━━━━\n"
            f"Уровень {clan['clan_level']} (+{bonus_pct:.0f}% к доходу фермы)\n"
            f"{bar}\nБанк: {clan['clan_xp']:,} / {next_level_xp:,}\n━━━━━━━━━━━━━━\n"
            f"👥 Участников: {members}\n📝 {clan['description'] or '—'}"
        ).replace(",", " ")
    else:
        text = f"🏛 У вас пока нет клана.\nСоздание клана стоит {CLAN_CREATION_COST:,} серебра.".replace(",", " ")
    await callback.message.answer(text, parse_mode="HTML", reply_markup=clan_menu_kb(has_clan))
    await callback.answer()


@router.callback_query(F.data == "clan:create")
async def clan_create_start(callback: CallbackQuery, state: FSMContext):
    conn = await get_db()
    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if row["silver"] < CLAN_CREATION_COST:
        await callback.answer("Недостаточно серебра для создания клана", show_alert=True)
        return
    await callback.message.answer("✏️ Введите название вашего клана:")
    await state.set_state(ClanStates.waiting_name)
    await callback.answer()


@router.message(StateFilter(ClanStates.waiting_name))
async def clan_create_name(message: Message, state: FSMContext):
    await state.update_data(clan_name=message.text.strip()[:32])
    await message.answer("📝 Теперь введите короткое описание клана:")
    await state.set_state(ClanStates.waiting_description)


@router.message(StateFilter(ClanStates.waiting_description))
async def clan_create_description(message: Message, state: FSMContext):
    data = await state.get_data()
    clan_name = data["clan_name"]
    description = message.text.strip()[:200]
    tg_id = message.from_user.id

    conn = await get_db()
    cur = await conn.execute("SELECT silver FROM users WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    if row["silver"] < CLAN_CREATION_COST:
        await message.answer("⚠️ Недостаточно серебра. Создание клана отменено.")
        await state.clear()
        return

    try:
        cur = await conn.execute(
            "INSERT INTO clans (clan_name, owner_id, description) VALUES (?, ?, ?) RETURNING clan_id",
            (clan_name, tg_id, description),
        )
        clan_row = await cur.fetchone()
        clan_id = clan_row["clan_id"]
        await conn.execute("UPDATE users SET silver = silver - ?, clan_id = ? WHERE tg_id = ?",
                            (CLAN_CREATION_COST, clan_id, tg_id))
        await conn.commit()
        is_admin = tg_id in ADMIN_IDS
        await message.answer(f"🎉 Клан <b>{clan_name}</b> успешно создан!", parse_mode="HTML",
                              reply_markup=main_menu_kb(is_admin))
    except Exception:
        await message.answer("⚠️ Клан с таким названием уже существует. Попробуйте снова с другим именем.")
    await state.clear()


@router.callback_query(F.data == "clan:leave")
async def clan_leave(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    clan_id = row["clan_id"] if row else None
    await conn.execute("UPDATE users SET clan_id = NULL WHERE tg_id = ?", (callback.from_user.id,))
    await conn.commit()

    if clan_id:
        cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE clan_id = ?", (clan_id,))
        remaining = (await cur.fetchone())["cnt"]
        if remaining == 0:
            # Клан опустел — удаляем его, чтобы он не висел "мёртвым" в топе кланов.
            await conn.execute("DELETE FROM clans WHERE clan_id = ?", (clan_id,))
            await conn.commit()

    await callback.message.answer("🚪 Вы покинули клан.")
    await callback.answer()


@router.callback_query(F.data == "clan:invite")
async def clan_invite(callback: CallbackQuery, state: FSMContext):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if not row["clan_id"]:
        await callback.answer("У вас нет клана", show_alert=True)
        return
    await callback.message.answer(
        "👥 Введите @username игрока, которого хотите пригласить в клан "
        "(он должен был хотя бы раз запустить бота):"
    )
    await state.set_state(ClanStates.waiting_invite_username)
    await callback.answer()


@router.message(StateFilter(ClanStates.waiting_invite_username))
async def clan_invite_send(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (message.from_user.id,))
    row = await cur.fetchone()
    if not row["clan_id"]:
        await message.answer("⚠️ У вас больше нет клана.")
        return

    target = await resolve_player(message.text)
    if not target:
        await message.answer("⚠️ Игрок не найден. Попросите его сначала написать боту /start.")
        return
    if target["tg_id"] == message.from_user.id:
        await message.answer("⚠️ Нельзя пригласить самого себя.")
        return
    if target["clan_id"] == row["clan_id"]:
        await message.answer("⚠️ Этот игрок уже в вашем клане.")
        return
    if target["clan_id"]:
        await message.answer("⚠️ Этот игрок уже состоит в другом клане.")
        return

    cur = await conn.execute("SELECT clan_name FROM clans WHERE clan_id = ?", (row["clan_id"],))
    clan = await cur.fetchone()
    if not clan:
        await message.answer("⚠️ У вас больше нет клана.")
        return

    inviter_name = message.from_user.username and f"@{message.from_user.username}" or message.from_user.first_name
    try:
        await bot.send_message(
            target["tg_id"],
            f"👥 Игрок <b>{inviter_name}</b> приглашает вас в клан «<b>{clan['clan_name']}</b>»!\n"
            f"Хотите вступить?",
            parse_mode="HTML",
            reply_markup=clan_invite_response_kb(row["clan_id"]),
        )
        await message.answer(f"✅ Приглашение отправлено игроку {target['username'] or target['tg_id']}.")
    except Exception:
        await message.answer("⚠️ Не удалось отправить приглашение — возможно, игрок заблокировал бота.")


@router.callback_query(F.data.startswith("clan:inviteresp:"))
async def clan_invite_response(callback: CallbackQuery):
    parts = callback.data.split(":")
    action, clan_id = parts[2], int(parts[3])

    if action == "decline":
        try:
            await callback.message.edit_text("❌ Приглашение отклонено.")
        except Exception:
            pass
        await callback.answer()
        return

    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if row["clan_id"]:
        await callback.answer("Вы уже состоите в клане", show_alert=True)
        return

    cur = await conn.execute("SELECT clan_name FROM clans WHERE clan_id = ?", (clan_id,))
    clan = await cur.fetchone()
    if not clan:
        await callback.answer("Этот клан больше не существует", show_alert=True)
        try:
            await callback.message.edit_text("⚠️ Этот клан больше не существует.")
        except Exception:
            pass
        return

    await conn.execute("UPDATE users SET clan_id = ? WHERE tg_id = ?", (clan_id, callback.from_user.id))
    await conn.commit()
    try:
        await callback.message.edit_text(f"✅ Вы вступили в клан «{clan['clan_name']}»!")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "clan:browse")
async def clan_browse(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if row["clan_id"]:
        await callback.answer("Вы уже состоите в клане", show_alert=True)
        return

    # Случайная выборка каждый раз — список рекомендаций обновляется при каждом заходе.
    cur = await conn.execute(
        """SELECT c.clan_id, c.clan_name, c.clan_level, COUNT(u.tg_id) as members
           FROM clans c LEFT JOIN users u ON u.clan_id = c.clan_id
           GROUP BY c.clan_id, c.clan_name, c.clan_level
           HAVING COUNT(u.tg_id) > 0
           ORDER BY RANDOM() LIMIT 5"""
    )
    clans = await cur.fetchall()
    if not clans:
        await callback.message.answer("🔎 Пока нет активных кланов — станьте первым, создайте свой!")
        await callback.answer()
        return
    clans_list = [(c["clan_id"], c["clan_name"], c["clan_level"], c["members"]) for c in clans]
    await callback.message.answer(
        "🔎 <b>Рекомендации кланов</b>\n━━━━━━━━━━━━━━\nНажмите на клан, чтобы вступить:",
        parse_mode="HTML", reply_markup=clan_browse_kb(clans_list, "clan:browse"),
    )
    await callback.answer()


@router.callback_query(F.data == "clan:search")
async def clan_search_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Введите название клана (или его часть) для поиска:")
    await state.set_state(ClanStates.waiting_search_query)
    await callback.answer()


@router.message(StateFilter(ClanStates.waiting_search_query))
async def clan_search_results(message: Message, state: FSMContext):
    await state.clear()
    query = message.text.strip()[:32]
    conn = await get_db()
    cur = await conn.execute(
        """SELECT c.clan_id, c.clan_name, c.clan_level, COUNT(u.tg_id) as members
           FROM clans c LEFT JOIN users u ON u.clan_id = c.clan_id
           WHERE c.clan_name ILIKE ?
           GROUP BY c.clan_id, c.clan_name, c.clan_level
           HAVING COUNT(u.tg_id) > 0
           ORDER BY c.clan_level DESC LIMIT 10""",
        (f"%{query}%",),
    )
    clans = await cur.fetchall()
    if not clans:
        await message.answer(f"🔍 По запросу «{query}» ничего не найдено.")
        return
    clans_list = [(c["clan_id"], c["clan_name"], c["clan_level"], c["members"]) for c in clans]
    await message.answer(
        f"🔍 <b>Результаты по запросу «{query}»</b>\n━━━━━━━━━━━━━━\nНажмите на клан, чтобы вступить:",
        parse_mode="HTML", reply_markup=clan_browse_kb(clans_list, "clan:search"),
    )


@router.callback_query(F.data.startswith("clan:join:"))
async def clan_join(callback: CallbackQuery):
    clan_id = int(callback.data.split(":")[2])
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if row["clan_id"]:
        await callback.answer("Вы уже состоите в клане", show_alert=True)
        return
    cur = await conn.execute("SELECT clan_name FROM clans WHERE clan_id = ?", (clan_id,))
    clan = await cur.fetchone()
    if not clan:
        await callback.answer("Этот клан больше не существует", show_alert=True)
        return
    await conn.execute("UPDATE users SET clan_id = ? WHERE tg_id = ?", (clan_id, callback.from_user.id))
    await conn.commit()
    await callback.message.answer(f"✅ Вы вступили в клан «{clan['clan_name']}»!")
    await callback.answer()


@router.callback_query(F.data == "clan:level")
async def clan_level(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if not row["clan_id"]:
        await callback.answer("У вас нет клана", show_alert=True)
        return
    cur = await conn.execute("SELECT clan_name, clan_level, clan_xp FROM clans WHERE clan_id = ?", (row["clan_id"],))
    clan = await cur.fetchone()
    bonus_pct = min(clan["clan_level"], CLAN_MAX_LEVEL) * CLAN_INCOME_BONUS_PER_LEVEL * 100
    next_level_xp = clan["clan_level"] * CLAN_XP_PER_LEVEL
    await callback.message.answer(
        f"📊 <b>{clan['clan_name']}</b>\nУровень: {clan['clan_level']} (+{bonus_pct:.0f}% к доходу фермы)\n"
        f"Банк клана: {clan['clan_xp']:,} / {next_level_xp:,} до след. уровня".replace(",", " "),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "clan:leaderboard")
async def clan_leaderboard(callback: CallbackQuery):
    conn = await get_db()
    # На всякий случай подчищаем "мёртвые" кланы без единого участника (если вдруг
    # остались из старых данных) — они не должны засорять топ.
    await conn.execute("DELETE FROM clans WHERE clan_id NOT IN (SELECT DISTINCT clan_id FROM users WHERE clan_id IS NOT NULL)")
    await conn.commit()
    cur = await conn.execute(
        """SELECT c.clan_name, c.clan_level, c.clan_xp, COUNT(u.tg_id) as members
           FROM clans c JOIN users u ON u.clan_id = c.clan_id
           GROUP BY c.clan_id, c.clan_name, c.clan_level, c.clan_xp
           HAVING COUNT(u.tg_id) > 0
           ORDER BY c.clan_level DESC, c.clan_xp DESC LIMIT 10"""
    )
    clans = await cur.fetchall()
    if not clans:
        await callback.answer("Кланов пока нет", show_alert=True)
        return
    lines = ["🏆 <b>Топ-10 кланов</b>\n"]
    for i, c in enumerate(clans, start=1):
        lines.append(
            f"{i}. {c['clan_name']} — уровень {c['clan_level']} ({c['clan_xp']:,} банк, 👥{c['members']})"
        .replace(",", " "))
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "clan:donate")
async def clan_donate_start(callback: CallbackQuery):
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id FROM users WHERE tg_id = ?", (callback.from_user.id,))
    row = await cur.fetchone()
    if not row["clan_id"]:
        await callback.answer("У вас нет клана", show_alert=True)
        return
    await callback.message.answer(
        "🏦 Выберите сумму серебра, которую хотите вложить в банк клана "
        "(это ускоряет прокачку уровня клана — бонус к доходу для всех участников):",
        reply_markup=clan_donate_kb(),
    )
    await callback.answer()


async def _do_clan_donate(tg_id: int, amount: int) -> str:
    conn = await get_db()
    cur = await conn.execute("SELECT clan_id, silver FROM users WHERE tg_id = ?", (tg_id,))
    u = await cur.fetchone()
    if not u["clan_id"]:
        return "⚠️ У вас нет клана."
    if amount <= 0 or u["silver"] < amount:
        return "⚠️ Недостаточно серебра для такого взноса."

    cur = await conn.execute("SELECT clan_name, clan_level, clan_xp FROM clans WHERE clan_id = ?", (u["clan_id"],))
    clan = await cur.fetchone()
    new_xp = clan["clan_xp"] + amount
    new_level = clan["clan_level"]
    while new_xp >= new_level * CLAN_XP_PER_LEVEL:
        new_level += 1

    await conn.execute("UPDATE users SET silver = silver - ? WHERE tg_id = ?", (amount, tg_id))
    await conn.execute("UPDATE clans SET clan_xp = ?, clan_level = ? WHERE clan_id = ?",
                        (new_xp, new_level, u["clan_id"]))
    await conn.commit()
    await add_user_exp(tg_id, 10)

    level_up_note = f"\n🎉 Клан повысил уровень до {new_level}!" if new_level > clan["clan_level"] else ""
    return f"✅ Вы вложили {amount:,} серебра в банк клана «{clan['clan_name']}». +10 XP профиля.{level_up_note}".replace(",", " ")


@router.callback_query(F.data.startswith("clan:donate:amt:"))
async def clan_donate_amount(callback: CallbackQuery):
    amount = int(callback.data.split(":")[3])
    text = await _do_clan_donate(callback.from_user.id, amount)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "clan:donate:custom")
async def clan_donate_custom_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Введите сумму серебра для взноса в банк клана:")
    await state.set_state(ClanStates.waiting_donation)
    await callback.answer()


@router.message(StateFilter(ClanStates.waiting_donation))
async def clan_donate_custom_amount(message: Message, state: FSMContext):
    await state.clear()
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    text = await _do_clan_donate(message.from_user.id, int(message.text.strip()))
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------- Баг-репорты
@router.message(F.text == "🐞 Сообщить о баге")
async def bug_report_start(message: Message, state: FSMContext):
    await message.answer("🐞 Опишите проблему как можно подробнее (что делали, что пошло не так):")
    await state.set_state(BugReportStates.waiting_text)


@router.message(StateFilter(BugReportStates.waiting_text))
async def bug_report_submit(message: Message, state: FSMContext):
    await state.clear()
    conn = await get_db()
    cur = await conn.execute(
        "INSERT INTO bug_reports (reporter_tg_id, report_text, created_at) VALUES (?, ?, ?) RETURNING report_id",
        (message.from_user.id, message.text.strip()[:2000], datetime.datetime.utcnow().isoformat()),
    )
    row = await cur.fetchone()
    report_id = row["report_id"]
    await conn.commit()

    username = message.from_user.username or str(message.from_user.id)
    try:
        await message.bot.send_message(
            HEAD_ADMIN_ID,
            f"🐞 <b>Новый баг-репорт #{report_id}</b>\nОт: {username} (ID: {message.from_user.id})\n\n"
            f"{message.text.strip()[:2000]}",
            parse_mode="HTML",
            reply_markup=bug_report_admin_kb(report_id),
        )
    except Exception:
        pass
    await message.answer("✅ Спасибо! Ваш репорт отправлен администрации.")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()
