"""GoldPilot Recovery v4.6 — Python simulator for fast what-if backtests.

The MT4 Strategy Tester is the reference. This simulator re-implements the
EA's logic so many parameter sets can be compared in minutes:

  * Analysis on closed M15 bars (swings, S/R levels, trendlines, supply/demand
    zones, liquidity sweeps, FVGs) and the H1 EMA trend filter — same rules
    and same shift semantics as GoldPilotRecovery.mq4.
  * Execution on M1 bars. Each M1 bar is walked open -> low -> high -> close
    (bullish bar) or open -> high -> low -> close (bearish bar), roughly like
    MT4's tick generator. Recovery adds, basket target and emergency stop fill
    at their exact price levels (like server-side TP/SL).
  * Spread is constant; the data is Bid. Swap and commission are ignored.

Usage:
    python goldpilot_sim.py DATA.zip [DATA2.csv ...] --start 2026-01-01 --end 2026-07-25
    python goldpilot_sim.py DATA.zip --scenarios          # compare parameter sets
"""

from __future__ import annotations

import argparse
import io
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

CONTRACT = 100.0  # XAUUSD: 1 lot = 100 oz -> $100 per 1.0 price move per lot


# ═══════════════════════════════ parameters ═══════════════════════════════


@dataclass(frozen=True)
class Params:
    # money policy
    take_profit_usd: float = 10.0
    step_loss_usd: float = 10.0
    step_mode_atr: bool = False
    step_atr_mult: float = 1.5
    recovery_ratio: float = 0.3333
    max_trades: int = 5
    max_basket_loss_usd: float = 150.0
    lots: float = 0.01
    pause_after_stop_min: int = 60
    # entry
    min_confluence: int = 2
    use_sweep: bool = True
    use_fvg: bool = True
    use_tl: bool = True                 # count the trendline as a reason
    require_fvg: bool = False
    use_d1_filter: bool = False         # no new basket against the D1 EMA trend
    min_atr_ratio: float = 0.8          # no new basket when ATR14/ATR100 is below this
    add_on_bar_close: bool = False      # recovery trade only at the close of an M15 bar
    max_weekly_loss_usd: float = 0.0    # no new basket for the rest of the week after this closed loss
    # higher-timeframe direction used with the M15 structure:
    #   h1ema = H1 EMA50/200 (EA <= v4.4), h4slope = slope of the H4 EMA50 over 3 bars,
    #   d1ema = D1 EMA20/50, h4slope_only = H4 slope alone (structure ignored)
    trend_mode: str = "h4slope_only"
    h4_ema: int = 50
    h4_slope_bars: int = 3
    # basket-management experiments
    no_add_against_trend: bool = False  # skip recovery adds while the H4 slope points against the basket
    trail_usd: float = 10.0             # >0: at the target, trail the basket profit by this many dollars
    deep_trades: int = 5                # >0: baskets with at least this many trades ...
    deep_target_usd: float = 10.0       # ... close at this profit instead of the 1/3 rule
    pessimistic_path: bool = False      # stress test: inside each M1 bar price first moves against the basket
    use_session: bool = True
    session_start: int = 10
    session_end: int = 22
    # new-basket filters
    max_atr_ratio: float = 2.0
    max_daily_loss_usd: float = 150.0
    use_friday_cutoff: bool = True
    friday_cutoff_hour: int = 0
    direction_cooldown_h: int = 24
    close_before_weekend: bool = True
    weekend_close_hour: int = 21
    weekend_close_max_loss: float = 20.0
    # market
    spread: float = 0.35
    max_spread: float = 0.80
    # analysis
    lookback: int = 300
    swing_left: int = 3
    swing_right: int = 3
    atr_period: int = 14
    ema_fast: int = 50
    ema_slow: int = 200
    level_tol_atr: float = 0.5
    near_atr: float = 0.5
    impulse_atr: float = 1.5
    max_base: int = 3
    trendline_points: int = 6
    fvg_min_atr: float = 0.3
    fvg_lookback: int = 60


# ═══════════════════════════════ data loading ═══════════════════════════════


