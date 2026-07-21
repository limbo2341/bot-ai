"""
db.py — асинхронная работа с PostgreSQL через asyncpg.

Внутри реализована тонкая совместимая обёртка (DBConnection/_Result), которая
повторяет API aiosqlite (execute/executemany/executescript/commit,
fetchone/fetchall, доступ к колонкам по имени через row["col"]), чтобы весь
остальной код бота (handlers/*) не пришлось переписывать запрос за запросом.
Внутри себя обёртка сама конвертирует SQLite-плейсхолдеры "?" в постгресовые
"$1, $2, ...".
"""
import os
import logging
import datetime
import urllib.parse
import asyncpg
from aiogram.types import FSInputFile
from config import DATABASE_URL, BASE_GARAGE_SLOTS, BASE_MAX_FARM_HOURS, ADMIN_IDS

logger = logging.getLogger("carcollection.db")

_pool: asyncpg.Pool | None = None
_conn_wrapper: "DBConnection | None" = None

# ---- Система уровней профиля ----
# Уровни 1-10 (до открытия аукциона на 10 уровне) специально сделаны дешевле —
# чтобы новые игроки быстро доходили до аукциона, не застревая на раннем гринде.
# С 10 уровня и выше — обычный темп.
EARLY_LEVEL_CAP = 10
EARLY_XP_PER_LEVEL = 400    # опыта на уровень с 1 по 10 (было 1000)
EXP_PER_LEVEL = 1000        # опыта на уровень начиная с 11-го
MAX_USER_LEVEL = 50         # потолок обычного игрока
ADMIN_LEVEL = MAX_USER_LEVEL  # уровень, который получает админ автоматически


def cumulative_exp_for_level(level: int) -> int:
    """Сколько всего опыта нужно НАБРАТЬ, чтобы достичь этого уровня."""
    if level <= 1:
        return 0
    if level <= EARLY_LEVEL_CAP:
        return (level - 1) * EARLY_XP_PER_LEVEL
    early_total = (EARLY_LEVEL_CAP - 1) * EARLY_XP_PER_LEVEL
    return early_total + (level - EARLY_LEVEL_CAP) * EXP_PER_LEVEL


