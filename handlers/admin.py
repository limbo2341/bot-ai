"""
handlers/admin.py — административная панель: динамическое добавление машин,
сезонов, экономика, модерация и рассылка. Доступно только ADMIN_IDS.
"""
import asyncio
import datetime
import math
import json
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from db import (
    get_db, resolve_player, get_setting, set_setting,
    get_fsub_channels, add_fsub_channel, remove_fsub_channel, get_bot_stats, get_donation_history,
)
from config import ADMIN_IDS, HEAD_ADMIN_ID, RARITY_EMOJI
from keyboards import (
    admin_menu_kb, admin_catalog_nav_kb, admin_approval_kb, admin_currency_choice_kb, admin_delcar_confirm_kb,
    promo_reward_type_kb, promo_container_choice_kb, fsub_menu_kb, admin_gift_list_kb,
)

router = Router(name="admin")


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


def is_head_admin(tg_id: int) -> bool:
    return tg_id == HEAD_ADMIN_ID


class AddCarStates(StatesGroup):
    name = State()
    brand = State()
    rarity = State()
    tier = State()
    hourly_income = State()
    base_value = State()
    image = State()


class AddSeasonStates(StatesGroup):
    title = State()
    duration = State()
    banner = State()


class BroadcastStates(StatesGroup):
    content = State()


class LookupPlayerStates(StatesGroup):
    waiting_query = State()


class GiveCarStates(StatesGroup):
    waiting_player = State()
    waiting_car = State()


class GiveCurrencyStates(StatesGroup):
    waiting_player = State()
    waiting_amount = State()


class GiftStates(StatesGroup):
    waiting_player = State()


class DeleteCarStates(StatesGroup):
    waiting_car = State()


class SetPhotoStates(StatesGroup):
    waiting_car = State()
    waiting_photo = State()


class ReplyBugStates(StatesGroup):
    waiting_reply = State()


class PromoCreateStates(StatesGroup):
    waiting_code = State()
    waiting_amount = State()
    waiting_car_id = State()
    waiting_max_uses = State()
    waiting_duration = State()


class AddFsubChannelStates(StatesGroup):
    waiting_channel = State()


VALID_RARITIES = list(RARITY_EMOJI.keys())
VALID_TIERS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
CATALOG_PAGE_SIZE = 15


# ---------------------------------------------------------------- /admin
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    admins_hidden = (await get_setting("hide_admins_from_leaderboard", "0")) == "1"
    await message.answer("🛠 <b>Панель администратора</b>\n━━━━━━━━━━━━━━\nВыберите действие:", parse_mode="HTML",
                          reply_markup=admin_menu_kb(is_head_admin(message.from_user.id), admins_hidden))


@router.message(F.text == "🛠 Админ-панель")
async def admin_panel_button(message: Message):
    if not is_admin(message.from_user.id):
        return
    admins_hidden = (await get_setting("hide_admins_from_leaderboard", "0")) == "1"
    await message.answer("🛠 <b>Панель администратора</b>\n━━━━━━━━━━━━━━\nВыберите действие:", parse_mode="HTML",
                          reply_markup=admin_menu_kb(is_head_admin(message.from_user.id), admins_hidden))


