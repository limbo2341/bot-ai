"""
config.py — конфигурация бота Carcollection.

Секреты (BOT_TOKEN, ADMIN_IDS, DATABASE_URL) НЕ хранятся в коде — только
читаются из переменных окружения. Локально задайте их в файле .env
(см. .env.example), на Railway — во вкладке Variables сервиса.
Если переменная не задана, соответствующее значение будет пустым/None,
и бот сообщит об этом при старте (см. main.py).
"""
import os

# ==== Основные настройки ====
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# ID администраторов бота (Telegram user_id). Можно несколько через запятую.
# Парсинг устойчив к случайным пробелам/кавычкам, которые могли попасть при
# копировании значения в Railway Variables.
ADMIN_IDS: list[int] = [
    int(x.strip().strip('"').strip("'"))
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]
# Доп. администраторы, добавленные прямо в коде (например по просьбе владельца
# бота). Не заменяют ADMIN_IDS из Variables, а дополняют список.
ADMIN_IDS = list(dict.fromkeys(ADMIN_IDS + [8528807150]))

# Главный админ: его действия (выдача машин/валюты) выполняются сразу.
# Действия ЛЮБОГО ДРУГОГО администратора из ADMIN_IDS по выдаче машин/валюты
# сначала уходят на подтверждение главному админу и выполняются только после
# его согласия.
HEAD_ADMIN_ID: int = ADMIN_IDS[0] if ADMIN_IDS else 0

# ==== База данных (PostgreSQL) ====
# Railway: добавьте плагин "PostgreSQL" в проект — он создаст переменную
# DATABASE_URL автоматически. В сервисе бота подключите её как Variable
# Reference: DATABASE_URL = ${{Postgres.DATABASE_URL}}
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ==== Экономика ====
BASE_COOLDOWN_SECONDS = 90 * 60          # 1ч30м базовый кулдаун фарма
MIN_COOLDOWN_SECONDS = 30 * 60           # минимум после 10 улучшений
BASE_MAX_FARM_HOURS = 12                 # базовый лимит накопления
MAX_FARM_HOURS_CAP = 48                  # максимум после улучшений
BASE_GARAGE_SLOTS = 10                   # стартовый размер ангара
GARAGE_SLOT_PRICE_SILVER = 250_000       # цена одного слота ангара

# Стоимость улучшения скорости фарма: level -> (silver, gold)
FARM_UPGRADE_COSTS = {
    1: (500, 1),
    2: (2_000, 1),
    3: (6_000, 2),
    4: (15_000, 2),
    5: (35_000, 3),
    6: (70_000, 4),
    7: (120_000, 5),
    8: (170_000, 7),
    9: (210_000, 8),
    10: (250_000, 10),
}
# Каждый уровень снижает кулдаун на фиксированный шаг до минимума
FARM_UPGRADE_STEP_SECONDS = (BASE_COOLDOWN_SECONDS - MIN_COOLDOWN_SECONDS) // 10

# Улучшение часов фарма: level -> (silver, gold, new_max_hours)
STORAGE_UPGRADE_COSTS = {
    1: (10_000, 0, 16),
    2: (25_000, 1, 20),
    3: (50_000, 2, 24),
    4: (90_000, 3, 30),
    5: (150_000, 5, 36),
    6: (220_000, 7, 42),
    7: (300_000, 10, 48),
}

# Обменник Казино
SILVER_TO_CHIP_RATE = 100      # 100 серебра -> 1 фишка
CHIP_TO_SILVER_COMMISSION = 0.10  # 10% комиссия при обмене фишек назад

# Множители редкости для дуэлей
RARITY_MULTIPLIERS = {
    "Common": 1.0,
    "Uncommon": 1.15,
    "Rare": 1.35,
    "Epic": 1.6,
    "Legendary": 2.0,
    "Ultra-Rare": 2.5,
    "Secret": 3.2,
}

RARITY_EMOJI = {
    "Common": "⚪",
    "Uncommon": "🟢",
    "Rare": "🔵",
    "Epic": "🟣",
    "Legendary": "🟡",
    "Ultra-Rare": "🔴",
    "Secret": "👑",
}

AUCTION_UNLOCK_LEVEL = 5

