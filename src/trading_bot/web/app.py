"""سرور پنل وب.

همه مسیرهای /api/* (جز ورود و سلامت) رمز لازم دارند.
"""

from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager
import os
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..backtest import Backtester
from ..backtest.verdict import judge
from ..config import Config, clear_overrides, save_overrides
from ..data import SOURCES, AutoSource, get_source, is_gold, load_ohlcv
from ..data.base import TIMEFRAME_MINUTES
from ..live import REASON_TEXT, closed_bars
from ..risk import RiskManager
from ..strategy import STRATEGIES, get_strategy
from . import logbuffer
from .auth import SESSION_COOKIE, SESSION_TTL, Auth, load_secret
from .runner import BotRunner

log = logging.getLogger("trading_bot.web")
STATIC_DIR = Path(__file__).parent / "static"

#: نمادهای پیشنهادی در صفحه تنظیمات
SYMBOL_PRESETS = [
    {"symbol": "XAUUSD", "title": "طلای جهانی (اونس به دلار) — پیشنهادی",
     "hint": "هر منبع خودش نماد درست را انتخاب می‌کند: نوبیتکس/بایننس ← PAXGUSDT، یاهو ← GC=F"},
    {"symbol": "PAXGUSDT", "title": "پکس‌گلد به تتر (PAXG)", "hint": "توکن طلا؛ هر واحد = یک اونس طلای واقعی. نوبیتکس/بایننس/یاهو"},
    {"symbol": "PAXGIRT", "title": "پکس‌گلد به ریال (نوبیتکس)", "hint": "فقط منبع nobitex. قیمت به ریال است."},
    {"symbol": "XAUTUSDT", "title": "تتر گلد (XAUT)", "hint": "توکن طلای شرکت تتر. نوبیتکس/یاهو"},
    {"symbol": "GC=F", "title": "قرارداد آتی طلا (COMEX)", "hint": "فقط منبع yahoo"},
]

SOURCE_INFO = {
    "auto": "خودکار — به ترتیب نوبیتکس، بایننس و یاهو را امتحان می‌کند",
    "nobitex": "نوبیتکس — صرافی ایرانی؛ از سرور داخل ایران در دسترس است",
    "binance": "بایننس — بزرگ‌ترین صرافی دنیا؛ فقط از سرور خارج از ایران",
    "yahoo": "یاهو فایننس — قیمت جهانی طلا؛ فقط از سرور خارج از ایران",
    "sample": "داده مصنوعی — بدون اینترنت، فقط برای آشنایی (ارزش تحلیلی ندارد)",
}


# ───────────────────────── کمک‌کننده‌ها ─────────────────────────


def clean(x: Any) -> Any:
    """NaN/inf را به None تبدیل می‌کند تا JSON معتبر بماند."""
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def ts(t: pd.Timestamp | str) -> int:
    return int(pd.Timestamp(t).timestamp())


def candles_json(df: pd.DataFrame) -> list[dict]:
    return [
        {"time": ts(t), "open": o, "high": h, "low": l, "close": c}
        for t, o, h, l, c in zip(df.index, df["open"], df["high"], df["low"], df["close"])
    ]


def line_json(series: pd.Series) -> list[dict]:
    s = series.dropna()
    return [{"time": ts(t), "value": float(v)} for t, v in zip(s.index, s.values)]


