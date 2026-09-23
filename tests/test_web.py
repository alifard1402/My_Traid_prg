"""تست‌های پنل وب: ورود، قفل IP، و مسیرهای اصلی (با داده مصنوعی)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from trading_bot.web.app import create_app  # noqa: E402
from trading_bot.web.auth import Auth  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "market: {symbol: XAUUSD, timeframe: 4h, source: sample}\n"
        "live: {poll_seconds: 5}\n", encoding="utf-8")
    app = create_app("config.yaml", password=PASSWORD)
    with TestClient(app) as c:
        yield c
        app.state.runner.stop(remember=False)


def login(c):
    r = c.post("/api/login", json={"password": PASSWORD})
    assert r.status_code == 200


def test_api_requires_login(client):
    assert client.get("/api/health").status_code == 200
    for path in ("/api/status", "/api/market", "/api/settings", "/api/trades"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/bot/start").status_code == 401


def test_wrong_password_then_lockout(client):
    for _ in range(5):
        assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 429


def test_forged_cookie_is_rejected(client):
    client.cookies.set("gold_session", "OTk5OTk5OTk5OQ==.deadbeef")
    assert client.get("/api/status").status_code == 401


def test_short_password_refused():
    with pytest.raises(ValueError, match="حداقل"):
        Auth("short", b"k")


def test_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_dashboard_endpoints(client):
    login(client)
    status = client.get("/api/status").json()
    assert status["bot"]["running"] is False
    assert status["account"]["equity"] == pytest.approx(1000.0)

    market = client.get("/api/market?limit=200").json()
    assert len(market["candles"]) == 200
    assert market["lines"] and market["checks"]
    assert market["price"] > 0


def test_backtest_endpoint_returns_verdict(client):
    login(client)
    r = client.post("/api/backtest", json={"strategy": "ema_trend", "params": {}, "timeframe": "4h", "limit": 1500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"]["level"] in ("good", "ok", "bad")
    assert len(body["equity"]) == len(body["buy_hold"])
    assert body["halves"] and len(body["halves"]) == 2


def test_backtest_rejects_unknown_strategy(client):
    login(client)
    r = client.post("/api/backtest", json={"strategy": "magic", "timeframe": "4h", "limit": 500})
    assert r.status_code == 400


def test_settings_roundtrip_and_validation(client):
    login(client)
    s = client.get("/api/settings").json()
    assert {x["name"] for x in s["strategies"]} >= {"ema_trend", "donchian_breakout", "rsi_pullback"}

    r = client.put("/api/settings", json={"strategy": {"name": "donchian_breakout", "params": {"entry_period": 40}}})
    assert r.status_code == 200
    assert client.get("/api/status").json()["market"]["strategy"] == "donchian_breakout"

    bad = client.put("/api/settings", json={"risk": {"risk_per_trade": 0.5}})
    assert bad.status_code == 400
    assert client.delete("/api/settings").status_code == 200
    assert client.get("/api/status").json()["market"]["strategy"] == "ema_trend"


def test_bot_start_stop_and_reset(client):
    login(client)
    assert client.post("/api/bot/start").status_code == 200
    assert client.get("/api/status").json()["bot"]["running"] is True
    assert client.post("/api/bot/start").status_code == 409          # دوبار روشن نمی‌شود
    assert client.post("/api/bot/reset").status_code == 409          # روشن است، ریست نمی‌شود
    assert client.post("/api/bot/stop").status_code == 200
    assert client.get("/api/status").json()["bot"]["running"] is False
    assert client.post("/api/bot/reset").status_code == 200
