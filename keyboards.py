"""
keyboards.py — все инлайн/reply клавиатуры бота Carcollection.

Цветовые стили кнопок (Bot API 9.4+, aiogram>=3.28) — раскрашены ВСЕ кнопки:
зелёный (success) для позитивных/подтверждающих/покупных действий и выбранных
пунктов, красный (danger) для продажи/удаления/отмены/заблокированных вариантов,
синий (primary) для навигации и нейтральных информационных пунктов.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ButtonStyle
from config import RARITY_EMOJI

BACK = "⬅️ Назад"


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Компактное главное меню: самые частые действия — сразу на виду,
    остальное разложено по разделам (см. menu_*_kb ниже) — ни одна функция
    никуда не делась, просто спрятана на уровень глубже."""
    kb = [
        [KeyboardButton(text="🚗 Гараж"), KeyboardButton(text="💰 Собрать")],
        [KeyboardButton(text="📈 Прогресс"), KeyboardButton(text="⚔️ PvP и соц.")],
        [KeyboardButton(text="🎡 Экономика"), KeyboardButton(text="🎁 Ещё")],
    ]
    if is_admin:
        kb.append([KeyboardButton(text="🛠 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def menu_progress_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎫 Боевой пропуск")],
        [KeyboardButton(text="📦 Инвентарь")],
        [KeyboardButton(text="⬅️ Главное меню")],
    ])


def menu_pvp_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="⚔️ Дуэли"), KeyboardButton(text="🏛 Клан")],
        [KeyboardButton(text="🔨 Аукцион"), KeyboardButton(text="🎰 Казино")],
        [KeyboardButton(text="⬅️ Главное меню")],
    ])


def menu_economy_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="🎁 Бесплатная машина"), KeyboardButton(text="⚙️ Улучшения")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="📥 Контейнеры")],
        [KeyboardButton(text="⬅️ Главное меню")],
    ])


def menu_more_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="🎁 Бонусы"), KeyboardButton(text="🐞 Сообщить о баге")],
        [KeyboardButton(text="⬅️ Главное меню")],
    ])


def bonuses_menu_kb(is_premium: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎰 Ежедневный бонус", callback_data="bonus:daily", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="👥 Реферальная система", callback_data="bonus:referral")],
        [InlineKeyboardButton(text="🎫 Ввести промокод", callback_data="bonus:promo")],
    ]
    if is_premium:
        rows.append([InlineKeyboardButton(text="💎 Ежедневный премиум-контейнер",
                                           callback_data="bonus:premium_container", style=ButtonStyle.SUCCESS)])
    rows.append([InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:more", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_reward_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Серебро", callback_data="promo:type:silver"),
            InlineKeyboardButton(text="🥇 Золото", callback_data="promo:type:gold"),
            InlineKeyboardButton(text="🎟 Фишки", callback_data="promo:type:chips"),
        ],
        [
            InlineKeyboardButton(text="📦 Контейнер", callback_data="promo:type:container"),
            InlineKeyboardButton(text="🚗 Машина", callback_data="promo:type:car"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_flow", style=ButtonStyle.DANGER)],
    ])


def promo_container_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Обычный", callback_data="promo:container:common")],
        [InlineKeyboardButton(text="📦 Редкий", callback_data="promo:container:rare")],
        [InlineKeyboardButton(text="📦 Премиум", callback_data="promo:container:premium")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_flow", style=ButtonStyle.DANGER)],
    ])


def bug_report_admin_kb(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"bug:reply:{report_id}")],
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"bug:accept:{report_id}", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="🚫 Игнорировать", callback_data=f"bug:ignore:{report_id}", style=ButtonStyle.DANGER),
        ],
    ])


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Установить аватар", callback_data="profile:set_avatar", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🏆 Топ богачей", callback_data="profile:leaderboard")],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:progress", style=ButtonStyle.PRIMARY)],
    ])


def upgrades_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Улучшение фарма", callback_data="upg:farm")],
        [InlineKeyboardButton(text="🏠 Улучшение ангара", callback_data="upg:garage")],
        [InlineKeyboardButton(text="⏳ Улучшение часов фарма", callback_data="upg:hours")],
        [InlineKeyboardButton(text="🎁 Ускорение бесплатной машины", callback_data="upg:freecar")],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:economy", style=ButtonStyle.PRIMARY)],
    ])


def garage_slot_purchase_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+1 слот", callback_data="upg:garage:buy:1", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="+10 слотов", callback_data="upg:garage:buy:10", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="Максимум", callback_data="upg:garage:buy:max", style=ButtonStyle.SUCCESS),
        ],
        [InlineKeyboardButton(text=BACK, callback_data="upg:back", style=ButtonStyle.PRIMARY)],
    ])