def _read_text(path: Path) -> list[tuple[str, str]]:
    """(name, text) for a csv file or every csv inside a zip."""
    if path.suffix.lower() == ".zip":
        out = []
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if name.lower().endswith((".csv", ".txt")):
                    out.append((name, zf.read(name).decode("utf-8", "replace")))
        return out
    return [(path.name, path.read_text(encoding="utf-8", errors="replace"))]


def _parse(text: str) -> tuple[pd.DataFrame, str]:
    """Returns M1 bars in the file's own time zone and that zone ('newyork' or 'utc').

    HistData says "EST without daylight saving", but its gold files follow New
    York local time: the daily 17:00-18:00 break is at the same clock time in
    summer and winter, and matching LiteFinance fills from two MT4 reports
    (Aug-Sep 2026) gives the best fit with New York time + 7 h.
    """
    first = next(line for line in text.splitlines() if line.strip() and line[0].isdigit())
    if ";" in first:  # HistData ASCII: 20250102 180000;o;h;l;c;v
        df = pd.read_csv(io.StringIO(text), sep=";", header=None,
                         names=["dt", "open", "high", "low", "close", "vol"])
        df.index = pd.to_datetime(df["dt"], format="%Y%m%d %H%M%S")
        return df, "newyork"
    if len(first.split(",")[0]) == 10 and first[4] == ".":  # HistData MT: 2025.01.02,18:00,...
        df = pd.read_csv(io.StringIO(text), header=None,
                         names=["d", "t", "open", "high", "low", "close", "vol"])
        df.index = pd.to_datetime(df["d"] + " " + df["t"], format="%Y.%m.%d %H:%M")
        return df, "newyork"
    # Dukascopy: 02.01.2025 00:00:00.000,o,h,l,c,v (UTC), possibly with a header line
    df = pd.read_csv(io.StringIO(text), header=None, comment=None,
                     names=["dt", "open", "high", "low", "close", "vol"])
    df = df[df["dt"].astype(str).str[:1].str.isdigit()]
    df.index = pd.to_datetime(df["dt"].str[:19], format="%d.%m.%Y %H:%M:%S")
    return df, "utc"


def to_broker(index: pd.DatetimeIndex, zone: str, broker_winter: int = 2,
              us_dst: bool = True) -> pd.DatetimeIndex:
    """Source time -> broker server time (GMT+2, +1 during US daylight saving)."""
    if zone == "newyork":
        utc = index.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
        utc = utc.tz_convert("UTC").tz_localize(None)
    else:
        utc = index
    if not us_dst:
        return utc + pd.Timedelta(hours=broker_winter)
    ny = utc.tz_localize("UTC").tz_convert("America/New_York")
    return ny.tz_localize(None) + pd.Timedelta(hours=broker_winter + 5)


def load_m1(paths: list[str], broker_winter: int = 2, us_dst: bool = True) -> pd.DataFrame:
    frames = []
    for p in paths:
        for name, text in _read_text(Path(p)):
            df, zone = _parse(text)
            df = df[["open", "high", "low", "close"]].astype(float)
            df.index = to_broker(df.index, zone, broker_winter, us_dst)
            df = df[df.index.notna()]
            frames.append(df)
            print(f"  loaded {name}: {len(df):,} M1 bars ({zone})")
    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="last")]
    ok = (m1["high"] >= m1[["open", "close"]].max(axis=1)) & (m1["low"] <= m1[["open", "close"]].min(axis=1))
    return m1[ok]


