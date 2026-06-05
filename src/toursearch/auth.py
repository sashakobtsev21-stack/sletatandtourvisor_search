"""Аутентификация: хеширование паролей, токены сессий, роли и права (только stdlib).

Никаких внешних зависимостей — PBKDF2 из `hashlib` + `secrets`, в духе минимализма проекта.
Чистая крипто/политика без БД: пользователей и сессии хранит `storage.Storage`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

# --- Пароли: PBKDF2-HMAC-SHA256, строка 'pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>' ---
_ALGO = "pbkdf2_sha256"
_ITERS = 600_000          # OWASP-2023 для PBKDF2-HMAC-SHA256; число в строке → можно поднимать
_SALT_BYTES = 16


def hash_password(password: str, *, iters: int | None = None) -> str:
    """Хеш пароля для хранения. `iters` читается из модуля во время вызова — тесты могут
    понизить `_ITERS` или передать малое значение, чтобы не платить ~0.3с за хеш."""
    iters = iters if iters is not None else _ITERS
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return f"{_ALGO}${iters}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Проверить пароль против хранимого хеша (constant-time сравнение)."""
    try:
        algo, iters_s, salt_s, hash_s = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 base64.b64decode(salt_s), int(iters_s))
        return hmac.compare_digest(dk, base64.b64decode(hash_s))
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True, если хеш слабее текущей политики (другой алгоритм или меньше итераций) —
    повод тихо пересчитать его при следующем успешном входе."""
    try:
        algo, iters_s, _, _ = stored.split("$")
        return algo != _ALGO or int(iters_s) < _ITERS
    except Exception:
        return True


# --- Токены сессий: в cookie едет сам токен, в БД хранится только его sha256 ---
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- Время (UTC ISO; одинаково форматированные строки лексикографически сравнимы,
#     поэтому годятся для WHERE expires_at > ? без парсинга) ---
SESSION_TTL_DEFAULT = timedelta(hours=12)
SESSION_TTL_REMEMBER = timedelta(days=30)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def utcnow_iso() -> str:
    return iso(utcnow())


def session_ttl(remember: bool) -> timedelta:
    return SESSION_TTL_REMEMBER if remember else SESSION_TTL_DEFAULT


# --- Роли и права (2 роли; абстракция прав сохранена — 3-я роль = строка + запись здесь) ---
ROLES = ("admin", "user")
PERMISSIONS = (
    "search.run",            # запускать анализ
    "history.view.own",      # своя история
    "history.view.all",      # вся история (чужие прогоны)
    "tests.run",             # запускать автотесты
    "tests.view",            # каталог автотестов
    "users.manage",          # управление пользователями
    "system.health",         # health / настройки
)
ROLE_PERMISSIONS = {
    "admin": set(PERMISSIONS),                      # всё
    "user": {"search.run", "history.view.own"},     # запуск анализа + своя история
}


def has_permission(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for(role: str) -> list[str]:
    """Права роли в стабильном порядке (для `/api/me` на фронт)."""
    granted = ROLE_PERMISSIONS.get(role, frozenset())
    return [p for p in PERMISSIONS if p in granted]
