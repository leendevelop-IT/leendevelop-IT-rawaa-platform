"""Selecting the readings that are allowed to drive decisions."""
from __future__ import annotations
import math
from datetime import date

TRUSTED_RELIABILITY = ('reliable', 'limited')


def _fin(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def reading_date(r) -> str:
    return (r.get('acquired_at') or r['measured_at'])[:10]


def trusted_series(rows, boundary_version=None):
    """Satellite readings only, reliable/limited quality, same boundary version, one per calendar month.

    Imported CSV, manual and demo readings are never part of this series. When two readings fall in the same
    month, the one with the higher clear-sky share wins (then the scene-level one, then the later one)."""
    keep = []
    for r in rows:
        if r.get('origin') != 'satellite' or r.get('reliability') not in TRUSTED_RELIABILITY:
            continue
        if not _fin(r.get('ndvi')):
            continue
        if boundary_version is not None and (r.get('boundary_version') or 1) != boundary_version:
            continue
        keep.append(r)
    by_month = {}
    for r in keep:
        k = reading_date(r)[:7]
        cur = by_month.get(k)
        rank = ((r.get('valid_pixels_pct') or 0), 1 if r.get('acquired_at') else 0, reading_date(r))
        if cur is None or rank > cur[0]:
            by_month[k] = (rank, r)
    out = [v[1] for _, v in sorted(by_month.items())]
    return out


def to_points(series):
    """[(date, ndvi)] sorted by date."""
    return [(date.fromisoformat(reading_date(r)), float(r['ndvi'])) for r in series]
