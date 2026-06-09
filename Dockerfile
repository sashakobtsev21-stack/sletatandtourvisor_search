# Multi-stage build для toursearch.
# Stage 1: фронт (Node) — собираем dist; Stage 2: бэк (Python+Playwright) — копируем dist.
# Итоговый образ — Python с Playwright Chromium, статика встроена.

# --- Stage 1: frontend ---
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend ---
# mcr.microsoft.com/playwright/python включает Python 3.12 + системные либы Chromium.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Запуск НЕ от root (контейнер уже идёт с пользователем pwuser, но создадим явный app-user
# в HOME-овой папке, чтобы права на /app и /data были чистыми).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Сначала только pyproject.toml + requirements.txt — для слойного кэша Docker.
COPY pyproject.toml requirements.txt ./
RUN pip install -r requirements.txt && pip install --no-deps .

# Копируем код и собранный фронт.
COPY src/ ./src/
COPY README.md LICENSE ./
RUN pip install --no-deps -e .   # editable, чтобы entrypoint видел изменения src
COPY --from=frontend /build/dist ./frontend/dist

# Папка для БД и скриншотов — пробрасывается как volume в проде.
RUN mkdir -p /data/screenshots && chown -R 1000:1000 /data
ENV TOURSEARCH_DB=/data/toursearch.db
VOLUME ["/data"]

# Healthcheck — /healthz без auth, без БД (только что процесс жив + event loop отвечает).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

EXPOSE 8000

# ВАЖНО: workers=1 by design — rate-limit и retention loop не координируются между
# воркерами SQLite. Для горизонтального масштабирования нужны Redis + внешний планировщик
# (см. README раздел «Деплой за reverse-proxy»).
USER 1000
WORKDIR /data
CMD ["toursearch", "web", "--host", "0.0.0.0", "--port", "8000", "--db", "/data/toursearch.db"]
