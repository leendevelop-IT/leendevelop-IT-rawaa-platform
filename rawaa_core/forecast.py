"""NDVI forecasts at +7 and +30 days with rolling-origin backtesting against a naive baseline.

Design rules
- Only trusted satellite readings are used (see series.trusted_series).
- No forecast at all when there are fewer than MIN_POINTS readings or the latest reading is stale.
- Every candidate model is backtested on the same rolling origins; the "naive" model (tomorrow = last
  reading) is the reference. A model is only preferred if it beats naive on the backtest.
- Uncertainty comes from the chosen model's own backtest errors, widened with the forecast horizon.
- The probability of continued decline is only reported when the model has skill and the trend is downward.
"""
from __future__ import annotations
import math
import statistics
from datetime import date, timedelta

MIN_POINTS = 6
MAX_STALE_DAYS = 75
HORIZONS = (7, 30)

MODEL_LABELS = {
    'naive': ('آخر قراءة كما هي (النموذج المرجعي)', 'Last reading carried forward (reference)'),
    'drift': ('اتجاه خطي مقاوم للقيم الشاذة (Theil–Sen) مخمّد', 'Damped robust linear trend (Theil–Sen)'),
    'holt': ('تمهيد أُسّي بالاتجاه المخمّد (Holt)', 'Damped-trend exponential smoothing (Holt)'),
    'seasonal': ('نفس الموسم من العام الماضي + الانحراف الحالي', 'Same season last year + current anomaly'),
}


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def theil_sen_slope(points):
    """Median of pairwise slopes, NDVI per day."""
    s = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dd = (points[j][0] - points[i][0]).days
            if dd > 0:
                s.append((points[j][1] - points[i][1]) / dd)
    return statistics.median(s) if s else 0.0


def _fit_naive(pts):
    last = pts[-1][1]
    return lambda target: last


def _fit_drift(pts):
    window = pts[-6:]
    if len(window) < 3:
        return None
    slope = theil_sen_slope(window)
    last_d, last_v = pts[-1]
    def f(target):
        days = min(max((target - last_d).days, 0), 45)  # damping: trend is not extended beyond ~6 weeks
        return last_v + slope * days
    return f


def _fit_holt(pts, alpha=0.5, beta=0.2, phi=0.8):
    y = [v for _, v in pts]
    if len(y) < 4:
        return None
    level, trend = y[0], y[1] - y[0]
    for v in y[1:]:
        new_level = alpha * v + (1 - alpha) * (level + phi * trend)
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    gaps = [(pts[i + 1][0] - pts[i][0]).days for i in range(len(pts) - 1)]
    step = statistics.median(gaps) if gaps else 30
    last_d = pts[-1][0]
    def f(target):
        h = max((target - last_d).days, 0) / step
        whole = int(h)
        damp = sum(phi ** k for k in range(1, whole + 1)) + (h - whole) * phi ** (whole + 1)
        return level + trend * damp
    return f


def _nearest(pts, d, tol=20):
    best = None
    for pd_, v in pts:
        dd = abs((pd_ - d).days)
        if dd <= tol and (best is None or dd < best[0]):
            best = (dd, v)
    return None if best is None else best[1]


def _fit_seasonal(pts):
    last_d, last_v = pts[-1]
    if (last_d - pts[0][0]).days < 380:
        return None
    ref_last = _nearest(pts[:-1], last_d - timedelta(days=365))
    if ref_last is None:
        return None
    anomaly = last_v - ref_last
    def f(target):
        ref = _nearest(pts, target - timedelta(days=365))
        return None if ref is None else ref + anomaly
    return f


FITTERS = {'naive': _fit_naive, 'drift': _fit_drift, 'holt': _fit_holt, 'seasonal': _fit_seasonal}


def backtest(pts, max_origins=8):
    """Rolling origin: fit on pts[:i], predict pts[i]. Returns {model: [(origin_index, error)]}."""
    n = len(pts)
    start = max(4, n - max_origins)
    errs = {k: [] for k in FITTERS}
    for i in range(start, n):
        hist = pts[:i]
        target_d, target_v = pts[i]
        for name, fit in FITTERS.items():
            f = fit(hist)
            if f is None:
                continue
            p = f(target_d)
            if p is None:
                continue
            errs[name].append((i, p - target_v))
    return errs, list(range(start, n))