def _level_for_exp(exp: int) -> int:
    if exp < cumulative_exp_for_level(EARLY_LEVEL_CAP):
        return min(exp // EARLY_XP_PER_LEVEL + 1, EARLY_LEVEL_CAP)
    remaining = exp - cumulative_exp_for_level(EARLY_LEVEL_CAP)
    return min(EARLY_LEVEL_CAP + remaining // EXP_PER_LEVEL, MAX_USER_LEVEL)


def _convert_placeholders(query: str) -> str:
    """Конвертирует SQLite-style '?' плейсхолдеры в позиционные постгресовые '$1, $2, ...'.
    Учитывает простые одинарные кавычки, чтобы не трогать '?' внутри строковых литералов
    (в текущих запросах бота такого нет, но на будущее — безопаснее)."""
    result = []
    count = 0
    in_quote = False
    for ch in query:
        if ch == "'":
            in_quote = not in_quote
            result.append(ch)
        elif ch == "?" and not in_quote:
            count += 1
            result.append(f"${count}")
        else:
            result.append(ch)
    return "".join(result)


class _Result:
    """Имитирует aiosqlite-курсор: fetchone()/fetchall() + lastrowid."""

    def __init__(self, rows, lastrowid=None):
        self._rows = list(rows)
        self._pos = 0
        self.lastrowid = lastrowid

    async def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    async def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows


class DBConnection:
    """Обёртка над asyncpg.Pool с API, повторяющим aiosqlite.Connection."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def execute(self, query: str, params=()) -> _Result:
        pg_query = _convert_placeholders(query)
        stripped = query.strip().lower()
        async with self.pool.acquire() as conn:
            if stripped.startswith("select"):
                rows = await conn.fetch(pg_query, *params)
                return _Result(rows)
            if stripped.startswith("insert") and "returning" in stripped:
                row = await conn.fetchrow(pg_query, *params)
                lastrowid = row[0] if row else None
                return _Result([row] if row else [], lastrowid=lastrowid)
            await conn.execute(pg_query, *params)
            return _Result([])

    async def executemany(self, query: str, seq_of_params) -> None:
        pg_query = _convert_placeholders(query)
        async with self.pool.acquire() as conn:
            await conn.executemany(pg_query, list(seq_of_params))

    async def executescript(self, script: str) -> None:
        # asyncpg выполняет несколько SQL-команд за один вызов execute(),
        # если запрос не содержит параметров (простой протокол запроса).
        async with self.pool.acquire() as conn:
            await conn.execute(script)

    async def commit(self) -> None:
        # PostgreSQL/asyncpg работает в режиме autocommit вне явных транзакций,
        # поэтому commit() — это no-op, оставлен только для совместимости API.
        pass


async def get_db() -> DBConnection:
    """Возвращает singleton-обёртку над пулом соединений PostgreSQL."""
    global _pool, _conn_wrapper
    if _pool is None:
        logger.info("Подключаюсь к PostgreSQL...")
        _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=10)
        _conn_wrapper = DBConnection(_pool)
    return _conn_wrapper


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id BIGINT PRIMARY KEY,
    username TEXT,
    level INTEGER NOT NULL DEFAULT 1,
    exp BIGINT NOT NULL DEFAULT 0,
    silver BIGINT NOT NULL DEFAULT 5000,
    gold BIGINT NOT NULL DEFAULT 10,
    chips BIGINT NOT NULL DEFAULT 0,
    slots_limit INTEGER NOT NULL DEFAULT {base_slots},
    cooldown_reduction INTEGER NOT NULL DEFAULT 0,
    max_farming_hours INTEGER NOT NULL DEFAULT {base_hours},
    avatar_file_id TEXT,
    is_banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    clan_id INTEGER,
    profile_visits INTEGER NOT NULL DEFAULT 0,
    last_claim_at TEXT,
    unclaimed_silver BIGINT NOT NULL DEFAULT 0,
    joined_date TEXT NOT NULL,
    last_free_car_at TEXT,
    free_car_cooldown_reduction INTEGER NOT NULL DEFAULT 0,
    referred_by BIGINT,
    referral_bonus_claimed INTEGER NOT NULL DEFAULT 0,
    referral_confirmed INTEGER NOT NULL DEFAULT 0,
    last_daily_bonus_at TEXT,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    last_active_at TEXT,
    action_count BIGINT NOT NULL DEFAULT 0,
    blocked_bot INTEGER NOT NULL DEFAULT 0,
    premium_container_claimed_at TEXT
);

CREATE TABLE IF NOT EXISTS cars (
    car_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    rarity TEXT NOT NULL,
    tier TEXT NOT NULL,
    hourly_income BIGINT NOT NULL,
    base_value BIGINT NOT NULL,
    image_url TEXT,
    telegram_file_id TEXT,
    photo_is_custom INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_garage (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    car_id INTEGER NOT NULL REFERENCES cars(car_id) ON DELETE CASCADE,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    acquired_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    UNIQUE(tg_id, item_type, item_name)
);

CREATE TABLE IF NOT EXISTS battle_pass (
    tg_id BIGINT PRIMARY KEY REFERENCES users(tg_id) ON DELETE CASCADE,
    current_level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    premium_unlocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS active_season (
    season_id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    image_url TEXT,
    start_date TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clans (
    clan_id SERIAL PRIMARY KEY,
    clan_name TEXT NOT NULL UNIQUE,
    owner_id BIGINT NOT NULL,
    clan_level INTEGER NOT NULL DEFAULT 1,
    clan_xp INTEGER NOT NULL DEFAULT 0,
    description TEXT
);

CREATE TABLE IF NOT EXISTS auctions (
    auction_id SERIAL PRIMARY KEY,
    seller_id BIGINT NOT NULL,
    car_id INTEGER NOT NULL,
    price_silver BIGINT NOT NULL DEFAULT 0,
    price_gold BIGINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id SERIAL PRIMARY KEY,
    tg_id BIGINT NOT NULL,
    stars_amount INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quests (
    quest_id SERIAL PRIMARY KEY,
    tg_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    quest_key TEXT NOT NULL,
    description TEXT NOT NULL,
    target INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    bp_xp_reward INTEGER NOT NULL DEFAULT 5,
    claimed INTEGER NOT NULL DEFAULT 0,
    day_stamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bp_claimed_levels (
    tg_id BIGINT NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (tg_id, level)
);

CREATE TABLE IF NOT EXISTS duels (
    duel_id SERIAL PRIMARY KEY,
    player_a BIGINT NOT NULL,
    player_b BIGINT,
    stake_silver BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'waiting',
    winner_id BIGINT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_pending_actions (
    request_id SERIAL PRIMARY KEY,
    requested_by BIGINT NOT NULL,
    action_type TEXT NOT NULL,
    target_tg_id BIGINT NOT NULL,
    target_label TEXT NOT NULL,
    detail TEXT NOT NULL,
    currency TEXT,
    amount BIGINT,
    car_id INTEGER,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bug_reports (
    report_id SERIAL PRIMARY KEY,
    reporter_tg_id BIGINT NOT NULL,
    report_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    reward_type TEXT NOT NULL,
    reward_value TEXT NOT NULL,
    max_uses INTEGER,
    uses_count INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_by BIGINT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    code TEXT NOT NULL,
    tg_id BIGINT NOT NULL,
    redeemed_at TEXT NOT NULL,
    PRIMARY KEY (code, tg_id)
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fsub_channels (
    fsub_id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    invite_link TEXT NOT NULL,
    added_at TEXT NOT NULL
);
""".format(base_slots=BASE_GARAGE_SLOTS, base_hours=BASE_MAX_FARM_HOURS)

# Изменения схемы, добавленные ПОСЛЕ первого деплоя (для баз, где таблицы уже
# существуют, CREATE TABLE IF NOT EXISTS новые колонки не добавит — нужен ALTER).
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_free_car_at TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS free_car_cooldown_reduction INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_bonus_claimed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_confirmed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_streak INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS action_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_bot INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_container_claimed_at TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_daily_bonus_at TEXT",
    "ALTER TABLE cars ADD COLUMN IF NOT EXISTS telegram_file_id TEXT",
    "ALTER TABLE cars ADD COLUMN IF NOT EXISTS photo_is_custom INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE admin_pending_actions ADD COLUMN IF NOT EXISTS payload TEXT",
    "ALTER TABLE battle_pass ADD COLUMN IF NOT EXISTS premium_expires_at TEXT",
    "ALTER TABLE quests ADD COLUMN IF NOT EXISTS is_premium INTEGER NOT NULL DEFAULT 0",
]


# Базовый доход за час на 1 единицу тира (до 2026-07-16 было 40 — увеличено
# по просьбе, чтобы фарм в целом приносил больше). Используется и при
# генерации каталога, и в идемпотентном пересчёте _rebalance_car_income().
INCOME_BASE_PER_TIER = 55


# Слаг редкости -> имя файла в assets/car_placeholders/ (оригинальные
# стилизованные карточки-заглушки, нарисованные локально — не фото реальных
# машин конкретных марок, чтобы не нарушать авторские права производителей).
RARITY_IMAGE_SLUG = {
    "Common": "common", "Uncommon": "uncommon", "Rare": "rare", "Epic": "epic",
    "Legendary": "legendary", "Ultra-Rare": "ultra-rare", "Secret": "secret",
}
CAR_PLACEHOLDERS_DIR = "assets/car_placeholders"


def _build_car_catalog() -> list[tuple]:
    """
    Строит каталог из 100+ реальных машин с характеристиками,
    рассчитанными по редкости/тиру, чтобы экономика была сбалансирована.
    Формат кортежа: (name, brand, rarity, tier, hourly_income, base_value, image_url)
    """
    # (brand, model, rarity, tier)
    roster = [
        # ---- Common / Tier I-III ----
        ("Lada", "Riva", "Common", "I"),
        ("Lada", "Priora", "Common", "I"),
        ("Daewoo", "Lanos", "Common", "I"),
        ("Daewoo", "Nexia", "Common", "I"),
        ("Chevrolet", "Aveo", "Common", "II"),
        ("Chevrolet", "Spark", "Common", "I"),
        ("Hyundai", "Accent", "Common", "II"),
        ("Hyundai", "Getz", "Common", "I"),
        ("Fiat", "Panda", "Common", "I"),
        ("Fiat", "Punto", "Common", "II"),
        ("Renault", "Logan", "Common", "II"),
        ("Renault", "Sandero", "Common", "II"),
        ("Kia", "Rio", "Common", "II"),
        ("Kia", "Picanto", "Common", "I"),
        ("Toyota", "Corolla", "Common", "III"),
        ("Toyota", "Yaris", "Common", "II"),
        ("Honda", "Civic", "Common", "III"),
        ("Honda", "Fit", "Common", "II"),
        ("Volkswagen", "Golf", "Common", "III"),
        ("Volkswagen", "Polo", "Common", "II"),
        ("Ford", "Focus", "Common", "III"),
        ("Ford", "Fiesta", "Common", "II"),
        ("Skoda", "Octavia", "Uncommon", "III"),
        ("Skoda", "Fabia", "Common", "II"),
        ("Opel", "Astra", "Uncommon", "III"),
        ("Opel", "Corsa", "Common", "II"),
        ("Peugeot", "308", "Uncommon", "III"),
        ("Citroen", "C4", "Uncommon", "III"),
        ("Nissan", "Almera", "Common", "II"),
        ("Mazda", "3", "Uncommon", "III"),
        # ---- Uncommon / Tier IV ----
        ("Volkswagen", "Passat", "Uncommon", "IV"),
        ("Toyota", "Camry", "Uncommon", "IV"),
        ("Honda", "Accord", "Uncommon", "IV"),
        ("Mazda", "6", "Uncommon", "IV"),
        ("Hyundai", "Sonata", "Uncommon", "IV"),
        ("Kia", "Optima", "Uncommon", "IV"),
        ("Nissan", "Altima", "Uncommon", "IV"),
        ("Ford", "Mondeo", "Uncommon", "IV"),
        ("Subaru", "Legacy", "Uncommon", "IV"),
        ("Chevrolet", "Malibu", "Uncommon", "IV"),
        # ---- Rare / Tier V-VI ----
        ("BMW", "3-Series", "Rare", "V"),
        ("Mercedes-Benz", "C-Class", "Rare", "V"),
        ("Audi", "A4", "Rare", "V"),
        ("Subaru", "Impreza WRX", "Rare", "VI"),
        ("Mitsubishi", "Lancer Evolution", "Rare", "VI"),
        ("Mazda", "RX-8", "Rare", "VI"),
        ("Ford", "Mustang GT", "Rare", "VI"),
        ("Chevrolet", "Camaro SS", "Rare", "VI"),
        ("Dodge", "Challenger R/T", "Rare", "VI"),
        ("Nissan", "350Z", "Rare", "V"),
        ("Nissan", "370Z", "Rare", "VI"),
        ("Toyota", "Supra MK4", "Rare", "VI"),
        ("Volkswagen", "Golf R", "Rare", "V"),
        ("Audi", "TT RS", "Rare", "VI"),
        ("BMW", "1M Coupe", "Rare", "VI"),
        # ---- Epic / Tier VII-VIII ----
        ("Porsche", "911 Carrera", "Epic", "VII"),
        ("BMW", "M5", "Epic", "VIII"),
        ("Mercedes-AMG", "E63 AMG", "Epic", "VIII"),
        ("Audi", "RS6", "Epic", "VIII"),
        ("Nissan", "GT-R", "Epic", "VIII"),
        ("Chevrolet", "Corvette C7", "Epic", "VII"),
        ("Jaguar", "F-Type R", "Epic", "VII"),
        ("Aston Martin", "Vantage", "Epic", "VII"),
        ("Lexus", "LC500", "Epic", "VII"),
        ("Maserati", "GranTurismo", "Epic", "VII"),
        ("BMW", "M3 Competition", "Epic", "VII"),
        ("Mercedes-AMG", "C63 AMG", "Epic", "VII"),
        ("Audi", "RS7", "Epic", "VIII"),
        ("Cadillac", "CTS-V", "Epic", "VII"),
        ("Lexus", "RC F", "Epic", "VII"),
        ("Alfa Romeo", "Giulia Quadrifoglio", "Epic", "VII"),
        # ---- Legendary / Tier IX ----
        ("Ferrari", "F8 Tributo", "Legendary", "IX"),
        ("Lamborghini", "Huracan", "Legendary", "IX"),
        ("Porsche", "911 GT3 RS", "Legendary", "IX"),
        ("McLaren", "720S", "Legendary", "IX"),
        ("Aston Martin", "DB11", "Legendary", "IX"),
        ("Ferrari", "812 Superfast", "Legendary", "IX"),
        ("Lamborghini", "Aventador", "Legendary", "IX"),
        ("Bentley", "Continental GT", "Legendary", "IX"),
        ("Rolls-Royce", "Wraith", "Legendary", "IX"),
        ("Maserati", "MC20", "Legendary", "IX"),
        # ---- Ultra-Rare / Tier X ----
        ("Bugatti", "Chiron", "Ultra-Rare", "X"),
        ("Pagani", "Huayra", "Ultra-Rare", "X"),
        ("Koenigsegg", "Jesko", "Ultra-Rare", "X"),
        ("Aston Martin", "Valkyrie", "Ultra-Rare", "X"),
        ("Porsche", "918 Spyder", "Ultra-Rare", "X"),
        ("McLaren", "P1", "Ultra-Rare", "X"),
        ("Ferrari", "LaFerrari", "Ultra-Rare", "X"),
        ("Koenigsegg", "Regera", "Ultra-Rare", "X"),
        ("Bugatti", "Divo", "Ultra-Rare", "X"),
        # ---- Secret / Tier X (top of the pyramid) ----
        ("Ferrari", "LaFerrari Aperta", "Secret", "X"),
        ("Bugatti", "Bolide", "Secret", "X"),
        ("Koenigsegg", "One:1", "Secret", "X"),
        ("Pagani", "Zonda HP Barchetta", "Secret", "X"),
        ("Mercedes-Benz", "AMG ONE", "Secret", "X"),
        # ---- filler to broaden roster (Common-Rare daily drivers/tuners) ----
        ("Toyota", "Corolla GR", "Uncommon", "III"),
        ("Honda", "Civic Type R", "Rare", "VI"),
        ("Volkswagen", "Scirocco", "Uncommon", "IV"),
        ("Peugeot", "208 GTI", "Uncommon", "IV"),
        ("Renault", "Megane RS", "Rare", "V"),
        ("Seat", "Leon Cupra", "Rare", "V"),
        ("Skoda", "Superb", "Uncommon", "IV"),
        ("Toyota", "Land Cruiser", "Rare", "VI"),
        ("Jeep", "Wrangler", "Uncommon", "IV"),
        ("Land Rover", "Defender", "Rare", "VI"),
        ("Range Rover", "Sport SVR", "Epic", "VII"),
        ("GMC", "Yukon Denali", "Uncommon", "IV"),
        ("Ford", "Raptor F-150", "Rare", "VI"),
        ("Dodge", "RAM 1500 TRX", "Rare", "VI"),
        ("Chevrolet", "Silverado ZR2", "Uncommon", "V"),
        ("Toyota", "GR86", "Rare", "V"),
        ("Subaru", "BRZ", "Rare", "V"),
        ("Hyundai", "Elantra N", "Rare", "V"),
        ("Kia", "Stinger GT", "Rare", "VI"),
        ("Genesis", "G70", "Rare", "VI"),
    ]

    # Значения экономики зависят от тира (I..X -> 1..10)
    tier_index = {t: i + 1 for i, t in enumerate(
        ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    )}
    rarity_income_mult = {
        "Common": 1.0, "Uncommon": 1.4, "Rare": 2.0, "Epic": 3.2,
        "Legendary": 5.0, "Ultra-Rare": 8.0, "Secret": 13.0,
    }

    catalog = []
    for brand, model, rarity, tier in roster:
        t = tier_index[tier]
        base = INCOME_BASE_PER_TIER * t  # базовый доход растёт с тиром
        hourly_income = round(base * rarity_income_mult[rarity])
        base_value = hourly_income * 45  # цена продажи ~45 часов дохода
        name = model
        # Локальная нарисованная карточка по редкости (см. assets/car_placeholders/),
        # без зависимости от внешнего сервиса — надёжнее и не хотлинкает чужой контент.
        slug = RARITY_IMAGE_SLUG.get(rarity, "common")
        image_url = f"local:{slug}"
        catalog.append((name, brand, rarity, tier, hourly_income, base_value, image_url))

    return catalog


async def init_db() -> None:
    """Создаёт схему БД, накатывает миграции и заполняет каталог машин при первом запуске."""
    conn = await get_db()
    await conn.executescript(SCHEMA)
    await conn.commit()

    for migration_sql in MIGRATIONS:
        await conn.execute(migration_sql)
    await conn.commit()

    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM cars")
    row = await cursor.fetchone()
    if row["cnt"] == 0:
        catalog = _build_car_catalog()
        await conn.executemany(
            """INSERT INTO cars (name, brand, rarity, tier, hourly_income, base_value, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            catalog,
        )
        await conn.commit()

    await _rebalance_car_income()


async def _rebalance_car_income() -> None:
    """Идемпотентно пересчитывает доход/цену машин по текущей формуле баланса.
    Безопасно запускать при каждом старте — значения не накапливаются, а
    просто выставляются заново по тем же tier/rarity, что уже есть в базе."""
    conn = await get_db()
    tier_index = {t: i + 1 for i, t in enumerate(
        ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    )}
    rarity_income_mult = {
        "Common": 1.0, "Uncommon": 1.4, "Rare": 2.0, "Epic": 3.2,
        "Legendary": 5.0, "Ultra-Rare": 8.0, "Secret": 13.0,
    }
    cur = await conn.execute(
        "SELECT car_id, tier, rarity, brand, name, image_url FROM cars WHERE photo_is_custom = 0"
    )
    all_cars = await cur.fetchall()
    for car in all_cars:
        t = tier_index.get(car["tier"], 1)
        base = INCOME_BASE_PER_TIER * t
        hourly_income = round(base * rarity_income_mult.get(car["rarity"], 1.0))
        base_value = hourly_income * 45
        slug = RARITY_IMAGE_SLUG.get(car["rarity"], "common")
        image_url = f"local:{slug}"

        already_migrated = bool(car["image_url"]) and car["image_url"].startswith("local:")
        if already_migrated:
            # Картинка уже актуальна — просто освежаем цифры дохода, не трогая кэш фото.
            await conn.execute(
                "UPDATE cars SET hourly_income = ?, base_value = ? WHERE car_id = ?",
                (hourly_income, base_value, car["car_id"]),
            )
        else:
            # Первая миграция со старого формата (URL-плейсхолдер или пусто) —
            # сбрасываем закэшированный file_id, иначе игроки продолжат видеть
            # старую картинку вместо новой отрисованной карточки машины.
            await conn.execute(
                "UPDATE cars SET hourly_income = ?, base_value = ?, image_url = ?, telegram_file_id = NULL "
                "WHERE car_id = ?",
                (hourly_income, base_value, image_url, car["car_id"]),
            )
    await conn.commit()

    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM active_season WHERE is_active = 1")
    row = await cursor.fetchone()
    if row["cnt"] == 0:
        await conn.execute(
            """INSERT INTO active_season (title, duration_days, image_url, start_date, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (
                "Сезон 1: Гараж мечты",
                30,
                "https://placehold.co/800x400?text=Season+1",
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        await conn.commit()


async def ensure_user(tg_id: int, username: str | None, referrer_id: int | None = None) -> bool:
    """Создаёт запись пользователя, если её ещё нет. Админы сразу получают
    максимальный уровень профиля (доступ к аукциону и прочим level-gated фичам).
    Возвращает True, если пользователь был создан только что (для реферальной логики)."""
    conn = await get_db()
    cursor = await conn.execute("SELECT tg_id, level FROM users WHERE tg_id = ?", (tg_id,))
    existing = await cursor.fetchone()
    is_admin = tg_id in ADMIN_IDS

    if existing is None:
        start_level = ADMIN_LEVEL if is_admin else 1
        start_exp = cumulative_exp_for_level(ADMIN_LEVEL) if is_admin else 0
        # Реферал засчитывается, только если пригласивший реально существует и это не сам игрок.
        valid_referrer = None
        if referrer_id and referrer_id != tg_id:
            cur_ref = await conn.execute("SELECT tg_id FROM users WHERE tg_id = ?", (referrer_id,))
            if await cur_ref.fetchone():
                valid_referrer = referrer_id
        await conn.execute(
            """INSERT INTO users (tg_id, username, level, exp, joined_date, last_claim_at, referred_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tg_id, username or "", start_level, start_exp,
             datetime.datetime.utcnow().isoformat(), datetime.datetime.utcnow().isoformat(), valid_referrer),
        )
        await conn.execute(
            "INSERT INTO battle_pass (tg_id, current_level, xp, premium_unlocked) VALUES (?, 1, 0, 0)",
            (tg_id,),
        )
        await conn.commit()
        return True
    else:
        await conn.execute(
            "UPDATE users SET username = ?, profile_visits = profile_visits + 1 WHERE tg_id = ?",
            (username or "", tg_id),
        )
        # Если человека добавили в ADMIN_IDS уже после регистрации — подтягиваем уровень при каждом визите.
        if is_admin and existing["level"] < ADMIN_LEVEL:
            await conn.execute(
                "UPDATE users SET level = ?, exp = ? WHERE tg_id = ?",
                (ADMIN_LEVEL, cumulative_exp_for_level(ADMIN_LEVEL), tg_id),
            )
        await conn.commit()
        return False


async def get_setting(key: str, default: str | None = None) -> str | None:
    conn = await get_db()
    cur = await conn.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    conn = await get_db()
    await conn.execute(
        """INSERT INTO bot_settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    await conn.commit()


async def resolve_player(query: str):
    """Ищет игрока по числовому tg_id или по username (без @). Возвращает
    запись пользователя (tg_id, username, ...) либо None, если не найден."""
    conn = await get_db()
    query = query.strip().lstrip("@")
    if query.isdigit():
        cur = await conn.execute("SELECT * FROM users WHERE tg_id = ?", (int(query),))
    else:
        cur = await conn.execute("SELECT * FROM users WHERE username ILIKE ? LIMIT 1", (query,))
    return await cur.fetchone()


async def get_garage_usage(tg_id: int) -> tuple[int, int]:
    """Возвращает (текущее количество машин в гараже, лимит слотов) игрока."""
    conn = await get_db()
    cur = await conn.execute("SELECT slots_limit FROM users WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    limit = row["slots_limit"] if row else 0
    cur = await conn.execute("SELECT COUNT(*) as cnt FROM user_garage WHERE tg_id = ?", (tg_id,))
    count = (await cur.fetchone())["cnt"]
    return count, limit


async def has_garage_space(tg_id: int) -> bool:
    count, limit = await get_garage_usage(tg_id)
    return count < limit


async def add_user_exp(tg_id: int, amount: int) -> tuple[int, bool]:
    """Начисляет опыт профиля и пересчитывает уровень.
    Возвращает (новый_уровень, произошёл_ли_level_up)."""
    conn = await get_db()
    cur = await conn.execute("SELECT exp, level FROM users WHERE tg_id = ?", (tg_id,))
    row = await cur.fetchone()
    if row is None:
        return 1, False

    # Админы уже на максимуме — просто не трогаем их уровень.
    if tg_id in ADMIN_IDS:
        return row["level"], False

    new_exp = row["exp"] + max(amount, 0)
    new_level = _level_for_exp(new_exp)
    leveled_up = new_level > row["level"]

    await conn.execute("UPDATE users SET exp = ?, level = ? WHERE tg_id = ?", (new_exp, new_level, tg_id))
    await conn.commit()
    return new_level, leveled_up


async def send_car_photo(target, car_id: int, image_url: str | None, telegram_file_id: str | None,
                          caption: str, parse_mode: str = "HTML", reply_markup=None) -> bool:
    """
    Отправляет карточку машины как фото с кэшированием file_id:
    1) если уже есть закэшированный telegram_file_id — используем его (быстро,
       не зависит от внешнего сервиса-заглушки);
    2) иначе пробуем image_url и, если Telegram успешно его принял, сохраняем
       полученный file_id в базу для всех будущих показов этой машины;
    3) если оба варианта не сработали — возвращаем False (вызывающий код
       должен показать текстовое сообщение как запасной вариант).
    target — объект с методом .answer_photo(...) (aiogram Message или CallbackQuery.message).
    """
    if telegram_file_id:
        try:
            await target.answer_photo(telegram_file_id, caption=caption, parse_mode=parse_mode,
                                       reply_markup=reply_markup)
            return True
        except Exception:
            pass  # закэшированный file_id мог протухнуть — пробуем image_url ниже

    if image_url and image_url.startswith("local:"):
        slug = image_url.split(":", 1)[1]
        local_path = os.path.join(CAR_PLACEHOLDERS_DIR, f"{slug}.png")
        if os.path.isfile(local_path):
            try:
                sent = await target.answer_photo(FSInputFile(local_path), caption=caption, parse_mode=parse_mode,
                                                  reply_markup=reply_markup)
                new_file_id = sent.photo[-1].file_id if sent.photo else None
                if new_file_id:
                    conn = await get_db()
                    await conn.execute("UPDATE cars SET telegram_file_id = ? WHERE car_id = ?",
                                        (new_file_id, car_id))
                    await conn.commit()
                return True
            except Exception:
                pass
        return False

    if image_url:
        try:
            sent = await target.answer_photo(image_url, caption=caption, parse_mode=parse_mode,
                                              reply_markup=reply_markup)
            new_file_id = sent.photo[-1].file_id if sent.photo else None
            if new_file_id:
                conn = await get_db()
                await conn.execute("UPDATE cars SET telegram_file_id = ? WHERE car_id = ?", (new_file_id, car_id))
                await conn.commit()
            return True
        except Exception:
            pass

    return False


# ---------------------------------------------------------------- Обязательная подписка (fsub)
async def get_fsub_channels() -> list:
    """Возвращает список обязательных каналов/групп: (fsub_id, chat_id, title, invite_link)."""
    conn = await get_db()
    cur = await conn.execute("SELECT fsub_id, chat_id, title, invite_link FROM fsub_channels ORDER BY fsub_id")
    rows = await cur.fetchall()
    return [(r["fsub_id"], r["chat_id"], r["title"], r["invite_link"]) for r in rows]


async def add_fsub_channel(chat_id: int, title: str, invite_link: str) -> None:
    conn = await get_db()
    await conn.execute(
        "INSERT INTO fsub_channels (chat_id, title, invite_link, added_at) VALUES (?, ?, ?, ?)",
        (chat_id, title, invite_link, datetime.datetime.utcnow().isoformat()),
    )
    await conn.commit()


async def remove_fsub_channel(fsub_id: int) -> None:
    conn = await get_db()
    await conn.execute("DELETE FROM fsub_channels WHERE fsub_id = ?", (fsub_id,))
    await conn.commit()


async def get_not_subscribed_channels(bot, tg_id: int) -> list:
    """Проверяет реальную подписку пользователя на все обязательные каналы/группы через
    Bot API (get_chat_member) и возвращает список тех, на которые он НЕ подписан.
    Бот должен быть добавлен админом в каждый такой канал/группу, иначе Telegram не
    отдаст статус участника. Если проверить не удалось (ошибка API) — считаем, что
    пользователь не подписан, чтобы не пропустить мимо обязательного требования."""
    channels = await get_fsub_channels()
    if not channels:
        return []
    not_subscribed = []
    for fsub_id, chat_id, title, invite_link in channels:
        try:
            member = await bot.get_chat_member(chat_id, tg_id)
            if member.status in ("left", "kicked"):
                not_subscribed.append((fsub_id, chat_id, title, invite_link))
        except Exception:
            not_subscribed.append((fsub_id, chat_id, title, invite_link))
    return not_subscribed


# ---------------------------------------------------------------- Premium BP — общий хелпер
async def is_user_premium(tg_id: int) -> bool:
    """Общая проверка активного Premium BP — используется гаражом, бонусами,
    контейнерами и т.д. для начисления премиум-плюшек."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT premium_unlocked, premium_expires_at FROM battle_pass WHERE tg_id = ?", (tg_id,)
    )
    row = await cur.fetchone()
    if not row or not row["premium_unlocked"]:
        return False
    expires_at = row["premium_expires_at"]
    if not expires_at:
        return True
    try:
        return datetime.datetime.fromisoformat(expires_at) > datetime.datetime.utcnow()
    except ValueError:
        return True


# ---------------------------------------------------------------- Активность / статистика (админка)
async def touch_user_activity(tg_id: int) -> None:
    """Отмечает пользователя активным (не заблокировал бота) и обновляет метрики —
    вызывается на каждое сообщение/callback, чтобы админ видел реальную статистику."""
    conn = await get_db()
    await conn.execute(
        "UPDATE users SET last_active_at = ?, action_count = action_count + 1, blocked_bot = 0 WHERE tg_id = ?",
        (datetime.datetime.utcnow().isoformat(), tg_id),
    )
    await conn.commit()


async def set_user_blocked(tg_id: int, blocked: bool) -> None:
    conn = await get_db()
    await conn.execute("UPDATE users SET blocked_bot = ? WHERE tg_id = ?", (1 if blocked else 0, tg_id))
    await conn.commit()


async def get_bot_stats() -> dict:
    """Данные для админ-панели: сколько всего/активных/заблокировавших бота, новых сегодня,
    и топ самых активных игроков — всё считается на лету, так что цифры всегда актуальны
    (когда юзер блокирует/разблокирует бота, blocked_bot обновляется мгновенно)."""
    conn = await get_db()
    today = datetime.date.today().isoformat()

    cur = await conn.execute("SELECT COUNT(*) as cnt FROM users")
    total = (await cur.fetchone())["cnt"]

    cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE blocked_bot = 0")
    active_members = (await cur.fetchone())["cnt"]

    cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE blocked_bot = 1")
    blocked = (await cur.fetchone())["cnt"]

    cur = await conn.execute("SELECT COUNT(*) as cnt FROM users WHERE joined_date LIKE ?", (f"{today}%",))
    new_today = (await cur.fetchone())["cnt"]

    cur = await conn.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE last_active_at LIKE ?", (f"{today}%",)
    )
    active_today = (await cur.fetchone())["cnt"]

    cur = await conn.execute(
        """SELECT tg_id, username, action_count, level FROM users
           WHERE blocked_bot = 0 ORDER BY action_count DESC LIMIT 10"""
    )
    top_active = await cur.fetchall()

    return {
        "total": total,
        "active_members": active_members,
        "blocked": blocked,
        "new_today": new_today,
        "active_today": active_today,
        "top_active": [(r["tg_id"], r["username"], r["action_count"], r["level"]) for r in top_active],
    }
