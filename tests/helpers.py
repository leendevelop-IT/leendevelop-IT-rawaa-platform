"""Synthetic readings for TESTS ONLY (never inserted into a real database)."""
import math
import random
from datetime import date, timedelta


def monthly(values, start=date(2024, 1, 10), origin='satellite', reliability='reliable', valid=92.0, bv=1, step=30):
    rows = []
    for i, v in enumerate(values):
        d = start + timedelta(days=step * i)
        rows.append({'id': i + 1, 'measured_at': d.isoformat(), 'acquired_at': d.isoformat(), 'ndvi': v, 'ndmi': v - 0.15,
                     'ndre': v - 0.1, 'savi': v * 0.9, 'valid_pixels_pct': valid, 'origin': origin, 'reliability': reliability,
                     'boundary_version': bv, 'source': 'test', 'is_demo': 0})
    return rows


def seasonal(n, base=0.45, amp=0.06, trend=0.0, noise=0.008, seed=1, start=date(2023, 1, 15)):
    """Jeddah-like seasonality: lower in summer (Jul–Aug), plus optional trend per month."""
    rnd = random.Random(seed)
    vals = []
    for i in range(n):
        d = start + timedelta(days=30.44 * i)
        s = amp * math.cos(2 * math.pi * (d.month - 1) / 12)  # peak in January
        vals.append(round(base + s + trend * i + rnd.gauss(0, noise), 4))
    return vals, start
