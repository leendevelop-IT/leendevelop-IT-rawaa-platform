"""Decision summary for each park: current vs previous reading, trend, meaning, reliability, priority, reason, action.

Priority classes: 'urgent' (تدخل عاجل), 'follow_up' (تحتاج متابعة), 'stable' (مستقرة), 'insufficient' (بيانات غير كافية).
The class is never decided by one NDVI value. It combines: the park's own history, the season (same months of
earlier years when available), data quality, and whether the decline persists across consecutive readings.
Satellite data alone cannot diagnose plant disease or an irrigation fault; the actions therefore ask for field checks.
"""
from __future__ import annotations
import statistics
from datetime import date

from . import indices
from .forecast import theil_sen_slope
from .series import reading_date

PRIORITIES = ('urgent', 'follow_up', 'stable', 'insufficient')
PRIORITY_AR = {'urgent': 'تدخل عاجل', 'follow_up': 'تحتاج متابعة', 'stable': 'مستقرة', 'insufficient': 'بيانات غير كافية'}
PRIORITY_EN = {'urgent': 'Urgent intervention', 'follow_up': 'Needs follow-up', 'stable': 'Stable', 'insufficient': 'Insufficient data'}
MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']

MIN_READINGS = 4          # below this: insufficient
STALE_DAYS = 90           # latest trusted reading older than this: insufficient
DECLINE_PCT = -10.0       # anomaly vs expected value that counts as a decline
STRONG_DECLINE_PCT = -20.0
SLOPE_PER_MONTH = 0.01    # NDVI change per 30 days treated as a real trend


def _month_gap(a: int, b: int) -> int:
    d = abs(a - b) % 12
    return min(d, 12 - d)


def expected_value(series, idx):
    """Expected NDVI for reading idx from earlier readings only.
    Seasonal: median of readings from the same month ±1 in earlier years (needs ≥2).
    Otherwise rolling: median of up to 6 readings before idx (excluding the 1 just before, to avoid
    the expectation chasing a decline that has already started)."""
    d = date.fromisoformat(reading_date(series[idx]))
    earlier = series[:idx]
    same = [r['ndvi'] for r in earlier
            if (d - date.fromisoformat(reading_date(r))).days > 300 and _month_gap(int(reading_date(r)[5:7]), d.month) <= 1]
    if len(same) >= 2:
        return statistics.median(same), 'seasonal', len(same)
    pool = earlier[:-1] if len(earlier) >= 4 else earlier
    pool = pool[-6:]
    if len(pool) >= 2:
        return statistics.median(r['ndvi'] for r in pool), 'rolling', len(pool)
    return None, None, 0


def anomaly_pct(series, idx):
    exp, kind, n = expected_value(series, idx)
    if exp is None or abs(exp) < 1e-6:
        return None, exp, kind, n
    return (series[idx]['ndvi'] - exp) / abs(exp) * 100, exp, kind, n


def _reading(r):
    if r is None:
        return None
    return {'date': reading_date(r), 'ndvi': round(r['ndvi'], 3), 'ndmi': r.get('ndmi'), 'ndre': r.get('ndre'),
            'savi': r.get('savi'), 'valid_pixels_pct': r.get('valid_pixels_pct'), 'reliability': r.get('reliability'),
            'source': r.get('source'), 'scene_ids': r.get('scene_ids'), 'observation_id': r.get('id')}


