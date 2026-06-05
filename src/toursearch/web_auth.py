"""Авторизация веба: middleware с тремя режимами, эндпоинты входа/профиля/пользователей,
хелперы прав. Выделено из web.py (god-модуль) — поведение не меняется. См. docs/AUTH_PLAN.md.

`register_auth(app, ...)` навешивает на приложение middleware и эндпоинты /api/login|logout|me|users.
`current_user_id` / `owner_filter` / `LOCAL_HOSTS` импортирует web.py для своих хендлеров.
"""

from __future__ import annotations

import hmac
import time
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from toursearch import auth, billing
from toursearch.storage import Storage

# Хосты, считающиеся локальными (secure-cookie выкл, предохранитель не нужен).
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", ""}

# Пути, где middleware не делает НИЧЕГО (статика SPA, docs, корень-редирект).
# `/screenshots` НЕ здесь намеренно: скриншоты выдачи — данные прогонов, в мультиюзере их
# гейтит вход (<img> шлёт cookie сам). В локальном режиме они по-прежнему открыты.
_AUTH_SKIP_PREFIXES = ("/app", "/assets")
_AUTH_SKIP_EXACT = ("/", "/favicon.ico", "/openapi.json", "/docs", "/redoc")
# Пути, где creds резолвятся, но доступ НЕ требуется (вход / регистрация / выход / «кто я»).
_AUTH_EXEMPT_EXACT = ("/api/login", "/api/register", "/api/logout", "/api/me")
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Пути, доступные анонимному гостю (мультиюзер, без входа): сам поиск + справочники/статус.
# Лимит ANON_CREDITS на устройство; история/тесты/пользователи — только после входа.
_ANON_ALLOWED_PREFIXES = ("/search/",)               # /search/prepare|stream|cancel (не bare /search)
_ANON_ALLOWED_EXACT = ("/api/refdata", "/api/billing/status")


def _bearer(header: "str | None") -> str:
    """Достать токен из заголовка `Authorization: Bearer <token>` (иначе '')."""
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _auth_skip(path: str) -> bool:
    return path in _AUTH_SKIP_EXACT or any(
        path == p or path.startswith(p + "/") for p in _AUTH_SKIP_PREFIXES)


def _anon_allowed(path: str) -> bool:
    """Доступен ли путь анонимному гостю в мультиюзер-режиме."""
    return path in _ANON_ALLOWED_EXACT or any(path.startswith(p) for p in _ANON_ALLOWED_PREFIXES)


def _csrf_ok(request: Request) -> bool:
    """Double-submit: заголовок X-CSRF-Token совпадает с НЕ-httponly cookie ts_csrf."""
    cookie_csrf = request.cookies.get("ts_csrf") or ""
    header_csrf = request.headers.get("x-csrf-token") or ""
    return bool(cookie_csrf and hmac.compare_digest(cookie_csrf, header_csrf))


def _required_permission(path: str) -> "str | None":
    """Право, нужное для пути в мультиюзер-режиме. None — достаточно быть авторизованным."""
    if path == "/api/tests/catalog" or path == "/tests":
        return "tests.view"
    if path.startswith("/tests/"):                       # /tests/prepare, /tests/stream
        return "tests.run"
    if path.startswith("/api/users"):
        return "users.manage"
    if path.startswith("/search"):                       # /search, /prepare, /cancel, /stream
        return "search.run"
    if path.startswith("/api/runs") or path == "/history" or path.startswith("/run/"):
        return "history.view.own"
    return None                                          # /api/refdata и пр. — только вход


def _origin_ok(request: Request) -> bool:
    """Origin/Referer совпадает с хостом сервиса (анти-CSRF). Нет заголовка → не блокируем
    (не браузерный кросс-сайт-запрос)."""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        return True
    try:
        return urlparse(origin).netloc == request.url.netloc
    except Exception:
        return False


def _current_user(request: Request) -> "dict | None":
    return getattr(request.state, "user", None)


def current_user_id(request: Request) -> "int | None":
    u = _current_user(request)
    return u["id"] if u else None


def owner_filter(request: Request) -> "int | None":
    """None = вся история (local/legacy/admin); иначе id текущего пользователя (своя)."""
    mode = getattr(request.state, "auth_mode", "local")
    if mode in ("local", "legacy"):
        return None
    u = _current_user(request)
    if u is None:
        return None
    return None if auth.has_permission(u["role"], "history.view.all") else u["id"]