def forecast(pts, today: date | None = None) -> dict:
    today = today or date.today()
    n = len(pts)
    if n < MIN_POINTS:
        return {'available': False, 'kind': 'forecast', 'n': n,
                'reason_ar': f'التوقع يحتاج {MIN_POINTS} قراءات فضائية موثوقة على الأقل (المتوفر {n}). لا نختلق توقعًا.',
                'reason_en': f'Forecasting needs at least {MIN_POINTS} trusted satellite readings (have {n}). No forecast is made up.'}
    last_d, last_v = pts[-1]
    stale = (today - last_d).days
    if stale > MAX_STALE_DAYS:
        return {'available': False, 'kind': 'forecast', 'n': n,
                'reason_ar': f'آخر قراءة موثوقة عمرها {stale} يومًا؛ التوقع من بيانات قديمة غير موثوق. اجلبوا قراءات أحدث.',
                'reason_en': f'Latest trusted reading is {stale} days old; refresh satellite data before forecasting.'}
    errs, origins = backtest(pts)
    naive_by_origin = dict(errs['naive'])
    board = []
    for name, e in errs.items():
        if len(e) < max(3, int(0.6 * len(origins))):
            continue
        mae = statistics.mean(abs(x) for _, x in e)
        mae_naive = statistics.mean(abs(naive_by_origin[i]) for i, _ in e)
        skill = 1 - mae / mae_naive if mae_naive > 0 else 0.0
        rmse = math.sqrt(statistics.mean(x * x for _, x in e))
        board.append({'model': name, 'label_ar': MODEL_LABELS[name][0], 'label_en': MODEL_LABELS[name][1],
                      'mae': round(mae, 4), 'mae_naive_same_origins': round(mae_naive, 4),
                      'skill_pct': round(100 * skill, 1), 'rmse': rmse, 'origins': len(e)})
    if not board:
        return {'available': False, 'kind': 'forecast', 'n': n,
                'reason_ar': 'تعذّر اختبار النماذج على السجل التاريخي.', 'reason_en': 'Backtesting was not possible.'}
    board.sort(key=lambda b: (-b['skill_pct'], b['mae']))
    best = board[0] if board[0]['skill_pct'] > 0 else next(b for b in board if b['model'] == 'naive')
    model = best['model']
    f = FITTERS[model](pts)
    gaps = [(pts[i + 1][0] - pts[i][0]).days for i in range(len(pts) - 1)]
    step = max(5, statistics.median(gaps))
    sd = max(best['rmse'], 0.01)
    horizons = []
    for h in HORIZONS:
        target = today + timedelta(days=h)
        v = f(target)
        if v is None:
            v = _fit_naive(pts)(target)
        v = max(-1.0, min(1.0, v))
        h_eff = max(1, (target - last_d).days)
        scale = min(3.0, max(0.5, math.sqrt(h_eff / step)))
        w80, w95 = 1.2816 * sd * scale, 1.96 * sd * scale
        horizons.append({'days': h, 'target_date': target.isoformat(), 'ndvi': round(v, 3),
                         'low80': round(v - w80, 3), 'high80': round(v + w80, 3),
                         'low95': round(v - w95, 3), 'high95': round(v + w95, 3),
                         'days_from_last_reading': h_eff, 'sd': round(sd * scale, 4)})
    skill = best['skill_pct']
    if skill >= 15 and n >= 12 and best['origins'] >= 6:
        confidence = 'high'
    elif skill > 0 and n >= 8:
        confidence = 'medium'
    else:
        confidence = 'low'
    h30 = horizons[-1]
    delta = h30['ndvi'] - last_v
    direction = 'declining' if delta <= -0.01 else 'improving' if delta >= 0.01 else 'stable'
    p_decline, p_reason_ar, p_reason_en = None, None, None
    if model == 'naive' or skill <= 0:
        p_reason_ar = 'لم يتفوّق أي نموذج على النموذج المرجعي البسيط، فلا نقدّم احتمال تراجع.'
        p_reason_en = 'No model beats the naive reference, so no decline probability is given.'
    elif n < 8:
        p_reason_ar = 'السجل أقصر من 8 قراءات؛ احتمال التراجع غير مدعوم بالبيانات بعد.'
        p_reason_en = 'Fewer than 8 readings; a decline probability is not supported yet.'
    elif direction != 'declining':
        p_reason_ar = 'الاتجاه المتوقع ليس تراجعًا.'
        p_reason_en = 'The expected direction is not a decline.'
    else:
        p_decline = round(100 * _phi((last_v - h30['ndvi']) / h30['sd']))
    label_ar, label_en = MODEL_LABELS[model]
    for b in board:
        b['rmse'] = round(b['rmse'], 4)
    return {'available': True, 'kind': 'forecast', 'n': n, 'model': model, 'model_ar': label_ar, 'model_en': label_en,
            'last_actual': {'date': last_d.isoformat(), 'ndvi': round(last_v, 3)},
            'horizons': horizons, 'direction': direction, 'confidence': confidence,
            'interval': '80% and 95% prediction intervals from backtest errors',
            'backtest': {'origins': len(origins), 'leaderboard': board, 'skill_pct': skill,
                         'beats_naive': model != 'naive', 'mae': best['mae'], 'mae_naive': best['mae_naive_same_origins']},
            'decline_probability_pct': p_decline, 'decline_probability_reason_ar': p_reason_ar,
            'decline_probability_reason_en': p_reason_en,
            'explain_ar': (f"توقّع (وليس قراءة فعلية): بعد 30 يومًا يُتوقع NDVI ≈ {h30['ndvi']:.2f} ضمن نطاق {h30['low80']:.2f}–{h30['high80']:.2f} (احتمال 80%). "
                           f"النموذج المختار: {label_ar}، اختُبر على آخر {len(origins)} قراءات تاريخية "
                           + (f"وكان أدق من النموذج المرجعي بنسبة {skill:.0f}%." if model != 'naive' else "ولم يتفوّق عليه أي نموذج، لذا نعرض آخر قراءة كمرجع.")),
            'explain_en': (f"Forecast (not a measurement): in 30 days NDVI ≈ {h30['ndvi']:.2f}, 80% range {h30['low80']:.2f}–{h30['high80']:.2f}. "
                           f"Model: {label_en}, backtested on {len(origins)} past readings"
                           + (f", {skill:.0f}% more accurate than naive." if model != 'naive' else '; no model beat naive.'))}