@router.callback_query(F.data == "admin:toggle_leaderboard")
async def admin_toggle_leaderboard(callback: CallbackQuery):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("Только главный администратор", show_alert=True)
        return
    current = (await get_setting("hide_admins_from_leaderboard", "0")) == "1"
    new_value = "0" if current else "1"
    await set_setting("hide_admins_from_leaderboard", new_value)
    status = "скрыты из топа" if new_value == "1" else "снова видны в топе"
    await callback.message.edit_text(
        f"🛠 <b>Панель администратора</b>\n━━━━━━━━━━━━━━\nВыберите действие:\n\n✅ Админы теперь {status} богачей.",
        parse_mode="HTML", reply_markup=admin_menu_kb(True, new_value == "1"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    admins_hidden = (await get_setting("hide_admins_from_leaderboard", "0")) == "1"
    await callback.message.answer(
        "🛠 <b>Панель администратора</b>\n━━━━━━━━━━━━━━\nВыберите действие:",
        parse_mode="HTML", reply_markup=admin_menu_kb(is_head_admin(callback.from_user.id), admins_hidden),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:cancel_flow")
async def admin_cancel_flow(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    admins_hidden = (await get_setting("hide_admins_from_leaderboard", "0")) == "1"
    await callback.message.answer(
        "❌ Действие отменено.\n\n🛠 <b>Панель администратора</b>\n━━━━━━━━━━━━━━\nВыберите действие:",
        parse_mode="HTML", reply_markup=admin_menu_kb(is_head_admin(callback.from_user.id), admins_hidden),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        stats = await get_bot_stats()
        lines = [
            "📊 <b>Статистика бота</b>\n━━━━━━━━━━━━━━",
            f"👥 Всего регистраций: <b>{stats['total']}</b>",
            f"✅ Реально активны (не заблокировали бота): <b>{stats['active_members']}</b>",
            f"🚫 Заблокировали бота: <b>{stats['blocked']}</b>",
            f"🆕 Новых сегодня: <b>{stats['new_today']}</b>",
            f"⚡ Заходили сегодня: <b>{stats['active_today']}</b>",
            "\n🏆 <b>Топ-10 самых активных</b> (по числу действий):",
        ]
        if not stats["top_active"]:
            lines.append("Пока нет данных — статистика действий только начала собираться.")
        for i, (tg_id, username, action_count, level) in enumerate(stats["top_active"], start=1):
            safe_username = str(username).replace("<", "").replace(">", "").replace("&", "") if username else None
            name = f"@{safe_username}" if safe_username else str(tg_id)
            lines.append(f"{i}. {name} — {action_count or 0:,} действий (ур. {level})".replace(",", " "))
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"⚠️ Не удалось собрать статистику: {e}")
    await callback.answer()


@router.callback_query(F.data == "admin:donations")
async def admin_donations(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        data = await get_donation_history(limit=20)
        lines = [
            "💸 <b>История донатов</b>\n━━━━━━━━━━━━━━",
            f"Всего пожертвований: <b>{data['total_count']}</b> на сумму <b>{data['total_stars']}⭐</b>",
            "\n<b>Последние {}:</b>".format(min(20, data['total_count'])),
        ]
        if not data["recent"]:
            lines.append("Пока никто не жертвовал.")
        for tg_id, username, stars, timestamp in data["recent"]:
            name = f"@{username}" if username else str(tg_id)
            try:
                dt = datetime.datetime.fromisoformat(timestamp).strftime("%d.%m.%Y %H:%M")
            except ValueError:
                dt = timestamp
            lines.append(f"• {name} — {stars}⭐ ({dt})")
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"⚠️ Не удалось получить историю донатов: {e}")
    await callback.answer()


# ---------------------------------------------------------------- Подарить подарок Telegram (только глав. админ)
GIFT_PAGE_SIZE = 6


async def _show_gift_page(target, state: FSMContext, page: int):
    """target — объект с методом .answer() (Message или CallbackQuery.message)."""
    data = await state.get_data()
    gifts = data.get("gifts", [])
    total_pages = max(1, math.ceil(len(gifts) / GIFT_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * GIFT_PAGE_SIZE
    page_gifts = gifts[start:start + GIFT_PAGE_SIZE]
    await state.update_data(page=page)

    if not gifts:
        await target.answer("⚠️ Telegram сейчас не возвращает ни одного доступного подарка. Попробуйте позже.")
        return

    text = f"🎁 <b>Выберите подарок</b> (стр. {page}/{total_pages})\nБудет отправлен игроку из баланса звёзд бота."
    await target.answer(text, parse_mode="HTML", reply_markup=admin_gift_list_kb(page_gifts, page, total_pages))


@router.callback_query(F.data == "admin:gift:start")
async def admin_gift_start(callback: CallbackQuery, state: FSMContext):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("🔒 Доступно только главному администратору", show_alert=True)
        return
    await callback.message.answer(
        "🎁 <b>Подарить Telegram-подарок</b>\n━━━━━━━━━━━━━━\n"
        "Введите @username или ID игрока, которому хотите подарить подарок.\n\n"
        "⚠️ Подарок оплачивается со звёздного баланса САМОГО БОТА (не из игровой валюты) — "
        "убедитесь, что на балансе бота достаточно звёзд.",
        parse_mode="HTML",
    )
    await state.set_state(GiftStates.waiting_player)
    await callback.answer()


@router.message(StateFilter(GiftStates.waiting_player))
async def admin_gift_player(message: Message, state: FSMContext, bot: Bot):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    target = await resolve_player(message.text)
    if not target:
        await message.answer("⚠️ Игрок не найден. Проверьте @username/ID и попробуйте снова.")
        return

    try:
        result = await bot.get_available_gifts()
    except Exception as e:
        await message.answer(f"⚠️ Не удалось получить список подарков: {e}")
        await state.clear()
        return

    gifts = []
    for g in result.gifts:
        emoji = getattr(g.sticker, "emoji", None) or "🎁"
        gifts.append((g.id, emoji, g.star_count))
    gifts.sort(key=lambda x: x[2])  # от дешёвых к дорогим

    await state.update_data(
        target_id=target["tg_id"],
        target_name=target["username"] or str(target["tg_id"]),
        gifts=gifts,
    )
    await _show_gift_page(message, state, page=1)


@router.callback_query(F.data.startswith("admin:gift:page:"), StateFilter(GiftStates.waiting_player))
async def admin_gift_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[3])
    await _show_gift_page(callback.message, state, page)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:gift:pick:"), StateFilter(GiftStates.waiting_player))
async def admin_gift_pick(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_head_admin(callback.from_user.id):
        await callback.answer()
        return
    gift_id = callback.data.split(":", 3)[3]
    data = await state.get_data()
    target_id = data.get("target_id")
    target_name = data.get("target_name", str(target_id))
    star_count = next((g[2] for g in data.get("gifts", []) if g[0] == gift_id), "?")
    await state.clear()

    try:
        await bot.send_gift(user_id=target_id, gift_id=gift_id)
    except Exception as e:
        await callback.message.answer(f"⚠️ Не удалось отправить подарок: {e}")
        await callback.answer()
        return

    await callback.message.answer(f"🎁 Подарок за {star_count}⭐ успешно отправлен игроку {target_name}!")
    try:
        await bot.send_message(target_id, "🎁 Вам подарили подарок от администрации Carcollection! Откройте профиль в Telegram, чтобы увидеть его.")
    except Exception:
        pass
    await callback.answer()


# ---------------------------------------------------------------- Обязательная подписка (fsub)
# Доступно ТОЛЬКО главному админу (HEAD_ADMIN_ID) — обычные админы даже не видят
# эту кнопку в меню (см. admin_menu_kb) и не могут вызвать её напрямую.
async def _fsub_menu_text() -> str:
    channels = await get_fsub_channels()
    if not channels:
        return ("🔔 <b>Обязательная подписка</b>\n━━━━━━━━━━━━━━\n"
                "Сейчас каналов/групп для обязательной подписки нет — бот доступен всем.")
    lines = ["🔔 <b>Обязательная подписка</b>\n━━━━━━━━━━━━━━",
             "Игроки должны быть подписаны на все каналы/группы ниже, иначе бот "
             "покажет им требование подписаться и заблокирует остальные функции:\n"]
    for _, chat_id, title, invite_link in channels:
        lines.append(f"• {title} — {invite_link}")
    return "\n".join(lines)


@router.callback_query(F.data == "admin:fsub:menu")
async def fsub_menu(callback: CallbackQuery):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("🔒 Доступно только главному администратору", show_alert=True)
        return
    channels = await get_fsub_channels()
    await callback.message.answer(await _fsub_menu_text(), parse_mode="HTML", reply_markup=fsub_menu_kb(channels))
    await callback.answer()


@router.callback_query(F.data == "admin:fsub:add")
async def fsub_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("🔒 Доступно только главному администратору", show_alert=True)
        return
    await callback.message.answer(
        "➕ <b>Добавление канала/группы на обязательную подписку</b>\n━━━━━━━━━━━━━━\n"
        "1. Добавьте бота администратором в нужный канал/группу (с правом приглашать пользователей).\n"
        "2. Перешлите сюда любое сообщение ИЗ этого канала/группы, либо пришлите его @username "
        "или ID (например -1001234567890).",
        parse_mode="HTML",
    )
    await state.set_state(AddFsubChannelStates.waiting_channel)
    await callback.answer()


@router.message(StateFilter(AddFsubChannelStates.waiting_channel))
async def fsub_add_finish(message: Message, state: FSMContext, bot: Bot):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return

    identifier = None
    if message.forward_from_chat:
        identifier = message.forward_from_chat.id
    elif message.text:
        identifier = message.text.strip()
    if not identifier:
        await message.answer("⚠️ Перешлите сообщение из канала/группы или пришлите @username / ID.")
        return

    try:
        chat = await bot.get_chat(identifier)
    except Exception:
        await message.answer("⚠️ Не удалось найти этот канал/группу. Проверьте @username/ID и попробуйте снова.")
        return

    try:
        member = await bot.get_chat_member(chat.id, bot.id)
        if member.status not in ("administrator", "creator"):
            await message.answer(
                "⚠️ Бот должен быть администратором в этом канале/группе, чтобы проверять подписки. "
                "Добавьте бота в админы и отправьте сообщение ещё раз."
            )
            return
    except Exception:
        await message.answer(
            "⚠️ Бот не состоит в этом канале/группе как администратор. Добавьте его в админы и повторите."
        )
        return

    invite_link = chat.username and f"https://t.me/{chat.username}"
    if not invite_link:
        try:
            invite_link = await bot.export_chat_invite_link(chat.id)
        except Exception:
            await message.answer(
                "⚠️ Не удалось получить пригласительную ссылку. Убедитесь, что у бота есть право "
                "«Приглашать пользователей» в настройках администратора, и попробуйте снова."
            )
            return

    title = chat.title or chat.username or str(chat.id)
    await add_fsub_channel(chat.id, title, invite_link)
    await state.clear()
    channels = await get_fsub_channels()
    await message.answer(f"✅ «{title}» добавлен в обязательную подписку!")
    await message.answer(await _fsub_menu_text(), parse_mode="HTML", reply_markup=fsub_menu_kb(channels))


@router.callback_query(F.data.startswith("admin:fsub:remove:"))
async def fsub_remove(callback: CallbackQuery):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("🔒 Доступно только главному администратору", show_alert=True)
        return
    fsub_id = int(callback.data.split(":")[3])
    await remove_fsub_channel(fsub_id)
    channels = await get_fsub_channels()
    await callback.answer("Убрано из обязательной подписки")
    try:
        await callback.message.edit_text(await _fsub_menu_text(), parse_mode="HTML",
                                          reply_markup=fsub_menu_kb(channels))
    except Exception:
        await callback.message.answer(await _fsub_menu_text(), parse_mode="HTML", reply_markup=fsub_menu_kb(channels))
async def admin_menu_addcar(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await _addcar_prompt(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin:addseason")
async def admin_menu_addseason(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await _addseason_prompt(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast")
async def admin_menu_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await _broadcast_prompt(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin:lookup")
async def admin_lookup_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer(
        "🔍 Введите Telegram ID игрока (число) или его username (с @ или без) — покажу его гараж."
    )
    await state.set_state(LookupPlayerStates.waiting_query)
    await callback.answer()


@router.message(StateFilter(LookupPlayerStates.waiting_query))
async def admin_lookup_query(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    query = message.text.strip().lstrip("@")
    await state.clear()

    conn = await get_db()
    if query.isdigit():
        cur = await conn.execute(
            "SELECT tg_id, username, level, silver, gold FROM users WHERE tg_id = ?", (int(query),)
        )
    else:
        cur = await conn.execute(
            "SELECT tg_id, username, level, silver, gold FROM users WHERE username ILIKE ? LIMIT 1", (query,)
        )
    player = await cur.fetchone()
    if not player:
        await message.answer("⚠️ Игрок не найден. Проверьте ID/username (игрок должен хотя бы раз запустить /start).")
        return

    cur = await conn.execute(
        """SELECT c.name, c.brand, c.rarity, c.tier, c.hourly_income FROM user_garage g
           JOIN cars c ON c.car_id = g.car_id WHERE g.tg_id = ? ORDER BY g.id DESC LIMIT 50""",
        (player["tg_id"],),
    )
    cars = await cur.fetchall()

    lines = [
        f"👤 <b>{player['username'] or player['tg_id']}</b> (ID: {player['tg_id']})",
        f"Уровень: {player['level']} | Серебро: {player['silver']:,} | Золото: {player['gold']:,}".replace(",", " "),
        f"\n🚗 <b>Гараж</b> ({len(cars)} машин, показаны последние 50):",
    ]
    if not cars:
        lines.append("— пусто —")
    for c in cars:
        emoji = RARITY_EMOJI.get(c["rarity"], "⚪")
        lines.append(f"{emoji} {c['brand']} {c['name']} (T{c['tier']}) — {c['hourly_income']:,}/ч".replace(",", " "))

    # Telegram ограничивает длину сообщения — если гараж очень большой, режем на части.
    text = "\n".join(lines)
    for chunk_start in range(0, len(text), 3500):
        await message.answer(text[chunk_start:chunk_start + 3500], parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:catalog:"))
async def admin_catalog(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    page = int(callback.data.split(":")[2])
    conn = await get_db()
    cur = await conn.execute(
        """SELECT car_id, name, brand, rarity, tier, hourly_income FROM cars
           ORDER BY CASE rarity
               WHEN 'Common' THEN 1 WHEN 'Uncommon' THEN 2 WHEN 'Rare' THEN 3
               WHEN 'Epic' THEN 4 WHEN 'Legendary' THEN 5 WHEN 'Ultra-Rare' THEN 6
               WHEN 'Secret' THEN 7 ELSE 8 END, car_id"""
    )
    all_cars = await cur.fetchall()
    total_pages = max(1, math.ceil(len(all_cars) / CATALOG_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * CATALOG_PAGE_SIZE
    page_cars = all_cars[start:start + CATALOG_PAGE_SIZE]

    lines = [f"📋 <b>Каталог машин</b> (стр. {page}/{total_pages}, всего {len(all_cars)})\n"]
    last_rarity = None
    for c in page_cars:
        if c["rarity"] != last_rarity:
            emoji = RARITY_EMOJI.get(c["rarity"], "⚪")
            lines.append(f"\n{emoji} <b>{c['rarity']}</b>")
            last_rarity = c["rarity"]
        lines.append(f"#{c['car_id']} {c['brand']} {c['name']} (T{c['tier']}) — {c['hourly_income']:,}/ч".replace(",", " "))

    text = "\n".join(lines)
    kb = admin_catalog_nav_kb(page, total_pages)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------------------------------------------------------------- Подтверждение чувствительных действий
async def _perform_admin_action(action_type: str, target_tg_id: int, currency: str | None = None,
                                 amount: int | None = None, car_id: int | None = None,
                                 payload: dict | None = None) -> str:
    """Непосредственно исполняет действие (вызывается либо сразу для главного
    админа, либо после подтверждения им запроса другого админа)."""
    conn = await get_db()
    if action_type == "give_currency":
        await conn.execute(f"UPDATE users SET {currency} = {currency} + ? WHERE tg_id = ?", (amount, target_tg_id))
        await conn.commit()
        sign = "+" if amount >= 0 else ""
        return f"{sign}{amount} {currency} пользователю {target_tg_id}"

    elif action_type == "give_car":
        cur = await conn.execute("SELECT name, brand FROM cars WHERE car_id = ?", (car_id,))
        car = await cur.fetchone()
        await conn.execute(
            "INSERT INTO user_garage (tg_id, car_id, acquired_date) VALUES (?, ?, ?)",
            (target_tg_id, car_id, datetime.datetime.utcnow().isoformat()),
        )
        await conn.commit()
        return f"{car['brand']} {car['name']} пользователю {target_tg_id}"

    elif action_type == "add_car":
        await conn.execute(
            """INSERT INTO cars (name, brand, rarity, tier, hourly_income, base_value,
                                  telegram_file_id, photo_is_custom)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (payload["name"], payload["brand"], payload["rarity"], payload["tier"],
             payload["hourly_income"], payload["base_value"], payload["file_id"]),
        )
        await conn.commit()
        return f"добавлена машина {payload['brand']} {payload['name']}"

    elif action_type == "delete_car":
        cur = await conn.execute("SELECT name, brand FROM cars WHERE car_id = ?", (car_id,))
        car = await cur.fetchone()
        label = f"{car['brand']} {car['name']}" if car else f"#{car_id}"
        await conn.execute("DELETE FROM cars WHERE car_id = ?", (car_id,))
        await conn.commit()
        return f"машина {label} удалена из каталога"

    elif action_type == "set_photo":
        cur = await conn.execute("SELECT name, brand FROM cars WHERE car_id = ?", (car_id,))
        car = await cur.fetchone()
        await conn.execute(
            "UPDATE cars SET telegram_file_id = ?, photo_is_custom = 1 WHERE car_id = ?",
            (payload["file_id"], car_id),
        )
        await conn.commit()
        label = f"{car['brand']} {car['name']}" if car else f"#{car_id}"
        return f"обновлено фото для {label}"

    return "неизвестное действие"


async def _execute_or_request_approval(bot: Bot, requesting_admin_id: int, action_type: str,
                                        target_tg_id: int, detail: str, currency: str | None = None,
                                        amount: int | None = None, car_id: int | None = None,
                                        payload: dict | None = None) -> str:
    """Если действие запрашивает главный админ — выполняет сразу. Если это
    другой (подчинённый) админ — ставит запрос в очередь и уведомляет главного
    админа кнопками подтверждения, ничего не выполняя до его решения."""
    if is_head_admin(requesting_admin_id):
        result = await _perform_admin_action(action_type, target_tg_id, currency, amount, car_id, payload)
        return f"✅ Выполнено: {result}"

    conn = await get_db()
    cur = await conn.execute(
        """INSERT INTO admin_pending_actions
           (requested_by, action_type, target_tg_id, target_label, detail, currency, amount, car_id, payload,
            created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING request_id""",
        (requesting_admin_id, action_type, target_tg_id, str(target_tg_id), detail,
         currency, amount, car_id, json.dumps(payload) if payload else None,
         datetime.datetime.utcnow().isoformat()),
    )
    row = await cur.fetchone()
    await conn.commit()
    request_id = row["request_id"]

    try:
        await bot.send_message(
            HEAD_ADMIN_ID,
            f"🔔 <b>Запрос на подтверждение</b>\nАдмин {requesting_admin_id} хочет выполнить: {detail}",
            parse_mode="HTML",
            reply_markup=admin_approval_kb(request_id),
        )
    except Exception:
        pass
    return "📨 Запрос отправлен главному администратору на подтверждение."


@router.callback_query(F.data.startswith("adminreq:"))
async def handle_admin_request_decision(callback: CallbackQuery):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("Подтверждать запросы может только главный администратор", show_alert=True)
        return
    _, decision, request_id_str = callback.data.split(":")
    request_id = int(request_id_str)

    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM admin_pending_actions WHERE request_id = ? AND status = 'pending'", (request_id,)
    )
    req = await cur.fetchone()
    if not req:
        await callback.answer("Этот запрос уже обработан", show_alert=True)
        return

    if decision == "approve":
        payload = json.loads(req["payload"]) if req["payload"] else None
        result = await _perform_admin_action(
            req["action_type"], req["target_tg_id"], req["currency"], req["amount"], req["car_id"], payload
        )
        await conn.execute("UPDATE admin_pending_actions SET status = 'approved' WHERE request_id = ?",
                            (request_id,))
        await conn.commit()
        await callback.message.edit_text(callback.message.text + f"\n\n✅ Подтверждено. {result}")
        try:
            await callback.bot.send_message(req["requested_by"], f"✅ Ваш запрос подтверждён: {req['detail']}")
        except Exception:
            pass
    else:
        await conn.execute("UPDATE admin_pending_actions SET status = 'rejected' WHERE request_id = ?",
                            (request_id,))
        await conn.commit()
        await callback.message.edit_text(callback.message.text + "\n\n❌ Отклонено.")
        try:
            await callback.bot.send_message(req["requested_by"], f"❌ Ваш запрос отклонён: {req['detail']}")
        except Exception:
            pass
    await callback.answer()


# ---------------------------------------------------------------- Выдать машину игроку
@router.callback_query(F.data == "admin:givecar")
async def admin_givecar_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("🎁 Введите ID или username игрока, которому хотите выдать машину:")
    await state.set_state(GiveCarStates.waiting_player)
    await callback.answer()


@router.message(StateFilter(GiveCarStates.waiting_player))
async def admin_givecar_player(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    player = await resolve_player(message.text)
    if not player:
        await message.answer("⚠️ Игрок не найден. Проверьте ID/username и попробуйте снова.")
        return
    await state.update_data(target_tg_id=player["tg_id"], target_label=player["username"] or str(player["tg_id"]))
    await state.set_state(GiveCarStates.waiting_car)
    await message.answer(
        f"👤 Игрок: {player['username'] or player['tg_id']}\n\n"
        f"🚗 Теперь введите car_id машины (посмотреть список — «📋 Каталог машин по редкости»):"
    )


@router.message(StateFilter(GiveCarStates.waiting_car))
async def admin_givecar_car(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой car_id.")
        return
    car_id = int(message.text.strip())
    conn = await get_db()
    cur = await conn.execute("SELECT car_id, name, brand FROM cars WHERE car_id = ?", (car_id,))
    car = await cur.fetchone()
    if not car:
        await message.answer("⚠️ Машина с таким car_id не найдена.")
        return
    data = await state.get_data()
    await state.clear()
    detail = f"{car['brand']} {car['name']} (#{car_id}) игроку {data['target_label']}"
    result = await _execute_or_request_approval(
        bot, message.from_user.id, "give_car", data["target_tg_id"], detail, car_id=car_id,
    )
    await message.answer(result)


# ---------------------------------------------------------------- Выдать валюту игроку
@router.callback_query(F.data == "admin:givecurrency")
async def admin_givecurrency_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("💰 Введите ID или username игрока, которому хотите выдать валюту:")
    await state.set_state(GiveCurrencyStates.waiting_player)
    await callback.answer()


@router.message(StateFilter(GiveCurrencyStates.waiting_player))
async def admin_givecurrency_player(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    player = await resolve_player(message.text)
    if not player:
        await message.answer("⚠️ Игрок не найден. Проверьте ID/username и попробуйте снова.")
        return
    await state.update_data(target_tg_id=player["tg_id"], target_label=player["username"] or str(player["tg_id"]))
    await message.answer("Выберите валюту:", reply_markup=admin_currency_choice_kb())


@router.callback_query(F.data.startswith("admin:currency:"), StateFilter(GiveCurrencyStates.waiting_player))
async def admin_givecurrency_choose(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    currency = callback.data.split(":")[2]
    await state.update_data(currency=currency)
    await state.set_state(GiveCurrencyStates.waiting_amount)
    await callback.message.answer(f"Введите сумму {currency} (отрицательное число — чтобы забрать):")
    await callback.answer()


@router.message(StateFilter(GiveCurrencyStates.waiting_amount))
async def admin_givecurrency_amount(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()
    if not text.lstrip("-").isdigit():
        await message.answer("⚠️ Введите целое число (можно отрицательное).")
        return
    amount = int(text)
    data = await state.get_data()
    await state.clear()
    detail = f"{amount} {data['currency']} игроку {data['target_label']}"
    result = await _execute_or_request_approval(
        bot, message.from_user.id, "give_currency", data["target_tg_id"], detail,
        currency=data["currency"], amount=amount,
    )
    await message.answer(result)


# ---------------------------------------------------------------- Удалить машину из каталога
@router.callback_query(F.data == "admin:delcar")
async def admin_delcar_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer(
        "🗑 Введите car_id машины, которую нужно ПОЛНОСТЬЮ удалить из бота "
        "(она исчезнет из каталога и из гаражей всех игроков, у кого есть):"
    )
    await state.set_state(DeleteCarStates.waiting_car)
    await callback.answer()


@router.message(StateFilter(DeleteCarStates.waiting_car))
async def admin_delcar_car(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой car_id.")
        return
    car_id = int(message.text.strip())
    await state.clear()
    conn = await get_db()
    cur = await conn.execute("SELECT car_id, name, brand, rarity FROM cars WHERE car_id = ?", (car_id,))
    car = await cur.fetchone()
    if not car:
        await message.answer("⚠️ Машина с таким car_id не найдена.")
        return
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM user_garage WHERE car_id = ?", (car_id,))
    owners_count = (await cur.fetchone())["cnt"]
    await message.answer(
        f"⚠️ Вы уверены, что хотите удалить <b>{car['brand']} {car['name']}</b> ({car['rarity']}, #{car_id})?\n"
        f"Она сейчас есть у {owners_count} игроков — у них она тоже пропадёт из гаража.\n"
        f"Это действие необратимо.",
        parse_mode="HTML",
        reply_markup=admin_delcar_confirm_kb(car_id),
    )


@router.callback_query(F.data.startswith("admin:delcar:confirm:"))
async def admin_delcar_confirm(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    car_id = int(callback.data.split(":")[3])
    conn = await get_db()
    cur = await conn.execute("SELECT name, brand, rarity FROM cars WHERE car_id = ?", (car_id,))
    car = await cur.fetchone()
    if not car:
        await callback.answer("Машина уже удалена", show_alert=True)
        return
    detail = f"удаление машины {car['brand']} {car['name']} ({car['rarity']}, #{car_id}) из каталога"
    result = await _execute_or_request_approval(
        bot, callback.from_user.id, "delete_car", callback.from_user.id, detail, car_id=car_id,
    )
    await callback.message.edit_text(result)
    await callback.answer()


@router.callback_query(F.data == "admin:delcar:cancel")
async def admin_delcar_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Удаление отменено.")
    await callback.answer()


# ---------------------------------------------------------------- Изменить фото машины
@router.callback_query(F.data == "admin:setphoto")
async def admin_setphoto_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer(
        "🖼 Введите car_id машины, для которой хотите загрузить своё фото "
        "(посмотреть список — «📋 Каталог машин по редкости»):"
    )
    await state.set_state(SetPhotoStates.waiting_car)
    await callback.answer()


@router.message(StateFilter(SetPhotoStates.waiting_car))
async def admin_setphoto_car(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой car_id.")
        return
    car_id = int(message.text.strip())
    conn = await get_db()
    cur = await conn.execute("SELECT car_id, name, brand FROM cars WHERE car_id = ?", (car_id,))
    car = await cur.fetchone()
    if not car:
        await message.answer("⚠️ Машина с таким car_id не найдена.")
        return
    await state.update_data(car_id=car_id, car_label=f"{car['brand']} {car['name']}")
    await state.set_state(SetPhotoStates.waiting_photo)
    await message.answer(f"📸 Пришлите фото для {car['brand']} {car['name']} (отправьте как фото, не файлом):")


@router.message(StateFilter(SetPhotoStates.waiting_photo), F.photo)
async def admin_setphoto_photo(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    file_id = message.photo[-1].file_id
    detail = f"новое фото для {data['car_label']} (#{data['car_id']})"
    result = await _execute_or_request_approval(
        bot, message.from_user.id, "set_photo", message.from_user.id, detail,
        car_id=data["car_id"], payload={"file_id": file_id},
    )
    await message.answer(result)


@router.message(StateFilter(SetPhotoStates.waiting_photo))
async def admin_setphoto_wrong(message: Message):
    await message.answer("⚠️ Пришлите именно фото (как изображение, не документом).")


# ---------------------------------------------------------------- Баг-репорты (ответ головного админа)
@router.callback_query(F.data.startswith("bug:accept:"))
async def bug_accept(callback: CallbackQuery):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("Только главный администратор", show_alert=True)
        return
    report_id = int(callback.data.split(":")[2])
    conn = await get_db()
    cur = await conn.execute("SELECT reporter_tg_id FROM bug_reports WHERE report_id = ?", (report_id,))
    report = await cur.fetchone()
    if not report:
        await callback.answer("Репорт не найден", show_alert=True)
        return
    await conn.execute("UPDATE bug_reports SET status = 'accepted' WHERE report_id = ?", (report_id,))
    await conn.commit()
    await callback.message.edit_text(callback.message.text + "\n\n✅ Принято.")
    try:
        await callback.bot.send_message(report["reporter_tg_id"], "✅ Ваш баг-репорт принят, спасибо! Мы разберёмся.")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("bug:ignore:"))
async def bug_ignore(callback: CallbackQuery):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("Только главный администратор", show_alert=True)
        return
    report_id = int(callback.data.split(":")[2])
    conn = await get_db()
    await conn.execute("UPDATE bug_reports SET status = 'ignored' WHERE report_id = ?", (report_id,))
    await conn.commit()
    await callback.message.edit_text(callback.message.text + "\n\n🚫 Проигнорировано.")
    await callback.answer()


@router.callback_query(F.data.startswith("bug:reply:"))
async def bug_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("Только главный администратор", show_alert=True)
        return
    report_id = int(callback.data.split(":")[2])
    await state.update_data(report_id=report_id)
    await state.set_state(ReplyBugStates.waiting_reply)
    await callback.message.answer(f"💬 Введите ответ пользователю по репорту #{report_id}:")
    await callback.answer()


@router.message(StateFilter(ReplyBugStates.waiting_reply))
async def bug_reply_send(message: Message, state: FSMContext):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    report_id = data["report_id"]
    await state.clear()

    conn = await get_db()
    cur = await conn.execute("SELECT reporter_tg_id FROM bug_reports WHERE report_id = ?", (report_id,))
    report = await cur.fetchone()
    if not report:
        await message.answer("⚠️ Репорт не найден.")
        return
    await conn.execute("UPDATE bug_reports SET status = 'replied' WHERE report_id = ?", (report_id,))
    await conn.commit()

    try:
        await message.bot.send_message(
            report["reporter_tg_id"],
            f"💬 <b>Ответ администрации по вашему репорту:</b>\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer("✅ Ответ отправлен пользователю.")
    except Exception:
        await message.answer("⚠️ Не удалось отправить ответ (возможно, пользователь заблокировал бота).")


# ---------------------------------------------------------------- Создание промокодов (только главный админ)
@router.callback_query(F.data == "promo:create")
async def promo_create_start(callback: CallbackQuery, state: FSMContext):
    if not is_head_admin(callback.from_user.id):
        await callback.answer("Только главный администратор может создавать промокоды", show_alert=True)
        return
    await callback.message.answer("🎟 Введите текст промокода (латиница/цифры, без пробелов):")
    await state.set_state(PromoCreateStates.waiting_code)
    await callback.answer()


@router.message(StateFilter(PromoCreateStates.waiting_code))
async def promo_create_code(message: Message, state: FSMContext):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    code = message.text.strip().upper().replace(" ", "")
    if not code.isalnum():
        await message.answer("⚠️ Код должен содержать только буквы и цифры, без пробелов.")
        return
    conn = await get_db()
    cur = await conn.execute("SELECT 1 FROM promo_codes WHERE code = ?", (code,))
    if await cur.fetchone():
        await message.answer("⚠️ Такой промокод уже существует. Введите другой.")
        return
    await state.update_data(code=code)
    await message.answer("🎁 Выберите тип награды:", reply_markup=promo_reward_type_kb())


@router.callback_query(F.data.startswith("promo:type:"), StateFilter(PromoCreateStates.waiting_code))
async def promo_create_type(callback: CallbackQuery, state: FSMContext):
    if not is_head_admin(callback.from_user.id):
        await callback.answer()
        return
    reward_type = callback.data.split(":")[2]
    await state.update_data(reward_type=reward_type)
    if reward_type in ("silver", "gold", "chips"):
        await state.set_state(PromoCreateStates.waiting_amount)
        await callback.message.answer(f"✏️ Введите количество ({reward_type}):")
    elif reward_type == "container":
        await callback.message.answer("📦 Выберите тип контейнера:", reply_markup=promo_container_choice_kb())
    elif reward_type == "car":
        await state.set_state(PromoCreateStates.waiting_car_id)
        await callback.message.answer(
            "🚗 Введите car_id машины (посмотреть список — «📋 Каталог машин по редкости»):"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("promo:container:"))
async def promo_create_container(callback: CallbackQuery, state: FSMContext):
    if not is_head_admin(callback.from_user.id):
        await callback.answer()
        return
    container_key = callback.data.split(":")[2]
    await state.update_data(reward_value=container_key)
    await state.set_state(PromoCreateStates.waiting_max_uses)
    await callback.message.answer("🔢 Введите максимальное число активаций (0 — без ограничений):")
    await callback.answer()


@router.message(StateFilter(PromoCreateStates.waiting_amount))
async def promo_create_amount(message: Message, state: FSMContext):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    await state.update_data(reward_value=message.text.strip())
    await state.set_state(PromoCreateStates.waiting_max_uses)
    await message.answer("🔢 Введите максимальное число активаций (0 — без ограничений):")


@router.message(StateFilter(PromoCreateStates.waiting_car_id))
async def promo_create_car_id(message: Message, state: FSMContext):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой car_id.")
        return
    car_id = int(message.text.strip())
    conn = await get_db()
    cur = await conn.execute("SELECT car_id FROM cars WHERE car_id = ?", (car_id,))
    if not await cur.fetchone():
        await message.answer("⚠️ Машина с таким car_id не найдена.")
        return
    await state.update_data(reward_value=str(car_id))
    await state.set_state(PromoCreateStates.waiting_max_uses)
    await message.answer("🔢 Введите максимальное число активаций (0 — без ограничений):")


@router.message(StateFilter(PromoCreateStates.waiting_max_uses))
async def promo_create_max_uses(message: Message, state: FSMContext):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число (0 — без ограничений).")
        return
    max_uses = int(message.text.strip())
    await state.update_data(max_uses=max_uses if max_uses > 0 else None)
    await state.set_state(PromoCreateStates.waiting_duration)
    await message.answer("📅 Введите срок действия в днях (0 — бессрочно):")


@router.message(StateFilter(PromoCreateStates.waiting_duration))
async def promo_create_finalize(message: Message, state: FSMContext):
    if not is_head_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число дней (0 — бессрочно).")
        return
    days = int(message.text.strip())
    data = await state.get_data()
    await state.clear()

    expires_at = None
    if days > 0:
        expires_at = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat()

    conn = await get_db()
    await conn.execute(
        """INSERT INTO promo_codes (code, reward_type, reward_value, max_uses, expires_at, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (data["code"], data["reward_type"], data["reward_value"], data.get("max_uses"),
         expires_at, message.from_user.id, datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()

    limit_text = f"{data.get('max_uses')} активаций" if data.get("max_uses") else "без ограничений по активациям"
    expiry_text = f"до {expires_at[:10]}" if expires_at else "бессрочный"
    await message.answer(
        f"✅ Промокод <code>{data['code']}</code> создан!\n"
        f"Награда: {data['reward_type']} — {data['reward_value']}\n"
        f"Лимит: {limit_text}\nСрок: {expiry_text}",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------- /addcar
async def _addcar_prompt(message: Message, state: FSMContext):
    await message.answer("🚗 Введите название модели машины:")
    await state.set_state(AddCarStates.name)


@router.message(Command("addcar"))
async def addcar_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await _addcar_prompt(message, state)


@router.message(StateFilter(AddCarStates.name))
async def addcar_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("🏭 Введите бренд машины:")
    await state.set_state(AddCarStates.brand)


@router.message(StateFilter(AddCarStates.brand))
async def addcar_brand(message: Message, state: FSMContext):
    await state.update_data(brand=message.text.strip())
    await message.answer(
        "💎 Введите редкость (одно из): " + ", ".join(VALID_RARITIES)
    )
    await state.set_state(AddCarStates.rarity)


@router.message(StateFilter(AddCarStates.rarity))
async def addcar_rarity(message: Message, state: FSMContext):
    rarity = message.text.strip()
    if rarity not in VALID_RARITIES:
        await message.answer("⚠️ Некорректная редкость. Попробуйте снова: " + ", ".join(VALID_RARITIES))
        return
    await state.update_data(rarity=rarity)
    await message.answer("🔢 Введите тир (одно из): " + ", ".join(VALID_TIERS))
    await state.set_state(AddCarStates.tier)


@router.message(StateFilter(AddCarStates.tier))
async def addcar_tier(message: Message, state: FSMContext):
    tier = message.text.strip().upper()
    if tier not in VALID_TIERS:
        await message.answer("⚠️ Некорректный тир. Попробуйте снова: " + ", ".join(VALID_TIERS))
        return
    await state.update_data(tier=tier)
    await message.answer("💰 Введите почасовой доход (число, серебро/ч):")
    await state.set_state(AddCarStates.hourly_income)


@router.message(StateFilter(AddCarStates.hourly_income))
async def addcar_income(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    await state.update_data(hourly_income=int(message.text.strip()))
    await message.answer("💵 Введите цену продажи (base_value, целое число серебра):")
    await state.set_state(AddCarStates.base_value)


@router.message(StateFilter(AddCarStates.base_value))
async def addcar_value(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    await state.update_data(base_value=int(message.text.strip()))
    await message.answer("📸 Отправьте фото машины (станет image_url через file_id):")
    await state.set_state(AddCarStates.image)


@router.message(StateFilter(AddCarStates.image), F.photo)
async def addcar_image(message: Message, state: FSMContext, bot: Bot):
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    await state.clear()

    payload = {
        "name": data["name"], "brand": data["brand"], "rarity": data["rarity"], "tier": data["tier"],
        "hourly_income": data["hourly_income"], "base_value": data["base_value"], "file_id": file_id,
    }
    detail = f"новая машина {data['brand']} {data['name']} ({data['rarity']}, T{data['tier']})"
    result = await _execute_or_request_approval(
        bot, message.from_user.id, "add_car", message.from_user.id, detail, payload=payload,
    )
    emoji = RARITY_EMOJI.get(data["rarity"], "⚪")
    await message.answer_photo(
        file_id,
        caption=(f"{result}\n{emoji} {data['brand']} {data['name']} "
                 f"(T{data['tier']}) — {data['hourly_income']} серебра/ч, продажа {data['base_value']}."),
    )


@router.message(StateFilter(AddCarStates.image))
async def addcar_image_wrong(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото.")


# ---------------------------------------------------------------- /addseason
async def _addseason_prompt(message: Message, state: FSMContext):
    await message.answer("🗓 Введите название нового сезона:")
    await state.set_state(AddSeasonStates.title)


@router.message(Command("addseason"))
async def addseason_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await _addseason_prompt(message, state)


@router.message(StateFilter(AddSeasonStates.title))
async def addseason_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📅 Введите длительность сезона в днях (число):")
    await state.set_state(AddSeasonStates.duration)


@router.message(StateFilter(AddSeasonStates.duration))
async def addseason_duration(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число дней.")
        return
    await state.update_data(duration=int(message.text.strip()))
    await message.answer("🖼 Отправьте баннер сезона (фото):")
    await state.set_state(AddSeasonStates.banner)


@router.message(StateFilter(AddSeasonStates.banner), F.photo)
async def addseason_banner(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    data = await state.get_data()

    conn = await get_db()
    await conn.execute("UPDATE active_season SET is_active = 0 WHERE is_active = 1")
    await conn.execute(
        """INSERT INTO active_season (title, duration_days, image_url, start_date, is_active)
           VALUES (?, ?, ?, ?, 1)""",
        (data["title"], data["duration"], file_id, datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()
    await state.clear()

    await message.answer_photo(
        file_id,
        caption=f"✅ Новый сезон запущен: {data['title']} ({data['duration']} дней)",
    )


@router.message(StateFilter(AddSeasonStates.banner))
async def addseason_banner_wrong(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото баннера.")


# ---------------------------------------------------------------- /give /givecar
@router.message(Command("give"))
async def give_currency(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 4 or not parts[1].isdigit() or parts[2] not in ("silver", "gold", "chips") \
            or not parts[3].lstrip("-").isdigit():
        await message.answer("⚠️ Формат: /give {tg_id} {silver/gold/chips} {amount}")
        return
    target_id, currency, amount = int(parts[1]), parts[2], int(parts[3])

    conn = await get_db()
    cur = await conn.execute("SELECT tg_id FROM users WHERE tg_id = ?", (target_id,))
    if not await cur.fetchone():
        await message.answer("⚠️ Пользователь не найден в базе (он должен хотя бы раз запустить /start).")
        return
    detail = f"{amount} {currency} игроку {target_id}"
    result = await _execute_or_request_approval(
        bot, message.from_user.id, "give_currency", target_id, detail, currency=currency, amount=amount,
    )
    await message.answer(result)


@router.message(Command("givecar"))
async def give_car(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("⚠️ Формат: /givecar {tg_id} {car_id}")
        return
    target_id, car_id = int(parts[1]), int(parts[2])

    conn = await get_db()
    cur = await conn.execute("SELECT name, brand FROM cars WHERE car_id = ?", (car_id,))
    car = await cur.fetchone()
    if not car:
        await message.answer("⚠️ Машина с таким car_id не найдена.")
        return
    detail = f"{car['brand']} {car['name']} (#{car_id}) игроку {target_id}"
    result = await _execute_or_request_approval(
        bot, message.from_user.id, "give_car", target_id, detail, car_id=car_id,
    )
    await message.answer(result)


# ---------------------------------------------------------------- /ban /unban
@router.message(Command("ban"))
async def ban_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("⚠️ Формат: /ban {tg_id} {причина}")
        return
    target_id = int(parts[1])
    reason = parts[2] if len(parts) > 2 else "Не указана"

    conn = await get_db()
    await conn.execute("UPDATE users SET is_banned = 1, ban_reason = ? WHERE tg_id = ?", (reason, target_id))
    await conn.commit()
    await message.answer(f"🚫 Пользователь {target_id} забанен. Причина: {reason}")


@router.message(Command("unban"))
async def unban_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("⚠️ Формат: /unban {tg_id}")
        return
    target_id = int(parts[1])

    conn = await get_db()
    await conn.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE tg_id = ?", (target_id,))
    await conn.commit()
    await message.answer(f"✅ Пользователь {target_id} разбанен.")


# ---------------------------------------------------------------- /broadcast
async def _broadcast_prompt(message: Message, state: FSMContext):
    await message.answer(
        "📢 Отправьте сообщение для рассылки (текст, можно с фото). "
        "Оно будет разослано всем пользователям бота."
    )
    await state.set_state(BroadcastStates.content)


@router.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await _broadcast_prompt(message, state)


@router.message(StateFilter(BroadcastStates.content))
async def broadcast_send(message: Message, state: FSMContext, bot: Bot):
    conn = await get_db()
    cur = await conn.execute("SELECT tg_id FROM users WHERE is_banned = 0")
    users = await cur.fetchall()
    await state.clear()

    sent, failed = 0, 0
    await message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")

    for row in users:
        try:
            if message.photo:
                await bot.send_photo(row["tg_id"], message.photo[-1].file_id, caption=message.caption or "")
            else:
                await bot.send_message(row["tg_id"], message.text or message.caption or "")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # троттлинг, чтобы не упереться в лимиты Telegram

    await message.answer(f"✅ Рассылка завершена. Успешно: {sent}, ошибок: {failed}.")
