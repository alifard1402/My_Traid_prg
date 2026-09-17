import pytest

from trading_bot.risk import RiskManager


def test_position_size_matches_configured_risk():
    """اگر حد ضرر بخورد، دقیقاً ۱٪ سرمایه باید از دست برود — نه بیشتر."""
    rm = RiskManager(risk_per_trade=0.01)
    plan = rm.plan(equity=10_000, entry_price=100.0, stop_distance=5.0, target_distance=10.0)

    assert plan.quantity == pytest.approx(20.0)      # 10000 × 1% ÷ 5
    assert plan.risk_amount == pytest.approx(100.0)  # ۱٪ از ۱۰٬۰۰۰
    assert plan.stop_price == pytest.approx(95.0)
    assert plan.target_price == pytest.approx(110.0)


def test_wider_stop_means_smaller_position():
    """در بازار پرنوسان (حد ضرر دورتر) باید حجم کمتری بگیریم."""
    rm = RiskManager(risk_per_trade=0.01)
    tight = rm.plan(10_000, 100.0, stop_distance=2.0, target_distance=4.0)
    wide = rm.plan(10_000, 100.0, stop_distance=10.0, target_distance=20.0)
    assert wide.quantity < tight.quantity


def test_position_capped_at_available_capital():
    """حد ضررِ خیلی نزدیک نباید باعث خرید با اهرم شود."""
    rm = RiskManager(risk_per_trade=0.01, max_position_pct=0.95)
    plan = rm.plan(equity=1_000, entry_price=100.0, stop_distance=0.01, target_distance=0.02)
    assert plan.notional <= 1_000 * 0.95 + 1e-9


def test_invalid_inputs_produce_no_trade():
    rm = RiskManager()
    assert rm.plan(0, 100, 5, 10).quantity == 0
    assert not rm.plan(1000, 100, 0, 10).is_valid


def test_max_drawdown_switch():
    rm = RiskManager(max_drawdown_stop=0.25)
    assert not rm.breached_max_drawdown(equity=800, peak_equity=1000)   # ۲۰٪ افت
    assert rm.breached_max_drawdown(equity=750, peak_equity=1000)       # ۲۵٪ افت
