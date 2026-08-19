# Cargo Bot

Минимальный Telegram-бот для оформления и обработки заявок на доставку. Текущий пользовательский сценарий сохранён; расширенный Cargo MVP внедряется поэтапно.

## Стек

- Python 3.11+
- aiogram 3
- asyncpg
- PostgreSQL
- python-dotenv

## Установка

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Создайте `.env` в корне проекта. Значения секретов нельзя добавлять в Git.

```dotenv
BOT_TOKEN=
ADMIN_ID=
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_SSL=require
```

Для локального PostgreSQL без SSL используйте `DB_SSL=disable`. Поддерживаются `disable`, `require`, `verify-ca`, `verify-full`.

## Запуск

```powershell
python main.py
```

При старте создаётся пул соединений, применяются ещё не выполненные SQL-миграции, затем запускается polling Telegram.

## Структура

```text
main.py                 точка запуска
config.py               загрузка и проверка настроек
database.py             создание asyncpg-пула
handlers/               Telegram-обработчики
repositories/           SQL-запросы приложения
migrations/             механизм и SQL-файлы миграций
filters.py              фильтры aiogram
keyboards.py            клавиатуры
states.py               FSM-состояния
tests/                  smoke-тесты
docs/                   спецификация Cargo MVP
```

## Миграции

Миграции находятся в `migrations/sql` и выполняются по имени файла. Применённые версии и контрольные суммы записываются в `schema_migrations`.

Правила:

1. Не редактировать уже применённую миграцию.
2. Для изменения схемы создавать следующий файл, например `002_add_example.sql`.
3. Перед production-миграцией сделать резервную копию базы.
4. Сначала проверить миграцию на копии базы.

Первая миграция использует `CREATE TABLE IF NOT EXISTS` и не изменяет существующую таблицу `orders`.

## Тесты

Smoke-тесты не подключаются к Telegram или PostgreSQL:

```powershell
python -m unittest discover -s tests -v
```
