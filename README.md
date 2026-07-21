# Carcollection — Telegram Game Bot

Экономический автокол-симулятор на `aiogram 3.x` + `PostgreSQL` (asyncpg).

## Установка (Termux / любой Linux)

```bash
pkg install python git   # только для Termux
git clone <ваш-репозиторий>
cd carcollection
pip install -r requirements.txt
cp .env.example .env     # заполните BOT_TOKEN, ADMIN_IDS, DATABASE_URL
export $(cat .env | xargs)
python main.py
```

Для локального теста нужен запущенный PostgreSQL, например:
```bash
docker run -d --name carcollection-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=carcollection -p 5432:5432 postgres:16
```

## Деплой на Railway (пошагово)

**От вас требуется:**
1. `BOT_TOKEN` — токен бота от [@BotFather](https://t.me/BotFather) (команда `/newbot`).
2. `ADMIN_IDS` — ваш числовой Telegram ID (узнать у [@userinfobot](https://t.me/userinfobot)). Можно несколько через запятую.
3. Плагин **PostgreSQL**, добавленный в тот же Railway-проект (даёт persistent базу данных — Volume для файлов больше не нужен).

**Шаги:**

1. Railway → **New Project** → **Deploy from GitHub repo** → выберите репозиторий с этим кодом.
2. В том же проекте: **+ New** → **Database** → **Add PostgreSQL**. Railway создаст сервис Postgres со своей переменной `DATABASE_URL`.
3. Откройте сервис бота → вкладка **Variables** → добавьте:
   - `BOT_TOKEN` = ваш токен
   - `ADMIN_IDS` = ваш Telegram ID
   - `DATABASE_URL` = нажмите **Add Reference** → выберите сервис Postgres → `DATABASE_URL` (это подставит `${{Postgres.DATABASE_URL}}` автоматически)
4. Нажмите **Deploy**. Railway сам подхватит `Procfile` (`worker: python main.py`) и `requirements.txt`.

Бот при первом запуске сам создаст все таблицы и заполнит каталог машин (см. `init_db()` в `db.py`). Прогресс игроков хранится в PostgreSQL и переживает редеплои без какой-либо ручной настройки Volume — база данных Railway PostgreSQL persistent по умолчанию.

**Про секреты**: `BOT_TOKEN`, `ADMIN_IDS` и `DATABASE_URL` нигде не хранятся в коде — только читаются из переменных окружения (см. `config.py`). Если какая-то из них не задана, бот при старте выведет понятную ошибку и не запустится, вместо непонятного краша. Файл `.env` с реальными секретами в `.gitignore` и никогда не попадёт в репозиторий — используйте `.env.example` только как шаблон.

## Структура проекта

```
carcollection/
├── config.py           # токены, админы, константы экономики
├── db.py                # схема PostgreSQL (asyncpg) + каталог 115 машин
├── keyboards.py         # все инлайн/reply клавиатуры
├── main.py               # точка входа, регистрация роутеров
└── handlers/
    ├── common.py         # /start, профиль, аватар, инвентарь, клан
    ├── garage.py          # фарм, гараж, улучшения
    ├── casino.py          # обменник, /basket /slot /dice
    ├── payments.py        # Telegram Stars (XTR) инвойсы
    ├── admin.py            # /addcar /addseason /give /ban /broadcast
    ├── battlepass.py       # боевой пропуск, задания
    ├── duels.py             # состав, матчмейкинг, формула силы
    ├── auctions.py          # аукцион (level 10+)
    └── containers.py        # гача-контейнеры с таблицей шансов
```

## Админ-команды

- `/addcar` — FSM добавления новой машины (с фото)
- `/addseason` — FSM запуска нового сезона Battle Pass (с баннером)
- `/give {tg_id} {silver|gold|chips} {amount}`
- `/givecar {tg_id} {car_id}`
- `/ban {tg_id} {причина}` / `/unban {tg_id}`
- `/broadcast` — рассылка всем пользователям

## Важное примечание об экономике казино

Мини-игры (`/basket`, `/slot`, `/dice`) используют исключительно
внутриигровую валюту «фишки», получаемую через обменник серебра.
Это игровая механика, а не реальные денежные ставки.

## Работа бота в группах

Бот умеет отвечать на обычные слова без эмодзи («Гараж», «Собрать», «Казино» и т.д.)
и на слэш-команды (`/garage`, `/collect`, `/casino`, `/pay` и др.) прямо в групповом чате —
не нужно нажимать кнопки.

**Обязательный шаг, который нельзя сделать через код:** зайдите к
[@BotFather](https://t.me/BotFather) → выберите вашего бота → **Bot Settings** →
**Group Privacy** → **Turn off**. Без этого Telegram по умолчанию показывает боту
в группах только команды с `/` и сообщения, где его явно упомянули (`@bot`) —
он физически не увидит текст «Собрать», написанный без обращения к нему.

Команда `/pay {сумма}` переводит серебро игроку — используйте её ответом
(reply) на сообщение получателя.