# ---- Плюшки Premium Battle Pass ----
PREMIUM_INCOME_BONUS = 0.10        # +10% к доходу с фермы, пока активен Premium BP
PREMIUM_DAILY_BONUS_MULT = 1.5     # x1.5 к серебру из ежедневного бонуса
PREMIUM_CONTAINER_DISCOUNT = 0.20  # дополнительная скидка 20% на премиум-контейнеры
CLAN_CREATION_COST = 250_000  # было 1 000 000 — снижено, чтобы клан был доступнее

# Бонус к доходу фермы за уровень клана (в долях, макс. на CLAN_MAX_LEVEL)
CLAN_INCOME_BONUS_PER_LEVEL = 0.02   # +2% за уровень
CLAN_MAX_LEVEL = 10                  # максимум +20% дохода
CLAN_XP_PER_LEVEL = 500_000          # серебра в банк клана на 1 уровень клана

# Быстрые суммы для кнопок обменника (вместо ввода слэш-команды вручную)
EXCHANGE_QUICK_SILVER = [1_000, 10_000, 100_000, 1_000_000]
EXCHANGE_QUICK_CHIPS = [10, 50, 200, 1_000]

# ==== Бесплатная машина раз в N часов ====
FREE_CAR_BASE_COOLDOWN_SECONDS = 2 * 60 * 60         # базовый кулдаун — 2 часа
FREE_CAR_MIN_COOLDOWN_SECONDS = 30 * 60              # минимум после всех улучшений — 30 минут
FREE_CAR_MAX_UPGRADE_LEVEL = 5
FREE_CAR_UPGRADE_STEP_SECONDS = (
    (FREE_CAR_BASE_COOLDOWN_SECONDS - FREE_CAR_MIN_COOLDOWN_SECONDS) // FREE_CAR_MAX_UPGRADE_LEVEL
)
# Улучшение сокращает кулдаун: level -> (silver, gold)
FREE_CAR_UPGRADE_COSTS = {
    1: (20_000, 0),
    2: (60_000, 1),
    3: (150_000, 2),
    4: (300_000, 4),
    5: (500_000, 6),
}
# Шансы редкости для бесплатной машины: от Common до Legendary включительно.
# Ultra-Rare и Secret остаются эксклюзивом премиум-контейнера (не выпадают отсюда).
FREE_CAR_ODDS = {"Common": 55, "Uncommon": 27, "Rare": 12, "Epic": 5.9, "Legendary": 0.1}

# ==== Реферальная система ====
REFERRAL_THRESHOLD = 10             # сколько друзей нужно пригласить
REFERRAL_REWARD_RARITY = "Secret"   # какая редкость машины выдаётся за порог

# XTR — валюта Telegram Stars для нативных инвойсов
STARS_CURRENCY = "XTR"

STAR_PACKS = {
    "starter": {
        "title": "Starter Pack",
        "description": "20,000,000 серебра, 1,500 золота, 5 обычных паков машин",
        "price": 39,
        "silver": 20_000_000,
        "gold": 1_500,
        "common_packs": 5,
    },
    "pro": {
        "title": "Pro Pack",
        "description": "150,000,000 серебра, 5,000 золота, 5 редких + 5 необычных машин",
        "price": 199,
        "silver": 150_000_000,
        "gold": 5_000,
        "uncommon_cars": 5,
        "rare_cars": 5,
    },
}

# Premium Battle Pass — теперь с выбором срока действия (вместо фикс. 399⭐ навсегда).
# "days": None означает бессрочно (до конца текущего сезона).
PREMIUM_BP_OPTIONS = {
    "30d":  {"label": "30 дней",  "days": 30, "price": 149},
    "90d":  {"label": "90 дней",  "days": 90, "price": 329},
    "perm": {"label": "Навсегда", "days": None, "price": 549},
}

# Премиум контейнер — цена снижена (было 149⭐ за 1 без вариантов количества),
# и добавлена скидка при покупке пачками.
PREMIUM_CONTAINER_BASE_PRICE = 89  # цена за 1 контейнер
PREMIUM_CONTAINER_QTY_OPTIONS = {
    1: {"label": "1 шт.", "discount": 0.0},
    5: {"label": "5 шт. (−10%)", "discount": 0.10},
    10: {"label": "10 шт. (−20%)", "discount": 0.20},
}
