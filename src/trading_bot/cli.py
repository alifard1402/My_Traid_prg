"""رابط خط فرمان ربات.

  python -m trading_bot doctor      بررسی سلامت محیط و دسترسی به صرافی‌ها
  python -m trading_bot fetch       دانلود و ذخیره کندل‌ها
  python -m trading_bot backtest    تست استراتژی روی داده گذشته
  python -m trading_bot optimize    جست‌وجوی پارامترهای بهتر (با احتیاط!)
  python -m trading_bot paper       اجرای زنده با پول تقلبی
  python -m trading_bot status      وضعیت فعلی حساب کاغذی
  python -m trading_bot web         پنل وب (داشبورد، بک‌تست، تنظیمات)
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from pathlib import Path

import pandas as pd

from .backtest import Backtester
from .config import Config
from .data import SOURCES, cache_path, get_source, load_ohlcv, save_cache
from .live import LiveTrader
from .risk import RiskManager
from .strategy import STRATEGIES, get_strategy
from .web.auth import load_env_file


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_backtester(cfg: Config) -> Backtester:
    return Backtester(
        strategy=get_strategy(cfg.strategy.name, **cfg.strategy.params),
        risk=RiskManager(
            risk_per_trade=cfg.risk.risk_per_trade,
            max_position_pct=cfg.risk.max_position_pct,
            max_drawdown_stop=cfg.risk.max_drawdown_stop,
        ),
        initial_capital=cfg.risk.initial_capital,
        fee_rate=cfg.costs.fee_rate,
        slippage_rate=cfg.costs.slippage_rate,
        timeframe=cfg.market.timeframe,
    )


# ────────────────────────────── دستورها ──────────────────────────────


def cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    print("بررسی محیط")
    print("─" * 52)
    print(f"  پایتون        : {sys.version.split()[0]}")
    for mod in ("pandas", "numpy", "requests", "yaml"):
        try:
            __import__(mod)
            print(f"  {mod:<13} : نصب است ✅")
        except ImportError:
            print(f"  {mod:<13} : نصب نیست ❌  →  pip install -r requirements.txt")

    print("\nبررسی دسترسی به منابع داده")
    print("─" * 52)
    for name in SOURCES:
        try:
            df = get_source(name).fetch_ohlcv(cfg.market.symbol, cfg.market.timeframe, 10)
            print(f"  {name:<13} : در دسترس ✅  ({len(df)} کندل، آخرین قیمت {df['close'].iloc[-1]:,.2f})")
        except Exception as exc:
            msg = str(exc).splitlines()[0][:60]
            print(f"  {name:<13} : در دسترس نیست ❌  ({msg})")

    print("\nتنظیمات فعلی")
    print("─" * 52)
    print(f"  نماد          : {cfg.market.symbol}")
    print(f"  تایم‌فریم      : {cfg.market.timeframe}")
    print(f"  منبع داده     : {cfg.market.source}")
    print(f"  استراتژی      : {cfg.strategy.name}")
    print(f"  سرمایه اولیه  : {cfg.risk.initial_capital:,.2f}")
    print(f"  ریسک هر معامله: {cfg.risk.risk_per_trade * 100:.1f}%")
    return 0


def cmd_fetch(args: argparse.Namespace, cfg: Config) -> int:
    source = args.source or cfg.market.source
    symbol = args.symbol or cfg.market.symbol
    timeframe = args.timeframe or cfg.market.timeframe

    print(f"دریافت {args.limit} کندل {symbol} ({timeframe}) از {source} ...")
    df = get_source(source).fetch_ohlcv(symbol, timeframe, args.limit)
    path = save_cache(df, source, symbol, timeframe)

    print(f"✅ {len(df)} کندل ذخیره شد در: {path}")
    print(f"   بازه زمانی: {df.index[0]:%Y-%m-%d} تا {df.index[-1]:%Y-%m-%d}")
    print(f"   قیمت: از {df['close'].iloc[0]:,.2f} تا {df['close'].iloc[-1]:,.2f}")
    return 0


def cmd_backtest(args: argparse.Namespace, cfg: Config) -> int:
    source = args.source or cfg.market.source
    symbol = args.symbol or cfg.market.symbol
    timeframe = args.timeframe or cfg.market.timeframe

    df = load_ohlcv(source, symbol, timeframe, limit=args.limit)
    cfg.market.timeframe = timeframe

    bt = build_backtester(cfg)
    print(f"\nاستراتژی : {bt.strategy}")
    print(f"داده     : {symbol} {timeframe} از {source} — {len(df)} کندل "
          f"({df.index[0]:%Y-%m-%d} تا {df.index[-1]:%Y-%m-%d})\n")

    result = bt.run(df)
    print(result.metrics.as_text())

    if result.stopped_early:
        print("\n⚠️  ربات به‌خاطر رد شدن از حد افت سرمایه، وسط راه متوقف شد.")

    trades = result.trades_frame()
    if not trades.empty and args.trades:
        print("\nآخرین معاملات:")
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(trades.tail(args.trades).to_string(index=False))

    if args.save:
        trades.to_csv(args.save, index=False)
        print(f"\n✅ جدول معاملات ذخیره شد در: {args.save}")

    print(
        "\n💡 یادآوری: نتیجه خوبِ بک‌تست هیچ تضمینی برای آینده نیست."
        "\n   قدم بعدی: همین استراتژی را ماه‌ها در حالت paper اجرا کن."
    )
    return 0


def cmd_optimize(args: argparse.Namespace, cfg: Config) -> int:
    """جست‌وجوی شبکه‌ای روی پارامترها.

    هشدار: این ابزار خطرناک است. هرچه ترکیب بیشتری امتحان کنی،
    احتمال اینکه بهترین نتیجه فقط «شانس روی همین داده» باشد بیشتر می‌شود
    (بیش‌برازش / overfitting). همیشه بهترین پارامتر را روی بازه زمانیِ
    دیگری هم تست کن.
    """
    source = args.source or cfg.market.source
    symbol = args.symbol or cfg.market.symbol
    timeframe = args.timeframe or cfg.market.timeframe

    df = load_ohlcv(source, symbol, timeframe, limit=args.limit)
    cfg.market.timeframe = timeframe

    grid = {
        "ema_fast": [8, 12, 20],
        "ema_slow": [26, 50],
        "atr_stop_mult": [2.0, 2.5, 3.0],
    }
    keys = list(grid)
    rows = []

    for combo in itertools.product(*grid.values()):
        params = {**cfg.strategy.params, **dict(zip(keys, combo))}
        if params["ema_fast"] >= params["ema_slow"]:
            continue
        cfg.strategy.params = params
        try:
            result = build_backtester(cfg).run(df)
        except ValueError:
            continue
        m = result.metrics
        rows.append({
            **dict(zip(keys, combo)),
            "بازده٪": round(m.total_return_pct, 2),
            "افت٪": round(m.max_drawdown_pct, 2),
            "شارپ": round(m.sharpe, 2),
            "معاملات": m.num_trades,
        })

    table = pd.DataFrame(rows).sort_values("شارپ", ascending=False)
    print(f"\n{len(table)} ترکیب تست شد — مرتب‌شده بر اساس نسبت شارپ:\n")
    with pd.option_context("display.width", 200):
        print(table.to_string(index=False))
    print(
        "\n⚠️  بهترین ردیفِ این جدول را باور نکن. آن را روی بازه زمانیِ دیگری"
        "\n    (مثلاً --limit بزرگ‌تر یا نماد دیگر) دوباره تست کن. اگر آنجا هم"
        "\n    خوب بود، شاید واقعی باشد."
    )
    return 0


def cmd_paper(args: argparse.Namespace, cfg: Config) -> int:
    trader = LiveTrader(cfg)
    if args.reset:
        trader.broker.reset(cfg.risk.initial_capital)
        print(f"حساب کاغذی با سرمایه {cfg.risk.initial_capital:,.2f} صفر شد.")
    if trader.broker.state.halted:
        print("⛔ کلید قطع اضطراری زده شده. اول نتیجه را بررسی کن، بعد با --reset شروع کن.")
        return 1
    try:
        trader.run(max_iterations=args.iterations)
    except KeyboardInterrupt:
        print("\nربات با دستور کاربر متوقف شد.")
    return 1 if trader.broker.state.halted else 0


def cmd_status(args: argparse.Namespace, cfg: Config) -> int:
    trader = LiveTrader(cfg)
    m = cfg.market
    df = load_ohlcv(m.source, m.symbol, m.timeframe, limit=5)
    print(trader.summary(float(df["close"].iloc[-1])))
    return 0


def cmd_web(args: argparse.Namespace, cfg: Config) -> int:
    import os

    try:
        import uvicorn
    except ImportError:
        print("پنل وب نصب نیست. اجرا کن:  pip install -r requirements.txt")
        return 1

    from .web.app import create_app
    from .web.auth import MIN_PASSWORD_LENGTH

    if len(os.environ.get("PANEL_PASSWORD", "")) < MIN_PASSWORD_LENGTH:
        print(
            "❌ رمز پنل تنظیم نشده (یا کوتاه‌تر از ۸ حرف است).\n"
            "   در فایل .env (کنار config.yaml) این خط را بگذار:\n"
            "   PANEL_PASSWORD=یک-رمز-طولانی-و-سخت"
        )
        return 1

    host = args.host or os.environ.get("PANEL_HOST") or cfg.panel.host
    port = int(args.port or os.environ.get("PANEL_PORT") or cfg.panel.port)
    app = create_app(args.config)
    print(f"پنل روی http://{host}:{port} بالا آمد. برای توقف Ctrl+C.")
    if host == "0.0.0.0":
        print("⚠️  پنل از همه‌جا در دسترس است. حتماً پشت HTTPS (nginx) یا فایروال باشد.")
    # proxy_headers: پشت nginx، IP واقعی کاربر را برای قفل تلاش‌های ناموفق می‌خواهیم.
    uvicorn.run(app, host=host, port=port, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", log_level="warning")
    return 0


# ────────────────────────────── ورودی ──────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading_bot",
        description="ربات ترید — بک‌تست و معامله کاغذی",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default="config.yaml", help="مسیر فایل تنظیمات")
    parser.add_argument("-v", "--verbose", action="store_true", help="گزارش کامل‌تر")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_market_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--symbol", help="نماد، مثلاً BTCUSDT")
        p.add_argument("--timeframe", help="تایم‌فریم: 1h / 4h / 1d")
        p.add_argument("--source", choices=list(SOURCES), help="منبع داده")

    p = sub.add_parser("doctor", help="بررسی سلامت محیط و دسترسی‌ها")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("fetch", help="دانلود و ذخیره کندل‌ها")
    add_market_args(p)
    p.add_argument("--limit", type=int, default=1000, help="تعداد کندل")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("backtest", help="تست استراتژی روی داده گذشته")
    add_market_args(p)
    p.add_argument("--limit", type=int, default=1000, help="تعداد کندل")
    p.add_argument("--trades", type=int, default=10, help="نمایش N معامله آخر")
    p.add_argument("--save", help="ذخیره جدول معاملات در فایل CSV")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("optimize", help="جست‌وجوی پارامتر (با احتیاط)")
    add_market_args(p)
    p.add_argument("--limit", type=int, default=1000, help="تعداد کندل")
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser("paper", help="اجرای زنده با پول تقلبی")
    p.add_argument("--iterations", type=int, help="تعداد دور (پیش‌فرض: بی‌نهایت)")
    p.add_argument("--reset", action="store_true", help="صفر کردن حساب کاغذی")
    p.set_defaults(func=cmd_paper)

    p = sub.add_parser("status", help="وضعیت حساب کاغذی")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("web", help="پنل وب (داشبورد، بک‌تست، تنظیمات)")
    p.add_argument("--host", help="آدرس شنود (پیش‌فرض از config.yaml یا PANEL_HOST)")
    p.add_argument("--port", type=int, help="پورت (پیش‌فرض ۸۰۰۰)")
    p.set_defaults(func=cmd_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    load_env_file(Path(args.config).resolve().parent / ".env")
    try:
        cfg = Config.load(args.config)
        for attr in ("symbol", "timeframe", "source"):
            value = getattr(args, attr, None)
            if value:
                setattr(cfg.market, attr, value)
        return args.func(args, cfg)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("trading_bot").error("%s", exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