def farm_upgrade_kb(next_level: int, can_afford: bool) -> InlineKeyboardMarkup:
    rows = []
    if next_level <= 10:
        label = f"⬆️ Улучшить до ур. {next_level}" if can_afford else f"🔒 Ур. {next_level} (не хватает средств)"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"upg:farm:buy:{next_level}",
            style=ButtonStyle.SUCCESS if can_afford else ButtonStyle.DANGER,
        )])
    rows.append([InlineKeyboardButton(text=BACK, callback_data="upg:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def storage_upgrade_kb(next_level: int, can_afford: bool) -> InlineKeyboardMarkup:
    rows = []
    if next_level <= 7:
        label = f"⬆️ Улучшить до ур. {next_level}" if can_afford else f"🔒 Ур. {next_level} (не хватает средств)"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"upg:hours:buy:{next_level}",
            style=ButtonStyle.SUCCESS if can_afford else ButtonStyle.DANGER,
        )])
    rows.append([InlineKeyboardButton(text=BACK, callback_data="upg:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def freecar_upgrade_kb(next_level: int, can_afford: bool) -> InlineKeyboardMarkup:
    rows = []
    if next_level <= 5:
        label = f"⬆️ Улучшить до ур. {next_level}" if can_afford else f"🔒 Ур. {next_level} (не хватает средств)"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"upg:freecar:buy:{next_level}",
            style=ButtonStyle.SUCCESS if can_afford else ButtonStyle.DANGER,
        )])
    rows.append([InlineKeyboardButton(text=BACK, callback_data="upg:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Starter Pack — 39⭐", callback_data="shop:buy:starter", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="⭐ Pro Pack — 199⭐", callback_data="shop:buy:pro", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="💎 Premium BP — открыть в «🎫 Боевой пропуск»", callback_data="bp:premium")],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:economy", style=ButtonStyle.PRIMARY)],
    ])


def garage_list_kb(cars: list, page: int, total_pages: int, owner_id: int) -> InlineKeyboardMarkup:
    rows = []
    for entry_id, car_id, name, brand, rarity, tier, income in cars:
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        rows.append([InlineKeyboardButton(
            text=f"{emoji} {brand} {name} (T{tier}) — {income}/ч",
            callback_data=f"garage:view:{owner_id}:{entry_id}",
        )])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"garage:page:{owner_id}:{page-1}", style=ButtonStyle.PRIMARY))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"garage:page:{owner_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🗑 Продать несколько", callback_data=f"garage:sellmode:{owner_id}:1", style=ButtonStyle.DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def garage_sellmode_kb(cars: list, selected_ids: set, page: int, total_pages: int, owner_id: int) -> InlineKeyboardMarkup:
    rows = []
    for entry_id, car_id, name, brand, rarity, tier, income in cars:
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        selected = entry_id in selected_ids
        mark = "✅ " if selected else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{emoji} {brand} {name} (T{tier})",
            callback_data=f"garage:selltoggle:{owner_id}:{entry_id}:{page}",
            style=ButtonStyle.SUCCESS if selected else None,
        )])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"garage:sellmode:{owner_id}:{page-1}", style=ButtonStyle.PRIMARY))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"garage:sellmode:{owner_id}:{page+1}"))
    if nav:
        rows.append(nav)
    count = len(selected_ids)
    rows.append([InlineKeyboardButton(
        text=f"💵 Продать выбранные ({count})" if count else "💵 Продать выбранные",
        callback_data=f"garage:sellconfirm:{owner_id}",
        style=ButtonStyle.DANGER if count else None,
    )])
    rows.append([InlineKeyboardButton(text="🔄 Снять все галочки", callback_data=f"garage:sellclear:{owner_id}")])
    rows.append([InlineKeyboardButton(text=f"{BACK} в гараж", callback_data=f"garage:page:{owner_id}:1", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def garage_car_detail_kb(entry_id: int, is_favorite: bool, owner_id: int) -> InlineKeyboardMarkup:
    fav_text = "💔 Убрать из избранного" if is_favorite else "❤️ В избранное"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=fav_text, callback_data=f"garage:fav:{owner_id}:{entry_id}",
                               style=ButtonStyle.DANGER if is_favorite else ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="💵 Продать", callback_data=f"garage:sell:{owner_id}:{entry_id}",
                               style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=f"{BACK} в гараж", callback_data=f"garage:page:{owner_id}:1", style=ButtonStyle.PRIMARY)],
    ])