class TTLCache:
    """کش کوتاه‌مدت داده بازار — تا با هر رفرش پنل، صرافی را بمباران نکنیم."""

    def __init__(self, ttl: float = 20.0) -> None:
        self.ttl = ttl
        self._data: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple, loader):
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = loader()
        with self._lock:
            self._data[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# ───────────────────────── مدل‌های ورودی ─────────────────────────


class LoginIn(BaseModel):
    password: str = Field(max_length=256)


class BacktestIn(BaseModel):
    strategy: str
    params: dict[str, float] = {}
    timeframe: str = "4h"
    limit: int = Field(2000, ge=300, le=5000)
    source: str | None = None
    symbol: str | None = None


class SettingsIn(BaseModel):
    market: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    risk: dict[str, float] | None = None
    costs: dict[str, float] | None = None
    live: dict[str, Any] | None = None


# ───────────────────────── برنامه ─────────────────────────


def create_app(config_path: str | Path = "config.yaml", password: str | None = None) -> FastAPI:
    config_path = Path(config_path)
    Config.load(config_path)  # اگر تنظیمات خراب است، همین اول بگوییم

    auth = Auth(password if password is not None else os.environ.get("PANEL_PASSWORD", ""), load_secret())
    runner = BotRunner(config_path)
    cache = TTLCache()
    logbuffer.install()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runner.resume_if_needed()
        yield
        runner.stop(remember=False)

    app = FastAPI(
        title="Gold Bot Panel", version=__version__, lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.state.runner = runner

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    def require_auth(request: Request) -> None:
        if not auth.verify(request.cookies.get(SESSION_COOKIE)):
            raise HTTPException(401, "ابتدا وارد شو.")

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def runtime_error(_: Request, exc: RuntimeError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ConnectionError)
    async def connection_error(_: Request, exc: ConnectionError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    # ── صفحه‌ها

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ── ورود

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__, "bot_running": runner.running}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict:
        ip = client_ip(request)
        wait = auth.locked_for(ip)
        if wait:
            raise HTTPException(429, f"تلاش‌های ناموفق زیاد بود. {wait // 60 + 1} دقیقه دیگر امتحان کن.")
        if not auth.check_password(ip, body.password):
            log.warning("تلاش ناموفق برای ورود به پنل از %s", ip)
            raise HTTPException(401, "رمز اشتباه است.")
        response.set_cookie(
            SESSION_COOKIE, auth.issue(), max_age=SESSION_TTL, httponly=True, samesite="strict",
            secure=request.url.scheme == "https", path="/",
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    protected = [Depends(require_auth)]

    @app.get("/api/me", dependencies=protected)
    def me() -> dict:
        return {"ok": True, "version": __version__}

    # ── وضعیت ربات و حساب (بدون تماس شبکه — سریع)

    def account_snapshot(cfg: Config, price: float | None) -> dict:
        broker = runner.broker(cfg)
        s = broker.state
        mark = price or s.position_entry or 0.0  # بدون قیمت زنده، پوزیشن را با قیمت ورود حساب می‌کنیم
        equity = broker.equity(mark)
        peak = max(s.peak_equity, equity, 1e-9)
        wins = [t for t in s.trades if t["pnl"] > 0]
        position = None
        if s.in_position:
            unrealized = (mark - s.position_entry) * s.position_qty
            position = {
                "quantity": s.position_qty,
                "entry_price": s.position_entry,
                "entry_time": s.position_time,
                "stop_price": s.stop_price,
                "target_price": s.target_price,
                "value": s.position_qty * mark,
                "unrealized_pnl": unrealized,
                "unrealized_pct": (mark / s.position_entry - 1) * 100 if s.position_entry else 0.0,
                "risk_to_stop": (s.position_entry - s.stop_price) * s.position_qty,
            }
        return {
            "initial_capital": cfg.risk.initial_capital,
            "cash": s.cash,
            "equity": equity,
            "return_pct": (equity / cfg.risk.initial_capital - 1) * 100,
            "realized_pnl": s.realized_pnl,
            "total_fees": s.total_fees,
            "peak_equity": peak,
            "drawdown_pct": (equity / peak - 1) * 100,
            "max_drawdown_stop_pct": cfg.risk.max_drawdown_stop * 100,
            "num_trades": len(s.trades),
            "win_rate_pct": len(wins) / len(s.trades) * 100 if s.trades else None,
            "halted": s.halted,
            "position": position,
            "last_bar": s.last_signal_bar,
        }

    def current_price() -> float | None:
        status = runner.last_status
        if status.get("price"):
            return float(status["price"])
        return getattr(app.state, "last_price", None)

    @app.get("/api/status", dependencies=protected)
    def status() -> dict:
        cfg = runner.load_config()
        price = current_price()
        return clean({
            "bot": {
                "running": runner.running,
                "mode": cfg.live.mode,
                "poll_seconds": cfg.live.poll_seconds,
                **runner.last_status,
            },
            "market": {
                "symbol": cfg.market.symbol, "timeframe": cfg.market.timeframe,
                "source": cfg.market.source, "active_source": AutoSource.active,
                "strategy": cfg.strategy.name,
                "strategy_title": STRATEGIES[cfg.strategy.name].title,
            },
            "account": account_snapshot(cfg, price),
        })

    @app.get("/api/trades", dependencies=protected)
    def trades() -> dict:
        s = runner.broker().state
        return clean({
            "trades": list(reversed(s.trades[-200:])),
            "orders": list(reversed(s.orders[-200:])),
            "equity_history": [{"time": ts(t), "value": v} for t, v in s.equity_history],
            "reasons": REASON_TEXT,
        })

    @app.get("/api/logs", dependencies=protected)
    def logs(after: int = 0) -> dict:
        return {"logs": logbuffer.LOG_BUFFER.since(after)}

    # ── بازار (تماس شبکه، با کش)

    @app.get("/api/market", dependencies=protected)
    def market(limit: int = 400) -> dict:
        cfg = runner.load_config()
        m = cfg.market
        strategy = get_strategy(cfg.strategy.name, **cfg.strategy.params)
        limit = max(100, min(limit, 1500))
        fetch = max(limit, strategy.warmup + 100)
        df = cache.get((m.source, m.symbol, m.timeframe, fetch),
                       lambda: load_ohlcv(m.source, m.symbol, m.timeframe, limit=fetch))
        price = float(df["close"].iloc[-1])
        app.state.last_price = price

        day_ago = df.index[-1] - pd.Timedelta(hours=24)
        earlier = df[df.index <= day_ago]
        change_24h = (price / float(earlier["close"].iloc[-1]) - 1) * 100 if len(earlier) else None

        done = closed_bars(df, m.timeframe)
        checks = [{"text": c.text, "ok": c.ok} for c in strategy.explain(done)] if len(done) > strategy.warmup else []
        view = df.tail(limit)
        start = view.index[0]
        lines = {name: line_json(series.loc[start:]) for name, series in strategy.indicators(df).items()}

        s = runner.broker(cfg).state
        markers = []
        for o in s.orders:
            t = pd.Timestamp(o["timestamp"])
            if t >= start:
                markers.append({"time": ts(t), "side": o["side"], "price": o["price"], "reason": o.get("reason", "")})

        return clean({
            "symbol": m.symbol,
            "timeframe": m.timeframe,
            "source": AutoSource.active if m.source == "auto" else m.source,
            "price": price,
            "change_24h_pct": change_24h,
            "candles": candles_json(view),
            "lines": lines,
            "markers": markers,
            "checks": checks,
            "updated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        })

    # ── فرمان‌های ربات

    @app.post("/api/bot/start", dependencies=protected)
    def bot_start() -> dict:
        runner.start()
        return {"ok": True}

    @app.post("/api/bot/stop", dependencies=protected)
    def bot_stop() -> dict:
        runner.stop()
        return {"ok": True}

    @app.post("/api/bot/reset", dependencies=protected)
    def bot_reset() -> dict:
        runner.reset()
        return {"ok": True}

    @app.post("/api/bot/close", dependencies=protected)
    def bot_close() -> dict:
        price = current_price()
        if not price:
            raise ValueError("قیمت فعلی معلوم نیست؛ چند ثانیه بعد دوباره امتحان کن.")
        runner.close_position(price)
        return {"ok": True}

    # ── بک‌تست

    @app.post("/api/backtest", dependencies=protected)
    def backtest(body: BacktestIn) -> dict:
        cfg = runner.load_config()
        if body.strategy not in STRATEGIES:
            raise ValueError("استراتژی ناشناخته")
        if body.timeframe not in TIMEFRAME_MINUTES:
            raise ValueError("تایم‌فریم ناشناخته")
        source = body.source or cfg.market.source
        if source not in SOURCES:
            raise ValueError("منبع داده ناشناخته")
        symbol = body.symbol or cfg.market.symbol

        df = cache.get((source, symbol, body.timeframe, body.limit),
                       lambda: load_ohlcv(source, symbol, body.timeframe, limit=body.limit))
        strategy = get_strategy(body.strategy, **body.params)

        def make() -> Backtester:
            return Backtester(
                strategy=strategy,
                risk=RiskManager(cfg.risk.risk_per_trade, cfg.risk.max_position_pct, cfg.risk.max_drawdown_stop),
                initial_capital=cfg.risk.initial_capital,
                fee_rate=cfg.costs.fee_rate,
                slippage_rate=cfg.costs.slippage_rate,
                timeframe=body.timeframe,
            )

        result = make().run(df)
        halves = None
        mid = len(df) // 2
        if mid > strategy.warmup + 30:
            halves = (make().run(df.iloc[:mid]).metrics, make().run(df.iloc[mid:]).metrics)

        eq = result.equity_curve
        close = df["close"].loc[eq.index]
        buy_hold = cfg.risk.initial_capital * close / float(df["close"].iloc[0])
        m = result.metrics
        trades_df = result.trades_frame()
        view = df.tail(1500)

        return clean({
            "strategy": strategy.name,
            "params": strategy.params,
            "source": AutoSource.active if source == "auto" else source,
            "symbol": symbol,
            "timeframe": body.timeframe,
            "period": [df.index[0].isoformat(), df.index[-1].isoformat()],
            "bars": len(df),
            "metrics": {**m.__dict__, "extras": None},
            "halves": [h.__dict__ | {"extras": None} for h in halves] if halves else None,
            "verdict": judge(m, halves),
            "stopped_early": result.stopped_early,
            "equity": line_json(eq),
            "buy_hold": line_json(buy_hold),
            "candles": candles_json(view),
            "lines": {k: line_json(v.loc[view.index[0]:]) for k, v in strategy.indicators(df).items()},
            "trades": [
                {**row, "entry_time": ts(row["entry_time"]), "exit_time": ts(row["exit_time"])}
                for row in trades_df.to_dict("records")
            ],
        })

    # ── تنظیمات

    @app.get("/api/settings", dependencies=protected)
    def settings() -> dict:
        cfg = runner.load_config()
        base = Config.load(config_path, use_overrides=False)
        return clean({
            "config": {k: v for k, v in cfg.to_dict().items() if k != "panel"},
            "defaults": {k: v for k, v in base.to_dict().items() if k != "panel"},
            "strategies": [cls.describe() for cls in STRATEGIES.values()],
            "sources": [{"name": n, "title": SOURCE_INFO.get(n, n)} for n in SOURCES],
            "timeframes": list(TIMEFRAME_MINUTES),
            "symbols": SYMBOL_PRESETS,
            "is_gold": is_gold(cfg.market.symbol),
        })

    @app.put("/api/settings", dependencies=protected)
    def update_settings(body: SettingsIn) -> dict:
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        if "strategy" in changes:
            name = changes["strategy"].get("name")
            if name not in STRATEGIES:
                raise ValueError("استراتژی ناشناخته")
            get_strategy(name, **changes["strategy"].get("params", {}))  # اعتبارسنجی
        if "market" in changes:
            if changes["market"].get("source", "auto") not in SOURCES:
                raise ValueError("منبع داده ناشناخته")
            if changes["market"].get("timeframe", "4h") not in TIMEFRAME_MINUTES:
                raise ValueError("تایم‌فریم ناشناخته")
        if "live" in changes:
            changes["live"] = {k: v for k, v in changes["live"].items() if k == "poll_seconds"}
        save_overrides(runner.load_config(), changes)
        cache.clear()
        restarted = runner.restart_if_running()
        log.info("تنظیمات از پنل ذخیره شد%s.", " و ربات با تنظیمات جدید دوباره روشن شد" if restarted else "")
        return {"ok": True, "restarted": restarted}

    @app.delete("/api/settings", dependencies=protected)
    def reset_settings() -> dict:
        clear_overrides(runner.load_config())
        cache.clear()
        restarted = runner.restart_if_running()
        log.info("تنظیمات به پیش‌فرض config.yaml برگشت.")
        return {"ok": True, "restarted": restarted}

    @app.get("/api/doctor", dependencies=protected)
    def doctor() -> dict:
        cfg = runner.load_config()
        results = []
        for name in SOURCES:
            if name == "auto":
                continue
            started = time.time()
            try:
                df = get_source(name).fetch_ohlcv(cfg.market.symbol, cfg.market.timeframe, 5)
                results.append({"source": name, "ok": True, "price": float(df["close"].iloc[-1]),
                                "ms": int((time.time() - started) * 1000)})
            except Exception as exc:
                results.append({"source": name, "ok": False, "error": str(exc).splitlines()[0][:160]})
        return clean({"symbol": cfg.market.symbol, "results": results})

    return app
