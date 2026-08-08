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

# Главный админ: его действия (выдача поездов/валюты) выполняются сразу.
# Действия ЛЮБОГО ДРУГОГО администратора из ADMIN_IDS по выдаче поездов/валюты
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
GARAGE_SLOT_PRICE_SILVER = 75_000        # цена одного слота ангара (снижено на ~70%)

# Стоимость улучшения скорости фарма: level -> (silver, gold) — цены снижены на ~70%
FARM_UPGRADE_COSTS = {
    1: (150, 1),
    2: (600, 1),
    3: (2_000, 1),
    4: (4_500, 1),
    5: (10_000, 2),
    6: (21_000, 2),
    7: (36_000, 2),
    8: (51_000, 4),
    9: (63_000, 4),
    10: (75_000, 5),
}
# Каждый уровень снижает кулдаун на фиксированный шаг до минимума
FARM_UPGRADE_STEP_SECONDS = (BASE_COOLDOWN_SECONDS - MIN_COOLDOWN_SECONDS) // 10

# Улучшение часов фарма: level -> (silver, gold, new_max_hours) — цены снижены на ~70%
STORAGE_UPGRADE_COSTS = {
    1: (3_000, 0, 16),
    2: (7_500, 0, 20),
    3: (15_000, 1, 24),
    4: (27_000, 2, 30),
    5: (45_000, 2, 36),
    6: (66_000, 4, 42),
    7: (90_000, 5, 48),
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

AUCTION_UNLOCK_LEVEL = 1

# ---- 🧬 Слияние поездов (крафт): N дубликатов одной редкости -> 1 поезд следующей редкости.
# Secret не крафтится — остаётся эксклюзивом premium/donate контейнеров.
FUSION_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Ultra-Rare"]
FUSION_REQUIREMENTS = {
    "Common": {"count": 3, "fee_silver": 2_000},
    "Uncommon": {"count": 3, "fee_silver": 6_000},
    "Rare": {"count": 4, "fee_silver": 15_000},
    "Epic": {"count": 4, "fee_silver": 40_000},
    "Legendary": {"count": 5, "fee_silver": 100_000},
    "Ultra-Rare": {"count": 6, "fee_silver": 250_000},
}
FUSION_NEXT_RARITY = {
    "Common": "Uncommon", "Uncommon": "Rare", "Rare": "Epic",
    "Epic": "Legendary", "Legendary": "Ultra-Rare", "Ultra-Rare": "Secret",
}

# ---- ⬆️ Прокачка конкретного поезда: +10% к его доходу/час за уровень (влияет и на
# мощь в дуэлях, т.к. она считается от дохода поездов). Стоимость растёт с уровнем и
# зависит от базового дохода поезда — дорогие редкие поезда дороже качать.
CAR_UPGRADE_MAX_LEVEL = 10
CAR_UPGRADE_INCOME_PER_LEVEL = 0.10
CAR_UPGRADE_COST_PER_INCOME = 8  # силвер за 1 очко часового дохода поезда, умножается на (уровень+1)
# (часы, комиссия за выставление лота серебром) — чем дольше висит лот, тем дороже
AUCTION_DURATION_OPTIONS = [(24, 5_000), (48, 10_000), (72, 18_000)]
AUCTION_MIN_BID_STEP = 100          # минимальный шаг ставки, если % от цены меньше этого
AUCTION_MIN_BID_STEP_PERCENT = 0.05  # +5% к текущей ставке как минимум
AUCTION_ANTISNIPE_WINDOW_MIN = 5     # если ставка в последние N минут — лот продлевается
AUCTION_ANTISNIPE_EXTEND_MIN = 5     # на сколько минут продлевается

# ---- Плюшки Premium Battle Pass ----
PREMIUM_INCOME_BONUS = 0.10        # +10% к доходу с фермы, пока активен Premium BP
PREMIUM_DAILY_BONUS_MULT = 1.5     # x1.5 к серебру из ежедневного бонуса
PREMIUM_CONTAINER_DISCOUNT = 0.20  # дополнительная скидка 20% на премиум-контейнеры

# ---- Бесплатные (но не лёгкие) способы заработать золото ----
DUEL_WIN_STREAK_GOLD = 40          # золото за каждые 3 победы в дуэлях подряд
DUEL_WIN_STREAK_TARGET = 3
CASINO_JACKPOT_CHANCE = 0.03       # 3% шанс джекпота на любую игру в казино
CASINO_JACKPOT_GOLD = (15, 30)     # диапазон золота за джекпот
WEEKLY_STREAK_GOLD = 80            # золото за каждые 7 дней серии ежедневного бонуса подряд
REFERRAL_GOLD_TIER1 = (3, 30)      # (рефералов, золота) — промежуточная награда до большой (car на 10-м)
REFERRAL_GOLD_TIER2 = (5, 60)
CLAN_LEVELUP_GOLD = 15             # золото каждому участнику клана при повышении уровня клана

# ---- 🌙 Ночной экспресс: бонус к доходу с депо в ночные часы (по UTC) — награда
# за захаживание в бота и ночью, не только днём.
NIGHT_EXPRESS_START_HOUR = 0
NIGHT_EXPRESS_END_HOUR = 6
NIGHT_EXPRESS_BONUS = 0.25

# ---- 🎯 Система "жалости" (pity) для контейнеров: если долго не везёт, следующий
# гарантированно даст Epic или выше — стандартная и любимая механика гача-игр.
CONTAINER_PITY_THRESHOLD = 15
RARITY_RANK = {"Common": 0, "Uncommon": 1, "Rare": 2, "Epic": 3, "Legendary": 4, "Ultra-Rare": 5, "Secret": 6}
CONTAINER_PITY_MIN_RANK = RARITY_RANK["Epic"]

# ---- Доп. плюшки Premium BP в боевом пропуске ----
PREMIUM_BP_XP_BOOST = 0.25         # +25% к получаемому XP боевого пропуска
PREMIUM_BP_LEVEL_DISCOUNT = 0.20   # скидка 20% на покупку уровней за золото

# ---- Золото за звёзды (донат-способ) ----
GOLD_PACKS = {
    "small": {"label": "1 000 золота", "gold": 1_000, "price": 129},
    "large": {"label": "5 000 золота", "gold": 5_000, "price": 549},
}
CLAN_CREATION_COST = 250_000  # было 1 000 000 — снижено, чтобы клан был доступнее

# Бонус к доходу фермы за уровень клана (в долях, макс. на CLAN_MAX_LEVEL)
CLAN_INCOME_BONUS_PER_LEVEL = 0.02   # +2% за уровень
CLAN_MAX_LEVEL = 10                  # максимум +20% дохода
CLAN_XP_PER_LEVEL = 500_000          # серебра в банк клана на 1 уровень клана

# Быстрые суммы для кнопок обменника (вместо ввода слэш-команды вручную)
EXCHANGE_QUICK_SILVER = [1_000, 10_000, 100_000, 1_000_000]
EXCHANGE_QUICK_CHIPS = [10, 50, 200, 1_000]

# ==== Бесплатный поезд раз в N часов ====
FREE_CAR_BASE_COOLDOWN_SECONDS = 2 * 60 * 60         # базовый кулдаун — 2 часа
FREE_CAR_MIN_COOLDOWN_SECONDS = 30 * 60              # минимум после всех улучшений — 30 минут
FREE_CAR_MAX_UPGRADE_LEVEL = 5
FREE_CAR_UPGRADE_STEP_SECONDS = (
    (FREE_CAR_BASE_COOLDOWN_SECONDS - FREE_CAR_MIN_COOLDOWN_SECONDS) // FREE_CAR_MAX_UPGRADE_LEVEL
)
# Улучшение сокращает кулдаун: level -> (silver, gold) — цены снижены на ~70%
FREE_CAR_UPGRADE_COSTS = {
    1: (6_000, 0),
    2: (18_000, 0),
    3: (45_000, 1),
    4: (90_000, 2),
    5: (150_000, 3),
}
# Шансы редкости для бесплатного поезда: от Common до Legendary включительно.
# Ultra-Rare и Secret остаются эксклюзивом премиум-контейнера (не выпадают отсюда).
FREE_CAR_ODDS = {"Common": 25, "Uncommon": 27, "Rare": 22, "Epic": 17, "Legendary": 8, "Secret": 1}

# ==== Реферальная система ====
REFERRAL_THRESHOLD = 10             # сколько друзей нужно пригласить
REFERRAL_REWARD_RARITY = "Secret"   # какая редкость поезда выдаётся за порог

# XTR — валюта Telegram Stars для нативных инвойсов
STARS_CURRENCY = "XTR"

STAR_PACKS = {
    "starter": {
        "title": "Starter Pack",
        "description": "20,000,000 серебра, 1,500 золота, 5 обычных паков поездов",
        "price": 39,
        "silver": 20_000_000,
        "gold": 1_500,
        "common_packs": 5,
    },
    "pro": {
        "title": "Pro Pack",
        "description": "150,000,000 серебра, 5,000 золота, 5 редких + 5 необычных поездов",
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
PREMIUM_CONTAINER_GOLD_PRICE = 700  # альтернативная фиксированная цена золотом (без пакетных скидок)

# ---- 🎟 Ежедневная лотерея: все билеты формируют общий банк, раз в 24ч случайный
# победитель (шанс пропорционален числу купленных билетов) забирает LOTTERY_PAYOUT_SHARE
# от банка — остальное считается "комиссией дома" (небольшой сброс серебра из экономики).
LOTTERY_TICKET_PRICE = 10_000  # было 1 000 — выше ставки, крупнее банк
LOTTERY_PAYOUT_SHARE = 0.85
PREMIUM_CONTAINER_QTY_OPTIONS = {
    1: {"label": "1 шт.", "discount": 0.0},
    5: {"label": "5 шт. (−10%)", "discount": 0.10},
    10: {"label": "10 шт. (−20%)", "discount": 0.20},
}