def register_auth(app: FastAPI, *, db_path: str, auth_token: str, secure_cookies: bool) -> None:
    """Навесить на приложение auth-middleware (3 режима) и эндпоинты входа/профиля/пользователей.

    Режимы (триггер — содержимое БД и env):
    • Локальный (нет пользователей и нет TOURSEARCH_TOKEN): всё открыто, как раньше.
    • Legacy-токен (TOURSEARCH_TOKEN задан, пользователей нет): прежнее поведение —
      Bearer/`?auth=`→cookie; токен = мастер-доступ.
    • Мультиюзер (в БД есть пользователи): серверные сессии (cookie ts_session), роли,
      CSRF на мутирующих запросах.
    """

    def _finalize(request: Request, response):
        """Единая точка выхода: доставить отложенные cookie на ответ — id устройства (учёт
        анонимных поисков), CSRF гостю (double-submit) и legacy `?auth=`→cookie. Так и
        exempt-пути (/api/me) выдают гостю ts_device+ts_csrf на первом заходе."""
        if getattr(request.state, "device_new", False):
            response.set_cookie("ts_device", request.state.device, httponly=True,
                                samesite="lax", secure=secure_cookies, max_age=365 * 24 * 3600)
        csrf_set = getattr(request.state, "csrf_set", None)
        if csrf_set:
            response.set_cookie("ts_csrf", csrf_set, httponly=False, samesite="lax",
                                secure=secure_cookies, max_age=30 * 24 * 3600)
        if (getattr(request.state, "auth_mode", "local") == "legacy"
                and request.query_params.get("auth")
                and request.cookies.get("ts_auth") != auth_token):
            response.set_cookie("ts_auth", auth_token, httponly=True, samesite="lax",
                                max_age=7 * 24 * 3600)
        return response

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        path = request.url.path
        if _auth_skip(path):
            return await call_next(request)

        # 1) Резолв режима и пользователя (одно открытие Storage на запрос)
        request.state.auth_mode = "local"
        request.state.user = None
        request.state.legacy_ok = False
        with Storage(db_path) as s:
            if s.has_any_user():
                request.state.auth_mode = "multiuser"
                tok = request.cookies.get("ts_session")
                request.state.user = s.get_session_user(tok) if tok else None
                if request.state.user is not None:
                    s.touch_session(tok)  # скользящее продление (дросселировано внутри)
            elif auth_token:
                request.state.auth_mode = "legacy"
                supplied = (request.cookies.get("ts_auth")
                            or _bearer(request.headers.get("authorization"))
                            or request.query_params.get("auth") or "")
                request.state.legacy_ok = hmac.compare_digest(supplied, auth_token)
        mode = request.state.auth_mode

        # id устройства (cookie ts_device) — для учёта анонимных бесплатных поисков. Заводим
        # на всех путях (в т.ч. exempt /api/me), чтобы гость получил cookie на первом заходе.
        device = request.cookies.get("ts_device")
        request.state.device_new = False
        if not device:
            device = auth.new_session_token()
            request.state.device_new = True
        request.state.device = device
        # CSRF-токен гостю (мультиюзер без входа), если ещё нет — для double-submit на мутациях.
        request.state.csrf_set = None
        if mode == "multiuser" and request.state.user is None and not request.cookies.get("ts_csrf"):
            request.state.csrf_set = auth.new_session_token()

        # 2) Вход/выход/«кто я»: creds резолвлены, доступ не требуем (хендлер сам решит).
        #    На мутирующих — лёгкая защита от login-CSRF через Origin.
        if path in _AUTH_EXEMPT_EXACT:
            if request.method in _UNSAFE_METHODS and not _origin_ok(request):
                return JSONResponse({"error": "Неверный источник запроса."}, status_code=403)
            return _finalize(request, await call_next(request))

        # 3) Защищённые пути. Origin-проверку мутирующих делаем во ВСЕХ режимах (дешёвый
        # анти-CSRF: скрипты/тесты без Origin не страдают, кросс-сайт из браузера — режется;
        # закрывает в т.ч. локальный режим от кросс-сайтового создания пользователя).
        if request.method in _UNSAFE_METHODS and not _origin_ok(request):
            return JSONResponse({"error": "Неверный источник запроса."}, status_code=403)
        if mode == "legacy" and not request.state.legacy_ok:
            return JSONResponse({"error": "Требуется авторизация (TOURSEARCH_TOKEN)."}, status_code=401)
        if mode == "multiuser":
            if request.state.user is None:
                # Анонимный гость: ограниченный доступ (поиск/справочники) с лимитом ANON_CREDITS.
                if not _anon_allowed(path):
                    if request.method == "GET" and "text/html" in (request.headers.get("accept") or ""):
                        return RedirectResponse(url="/app/")   # навигация браузера → SPA (вход/гость)
                    return JSONResponse({"error": "Требуется вход."}, status_code=401)
                if request.method in _UNSAFE_METHODS and not _csrf_ok(request):  # CSRF и для гостя
                    return JSONResponse({"error": "CSRF-проверка не пройдена."}, status_code=403)
                if path == "/search/prepare":                  # вход в поиск — гейт лимита гостя
                    with Storage(db_path) as s:                 # (жёсткое списание — на старте стрима)
                        if s.anon_used(request.state.device) >= billing.ANON_CREDITS:
                            return JSONResponse(
                                {"error": "Бесплатные поиски закончились — зарегистрируйтесь, "
                                          "5 поисков бесплатно."}, status_code=402)
            else:
                if request.method in _UNSAFE_METHODS and not _csrf_ok(request):  # Origin уже проверён
                    return JSONResponse({"error": "CSRF-проверка не пройдена."}, status_code=403)
                perm = _required_permission(path)
                if perm and not auth.has_permission(request.state.user["role"], perm):
                    return JSONResponse({"error": "Недостаточно прав."}, status_code=403)
                # Запуск анализа требует остатка поисков (admin — без ограничений). Отмену
                # (/search/cancel) не гейтим: остаток мог обнулиться уже запущенным поиском.
                if (perm == billing.PAID_PERMISSION and not path.endswith("/cancel")
                        and not billing.has_search_access(request.state.user)):
                    return JSONResponse({"error": "Закончились поиски — пополните на вкладке «Подписка»."},
                                        status_code=402)
        # local → открыто (Origin мутирующих уже проверён выше)

        return _finalize(request, await call_next(request))

    def _user_public(user: dict) -> dict:
        """Поля пользователя наружу — БЕЗ password_hash."""
        return {"id": user["id"], "username": user["username"], "role": user["role"],
                "is_active": bool(user["is_active"]), "created_at": user.get("created_at"),
                "last_login": user.get("last_login"), "comment": user.get("comment")}

    def _set_session_cookies(resp, token: str, csrf: str, *, remember: bool) -> None:
        max_age = 30 * 24 * 3600 if remember else None  # None → session-cookie (до закрытия)
        resp.set_cookie("ts_session", token, httponly=True, samesite="lax",
                        secure=secure_cookies, max_age=max_age)
        resp.set_cookie("ts_csrf", csrf, httponly=False, samesite="lax",  # JS читает → X-CSRF-Token
                        secure=secure_cookies, max_age=max_age)

    @app.post("/api/login")
    async def api_login(username: str = Form(...), password: str = Form(...),
                        remember: bool = Form(False)):
        with Storage(db_path) as storage:
            if not storage.has_any_user():
                return JSONResponse({"error": "Вход не настроен (нет пользователей)."}, status_code=400)
            user = storage.get_user_by_username(username)
            if not (user and bool(user["is_active"])
                    and auth.verify_password(password, user["password_hash"])):
                return JSONResponse({"error": "Неверный логин или пароль."}, status_code=401)
            token = auth.new_session_token()  # новый токен на каждый вход → нет session fixation
            storage.create_session(user["id"], token, remember=bool(remember))
            storage.touch_last_login(user["id"])
            if auth.needs_rehash(user["password_hash"]):
                storage.update_password(user["id"], password)  # тихо усилить хеш
        resp = JSONResponse({"username": user["username"], "role": user["role"],
                             "permissions": auth.permissions_for(user["role"])})
        _set_session_cookies(resp, token, auth.new_session_token(), remember=bool(remember))
        return resp

    _reg_log: dict = {}  # ip → [моменты регистраций], in-memory rate-limit (одно-процессный uvicorn)

    def _reg_allowed(ip: str, *, limit: int = 3, window: float = 600.0) -> bool:
        """Не более `limit` регистраций с IP за `window` секунд (анти-абьюз бесплатных 5)."""
        now = time.monotonic()
        times = [t for t in _reg_log.get(ip, []) if now - t < window]
        if len(times) >= limit:
            _reg_log[ip] = times
            return False
        times.append(now)
        _reg_log[ip] = times
        if len(_reg_log) > 5000:  # страховка от роста словаря
            _reg_log.clear()
        return True

    @app.post("/api/register")
    async def api_register(request: Request, username: str = Form(...), password: str = Form(...)):
        """Само-регистрация (открытая, с rate-limit). Создаёт юзера (5 бесплатных поисков) и
        сразу логинит. Включается в мультиюзере; в локальном режиме регистрация не нужна."""
        username = (username or "").strip()
        if len(username) < 3:
            return JSONResponse({"error": "Логин слишком короткий (мин. 3 символа)."}, status_code=400)
        if len(password) < 6:
            return JSONResponse({"error": "Пароль слишком короткий (мин. 6 символов)."}, status_code=400)
        ip = request.client.host if request.client else "?"
        if not _reg_allowed(ip):  # лимит считаем после валидации формата
            return JSONResponse({"error": "Слишком много регистраций — подождите немного."},
                                status_code=429)
        with Storage(db_path) as storage:
            if storage.get_user_by_username(username):
                return JSONResponse({"error": "Такой логин уже занят."}, status_code=409)
            uid = storage.create_user(username, password, role="user")  # роль user, 5 бесплатных
            token = auth.new_session_token()
            storage.create_session(uid, token)
            storage.touch_last_login(uid)
            user = storage.get_user_by_id(uid)
        resp = JSONResponse({"username": user["username"], "role": user["role"],
                             "permissions": auth.permissions_for(user["role"])})
        _set_session_cookies(resp, token, auth.new_session_token(), remember=False)
        return resp

    @app.post("/api/logout")
    async def api_logout(request: Request):
        token = request.cookies.get("ts_session")
        if token:
            with Storage(db_path) as storage:
                storage.delete_session(token)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("ts_session")
        resp.delete_cookie("ts_csrf")
        return resp

    @app.get("/api/me")
    async def api_me(request: Request):
        mode = getattr(request.state, "auth_mode", "local")
        if mode == "local":  # локальный режим → полный доступ без входа
            return {"mode": "local", "username": None, "role": None,
                    "permissions": list(auth.PERMISSIONS)}
        if mode == "legacy":
            if not getattr(request.state, "legacy_ok", False):
                raise HTTPException(status_code=401, detail="Требуется токен")
            return {"mode": "legacy", "username": "(token)", "role": "admin",
                    "permissions": list(auth.PERMISSIONS)}
        user = _current_user(request)  # multiuser
        if user is None:               # аноним → гостевое состояние (воронка: 2 поиска без входа)
            device = getattr(request.state, "device", "") or ""
            with Storage(db_path) as storage:
                used = storage.anon_used(device) if device else 0
            return {"mode": "guest", "username": None, "role": "guest",
                    "permissions": ["search.run"],  # ровно чтобы SPA показал вкладку «Поиск»
                    "searches_left": max(0, billing.ANON_CREDITS - used)}
        return {"mode": "multiuser", "username": user["username"], "role": user["role"],
                "permissions": auth.permissions_for(user["role"]),
                "searches_left": billing.searches_left(user)}  # None → безлимит (admin)

    @app.get("/api/users")
    async def api_users_list():
        with Storage(db_path) as storage:
            return storage.list_users()

    @app.post("/api/users")
    async def api_users_create(username: str = Form(...), password: str = Form(...),
                               role: str = Form("user"), comment: str = Form("")):
        if role not in auth.ROLES:
            return JSONResponse({"error": f"Неизвестная роль: {role}"}, status_code=400)
        if len(password) < 6:
            return JSONResponse({"error": "Пароль слишком короткий (мин. 6 символов)."}, status_code=400)
        with Storage(db_path) as storage:
            if storage.get_user_by_username(username):
                return JSONResponse({"error": "Пользователь уже существует."}, status_code=409)
            uid = storage.create_user(username, password, role=role, comment=(comment or None))
            return _user_public(storage.get_user_by_id(uid))

    @app.patch("/api/users/{user_id}")
    async def api_users_update(user_id: int, payload: dict):
        with Storage(db_path) as storage:
            user = storage.get_user_by_id(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            # гвард: нельзя разжаловать/заблокировать последнего активного админа
            demoting = "role" in payload and payload["role"] != "admin"
            blocking = "is_active" in payload and not payload["is_active"]
            if user["role"] == "admin" and (demoting or blocking) and storage.count_admins() <= 1:
                return JSONResponse({"error": "Нельзя убрать последнего админа."}, status_code=409)
            if "role" in payload:
                if payload["role"] not in auth.ROLES:
                    return JSONResponse({"error": "Неизвестная роль."}, status_code=400)
                storage.set_role(user_id, payload["role"])
                storage.delete_user_sessions(user_id)  # права сменились → перелогин
            if "is_active" in payload:
                storage.set_user_active(user_id, bool(payload["is_active"]))
            if payload.get("password"):
                if len(payload["password"]) < 6:
                    return JSONResponse({"error": "Пароль слишком короткий."}, status_code=400)
                storage.update_password(user_id, payload["password"])
                storage.delete_user_sessions(user_id)
            return _user_public(storage.get_user_by_id(user_id))
