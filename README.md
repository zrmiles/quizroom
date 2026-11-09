# QuizRoom — онлайн-викторины в реальном времени

Учебный проект («Проектный практикум», 2026). Ведущий собирает викторину и показывает код комнаты на большом экране, игроки отвечают с телефонов без регистрации, после каждого вопроса — разбор и таблица лидеров, после игры — отчёт для преподавателя.

## Что умеет

- **Три типа вопросов:** один ответ, «угадай число» (очки за близость, точное попадание ×2), «расставь по порядку».
- **Игра в реальном времени** по WebSocket: серверный таймер, очки за скорость, переподключение без потери очков.
- **Лобби-аквариум:** игрок собирает существо-аватар, оно плавает на экране ведущего; можно «помахать».
- **Отчёт преподавателя:** карта «ученик × вопрос», трудные вопросы, выгрузка для Excel, кнопка «повторить только ошибки».
- Регистрация и вход ведущих (JWT), редактор с проверкой ошибок, история игр.

## Стек

| Часть | Технологии |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), PostgreSQL / SQLite, PyJWT, bcrypt |
| Frontend | React 18, TypeScript, Vite, React Router |
| Тесты | Pytest (unit + интеграционные через WebSocket), Vitest |
| Инфраструктура | Docker Compose, Nginx, GitHub Actions |

Дизайн и токены стиля «Риф» — [docs/DESIGN.md](docs/DESIGN.md). План проекта, модель данных и спринты — [docs/PLAN.md](docs/PLAN.md).

## Запуск через Docker

```bash
cp .env.example .env   # впишите JWT_SECRET — без него compose не запустится
docker compose up --build
```

Откройте http://localhost:8080.

## Запуск для разработки

Нужны Python 3.12, [uv](https://docs.astral.sh/uv/) и Node.js 22.12+ (ветка 22) или 24.x.

```bash
# backend — http://localhost:8000, документация API: /docs
cd backend
export JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
uv sync
uv run uvicorn app.main:app --reload
```

```bash
# frontend — http://localhost:5173 (проксирует /api и /ws на :8000)
cd frontend
npm install
npm run dev
```

Backend требует `JWT_SECRET` длиной от 32 символов. Для постоянной локальной настройки сохраните его
в `backend/.env` и используйте один и тот же ключ после перезапуска. Файл `.env` не коммитьте.
Dev-сервер по умолчанию слушает `127.0.0.1`; для проверки с телефона в своей сети запустите
`npm run dev -- --host`. Доступ с посторонних веб-origin запрещён.

Без настроек backend использует SQLite-файл `backend/quizroom.db`. Для PostgreSQL задайте `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db`.

## Тесты

```bash
cd backend && uv run pytest        # очки, API, WebSocket, сбои БД и конкурентные операции
cd frontend && npm test            # проверка вопросов, форматирование, таймер, выгрузка
```

В CI backend-тесты проходят на SQLite и PostgreSQL. Для отдельной одноразовой PostgreSQL-базы локально:
`TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/quizroom_test uv run pytest`.
Frontend-тесты включают проверки компонентов: дробный ввод, подтверждение ответа, восстановление входа
и защита несохранённых правок редактора.

Сценарный и нагрузочный прогон по запущенному серверу (несколько игроков, обрывы связи, 60 игроков сразу):

```bash
cd backend && PORT=8000 uv run python scripts/live_scenarios.py
```

## Как это устроено

```
Телефоны игроков ─┐                    ┌─ PostgreSQL: пользователи, викторины, история, ответы
Экран ведущего ───┼─ Nginx ─ FastAPI ──┤
                  │   /api  REST       └─ Комнаты в памяти процесса (game/engine.py)
                  │   /ws   WebSocket
```

- Сервер — единственный источник истины: он хранит состояние комнаты, сам закрывает вопрос по таймеру и считает очки. Клиент рисует таймер от серверного `endsAt` с поправкой на разницу часов.
- При запуске игры вопросы копируются в `game_sessions.snapshot`, поэтому правка викторины не ломает историю и отчёты.
- Защита комнаты: ведущий может закрыть вход, удалённый игрок не вернётся под тем же именем. С одного адреса — не больше 30 неверных PIN и 120 входов в минуту (рассчитано на класс за одним роутером).
- **Ограничение MVP:** комнаты живут в памяти одного процесса API (один воркер). После перезапуска незаконченные игры помечаются как прерванные. Для масштабирования состояние переносится в Redis — это в плане развития.

### REST API (кратко)

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Регистрация и вход, возвращают JWT |
| GET/POST | `/api/quizzes` | Мои викторины / создать |
| GET/PUT/DELETE | `/api/quizzes/{id}` | Викторина целиком с вопросами |
| POST | `/api/sessions` | Запустить игру → PIN |
| GET | `/api/sessions/{pin}` | Проверить код комнаты |
| POST | `/api/sessions/{pin}/join` | Войти игроком (ник + аватар) → токен игрока |
| GET | `/api/sessions/history` | История игр ведущего |
| GET | `/api/sessions/{id}/report` | Отчёт по игре |
| POST | `/api/sessions/{id}/retry` | Новая игра из вопросов, где ошиблось большинство |

Полная интерактивная документация — http://localhost:8000/docs.

### WebSocket `/ws/game/{pin}`

Первым сообщением клиент присылает `{"type": "auth", "role": "host" | "player", "token": "…"}` — токен не передаётся в адресе, чтобы не попадать в логи сервера и прокси.

- Ведущий → сервер: `host:start`, `host:next`, `host:skip`, `host:end`, `host:kick`, `host:lock` / `host:unlock` (закрыть и открыть вход для новых игроков) (`host:next` и `host:skip` передают `questionIndex`, чтобы запоздавшее нажатие не задело следующий вопрос)
- Игрок → сервер: `player:answer {questionIndex, value}`, `player:wave`
- Сервер → клиенты: `state:snapshot`, `lobby:update`, `lobby:wave`, `question:start`, `question:progress`, `answer:ack`, `question:reveal`, `game:finished`, `error`

## Структура

```
backend/
  app/main.py            точка входа FastAPI
  app/models.py          таблицы
  app/schemas.py         проверка входных данных
  app/routers/           auth, quizzes, sessions, ws
  app/game/engine.py     игровые комнаты и таймер
  app/game/scoring.py    подсчёт очков
  tests/
frontend/
  src/pages/             главная, вход, мои викторины, редактор, ведущий, игрок, отчёт
  src/components/        существо, таймер, шапка
  src/lib/               API, авторизация, WebSocket, проверка вопросов
docs/                    план и дизайн
```

## Команда

| Участник | Роль | Зона ответственности |
|---|---|---|
| [ФИО] | Team Lead / Backend | архитектура, игровой движок |
| [ФИО] | Product Manager / Frontend | редактор, экраны игры |
| [ФИО] | Project Manager / Frontend | UI, адаптив |
| [ФИО] | DevOps & QA / Backend | CI/CD, деплой, тесты |
