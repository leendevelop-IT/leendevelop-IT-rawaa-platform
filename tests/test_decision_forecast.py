"""Decision summary (priority classes) and forecasting with backtesting."""
from datetime import date, timedelta

import pytest

from rawaa_core import decision, forecast, scheduler
from rawaa_core.series import trusted_series, to_points
from helpers import monthly, seasonal


def summarize(rows, boundary='approved', today=None):
    s = trusted_series(rows, 1)
    today = today or date.fromisoformat(s[-1]['measured_at']) + timedelta(days=5) if s else date(2024, 12, 1)
    return decision.summarize(s, boundary, sum(r['origin'] in ('imported', 'manual') for r in rows), today)


# ---------------------------------------------------------------- series selection
def test_only_trusted_satellite_readings_are_used():
    rows = monthly([0.5] * 6) + monthly([0.1] * 3, start=date(2024, 7, 12), origin='imported', reliability='unverified')
    rows += monthly([0.05], start=date(2024, 9, 12), reliability='unreliable', valid=30)
    rows += monthly([0.2], start=date(2024, 10, 12), bv=2)
    s = trusted_series(rows, 1)
    assert len(s) == 6 and all(r['origin'] == 'satellite' for r in s)


def test_one_reading_per_month_keeps_the_clearest():
    a = monthly([0.40], start=date(2024, 3, 2), valid=70)[0]
    b = dict(monthly([0.45], start=date(2024, 3, 20), valid=95)[0], id=99)
    assert trusted_series([a, b])[0]['id'] == 99


# ---------------------------------------------------------------- priority classes
def test_insufficient_when_few_readings():
    d = summarize(monthly([0.5, 0.5, 0.49]))
    assert d['priority'] == 'insufficient' and not d['automatic_actions_allowed']


def test_insufficient_when_only_imported_data():
    d = summarize(monthly([0.5] * 10, origin='imported', reliability='unverified'))
    assert d['priority'] == 'insufficient' and d['excluded_unverified_readings'] == 10


def test_insufficient_when_stale():
    rows = monthly([0.5] * 8)
    d = decision.summarize(trusted_series(rows), 'approved', 0, date(2025, 6, 1))
    assert d['priority'] == 'insufficient' and d['stale_days'] > 90


def test_stable_series():
    d = summarize(monthly([0.50, 0.51, 0.49, 0.50, 0.52, 0.50, 0.51, 0.50]))
    assert d['priority'] == 'stable' and d['trend']['direction'] == 'stable'
    assert d['current']['ndvi'] == 0.5 and d['previous']['ndvi'] == 0.51


def test_single_dip_is_follow_up_not_urgent():
    d = summarize(monthly([0.50, 0.51, 0.49, 0.50, 0.52, 0.50, 0.51, 0.38]))
    assert d['priority'] == 'follow_up' and d['persistence'] == 1


def test_persistent_reliable_decline_is_urgent():
    d = summarize(monthly([0.50, 0.51, 0.50, 0.50, 0.49, 0.50, 0.38, 0.34, 0.30]))
    assert d['priority'] == 'urgent' and d['persistence'] >= 2 and d['automatic_actions_allowed']
    assert any('3 أيام' in d['action_ar'] for _ in [0])
    assert 'ميداني' in d['action_ar']  # no diagnosis from satellite alone


def test_low_reliability_downgrades_urgent():
    d = summarize(monthly([0.50, 0.51, 0.50, 0.38, 0.34], valid=65, reliability='limited'), boundary='needs_review')
    assert d['priority'] == 'follow_up' and not d['automatic_actions_allowed']


def test_unapproved_boundary_marks_result_provisional():
    d = summarize(monthly([0.50, 0.51, 0.50, 0.50, 0.49, 0.50, 0.38, 0.34, 0.30]), boundary='pending_approval')
    assert d['provisional'] and d['automatic_actions_allowed']
    d2 = summarize(monthly([0.50, 0.51, 0.50, 0.50, 0.49, 0.50, 0.38, 0.34, 0.30]), boundary='needs_review')
    assert not d2['automatic_actions_allowed']


