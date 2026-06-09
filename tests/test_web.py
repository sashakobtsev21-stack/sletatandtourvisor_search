"""Тесты веб-интерфейса (рендер страниц; без реального поиска по сайтам)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

from toursearch.models import ComparisonReport, HotelOffer, Offer, ProviderResult, SearchParams
from toursearch.storage import Storage
from toursearch.web import create_app


def test_index_redirects_to_dashboard_or_renders_fallback(tmp_path):
    # Если фронт собран (frontend/dist есть) — / редиректит на дашборд /app/.
    # Если нет (напр. в CI без npm build) — отдаётся запасная Jinja-форма.
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")), follow_redirects=False)
    resp = client.get("/")
    if resp.status_code in (302, 307):
        assert resp.headers["location"] == "/app/"
    else:
        assert resp.status_code == 200
        assert "Параметры поиска" in resp.text


def test_api_runs_and_run_detail(tmp_path):
    db = str(tmp_path / "w.db")
    report = ComparisonReport(
        params=SearchParams(
            departure_city="Москва", destination_country="Турция",
            date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
            nights_min=3, nights_max=5, adults=2,
        ),
        run_at=datetime(2026, 4, 30, 12, 0, 0),
        results=[
            ProviderResult(
                provider="sletat", success=True, duration_seconds=10.0,
                offers=[Offer(provider="sletat", operator="Travelata", price=Decimal("75937"))],
            ),
            ProviderResult(
                provider="tourvisor", success=True, duration_seconds=30.0,
                hotel_offers=[HotelOffer(provider="tourvisor", hotel_name="Mert", stars=3, price=Decimal("80000"))],
            ),
        ],
    )
    with Storage(db) as s:
        rid = s.save_report(report)

    client = TestClient(create_app(db_path=db))

    runs = client.get("/api/runs").json()
    row = next(r for r in runs if r["run_id"] == rid)
    assert row["cheapest_label"] == "Travelata"
    # параметры прогона — для заголовка истории и кнопки «Повторить»
    assert row["params"]["departure_city"] == "Москва"
    assert row["params"]["destination_country"] == "Турция"
    assert row["params"]["nights_min"] == 3 and row["params"]["adults"] == 2
    assert set(row["params"]["providers"]) == {"sletat", "tourvisor"}

    detail = client.get(f"/api/runs/{rid}").json()
    assert detail["run_id"] == rid
    assert detail["params"]["destination_country"] == "Турция"
    assert detail["best"]["label"] == "Travelata"
    assert detail["fastest_provider"] == "sletat"
    providers = {r["provider"]: r for r in detail["results"]}
    assert providers["sletat"]["offers"][0]["operator"] == "Travelata"
    assert providers["tourvisor"]["hotel_offers"][0]["hotel_name"] == "Mert"

    assert client.get("/api/runs/999999").status_code == 404


def test_search_prepare_rejects_bad_price_gracefully(tmp_path):
    # Регрессия: нечисловая «Макс. цена» роняла /search/prepare в 500 — Decimal('abc')
    # бросает InvalidOperation, а это НЕ ValueError, поэтому except его не ловил.
    # Теперь мусор в цене → None (фильтр просто не применяется), запрос принят.
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    common = {
        "mode": "tours", "departure_city": "Москва", "destination_country": "Турция",
        "date_from": "2026-07-01", "date_to": "2026-07-08",
        "nights_min": "7", "nights_max": "10", "adults": "2",
    }
    resp = client.post("/search/prepare", data={**common, "price_max": "не число"})
    assert resp.status_code == 200
    assert "token" in resp.json(), resp.json()

    # «12 000 ₽» — допустимый ввод с разделителями/символом валюты: тоже принимается.
    resp = client.post("/search/prepare", data={**common, "price_max": "12 000 ₽"})
    assert resp.status_code == 200 and "token" in resp.json()

    # Кривые даты не валят сервер, а возвращают понятную ошибку.
    resp = client.post("/search/prepare", data={**common, "date_from": "oops"})
    assert resp.status_code == 200 and "error" in resp.json()


def test_api_v1_mirrors_legacy_routes(tmp_path):
    """audit-final 2026-06: /api/v1/X → внутри обрабатывается как /api/X.
    Legacy /api/* отвечает с Deprecation header'ом + Link на v1 (RFC 8594)."""
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    r_v1 = client.get("/api/v1/runs?limit=10")
    r_legacy = client.get("/api/runs?limit=10")
    assert r_v1.status_code == 200 and r_legacy.status_code == 200
    assert r_v1.json() == r_legacy.json()
    assert "deprecation" not in {k.lower() for k in r_v1.headers}
    assert r_legacy.headers.get("deprecation") == "true"
    assert "/api/v1/runs" in r_legacy.headers.get("link", "")


def test_api_v1_query_string_preserved(tmp_path):
    """Query-параметры (limit=201 → 422) работают одинаково на v1 и legacy."""
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    assert client.get("/api/v1/runs?limit=201").status_code == 422
    assert client.get("/api/runs?limit=201").status_code == 422


def test_api_v1_bare_no_trailing_slash(tmp_path):
    """reviewer-2026-06 P1: /api/v1 БЕЗ слэша раньше не переписывался И получал
    самосылающийся Deprecation `</api/v1/v1>`. Теперь и переписывается, и БЕЗ
    deprecation-заголовка (это валидный v1-вход)."""
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    r = client.get("/api/v1")
    # ровно `/api/v1` rewrite на `/api` → его нет, 404; но БЕЗ Deprecation
    assert "deprecation" not in {k.lower() for k in r.headers}, \
        "/api/v1 не должен получать самосылающийся deprecation"


def test_health_metrics_no_deprecation_header(tmp_path):
    """/healthz, /readyz, /metrics — НЕ под /api/*, deprecation НЕ ставим."""
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    for path in ("/healthz", "/readyz", "/metrics"):
        r = client.get(path)
        assert "deprecation" not in {k.lower() for k in r.headers}, path


def test_metrics_endpoint_returns_aggregates(tmp_path):
    """audit-final P2: /metrics — JSON-снимок без auth, агрегаты по основным таблицам."""
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    r = client.get("/metrics")
    assert r.status_code == 200
    j = r.json()
    for key in ("runs_total", "runs_24h", "jobs_total", "users_total",
                "payments_succeeded", "active_searches", "active_searches_limit",
                "bg_tasks_alive"):
        assert key in j, f"missing key: {key}"
    assert isinstance(j["jobs_by_status"], dict)


def test_static_assets_get_cache_headers(tmp_path):
    """audit-final P2: /app/assets/* должны иметь Cache-Control: immutable."""
    cli = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    # /app/assets/anyfile — 404 (нет файла), но middleware должно поставить header
    # для путей префикса. Сделаем GET на путь — даже на 404 middleware отрабатывает.
    r = cli.get("/app/assets/index-fake.js")
    # cache-header ставится middleware'ом до того как StaticFiles вернёт 404
    assert "cache-control" in {k.lower() for k in r.headers}
    assert "immutable" in r.headers.get("cache-control", "").lower()


def test_create_app_rejects_stub_billing_in_production(tmp_path, monkeypatch):
    """audit-final P1: stub-провайдер в проде = бесплатные подписки. App должен
    отказываться стартовать (RuntimeError) если host не локальный И провайдер stub."""
    monkeypatch.setenv("TOURSEARCH_PAYMENT_PROVIDER", "stub")
    # reload billing.PROVIDER из env (он читается при импорте, поэтому force-reload)
    import importlib
    from toursearch import billing as billing_mod
    importlib.reload(billing_mod)
    try:
        import pytest as _pt
        with _pt.raises(RuntimeError, match="stub"):
            create_app(db_path=str(tmp_path / "w.db"), host="0.0.0.0")
    finally:
        monkeypatch.delenv("TOURSEARCH_PAYMENT_PROVIDER", raising=False)
        importlib.reload(billing_mod)


def test_create_app_allows_stub_on_localhost(tmp_path, monkeypatch):
    """На localhost stub разрешён (разработка)."""
    monkeypatch.setenv("TOURSEARCH_PAYMENT_PROVIDER", "stub")
    import importlib
    from toursearch import billing as billing_mod
    importlib.reload(billing_mod)
    try:
        app = create_app(db_path=str(tmp_path / "w.db"), host="127.0.0.1")
        assert app is not None
    finally:
        monkeypatch.delenv("TOURSEARCH_PAYMENT_PROVIDER", raising=False)
        importlib.reload(billing_mod)


def test_create_app_stub_with_explicit_allow_insecure(tmp_path, monkeypatch):
    """TOURSEARCH_ALLOW_INSECURE=1 — opt-out для нагрузочного за TLS-прокси."""
    monkeypatch.setenv("TOURSEARCH_PAYMENT_PROVIDER", "stub")
    monkeypatch.setenv("TOURSEARCH_ALLOW_INSECURE", "1")
    import importlib
    from toursearch import billing as billing_mod
    importlib.reload(billing_mod)
    try:
        app = create_app(db_path=str(tmp_path / "w.db"), host="0.0.0.0")
        assert app is not None
    finally:
        monkeypatch.delenv("TOURSEARCH_PAYMENT_PROVIDER", raising=False)
        monkeypatch.delenv("TOURSEARCH_ALLOW_INSECURE", raising=False)
        importlib.reload(billing_mod)


def test_api_runs_limit_capped(tmp_path):
    """audit-3 P1: ?limit без верхней границы тянул бы всю историю в память.
    Теперь Query(le=200) — большие значения → 422."""
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    assert client.get("/api/runs?limit=100").status_code == 200
    assert client.get("/api/runs?limit=200").status_code == 200
    r = client.get("/api/runs?limit=201")
    assert r.status_code == 422
    assert client.get("/api/runs?limit=0").status_code == 422


def test_api_refdata(tmp_path):
    # Справочники формы отдаются бэкендом (единый источник правды; фронт берёт их отсюда).
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    rd = client.get("/api/refdata").json()
    assert "Москва" in rd["departure_cities"]
    assert "Турция" in rd["countries"]
    assert isinstance(rd["operators"], list) and rd["operators"]
    assert "sletat" in rd["providers"] and "tourvisor" in rd["providers"]
    assert rd["max_date_span_days"] == 13
    # Режимы площадок: фронт по ним гасит несовместимые с выбранным режимом площадки.
    pm = rd["provider_modes"]
    assert pm["ostrovok"] == ["hotels"]              # Островок — только «Отели»
    assert set(pm["travelata"]) == {"tours", "hotels"}  # туры + отели (/hotels/search)
    assert set(pm["sletat"]) == {"tours", "hotels"}     # зрелые — оба режима


def test_api_tests_catalog(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    cat = client.get("/api/tests/catalog").json()
    assert cat["total"] >= 200
    assert len(cat["groups"]) >= 10
    first = cat["groups"][0]
    assert {"group", "description", "cases"} <= set(first)
    assert "id" in first["cases"][0] and "name" in first["cases"][0]


def test_history_renders_saved_run(tmp_path):
    db = str(tmp_path / "w.db")
    report = ComparisonReport(
        params=SearchParams(
            departure_city="Москва", destination_country="Турция",
            date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
            nights_min=3, nights_max=5, adults=2,
        ),
        run_at=datetime(2026, 4, 30, 12, 0, 0),
        results=[
            ProviderResult(
                provider="sletat", success=True, duration_seconds=10.0,
                offers=[Offer(provider="sletat", operator="Travelata", price=Decimal("75937"))],
            ),
            ProviderResult(
                provider="tourvisor", success=True, duration_seconds=30.0,
                hotel_offers=[HotelOffer(provider="tourvisor", hotel_name="Mert", stars=3, price=Decimal("80000"))],
            ),
        ],
    )
    with Storage(db) as s:
        rid = s.save_report(report)

    client = TestClient(create_app(db_path=db))
    h = client.get("/history")
    assert h.status_code == 200
    assert f"#{rid}" in h.text
    assert "Travelata" in h.text

    r = client.get(f"/run/{rid}")
    assert r.status_code == 200
    assert "Travelata" in r.text
    assert "Mert" in r.text


def test_tests_panel_renders(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    resp = client.get("/tests")
    assert resp.status_code == 200
    assert "Запустить выбранные" in resp.text
    assert "Автотесты" in resp.text


def test_tests_run_stream(tmp_path):
    from toursearch.testkit import REGISTRY

    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    ids = [c.id for c in REGISTRY.cases() if not c.live][:6]
    prep = client.post("/tests/prepare", json={"ids": ids})
    assert prep.status_code == 200
    token = prep.json()["token"]
    assert prep.json()["count"] == 6

    stream = client.get(f"/tests/stream?token={token}")
    text = stream.text
    assert '"type": "begin"' in text
    assert '"type": "end"' in text
    assert '"passed": 6' in text