def resample(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    return m1.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def mt4_atr(df: pd.DataFrame, period: int) -> np.ndarray:
    """MT4 iATR = simple moving average of True Range."""
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean().to_numpy()


# ═══════════════════════════════ analysis (M15) ═══════════════════════════════
# Chronological index j. At evaluation, bar i is the last CLOSED bar (EA shift 1);
# EA shift s  <->  j = i + 1 - s.


@dataclass
class SignalRow:
    time: pd.Timestamp        # evaluation time = open of the next M15 bar
    side: int                 # +1 buy, -1 sell, 0 none (trend neutral or wrong candle)
    level: bool
    zone: bool
    tl: bool
    sweep: bool
    fvg: bool
    atr_ratio: float
    d1: int = 0               # D1 trend (EMA20/EMA50 on closed daily bars): +1 / -1 / 0


def compute_signals(m15: pd.DataFrame, h1: pd.DataFrame, p: Params,
                    start: pd.Timestamp | None = None) -> list[SignalRow]:
    O, H, L, C = (m15[c].to_numpy() for c in ("open", "high", "low", "close"))
    A = mt4_atr(m15, p.atr_period)
    A100 = mt4_atr(m15, 100)
    n = len(C)
    times = m15.index

    # swings (independent of the window except for its bounds)
    left, right = p.swing_left, p.swing_right
    is_hi = np.zeros(n, bool)
    is_lo = np.zeros(n, bool)
    for j in range(left, n - right):
        hw = np.r_[H[j - left:j], H[j + 1:j + right + 1]]
        lw = np.r_[L[j - left:j], L[j + 1:j + right + 1]]
        is_hi[j] = H[j] > hw.max()
        is_lo[j] = L[j] < lw.min()

    rng = H - L
    body = np.abs(C - O)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(rng > 0, body / rng, 0.0)
    impulse = (rng > 0) & (A > 0) & (rng >= p.impulse_atr * A) & (ratio >= 0.6)
    base = (rng <= 0) | (ratio <= 0.5) | (rng <= 0.7 * A)

    # H1 trend: last CLOSED H1 bar at evaluation time
    h1c = h1["close"]
    ema_f = h1c.ewm(span=p.ema_fast, adjust=False).mean().to_numpy()
    ema_s = h1c.ewm(span=p.ema_slow, adjust=False).mean().to_numpy()
    h1_close_time = (h1.index + pd.Timedelta(hours=1)).to_numpy()
    h1_close = h1c.to_numpy()
    d1 = h1.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    d1_f = d1["close"].ewm(span=20, adjust=False).mean().to_numpy()
    d1_s = d1["close"].ewm(span=50, adjust=False).mean().to_numpy()
    d1_c = d1["close"].to_numpy()
    d1_close_time = (d1.index + pd.Timedelta(days=1)).to_numpy()
    h4 = h1.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    h4_ema = h4["close"].ewm(span=p.h4_ema, adjust=False).mean()
    h4_slope = np.sign(h4_ema - h4_ema.shift(p.h4_slope_bars)).fillna(0).to_numpy()
    h4_close_time = (h4.index + pd.Timedelta(hours=4)).to_numpy()

    rows: list[SignalRow] = []
    first_i = 0
    if start is not None:
        first_i = max(0, int(np.searchsorted(times.to_numpy(), np.datetime64(start - pd.Timedelta(minutes=15)))))

    for i in range(first_i, n):
        eval_time = times[i] + pd.Timedelta(minutes=15)
        gN = min(p.lookback, (i + 2) - p.atr_period - 2)
        if gN < 50:
            continue
        w0 = i + 1 - gN          # chronological index of shift gN
        atr = A[i]
        if atr <= 0:
            continue
        tol = atr * p.level_tol_atr
        near = atr * p.near_atr
        atr_ratio = atr / A100[i] if A100[i] > 0 else 0.0

        # swings inside the EA window: shifts gN-left .. 1+right
        js = np.arange(w0 + left, i - right + 1)
        sw_hi = js[is_hi[js]]
        sw_lo = js[is_lo[js]]

        # trend
        k = int(np.searchsorted(h1_close_time, np.datetime64(eval_time), side="right")) - 1
        htf = 0
        if k >= 0:
            c_, f_, s_ = h1_close[k], ema_f[k], ema_s[k]
            if c_ > f_ > s_:
                htf = 1
            elif c_ < f_ < s_:
                htf = -1
        struct = 0
        if len(sw_hi) >= 2 and len(sw_lo) >= 2:
            h_last, h_prev = H[sw_hi[-1]], H[sw_hi[-2]]
            l_last, l_prev = L[sw_lo[-1]], L[sw_lo[-2]]
            if h_last > h_prev and l_last > l_prev:
                struct = 1
            elif h_last < h_prev and l_last < l_prev:
                struct = -1
        kd = int(np.searchsorted(d1_close_time, np.datetime64(eval_time), side="right")) - 1
        d1_trend = 0
        if kd >= 0:
            if d1_c[kd] > d1_f[kd] > d1_s[kd]:
                d1_trend = 1
            elif d1_c[kd] < d1_f[kd] < d1_s[kd]:
                d1_trend = -1
        k4 = int(np.searchsorted(h4_close_time, np.datetime64(eval_time), side="right")) - 1
        h4s = int(h4_slope[k4]) if k4 >= 0 else 0
        if p.trend_mode == "h4slope":
            htf = h4s
        elif p.trend_mode == "d1ema":
            htf = d1_trend
        if p.trend_mode == "h4slope_only":
            trend = h4s
        else:
            trend = 0 if htf * struct < 0 else (struct if struct != 0 else htf)

        o1, h1_, l1, c1 = O[i], H[i], L[i], C[i]
        side = 0
        if trend > 0 and c1 > o1:
            side = 1
        elif trend < 0 and c1 < o1:
            side = -1
        if side == 0:
            rows.append(SignalRow(eval_time, 0, False, False, False, False, False, atr_ratio, d1_trend))
            continue

        # S/R levels
        prices = np.sort(np.r_[H[sw_hi], L[sw_lo]])
        levels = []
        if len(prices):
            s_sum, cnt = prices[0], 1
            for pr in prices[1:]:
                if pr - s_sum / cnt <= tol:
                    s_sum += pr
                    cnt += 1
                else:
                    levels.append(s_sum / cnt)
                    s_sum, cnt = pr, 1
            levels.append(s_sum / cnt)
        levels = np.array(levels)

        if side > 0:
            below = levels[levels <= c1]
            f_level = len(below) > 0 and below.max() >= l1 - near
        else:
            above = levels[levels > c1]
            f_level = len(above) > 0 and above.min() <= h1_ + near

        # trendline through the last N swing lows (buy) / highs (sell)
        up = side > 0
        pts = sw_lo if up else sw_hi
        vals = L if up else H
        f_tl = False
        if len(pts) >= 2:
            cand = pts[-p.trendline_points:]
            best = None
            for a_i in range(len(cand) - 1):
                for b_i in range(a_i + 1, len(cand)):
                    ja, jb = cand[a_i], cand[b_i]
                    pa, pb = vals[ja], vals[jb]
                    if (up and pb <= pa) or (not up and pb >= pa):
                        continue
                    slope = (pb - pa) / (jb - ja)
                    seg = np.arange(ja, i + 1)
                    line = pa + slope * (seg - ja)
                    if up and np.any(C[ja:i + 1] < line - tol):
                        continue
                    if not up and np.any(C[ja:i + 1] > line + tol):
                        continue
                    later = pts[pts >= ja]
                    touches = int(np.sum(np.abs(vals[later] - (pa + slope * (later - ja))) <= tol))
                    key = (touches, jb)
                    if best is None or key > best[0]:
                        best = (key, pa + slope * (i - ja))
            if best is not None:
                ext = l1 if up else h1_
                f_tl = abs(ext - best[1]) <= near

        # supply / demand zone containing the bar-1 extreme (zones formed before bar 1)
        f_zone = False
        kind = 1 if up else -1
        ext = l1 if up else h1_
        for j in range(i - 1, w0 + p.max_base - 1, -1):   # most recent first, shift >= 2
            if not impulse[j]:
                continue
            bullish = C[j] > O[j]
            if (kind == 1) != bullish:
                continue
            bj = []
            jj = j - 1
            while jj >= w0 and len(bj) < p.max_base and base[jj] and not impulse[jj]:
                bj.append(jj)
                jj -= 1
            if not bj:
                continue
            bj = np.array(bj)
            if kind == 1:
                top = np.maximum(O[bj], C[bj]).max()
                bottom = L[bj].min()
                if C[j] <= top or np.any(C[j + 1:i + 1] < bottom):
                    continue
            else:
                top = H[bj].max()
                bottom = np.minimum(O[bj], C[bj]).min()
                if C[j] >= bottom or np.any(C[j + 1:i + 1] > top):
                    continue
            if bottom - near <= ext <= top + near:
                f_zone = True
                break

        # liquidity sweep of one of the last 3 swings
        f_sweep = False
        for js_ in (sw_lo if up else sw_hi)[::-1][:3]:
            lvl = L[js_] if up else H[js_]
            if up and not (l1 < lvl and c1 > lvl):
                continue
            if not up and not (h1_ > lvl and c1 < lvl):
                continue
            mid = C[js_ + 1:i]
            if (up and np.any(mid < lvl)) or (not up and np.any(mid > lvl)):
                continue
            f_sweep = True
            break

        # fair value gap formed before bar 1, bar 1 traded into it and closed back out
        f_fvg = False
        last_s = min(p.fvg_lookback, gN - 1)
        for s in range(3, last_s + 1):            # most recent first
            m = i + 1 - s
            if up:
                if not (L[m + 1] > H[m - 1] and C[m] > O[m]):
                    continue
                bottom, top = H[m - 1], L[m + 1]
            else:
                if not (H[m + 1] < L[m - 1] and C[m] < O[m]):
                    continue
                top, bottom = L[m - 1], H[m + 1]
            if top - bottom < p.fvg_min_atr * A[m]:
                continue
            between = slice(m + 2, i)
            if up and np.any(L[between] <= bottom):
                continue
            if not up and np.any(H[between] >= top):
                continue
            if (up and l1 <= top and c1 > bottom) or (not up and h1_ >= bottom and c1 < top):
                f_fvg = True
                break

        rows.append(SignalRow(eval_time, side, bool(f_level), f_zone, f_tl, f_sweep, f_fvg, atr_ratio, d1_trend))
    return rows


def confluence(r: SignalRow, p: Params) -> int:
    if p.require_fvg and not r.fvg:
        return 0
    return (int(r.level) + int(r.zone) + (int(r.tl) if p.use_tl else 0)
            + (int(r.sweep) if p.use_sweep else 0) + (int(r.fvg) if p.use_fvg else 0))


# ═══════════════════════════════ basket simulation (M1) ═══════════════════════════════


@dataclass
class Basket:
    side: int                                   # +1 buy, -1 sell
    start: pd.Timestamp
    entries: list = field(default_factory=list)  # (fill price, lots)
    worst: float = 0.0
    floor: float | None = None                   # trailing profit floor (money)

    @property
    def lots(self) -> float:
        return sum(l for _, l in self.entries)

    def pnl(self, bid: float, spread: float) -> float:
        if self.side > 0:
            return sum((bid - e) * l * CONTRACT for e, l in self.entries)
        ask = bid + spread
        return sum((e - ask) * l * CONTRACT for e, l in self.entries)

    def last_pnl(self, bid: float, spread: float) -> float:
        e, l = self.entries[-1]
        return (bid - e) * l * CONTRACT if self.side > 0 else (e - bid - spread) * l * CONTRACT

    def bid_for_money(self, money: float, spread: float) -> float:
        s = sum(e * l for e, l in self.entries)
        if self.side > 0:
            return (money / CONTRACT + s) / self.lots
        return (s - money / CONTRACT) / self.lots - spread

    def bid_for_last(self, money: float, spread: float) -> float:
        e, l = self.entries[-1]
        return e + money / (CONTRACT * l) if self.side > 0 else e - money / (CONTRACT * l) - spread


@dataclass
class Result:
    params: Params
    baskets: pd.DataFrame
    net: float
    max_dd: float
    max_dd_pct: float
    final_balance: float


def simulate(m1: pd.DataFrame, signals: list[SignalRow], p: Params, balance0: float = 1000.0,
             start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
             m15_atr: pd.Series | None = None) -> Result:
    if start is not None:
        m1 = m1[m1.index >= start]
    if end is not None:
        m1 = m1[m1.index < end]
    t_arr = m1.index
    O, H, L, C = (m1[c].to_numpy() for c in ("open", "high", "low", "close"))
    sig_by_time = {r.time: r for r in signals}
    slope_now = np.zeros(len(C), dtype=int)
    if p.no_add_against_trend:
        h4 = m1.resample("4h").agg({"close": "last"}).dropna()
        ema = h4["close"].ewm(span=p.h4_ema, adjust=False).mean()
        sl = np.sign(ema - ema.shift(p.h4_slope_bars)).fillna(0).to_numpy().astype(int)
        closed = (h4.index + pd.Timedelta(hours=4)).to_numpy()
        kk = np.searchsorted(closed, t_arr.to_numpy(), side="right") - 1
        slope_now = np.where(kk >= 0, sl[np.clip(kk, 0, None)], 0)
    cur_slope = 0

    balance = balance0
    peak_eq = balance0
    max_dd = 0.0
    max_dd_pct = 0.0
    basket: Basket | None = None
    pause_until = pd.Timestamp.min
    dir_block = {1: pd.Timestamp.min, -1: pd.Timestamp.min}
    day_pl: dict = {}
    records = []
    last_bar15 = None
    close_reason = ""

    def step_money(lots: float, now: pd.Timestamp) -> float:
        if not p.step_mode_atr or m15_atr is None:
            return p.step_loss_usd
        k = m15_atr.index.searchsorted(now, side="right") - 2   # last closed M15 bar
        atr = float(m15_atr.iloc[max(k, 0)])
        return max(p.step_loss_usd, p.step_atr_mult * atr * CONTRACT * lots)

    def equity_point(bid: float):
        nonlocal peak_eq, max_dd, max_dd_pct
        eq = balance + (basket.pnl(bid, p.spread) if basket else 0.0)
        if eq > peak_eq:
            peak_eq = eq
        dd = peak_eq - eq
        if dd > max_dd:
            max_dd = dd
        if peak_eq > 0 and dd / peak_eq > max_dd_pct:
            max_dd_pct = dd / peak_eq

    def finish(bid: float, now: pd.Timestamp, reason: str):
        nonlocal basket, balance, pause_until
        res = basket.pnl(bid, p.spread)
        balance += res
        worst = min(basket.worst, res)
        day = now.normalize()
        day_pl[day] = day_pl.get(day, 0.0) + res
        records.append({"open": basket.start, "close": now, "side": "BUY" if basket.side > 0 else "SELL",
                        "trades": len(basket.entries), "worst": round(worst, 2), "result": round(res, 2),
                        "reason": reason})
        if reason == "stop":
            pause_until = now + pd.Timedelta(minutes=p.pause_after_stop_min)
            if p.direction_cooldown_h > 0:
                dir_block[basket.side] = now + pd.Timedelta(hours=p.direction_cooldown_h)
        basket = None
        equity_point(bid)

    def target_of(b: Basket) -> float:
        if p.deep_trades > 0 and len(b.entries) >= p.deep_trades:
            return p.deep_target_usd
        return max(p.take_profit_usd, p.recovery_ratio * -b.worst)

    def move(p0: float, p1: float, now: pd.Timestamp):
        """Walk the Bid from p0 to p1 and fire adds / stop / target at their levels."""
        nonlocal basket
        if basket is None:
            return
        adverse = (p1 < p0) if basket.side > 0 else (p1 > p0)
        cur = p0
        if basket.floor is not None:
            # trailing: close when profit falls back to the floor, else raise the floor
            lvl = basket.bid_for_money(basket.floor, p.spread)
            if adverse and ((basket.side > 0 and p1 <= lvl) or (basket.side < 0 and p1 >= lvl)):
                fill = min(lvl, cur) if basket.side > 0 else max(lvl, cur)
                finish(fill, now, "target")
                return
            basket.floor = max(basket.floor, basket.pnl(p1, p.spread) - p.trail_usd)
            equity_point(p1)
            return
        if adverse:
            while basket is not None:
                stop_lvl = basket.bid_for_money(-p.max_basket_loss_usd, p.spread)
                add_lvl = None
                if (len(basket.entries) < p.max_trades and not p.add_on_bar_close
                        and not (p.no_add_against_trend and cur_slope == -basket.side)):
                    add_lvl = basket.bid_for_last(-step_money(basket.entries[-1][1], now), p.spread)
                if basket.side > 0:
                    stop_hit = p1 <= stop_lvl
                    add_hit = add_lvl is not None and p1 <= add_lvl
                    stop_first = stop_hit and (not add_hit or stop_lvl >= add_lvl)
                    fill_stop = min(stop_lvl, cur)
                    fill_add = min(add_lvl, cur) if add_hit else None
                else:
                    stop_hit = p1 >= stop_lvl
                    add_hit = add_lvl is not None and p1 >= add_lvl
                    stop_first = stop_hit and (not add_hit or stop_lvl <= add_lvl)
                    fill_stop = max(stop_lvl, cur)
                    fill_add = max(add_lvl, cur) if add_hit else None
                if stop_first:
                    basket.worst = min(basket.worst, basket.pnl(fill_stop, p.spread))
                    equity_point(fill_stop)
                    finish(fill_stop, now, "stop")
                    return
                if add_hit:
                    entry = fill_add + p.spread if basket.side > 0 else fill_add
                    basket.worst = min(basket.worst, basket.pnl(fill_add, p.spread))
                    basket.entries.append((entry, p.lots))
                    cur = fill_add
                    continue
                break
            basket.worst = min(basket.worst, basket.pnl(p1, p.spread))
            equity_point(p1)
        else:
            target = target_of(basket)
            lvl = basket.bid_for_money(target, p.spread)
            hit = p1 >= lvl if basket.side > 0 else p1 <= lvl
            if hit:
                if p.trail_usd > 0:
                    basket.floor = max(target, basket.pnl(p1, p.spread) - p.trail_usd)
                    equity_point(p1)
                    return
                fill = max(lvl, cur) if basket.side > 0 else min(lvl, cur)
                finish(fill, now, "target")
                return
            equity_point(p1)

    def blocked(now: pd.Timestamp, sig: SignalRow) -> str:
        if now < pause_until:
            return "pause"
        if p.use_session and not (p.session_start <= now.hour < p.session_end):
            return "session"
        if p.use_friday_cutoff and now.weekday() == 4 and now.hour >= p.friday_cutoff_hour:
            return "friday"
        if p.max_atr_ratio > 0 and sig.atr_ratio > p.max_atr_ratio:
            return "volatility"
        if p.min_atr_ratio > 0 and sig.atr_ratio < p.min_atr_ratio:
            return "quiet"
        if p.use_d1_filter and sig.d1 == -sig.side:
            return "d1"
        if p.max_daily_loss_usd > 0 and day_pl.get(now.normalize(), 0.0) <= -p.max_daily_loss_usd:
            return "daily"
        if p.max_weekly_loss_usd > 0:
            wk = (now - pd.Timedelta(days=now.weekday())).normalize()
            if sum(v for d, v in day_pl.items() if d >= wk) <= -p.max_weekly_loss_usd:
                return "weekly"
        if p.spread > p.max_spread:
            return "spread"
        return ""

    skips: dict = {}
    prev_close = None
    for k in range(len(C)):
        now = t_arr[k]
        o, h, l, c = O[k], H[k], L[k], C[k]
        cur_slope = slope_now[k]

        # 1) new M15 bar -> signal / auto entry (first tick of the bar)
        bar15 = now.floor("15min")
        if bar15 != last_bar15:
            last_bar15 = bar15
            # recovery on bar close: the previous M15 bar just closed at ~this open
            if (p.add_on_bar_close and basket is not None and len(basket.entries) < p.max_trades
                    and basket.last_pnl(o, p.spread) <= -step_money(basket.entries[-1][1], now)):
                entry = o + p.spread if basket.side > 0 else o
                basket.entries.append((entry, p.lots))
            sig = sig_by_time.get(bar15)
            if sig is not None and sig.side != 0 and confluence(sig, p) >= max(1, p.min_confluence):
                reason = blocked(now, sig)
                if not reason and now < dir_block[sig.side]:
                    reason = "cooldown"
                if not reason and basket is not None:
                    reason = "basket-open"
                if reason:
                    skips[reason] = skips.get(reason, 0) + 1
                else:
                    entry = o + p.spread if sig.side > 0 else o
                    basket = Basket(sig.side, now, [(entry, p.lots)])

        # gap from the previous bar close to this open
        if prev_close is not None and basket is not None:
            move(prev_close, o, now)

        # 2) weekend close (checked at the bar open)
        if (basket is not None and p.close_before_weekend and now.weekday() == 4
                and now.hour >= p.weekend_close_hour
                and basket.pnl(o, p.spread) >= -p.weekend_close_max_loss):
            finish(o, now, "weekend")

        # 3) intrabar path
        if p.pessimistic_path and basket is not None:
            path = (o, l, h, c) if basket.side > 0 else (o, h, l, c)
        else:
            path = (o, l, h, c) if c >= o else (o, h, l, c)
        for a, b in zip(path[:-1], path[1:]):
            if basket is None:
                break
            move(a, b, now)
        prev_close = c

    if basket is not None:
        finish(C[-1], t_arr[-1], "end")

    df = pd.DataFrame(records)
    res = Result(p, df, balance - balance0, max_dd, max_dd_pct * 100, balance)
    res.skips = skips  # type: ignore[attr-defined]
    return res


# ═══════════════════════════════ reporting ═══════════════════════════════


def summary(res: Result) -> dict:
    b = res.baskets
    if b.empty:
        return {"net": 0.0, "baskets": 0}
    wins = b[b.result >= 0]
    losses = b[b.result < 0]
    gp, gl = wins.result.sum(), -losses.result.sum()
    return {
        "net": round(res.net, 2),
        "baskets": len(b),
        "won": len(wins),
        "stops": int((b.reason == "stop").sum()),
        "weekend": int((b.reason == "weekend").sum()),
        "win%": round(len(wins) / len(b) * 100, 1),
        "PF": round(gp / gl, 2) if gl > 0 else float("inf"),
        "maxDD$": round(res.max_dd, 2),
        "maxDD%": round(res.max_dd_pct, 1),
        "5-trade": int((b.trades >= res.params.max_trades).sum()),
    }


SCENARIOS: dict[str, dict] = {
    "A  base v4.6": {},
    "B  no direction cooldown": {"direction_cooldown_h": 0},
    "C  no weekend close": {"close_before_weekend": False},
    "D  ATR step, 4 trades": {"step_mode_atr": True, "max_trades": 4},
    "E  no sweep / FVG": {"use_sweep": False, "use_fvg": False},
    "F  4 trades, stop 100": {"max_trades": 4, "max_basket_loss_usd": 100.0},
    "G  MinConfluence 1": {"min_confluence": 1},
    "H  MinConfluence 3": {"min_confluence": 3},
    "I  no session filter": {"use_session": False},
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="HistData / Dukascopy M1 csv or zip files")
    ap.add_argument("--start", help="first trading day (earlier data is warm-up), e.g. 2026-01-01")
    ap.add_argument("--end", help="end date (exclusive)")
    ap.add_argument("--spread", type=float, default=0.35)
    ap.add_argument("--balance", type=float, default=1000.0)
    ap.add_argument("--broker-winter", type=int, default=2)
    ap.add_argument("--no-us-dst", action="store_true")
    ap.add_argument("--scenarios", action="store_true", help="run all scenarios A..I")
    ap.add_argument("--save", help="write the base run's baskets to this CSV")
    args = ap.parse_args(argv)

    print("Loading data ...")
    m1 = load_m1(args.files, args.broker_winter, not args.no_us_dst)
    print(f"  {len(m1):,} M1 bars, {m1.index[0]} .. {m1.index[-1]} (broker time)")
    start = pd.Timestamp(args.start) if args.start else m1.index[0] + pd.Timedelta(days=21)
    end = pd.Timestamp(args.end) if args.end else None

    m15 = resample(m1, 15)
    h1 = resample(m1, 60)
    base = Params(spread=args.spread)
    print("Analysing M15 bars ...")
    signals = compute_signals(m15, h1, base, start)
    m15_atr = pd.Series(mt4_atr(m15, base.atr_period), index=m15.index)

    runs = SCENARIOS if args.scenarios else {"A  base v4.6": {}}
    rows = []
    for name, over in runs.items():
        p = replace(base, **over)
        res = simulate(m1, signals, p, args.balance, start, end, m15_atr)
        s = summary(res)
        rows.append({"scenario": name, **s})
        if name.startswith("A") and args.save:
            res.baskets.to_csv(args.save, index=False)
        if not args.scenarios:
            print(res.baskets.tail(15).to_string(index=False))
            print("skipped signals:", getattr(res, "skips", {}))
            if not res.baskets.empty:
                monthly = res.baskets.groupby(res.baskets["close"].dt.to_period("M"))["result"].sum()
                print("monthly P/L:\n" + monthly.round(2).to_string())
    print()
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