def test_normal_summer_dip_is_not_flagged_with_seasonal_history():
    vals, start = seasonal(31, noise=0.004)
    rows = monthly(vals, start=start, step=30.44)
    # find a summer month near the end
    d = summarize(rows)
    assert d['baseline_kind'] == 'seasonal'
    assert d['priority'] in ('stable', 'follow_up')
    assert d['anomaly_pct'] is not None and abs(d['anomaly_pct']) < 10


# ---------------------------------------------------------------- forecasting
def test_no_forecast_with_few_points():
    f = forecast.forecast(to_points(trusted_series(monthly([0.5] * 5))), date(2024, 6, 1))
    assert not f['available'] and 'لا نختلق' in f['reason_ar']


def test_no_forecast_when_stale():
    f = forecast.forecast(to_points(trusted_series(monthly([0.5] * 10))), date(2026, 1, 1))
    assert not f['available']


def test_declining_series_beats_naive_and_gives_probability():
    vals = [round(0.60 - 0.015 * i, 3) for i in range(14)]
    pts = to_points(trusted_series(monthly(vals)))
    f = forecast.forecast(pts, pts[-1][0] + timedelta(days=3))
    assert f['available'] and f['model'] in ('drift', 'holt') and f['backtest']['beats_naive']
    h7, h30 = f['horizons']
    assert h7['days'] == 7 and h30['days'] == 30
    assert h30['ndvi'] < pts[-1][1] and h30['low80'] < h30['ndvi'] < h30['high80']
    assert h30['high95'] - h30['low95'] > h30['high80'] - h30['low80']
    assert f['direction'] == 'declining' and f['decline_probability_pct'] is not None and f['decline_probability_pct'] > 50


def test_random_noise_falls_back_to_naive_without_probability():
    import random
    rnd = random.Random(3)
    vals = [round(0.5 + rnd.gauss(0, 0.02), 3) for _ in range(12)]
    pts = to_points(trusted_series(monthly(vals)))
    f = forecast.forecast(pts, pts[-1][0] + timedelta(days=3))
    assert f['available']
    assert f['decline_probability_pct'] is None or f['backtest']['beats_naive']
    assert any(b['model'] == 'naive' for b in f['backtest']['leaderboard'])


def test_seasonal_model_selected_for_strong_seasonality():
    vals, start = seasonal(30, amp=0.10, noise=0.003)
    pts = to_points(trusted_series(monthly(vals, start=start, step=30.44)))
    f = forecast.forecast(pts, pts[-1][0] + timedelta(days=3))
    assert f['available'] and f['model'] == 'seasonal' and f['backtest']['skill_pct'] > 15


def test_backtest_uses_only_past_data():
    """Changing a future value must not change predictions made at earlier origins."""
    vals = [round(0.6 - 0.01 * i, 3) for i in range(12)]
    pts = to_points(trusted_series(monthly(vals)))
    e1, _ = forecast.backtest(pts)
    pts2 = pts[:-1] + [(pts[-1][0], 0.9)]
    e2, _ = forecast.backtest(pts2)
    for m in e1:
        assert [x for i, x in e1[m] if i < len(pts) - 1] == [x for i, x in e2[m] if i < len(pts) - 1]


# ---------------------------------------------------------------- scheduling
def test_schedule_rules():
    today = date(2024, 11, 1)
    urgent = {'priority': 'urgent', 'provisional': False, 'current': {'date': '2024-10-28'}}
    p = scheduler.plan(urgent, None, today)
    assert p['next_check'] == '2024-11-04' and p['priority'] == 'high' and p['reassess_at'] > p['next_check']
    stable = {'priority': 'stable', 'provisional': False, 'current': {'date': '2024-10-28'}}
    assert scheduler.plan(stable, None, today)['next_check'] == '2024-12-01'
    risky = scheduler.plan(stable, {'available': True, 'decline_probability_pct': 70}, today)
    assert risky['next_check'] == '2024-11-15' and '70%' in risky['reason_ar']
    assert scheduler.plan(stable, None, today)['cycle_key'] == '2024-10-28:stable'
