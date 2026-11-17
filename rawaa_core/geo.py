"""Park boundary checks: GeoJSON validity, self-intersection, geodesic area and perimeter.

Area uses the spherical-excess formula on the WGS84 mean-radius sphere (same method as Turf.js / geojson-area);
at park scale the difference from an ellipsoidal area is well under 0.5 %.
"""
from __future__ import annotations
import hashlib
import json
import math

R = 6371008.8  # mean Earth radius (m)
JEDDAH_REGION = (38.95, 21.15, 39.45, 21.95)  # lon/lat box used for the plausibility check
MIN_PARK_M2 = 300.0
MAX_PARK_M2 = 5_000_000.0

BOUNDARY_STATUSES = ('approved', 'pending_approval', 'needs_review', 'rejected')


def _ring_area(ring):
    total = 0.0
    n = len(ring)
    if n < 3:
        return 0.0
    for i in range(n - 1):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return total * R * R / 2.0


def area_m2(geom) -> float:
    rings = geom['coordinates']
    a = abs(_ring_area(rings[0]))
    for hole in rings[1:]:
        a -= abs(_ring_area(hole))
    return max(0.0, a)


def haversine_m(p, q):
    lon1, lat1, lon2, lat2 = map(math.radians, (p[0], p[1], q[0], q[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def perimeter_m(geom) -> float:
    ring = geom['coordinates'][0]
    return sum(haversine_m(ring[i], ring[i + 1]) for i in range(len(ring) - 1))


def centroid(geom):
    ring = geom['coordinates'][0][:-1]
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def _orient(a, b, c):
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return 0 if abs(v) < 1e-18 else (1 if v > 0 else -1)


def _on_seg(a, b, c):
    return min(a[0], b[0]) - 1e-15 <= c[0] <= max(a[0], b[0]) + 1e-15 and min(a[1], b[1]) - 1e-15 <= c[1] <= max(a[1], b[1]) + 1e-15


def _segments_cross(p1, p2, p3, p4):
    o1, o2, o3, o4 = _orient(p1, p2, p3), _orient(p1, p2, p4), _orient(p3, p4, p1), _orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_seg(p1, p2, p3): return True
    if o2 == 0 and _on_seg(p1, p2, p4): return True
    if o3 == 0 and _on_seg(p3, p4, p1): return True
    if o4 == 0 and _on_seg(p3, p4, p2): return True
    return False


def self_intersections(ring):
    """Return pairs of non-adjacent edges that intersect (ring must be closed)."""
    edges = [(ring[i], ring[i + 1]) for i in range(len(ring) - 1)]
    n = len(edges)
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges share a vertex
            if _segments_cross(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                out.append((i, j))
                if len(out) >= 10:
                    return out
    return out


def looks_like_placeholder(ring) -> bool:
    """A 5-point axis-aligned rectangle is almost always a pin-based placeholder, not a surveyed outline."""
    if len(ring) != 5:
        return False
    xs = {round(p[0], 7) for p in ring}
    ys = {round(p[1], 7) for p in ring}
    return len(xs) == 2 and len(ys) == 2


def geometry_hash(geom) -> str:
    return hashlib.sha256(json.dumps(geom, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]


def validate(geom) -> dict:
    """Full boundary report. `valid` is False on any hard error; warnings never block."""
    errors, warnings = [], []
    if not isinstance(geom, dict) or geom.get('type') != 'Polygon':
        return {'valid': False, 'errors': ['Geometry must be a GeoJSON Polygon'], 'warnings': []}
    rings = geom.get('coordinates')
    if not isinstance(rings, list) or not rings:
        return {'valid': False, 'errors': ['Polygon has no rings'], 'warnings': []}
    for k, ring in enumerate(rings):
        if not isinstance(ring, list) or len(ring) < 4:
            errors.append(f'Ring {k} needs at least 4 positions'); continue
        try:
            pts = [(float(p[0]), float(p[1])) for p in ring]
        except (TypeError, ValueError, IndexError):
            errors.append(f'Ring {k} has non-numeric coordinates'); continue
        if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in pts):
            errors.append(f'Ring {k} has coordinates out of range (expected [lon, lat])')
        if pts[0] != pts[-1]:
            errors.append(f'Ring {k} is not closed')
        dups = sum(1 for i in range(len(pts) - 1) if pts[i] == pts[i + 1])
        if dups:
            warnings.append(f'Ring {k} has {dups} repeated consecutive vertices')
        if not errors and self_intersections(pts):
            errors.append(f'Ring {k} self-intersects')
    if errors:
        return {'valid': False, 'errors': errors, 'warnings': warnings}
    a = area_m2(geom)
    p = perimeter_m(geom)
    cx, cy = centroid(geom)
    if a <= 0:
        errors.append('Polygon has zero area')
    elif a < MIN_PARK_M2:
        warnings.append(f'Very small area ({a:.0f} m²): fewer than ~{int(a / 100)} Sentinel-2 pixels')
    elif a > MAX_PARK_M2:
        warnings.append(f'Very large area ({a / 1e6:.2f} km²) for a single park')
    x0, y0, x1, y1 = JEDDAH_REGION
    if not (x0 <= cx <= x1 and y0 <= cy <= y1):
        warnings.append('Centroid is outside the Jeddah region; check the coordinate order [lon, lat]')
    placeholder = looks_like_placeholder(rings[0])
    if placeholder:
        warnings.append('Boundary is an axis-aligned rectangle (likely a placeholder around a map pin); it may include streets and buildings')
    return {'valid': not errors, 'errors': errors, 'warnings': warnings,
            'area_m2': round(a, 1), 'area_ha': round(a / 10000, 3), 'perimeter_m': round(p, 1),
            'centroid': [round(cx, 6), round(cy, 6)], 'vertices': len(rings[0]) - 1,
            'placeholder': placeholder, 's2_pixels_10m': int(a / 100), 'hash': geometry_hash(geom)}


def initial_status(source: str, placeholder: bool) -> str:
    """Status for an un-reviewed boundary: an OSM-traced outline is awaiting approval, a placeholder needs review."""
    if placeholder or not source or source.lower().startswith('approx'):
        return 'needs_review'
    return 'pending_approval'
