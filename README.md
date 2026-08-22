# Cargo Bot

Telegram-бот на Python для регистрации клиентов и обработки заявок на доставку. Один код поддерживает два режима развёртывания: Railway через long polling и Render Web Service через webhook.

## Возможности текущего этапа

- регистрация клиента по Telegram user ID;
- постоянный уникальный Client ID в формате `C000001`;
- профиль клиента;
- персонализированное сообщение с адресом китайского склада;
- создание и просмотр существующих заявок;
- управление статусами заявок администратором.

После регистрации Client ID необходимо указывать на посылке или в данных получателя. Повторный `/start` не создаёт нового клиента.

## Стек

- Python 3.11+
- aiogram 3 и aiohttp
- asyncpg и PostgreSQL/Supabase
- python-dotenv
- Docker

## Установка

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Общие переменные окружения

```dotenv
BOT_TOKEN=
ADMIN_ID=
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_SSL=require
DEPLOY_MODE=polling
CHINA_WAREHOUSE_ADDRESS=
CHINA_WAREHOUSE_RECIPIENT=
CHINA_WAREHOUSE_PHONE=
```

Секреты нельзя добавлять в Git. Для Supabase используется `DB_SSL=require`; для локального PostgreSQL без SSL — `DB_SSL=disable`. Переменные китайского склада необязательны: если `CHINA_WAREHOUSE_ADDRESS` пуст, бот продолжит работать и покажет клиенту, что адрес ещё не настроен.

## Railway: long polling

Для Railway достаточно добавить к общим переменным:

```dotenv
DEPLOY_MODE=polling
```

Команда запуска остаётся общей:

```text
python main.py
```

Перед запуском polling приложение удаляет ранее установленный webhook без удаления накопившихся обновлений.

## Render: webhook

Создайте Render Web Service из того же репозитория и используйте Dockerfile. Добавьте общие переменные и:

```dotenv
DEPLOY_MODE=webhook
WEBHOOK_BASE_URL=https://your-service.onrender.com
WEBHOOK_PATH=/telegram/webhook
WEBHOOK_SECRET=replace-with-random-secret
PORT=10000
```

`WEBHOOK_BASE_URL` должен быть внешним HTTPS-адресом Render. `WEBHOOK_SECRET` — отдельная случайная строка из букв, цифр, `_` и `-`; это не `BOT_TOKEN`.

Render передаёт `PORT` автоматически. Приложение слушает `0.0.0.0:$PORT`, устанавливает webhook при старте и намеренно не удаляет его при shutdown, чтобы следующий Telegram webhook мог разбудить уснувший сервис.

Проверка HTTP-сервиса:

```text
GET https://your-service.onrender.com/health
```

Ожидаемый ответ:

```json
{"status": "ok"}
```

`/health` не обращается к PostgreSQL.

Render Free засыпает после периода без входящих запросов. Первое сообщение после сна может обрабатываться с задержкой из-за холодного запуска; Telegram обычно повторяет недоставленный webhook.

## Важное ограничение Telegram

**Не запускайте Railway polling и Render webhook одновременно с одним `BOT_TOKEN`.** Telegram не поддерживает одновременную нормальную работу webhook и `getUpdates` для одного бота.

Для параллельного сравнения используйте два тестовых бота с разными токенами. Предпочтительно использовать и отдельный тестовый проект Supabase.

Если токен один:

- Railway → Render: остановите Railway, задайте Render-переменные и запустите Render;
- Render → Railway: остановите Render, установите `DEPLOY_MODE=polling` и запустите Railway — приложение само удалит webhook.

## Проверка установленного webhook

Telegram Bot API позволяет проверить состояние webhook методом `getWebhookInfo`. Подставляйте токен только локально и не сохраняйте команду с реальным токеном в Git или публичных логах:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
```

В polling-режиме поле `url` должно быть пустым. В Render webhook-режиме оно должно содержать адрес из `WEBHOOK_BASE_URL` и `WEBHOOK_PATH`.

## Структура

```text
main.py                 выбор режима запуска
bot_app.py              общие Bot, Dispatcher, routers и команды
config.py               загрузка и проверка настроек
database.py             создание asyncpg-пула
runners/polling.py      Railway long polling
runners/webhook.py      Render webhook и /health
handlers/               общие Telegram-обработчики
repositories/           SQL-запросы приложения
services/               бизнес-логика клиентов и сообщений
migrations/             механизм и SQL-файлы миграций
tests/                  smoke-тесты без Telegram и PostgreSQL
docs/                   спецификация Cargo MVP
```

## Миграции

Миграции из `migrations/sql` выполняются по имени файла. Версии и контрольные суммы записываются в `schema_migrations`.

Правила:

1. Не редактировать уже применённую миграцию.
2. Для изменения схемы создавать следующий SQL-файл.
3. Перед production-миграцией сделать резервную копию.
4. Сначала проверять миграции на копии базы.

Первая миграция создаёт исходную таблицу `orders`. Миграция `002_create_clients.sql` отдельно создаёт клиентов и не изменяет `orders`. Client ID формируется из PostgreSQL identity, поэтому параллельные регистрации не используют небезопасный `MAX + 1`.

## Ручная проверка

1. Новый пользователь отправляет `/start`, проходит регистрацию и получает Client ID.
2. Повторный `/start` показывает тот же Client ID без повторной регистрации.
3. Кнопка «👤 Мой профиль» показывает Client ID, имя, телефон и город.
4. Кнопка «🏭 Адрес склада в Китае» показывает настроенный адрес и Client ID либо понятное сообщение, если адрес не задан.
5. «📦 Новая заявка» и «📋 Мои заявки» продолжают прежний сценарий.
6. Администратор проверяет `/orders` и смену статуса заявки.

## Тесты

```powershell
python -m unittest discover -s tests -v
```

Smoke-тесты не запускают polling, HTTP-сервер, Telegram API или PostgreSQL.