def summarize(series, boundary_status: str, other_rows_count: int = 0, today: date | None = None) -> dict:
    """series = trusted_series(...). other_rows_count = imported/manual readings that were NOT used."""
    today = today or date.today()
    n = len(series)
    cur = series[-1] if n else None
    prev = series[-2] if n >= 2 else None
    out = {'kind': 'decision', 'n_trusted': n, 'excluded_unverified_readings': other_rows_count,
           'current': _reading(cur), 'previous': _reading(prev), 'boundary_status': boundary_status,
           'provisional': boundary_status != 'approved', 'automatic_actions_allowed': False}
    reasons_ar, reasons_en = [], []

    # ---------- reliability of the latest reading / of the record
    stale = (today - date.fromisoformat(reading_date(cur))).days if cur else None
    if cur is None or n < MIN_READINGS or (stale is not None and stale > STALE_DAYS):
        if cur is None:
            reasons_ar.append('لا توجد قراءات فضائية موثوقة لهذه الحديقة بعد.'); reasons_en.append('No trusted satellite readings yet.')
        elif n < MIN_READINGS:
            reasons_ar.append(f'يوجد {n} قراءات فضائية موثوقة فقط؛ يلزم {MIN_READINGS} على الأقل للحكم.')
            reasons_en.append(f'Only {n} trusted satellite readings; at least {MIN_READINGS} are needed.')
        else:
            reasons_ar.append(f'آخر قراءة موثوقة عمرها {stale} يومًا (أقدم من {STALE_DAYS}).')
            reasons_en.append(f'Latest trusted reading is {stale} days old (>{STALE_DAYS}).')
        if other_rows_count:
            reasons_ar.append(f'توجد {other_rows_count} قراءات مستوردة/يدوية غير موثّقة المصدر لم تُستخدم في التصنيف.')
            reasons_en.append(f'{other_rows_count} imported/manual readings were not used for classification.')
        out.update(priority='insufficient', reliability='low', reasons_ar=reasons_ar, reasons_en=reasons_en,
                   action_ar='جلب قراءات Sentinel-2 أحدث' + (' واعتماد حدود الحديقة' if boundary_status != 'approved' else '') + ' قبل أي قرار.',
                   action_en='Fetch newer Sentinel-2 readings' + (' and approve the park boundary' if boundary_status != 'approved' else '') + ' before deciding.',
                   trend={'direction': 'unknown'}, indices=_indices_meaning(cur), stale_days=stale)
        _labels(out)
        return out

    # ---------- comparisons
    chg_prev = cur['ndvi'] - prev['ndvi']
    anom, exp, base_kind, base_n = anomaly_pct(series, n - 1)
    persistence = 0
    for i in range(n - 1, -1, -1):
        a, *_ = anomaly_pct(series, i)
        if a is not None and a <= DECLINE_PCT:
            persistence += 1
        else:
            break
    from .series import to_points
    pts = to_points(series[-6:])
    slope30 = theil_sen_slope(pts) * 30
    direction = 'declining' if slope30 <= -SLOPE_PER_MONTH else 'improving' if slope30 >= SLOPE_PER_MONTH else 'stable'

    # ---------- reliability level
    rel_pts = 0
    rel_pts += 1 if cur.get('reliability') == 'reliable' else 0
    rel_pts += 1 if n >= 8 else 0
    rel_pts += 1 if base_kind == 'seasonal' else 0
    rel_pts += 1 if stale <= 45 else 0
    rel_pts -= 1 if boundary_status in ('needs_review', 'rejected') else 0
    reliability = 'high' if rel_pts >= 3 else 'medium' if rel_pts >= 2 else 'low'

    # ---------- priority
    if anom is not None and anom <= STRONG_DECLINE_PCT and persistence >= 2:
        priority = 'urgent'
    elif anom is not None and anom <= -15 and persistence >= 3 and direction == 'declining':
        priority = 'urgent'
    elif (anom is not None and anom <= DECLINE_PCT) or (direction == 'declining' and persistence >= 1):
        priority = 'follow_up'
    else:
        priority = 'stable'
    if priority == 'urgent' and reliability == 'low':
        priority = 'follow_up'
        reasons_ar.append('الإشارة قوية لكن موثوقية البيانات منخفضة، فخُفّضت إلى «تحتاج متابعة» حتى تتأكد بقراءة أوضح.')
        reasons_en.append('Strong signal but low data reliability: downgraded to follow-up until confirmed.')

    month_ar = MONTHS_AR[date.fromisoformat(reading_date(cur)).month - 1]
    base_txt_ar = f"المتوقع لشهر {month_ar} من سجل نفس الموسم في الأعوام السابقة ({base_n} قراءات)" if base_kind == 'seasonal' \
        else f"وسيط آخر {base_n} قراءات (لا يوجد بعد سجل موسمي لعام سابق)"
    base_txt_en = 'same-season median of earlier years' if base_kind == 'seasonal' else f'rolling median of {base_n} readings (no prior-year season yet)'
    if anom is not None:
        reasons_ar.append(f"NDVI الحالي {cur['ndvi']:.3f} مقابل {base_txt_ar} {exp:.3f}: فرق {anom:+.1f}%.")
        reasons_en.append(f"NDVI {cur['ndvi']:.3f} vs {base_txt_en} {exp:.3f}: {anom:+.1f}%.")
    if persistence >= 2:
        reasons_ar.append(f'التراجع مستمر في آخر {persistence} قراءات متتالية.'); reasons_en.append(f'Decline persists over the last {persistence} consecutive readings.')
    elif persistence == 1:
        reasons_ar.append('التراجع ظهر في آخر قراءة فقط؛ يلزم تأكيده بالقراءة القادمة.'); reasons_en.append('Decline seen in the latest reading only; needs confirmation.')
    reasons_ar.append({'declining': f'اتجاه آخر 6 أشهر تراجع ({slope30:+.3f} شهريًا).', 'improving': f'اتجاه آخر 6 أشهر تحسّن ({slope30:+.3f} شهريًا).',
                       'stable': 'اتجاه آخر 6 أشهر مستقر.'}[direction])
    reasons_en.append(f'6-month trend {direction} ({slope30:+.3f}/month).')
    if base_kind != 'seasonal':
        reasons_ar.append('تنبيه: لا يتوفر عام سابق للمقارنة الموسمية، وقد يكون جزء من التغير موسميًا (حرارة الصيف).')
        reasons_en.append('No prior-year season available; part of the change may be seasonal.')
    if boundary_status != 'approved':
        reasons_ar.append('حدود الحديقة غير معتمدة بعد؛ النتيجة مبدئية حتى اعتمادها.')
        reasons_en.append('Park boundary is not approved yet; result is provisional.')

    actions = {
        'urgent': ('إسناد زيارة تحقق ميداني خلال 3 أيام: فحص شبكة الري وجدول التشغيل وحالة النباتات وتوثيق الصور قبل أي صيانة. '
                   'صور الأقمار تكشف التراجع ولا تحدد سببه (مرض/عطل ري/آفات)، فالتشخيص ميداني.',
                   'Assign a field inspection within 3 days: irrigation network and schedule, plant condition, photos before any work. '
                   'Satellite data shows the decline, not its cause; diagnosis must be done on site.'),
        'follow_up': ('جدولة فحص خلال أسبوعين ومراقبة القراءة الفضائية القادمة؛ إذا استمر التراجع تُرفع الأولوية إلى عاجل.',
                      'Schedule an inspection within two weeks and watch the next satellite reading; escalate if the decline continues.'),
        'stable': ('لا يلزم تدخل؛ الاستمرار في الصيانة الدورية وإعادة التقييم بعد القراءة الشهرية القادمة.',
                   'No intervention needed; continue routine maintenance and reassess after the next monthly reading.'),
    }[priority]
    allowed = priority in ('urgent', 'follow_up') and cur.get('reliability') in ('reliable', 'limited') \
        and reliability in ('high', 'medium') and boundary_status not in ('needs_review', 'rejected')
    out.update(priority=priority, reliability=reliability, reasons_ar=reasons_ar, reasons_en=reasons_en,
               action_ar=actions[0], action_en=actions[1], automatic_actions_allowed=allowed,
               change_vs_previous=round(chg_prev, 3), anomaly_pct=None if anom is None else round(anom, 1),
               expected_ndvi=None if exp is None else round(exp, 3), baseline_kind=base_kind, persistence=persistence,
               trend={'direction': direction, 'slope_per_30d': round(slope30, 4), 'window': len(pts)},
               indices=_indices_meaning(cur), stale_days=stale,
               season_note_ar=('أشهر الصيف (مايو–أكتوبر) يتراجع فيها NDVI طبيعيًا في جدة؛ المقارنة الموسمية تراعي ذلك.'
                               if date.fromisoformat(reading_date(cur)).month in (5, 6, 7, 8, 9, 10) else None))
    _labels(out)
    return out


def _labels(out):
    out['priority_ar'] = PRIORITY_AR[out['priority']]
    out['priority_en'] = PRIORITY_EN[out['priority']]
    out['reliability_ar'] = {'high': 'مرتفعة', 'medium': 'متوسطة', 'low': 'منخفضة'}[out['reliability']]


def _indices_meaning(r):
    if not r:
        return []
    res = []
    for k in ('ndvi', 'ndmi', 'ndre', 'savi'):
        v = r.get(k)
        if isinstance(v, (int, float)):
            res.append({'key': k, 'value': round(v, 3), 'formula': indices.FORMULAS[k],
                        'meaning_ar': indices.MEANINGS[k][0], 'meaning_en': indices.MEANINGS[k][1]})
    return res