def casino_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Обменник", callback_data="casino:exchange")],
        [InlineKeyboardButton(text="🏀 Баскетбол (/basket)", callback_data="casino:info:basket")],
        [InlineKeyboardButton(text="🎰 Слоты (/slot)", callback_data="casino:info:slot")],
        [InlineKeyboardButton(text="🎲 Кости (/dice)", callback_data="casino:info:dice")],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:pvp", style=ButtonStyle.PRIMARY)],
    ])


def exchange_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Серебро ➜ Фишки", callback_data="exch:s2c:menu", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="Фишки ➜ Серебро (-10%)", callback_data="exch:c2s:menu", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text=f"{BACK} в казино", callback_data="casino:back", style=ButtonStyle.PRIMARY)],
    ])


def exchange_amount_kb(direction: str, amounts: list[int]) -> InlineKeyboardMarkup:
    """direction: 's2c' (серебро->фишки) или 'c2s' (фишки->серебро)."""
    rows = []
    row = []
    for amount in amounts:
        row.append(InlineKeyboardButton(
            text=f"{amount:,}".replace(",", " "), callback_data=f"exch:{direction}:amt:{amount}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="💯 Максимум", callback_data=f"exch:{direction}:amt:max",
                                       style=ButtonStyle.SUCCESS)])
    rows.append([InlineKeyboardButton(text="✏️ Своя сумма", callback_data=f"exch:{direction}:custom")])
    rows.append([InlineKeyboardButton(text=BACK, callback_data="casino:exchange", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_pass_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="🎁 Награды", callback_data=f"bp:levels:{page}"),
        InlineKeyboardButton(text="📜 Задания", callback_data="bp:quests:1"),
    ], [
        InlineKeyboardButton(text="💎 Купить Premium BP", callback_data="bp:premium", style=ButtonStyle.SUCCESS),
    ], [
        InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:progress", style=ButtonStyle.PRIMARY),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bp_levels_kb(page: int, total_pages: int, claimable_levels: list[int]) -> InlineKeyboardMarkup:
    rows = []
    for lvl in claimable_levels:
        rows.append([InlineKeyboardButton(text=f"✅ Забрать награду ур.{lvl}", callback_data=f"bp:claim:{lvl}",
                                           style=ButtonStyle.SUCCESS)])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"bp:levels:{page-1}", style=ButtonStyle.PRIMARY))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"bp:levels:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text=f"{BACK} в пропуск", callback_data="bp:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bp_quests_kb(page: int, total_pages: int, claimable_keys: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for key in claimable_keys:
        rows.append([InlineKeyboardButton(text="✅ Забрать за задание", callback_data=f"bp:questclaim:{key}",
                                           style=ButtonStyle.SUCCESS)])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"bp:quests:{page-1}", style=ButtonStyle.PRIMARY))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"bp:quests:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text=f"{BACK} в пропуск", callback_data="bp:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bp_premium_kb() -> InlineKeyboardMarkup:
    from config import PREMIUM_BP_OPTIONS
    rows = [
        [InlineKeyboardButton(text="1 уровень", callback_data="bp:buy:1", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="10 уровней", callback_data="bp:buy:10", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="Все уровни", callback_data="bp:buy:max", style=ButtonStyle.SUCCESS)],
    ]
    for key, opt in PREMIUM_BP_OPTIONS.items():
        rows.append([InlineKeyboardButton(
            text=f"💎 Premium BP — {opt['label']} ({opt['price']}⭐)",
            callback_data=f"bp:buyprem:{key}", style=ButtonStyle.SUCCESS,
        )])
    rows.append([InlineKeyboardButton(text=f"{BACK} в пропуск", callback_data="bp:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_kb(items: list) -> InlineKeyboardMarkup:
    rows = []
    for item_id, item_type, item_name, qty in items:
        rows.append([InlineKeyboardButton(
            text=f"{item_name} x{qty}", callback_data=f"inv:view:{item_id}",
        )])
    rows.append([InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:progress", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_item_kb(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Использовать", callback_data=f"inv:use:{item_id}", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text=BACK, callback_data="inv:back", style=ButtonStyle.PRIMARY)],
    ])


def clan_menu_kb(has_clan: bool) -> InlineKeyboardMarkup:
    if has_clan:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 Пополнить банк клана", callback_data="clan:donate",
                                   style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="clan:invite")],
            [InlineKeyboardButton(text="📊 Уровень клана", callback_data="clan:level")],
            [InlineKeyboardButton(text="🏆 Топ кланов", callback_data="clan:leaderboard")],
            [InlineKeyboardButton(text="🚪 Покинуть клан", callback_data="clan:leave", style=ButtonStyle.DANGER)],
            [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:pvp", style=ButtonStyle.PRIMARY)],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Создать клан", callback_data="clan:create", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🔎 Рекомендации кланов", callback_data="clan:browse")],
        [InlineKeyboardButton(text="🔍 Искать клан по названию", callback_data="clan:search")],
        [InlineKeyboardButton(text="🏆 Топ кланов", callback_data="clan:leaderboard")],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:pvp", style=ButtonStyle.PRIMARY)],
    ])


