FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# app/ включает миграции (app/migrations): приложение применяет их само при запуске.
COPY alembic.ini ./
COPY app ./app

# Без прав root: уязвимость в приложении не даёт доступа ко всему контейнеру.
RUN useradd --system --uid 10001 --no-create-home quizroom
USER quizroom

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
# Один воркер: состояние игровых комнат хранится в памяти процесса.
# API не публикует порт наружу; Nginx перезаписывает X-Forwarded-For адресом клиента.
# --timeout-graceful-shutdown: при остановке комнаты успевают записать сыгранное в базу.
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--ws-max-size", "65536", "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--timeout-graceful-shutdown", "20", "--no-server-header"]
