"""Turn the decision + forecast into a monitoring schedule entry (pure function, no database)."""
from __future__ import annotations
from datetime import date, timedelta

S2_REVISIT_DAYS = 5   # Sentinel-2A/2B/2C combined revisit over Jeddah

BASE_DAYS = {'urgent': 3, 'follow_up': 14, 'stable': 30, 'insufficient': 7}
SCHEDULE_PRIORITY = {'urgent': 'high', 'follow_up': 'medium', 'stable': 'low', 'insufficient': 'low'}


def plan(decision: dict, fc: dict | None, today: date | None = None) -> dict:
    today = today or date.today()
    p = decision['priority']
    days = BASE_DAYS[p]
    why_ar, why_en = [], []
    why_ar.append({'urgent': 'تراجع مستمر وموثوق يستدعي زيارة عاجلة.', 'follow_up': 'إشارة تراجع تحتاج تأكيدًا ميدانيًا.',
                   'stable': 'الحالة مستقرة: فحص دوري شهري.', 'insufficient': 'البيانات غير كافية: مراجعة البيانات وحدود الحديقة.'}[p])
    why_en.append({'urgent': 'Persistent, reliable decline: urgent visit.', 'follow_up': 'Decline signal needs field confirmation.',
                   'stable': 'Stable: routine monthly check.', 'insufficient': 'Insufficient data: review data and boundary.'}[p])
    prob = (fc or {}).get('decline_probability_pct') if (fc or {}).get('available') else None
    if prob is not None:
        if p == 'follow_up' and prob >= 60:
            days = 7
            why_ar.append(f'التوقع يرجّح استمرار التراجع ({prob}%): قُدّم الموعد إلى أسبوع.')
            why_en.append(f'Forecast favours continued decline ({prob}%): moved to one week.')
        elif p == 'stable' and prob >= 50:
            days = 14
            why_ar.append(f'الحالة مستقرة الآن لكن التوقع يشير لاحتمال تراجع {prob}%: فحص وقائي خلال أسبوعين.')
            why_en.append(f'Stable now but forecast shows {prob}% decline risk: preventive check in two weeks.')
    if decision.get('provisional') and p != 'insufficient':
        why_ar.append('الحدود غير معتمدة: يُستحسن اعتمادها في نفس الزيارة.')
        why_en.append('Boundary not approved: confirm it during the visit.')
    next_check = today + timedelta(days=days)
    # Reassess once at least two Sentinel-2 passes after the visit are likely to have produced a clear reading.
    reassess = next_check + timedelta(days=max(10, 2 * S2_REVISIT_DAYS))
    basis = (decision.get('current') or {}).get('date') or 'none'
    return {'next_check': next_check.isoformat(), 'reassess_at': reassess.isoformat(), 'priority': SCHEDULE_PRIORITY[p],
            'decision_priority': p, 'reason_ar': ' '.join(why_ar), 'reason_en': ' '.join(why_en), 'basis_date': basis,
            'cycle_key': f'{basis}:{p}'}