def clan_invite_response_kb(clan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Вступить", callback_data=f"clan:inviteresp:accept:{clan_id}",
                              style=ButtonStyle.SUCCESS),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"clan:inviteresp:decline:{clan_id}",
                              style=ButtonStyle.DANGER),
    ]])


def clan_browse_kb(clans: list, refresh_cb: str) -> InlineKeyboardMarkup:
    """clans: список (clan_id, clan_name, clan_level, members)."""
    rows = []
    for clan_id, clan_name, clan_level, members in clans:
        rows.append([InlineKeyboardButton(
            text=f"🏛 {clan_name} (ур. {clan_level}, 👥{members})",
            callback_data=f"clan:join:{clan_id}", style=ButtonStyle.SUCCESS,
        )])
    rows.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data=refresh_cb)])
    rows.append([InlineKeyboardButton(text=f"{BACK} в кланы", callback_data="clan:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clan_donate_kb() -> InlineKeyboardMarkup:
    amounts = [5_000, 25_000, 100_000]
    row = [InlineKeyboardButton(text=f"{a:,}".replace(",", " "), callback_data=f"clan:donate:amt:{a}",
                                 style=ButtonStyle.SUCCESS)
           for a in amounts]
    return InlineKeyboardMarkup(inline_keyboard=[row, [
        InlineKeyboardButton(text="✏️ Своя сумма", callback_data="clan:donate:custom", style=ButtonStyle.SUCCESS)
    ], [
        InlineKeyboardButton(text=f"{BACK} в клан", callback_data="clan:back", style=ButtonStyle.PRIMARY)
    ]])


def duel_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 Собрать состав", callback_data="duel:squad")],
        [InlineKeyboardButton(text="⚔️ Найти соперника", callback_data="duel:find", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🚫 Отменить поиск", callback_data="duel:cancel_search", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:pvp", style=ButtonStyle.PRIMARY)],
    ])


def duel_squad_kb(cars: list, selected_ids: set, owner_id: int) -> InlineKeyboardMarkup:
    """cars: список (entry_id, name, brand, rarity) — редкость показывается эмодзи и цветом кнопки."""
    rows = []
    for entry_id, name, brand, rarity in cars:
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        selected = entry_id in selected_ids
        mark = "✅ " if selected else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{emoji} {brand} {name}",
            callback_data=f"duel:toggle:{owner_id}:{entry_id}",
            style=ButtonStyle.SUCCESS if selected else None,
        )])
    rows.append([InlineKeyboardButton(text="💾 Сохранить состав", callback_data=f"duel:save:{owner_id}",
                                       style=ButtonStyle.SUCCESS)])
    rows.append([InlineKeyboardButton(text=f"{BACK} в дуэли", callback_data="duel:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def auction_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Активные лоты", callback_data="auc:list:1")],
        [InlineKeyboardButton(text="🗂 Мои лоты", callback_data="auc:mylots:1")],
        [InlineKeyboardButton(text="➕ Выставить машину", callback_data="auc:create", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:pvp", style=ButtonStyle.PRIMARY)],
    ])


def auction_my_lots_kb(lots: list, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    for lot_id, brand, name in lots:
        rows.append([InlineKeyboardButton(
            text=f"❌ Снять: {brand} {name} (#{lot_id})", callback_data=f"auc:cancel:{lot_id}",
            style=ButtonStyle.DANGER,
        )])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"auc:mylots:{page-1}", style=ButtonStyle.PRIMARY))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"auc:mylots:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=BACK, callback_data="auc:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def container_menu_kb() -> InlineKeyboardMarkup:
    from config import PREMIUM_CONTAINER_BASE_PRICE
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Обычный контейнер — 5,000 серебра", callback_data="cont:buy:common:1", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="📦 Редкий контейнер — 50 золота", callback_data="cont:buy:rare:1", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text=f"📦 Премиум контейнер — от {PREMIUM_CONTAINER_BASE_PRICE}⭐",
                               callback_data="cont:premmenu", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="📊 Таблица шансов", callback_data="cont:odds")],
        [InlineKeyboardButton(text=f"{BACK} в меню", callback_data="nav:economy", style=ButtonStyle.PRIMARY)],
    ])


def premium_container_qty_kb(is_premium: bool = False) -> InlineKeyboardMarkup:
    from config import PREMIUM_CONTAINER_BASE_PRICE, PREMIUM_CONTAINER_QTY_OPTIONS, PREMIUM_CONTAINER_DISCOUNT
    rows = []
    extra_discount = PREMIUM_CONTAINER_DISCOUNT if is_premium else 0.0
    for qty, opt in PREMIUM_CONTAINER_QTY_OPTIONS.items():
        price = max(1, round(PREMIUM_CONTAINER_BASE_PRICE * qty * (1 - opt["discount"]) * (1 - extra_discount)))
        badge = " 💎" if is_premium else ""
        rows.append([InlineKeyboardButton(
            text=f"📦 {opt['label']} — {price}⭐{badge}", callback_data=f"cont:buy:premium:{qty}",
            style=ButtonStyle.SUCCESS,
        )])
    rows.append([InlineKeyboardButton(text=f"{BACK} к контейнерам", callback_data="cont:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_kb(is_head: bool = False, admins_hidden: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="➕ Добавить машину", callback_data="admin:addcar", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🎁 Выдать машину игроку", callback_data="admin:givecar", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="💰 Выдать валюту игроку", callback_data="admin:givecurrency", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🖼 Изменить фото машины", callback_data="admin:setphoto")],
        [InlineKeyboardButton(text="🗑 Удалить машину из каталога", callback_data="admin:delcar",
                               style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text="🗓 Новый сезон", callback_data="admin:addseason")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🔍 Гараж игрока (ID/username)", callback_data="admin:lookup")],
        [InlineKeyboardButton(text="📋 Каталог машин по редкости", callback_data="admin:catalog:1")],
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin:stats")],
    ]
    if is_head:
        rows.append([InlineKeyboardButton(text="🎟 Создать промокод", callback_data="promo:create",
                                           style=ButtonStyle.SUCCESS)])
        toggle_text = "✅ Показать админов в топе богачей" if admins_hidden else "🚫 Скрыть админов из топа богачей"
        rows.append([InlineKeyboardButton(text=toggle_text, callback_data="admin:toggle_leaderboard")])
        rows.append([InlineKeyboardButton(text="🔔 Обязательная подписка", callback_data="admin:fsub:menu")])
    rows.append([InlineKeyboardButton(text=f"{BACK} в игровое меню", callback_data="nav:main", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_approval_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adminreq:approve:{request_id}",
                                  style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adminreq:reject:{request_id}",
                                  style=ButtonStyle.DANGER),
        ]
    ])


def admin_currency_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Серебро", callback_data="admin:currency:silver"),
            InlineKeyboardButton(text="🥇 Золото", callback_data="admin:currency:gold"),
            InlineKeyboardButton(text="🎟 Фишки", callback_data="admin:currency:chips"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_flow", style=ButtonStyle.DANGER)],
    ])


def admin_delcar_confirm_kb(car_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить полностью", callback_data=f"admin:delcar:confirm:{car_id}",
                                  style=ButtonStyle.DANGER),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin:delcar:cancel"),
        ]
    ])


def admin_catalog_nav_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin:catalog:{page-1}", style=ButtonStyle.PRIMARY))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin:catalog:{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text=f"{BACK} в админку", callback_data="admin:back", style=ButtonStyle.PRIMARY)],
    ])


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=yes_cb, style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="❌ Отмена", callback_data=no_cb, style=ButtonStyle.DANGER),
        ]
    ])


def fsub_menu_kb(channels: list) -> InlineKeyboardMarkup:
    """channels: список (id, chat_id, title, invite_link) обязательных каналов/групп."""
    rows = []
    for ch_id, chat_id, title, invite_link in channels:
        rows.append([InlineKeyboardButton(
            text=f"🗑 Убрать: {title}", callback_data=f"admin:fsub:remove:{ch_id}", style=ButtonStyle.DANGER,
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить канал/группу", callback_data="admin:fsub:add",
                                       style=ButtonStyle.SUCCESS)])
    rows.append([InlineKeyboardButton(text=f"{BACK} в админку", callback_data="admin:back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fsub_check_kb(channels: list) -> InlineKeyboardMarkup:
    """Клавиатура, которую видит обычный игрок, если он не подписан на обязательные каналы."""
    rows = []
    for ch_id, chat_id, title, invite_link in channels:
        rows.append([InlineKeyboardButton(text=f"📢 {title}", url=invite_link)])
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="fsub:check",
                                       style=ButtonStyle.SUCCESS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
