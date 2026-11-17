"""Scene-level Sentinel-2 L2A statistics from Copernicus Data Space (Sentinel Hub Statistical + Catalog APIs).

For each calendar month we keep ONE real acquisition: the date whose clear-sky share inside the park polygon is
highest. Every saved reading carries the acquisition date, the Sentinel-2 product (scene) IDs from the Catalog API,
the pixel counts, the clear share, the evalscript hash and the boundary version it was computed on, so it can be
audited later. Nothing here invents values: if the API returns no usable statistics, nothing is saved.

`post_json(url, payload, headers, timeout)` is injected so the logic can be tested without network access.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone

from . import geo, indices

# New CDSE path format (March 2026); legacy /api/v1/... paths still work but will be deprecated.
STATS_URL = 'https://sh.dataspace.copernicus.eu/statistics/v1'
CATALOG_URL = 'https://sh.dataspace.copernicus.eu/catalog/v1/search'
CHUNK_DAYS = 120
RESOLUTION_DEG = 0.0001  # ≈ 10–11 m at Jeddah's latitude (native Sentinel-2 10 m bands)
SOURCE_LABEL = 'Copernicus Sentinel-2 L2A (scene)'


def _fin(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def _stat(outputs, key, field='mean'):
    v = outputs.get(key, {}).get('bands', {}).get('B0', {}).get('stats', {}).get(field)
    return v if _fin(v) else None


def stats_request(geometry, start: date, end: date):
    return {
        'input': {'bounds': {'geometry': geometry, 'properties': {'crs': 'http://www.opengis.net/def/crs/OGC/1.3/CRS84'}},
                  'data': [{'type': indices.COLLECTION, 'dataFilter': {'maxCloudCoverage': 90, 'mosaickingOrder': 'leastCC'}}]},
        'aggregation': {'timeRange': {'from': f'{start.isoformat()}T00:00:00Z', 'to': f'{end.isoformat()}T23:59:59Z'},
                        'aggregationInterval': {'of': 'P1D'}, 'evalscript': indices.EVALSCRIPT,
                        'resx': RESOLUTION_DEG, 'resy': RESOLUTION_DEG},
    }


def parse_daily(results):
    """One candidate per acquisition day with statistics; days without data are dropped."""
    out = []
    for item in (results or {}).get('data', []):
        if item.get('error'):
            continue
        o = item.get('outputs', {})
        ndvi_stats = o.get('ndvi', {}).get('bands', {}).get('B0', {}).get('stats', {})
        valid_mean = _stat(o, 'valid')
        sample = ndvi_stats.get('sampleCount')
        nodata = ndvi_stats.get('noDataCount')
        if valid_mean is None or not sample:
            continue
        # sampleCount counts pixels inside the bounds; dataMask removes those outside the polygon.
        vstats = o.get('valid', {}).get('bands', {}).get('B0', {}).get('stats', {})
        in_poly = (vstats.get('sampleCount') or 0) - (vstats.get('noDataCount') or 0)
        clear = (sample or 0) - (nodata or 0)
        if in_poly <= 0:
            continue
        valid_pct = valid_mean * 100
        ndvi = _stat(o, 'ndvi')
        if ndvi is None or clear <= 0:
            out.append({'date': item['interval']['from'][:10], 'valid_pct': round(valid_pct, 1), 'clear_pixels': max(clear, 0),
                        'pixels_in_polygon': in_poly, 'usable': False})
            continue
        out.append({
            'date': item['interval']['from'][:10], 'usable': True,
            'ndvi': ndvi, 'ndvi_std': _stat(o, 'ndvi', 'stDev'), 'ndmi': _stat(o, 'ndmi'), 'ndwi': _stat(o, 'ndwi'),
            'savi': _stat(o, 'savi'), 'ndre': _stat(o, 'ndre'), 'salinity': _stat(o, 'salinity'),
            'veg_fraction': _stat(o, 'veg'), 'ndvi_veg': _stat(o, 'ndvi_veg'),
            'valid_pct': round(valid_pct, 1), 'clear_pixels': clear, 'pixels_in_polygon': in_poly,
        })
    return out


def best_per_month(candidates):
    months = {}
    for c in candidates:
        k = c['date'][:7]
        months.setdefault(k, []).append(c)
    picked = []
    for k, cs in sorted(months.items()):
        usable = [c for c in cs if c.get('usable')]
        if not usable:
            continue
        best = max(usable, key=lambda c: (c['valid_pct'], c['clear_pixels'], c['date']))
        best = dict(best, candidates_in_month=len(cs), usable_in_month=len(usable))
        picked.append(best)
    return picked


def catalog_scenes(post_json, token, bbox, start: date, end: date, max_pages=20):
    """{'YYYY-MM-DD': [{'id':..., 'cloud_cover':...}, ...]} from the STAC Catalog API."""
    by_day = {}
    body = {'collections': [indices.COLLECTION], 'bbox': bbox,
            'datetime': f'{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z', 'limit': 100}
    for _ in range(max_pages):
        res = post_json(CATALOG_URL, body, {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, 60)
        for f in res.get('features', []):
            dt = (f.get('properties', {}).get('datetime') or '')[:10]
            if dt:
                by_day.setdefault(dt, []).append({'id': f.get('id'), 'cloud_cover': f.get('properties', {}).get('eo:cloud_cover')})
        nxt = res.get('context', {}).get('next')
        if not nxt:
            break
        body = dict(body, next=nxt)
    return by_day


def fetch_readings(post_json, token, geometry, start: date, end: date, boundary_version: int):
    """Returns (readings, report). Each reading is ready to be stored in `observations`."""
    rep = geo.validate(geometry)
    if not rep['valid']:
        raise ValueError('Invalid park polygon: ' + '; '.join(rep['errors']))
    ring = geometry['coordinates'][0]
    bbox = [min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring)]
    candidates = []
    s = start
    requests = 0
    while s <= end:
        e = min(end, s + timedelta(days=CHUNK_DAYS - 1))
        res = post_json(STATS_URL, stats_request(geometry, s, e), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, 120)
        requests += 1
        candidates.extend(parse_daily(res))
        s = e + timedelta(days=1)
    # A scene at the edge of a Sentinel-2 swath may cover only part of the park: measure clear share against the
    # full polygon (largest pixel count seen), not just the covered part.
    poly_px = max((c['pixels_in_polygon'] for c in candidates), default=0)
    for c in candidates:
        if poly_px:
            c['coverage_pct'] = round(100 * c['pixels_in_polygon'] / poly_px, 1)
            c['valid_pct'] = round(min(c['valid_pct'], 100 * c['clear_pixels'] / poly_px), 1)
    picked = best_per_month(candidates)
    try:
        scenes = catalog_scenes(post_json, token, bbox, start, end)
        catalog_error = None
    except Exception as ex:  # scene IDs are provenance, not a reason to discard the statistics
        scenes, catalog_error = {}, str(ex)[:200]
    ghash = geo.geometry_hash(geometry)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    readings = []
    for c in picked:
        sc = scenes.get(c['date'], [])
        rel = indices.classify_reliability('satellite', c['valid_pct'], c['clear_pixels'])
        prov = {
            'kind': 'scene_level', 'processing_version': indices.PROCESSING_VERSION, 'api': 'Sentinel Hub Statistical API (P1D)',
            'collection': indices.COLLECTION, 'acquisition_date': c['date'], 'scene_ids': [x['id'] for x in sc],
            'tile_cloud_cover_pct': [x['cloud_cover'] for x in sc], 'evalscript_sha256': indices.EVALSCRIPT_SHA256,
            'scl_excluded': list(indices.SCL_EXCLUDED), 'resolution_deg': RESOLUTION_DEG, 'geometry_hash': ghash,
            'boundary_version': boundary_version, 'pixels_in_polygon': c['pixels_in_polygon'], 'clear_pixels': c['clear_pixels'],
            'valid_pct': c['valid_pct'], 'scene_coverage_pct': c.get('coverage_pct'), 'candidates_in_month': c['candidates_in_month'], 'usable_in_month': c['usable_in_month'],
            'selection': 'Acquisition with the highest clear-sky share inside the polygon in this calendar month',
            'formulas': indices.FORMULAS, 'vegetation_ndvi_min': indices.VEGETATION_NDVI_MIN,
            'reliability_thresholds': {'reliable_pct': indices.RELIABLE_VALID_PCT, 'limited_pct': indices.LIMITED_VALID_PCT,
                                       'min_clear_pixels': indices.MIN_CLEAR_PIXELS},
            'requested_at': now, 'catalog_error': catalog_error,
        }
        readings.append({
            'measured_at': c['date'], 'acquired_at': c['date'], 'source': SOURCE_LABEL, 'origin': 'satellite',
            'reliability': rel, 'valid_pixels_pct': c['valid_pct'], 'clear_pixels': c['clear_pixels'],
            'scene_ids': ','.join(x['id'] for x in sc if x.get('id')) or None,
            'boundary_version': boundary_version, 'processing_version': indices.PROCESSING_VERSION,
            'provenance': json.dumps(prov, ensure_ascii=False),
            **{k: (round(c[k], 5) if _fin(c.get(k)) else None) for k in ('ndvi', 'ndmi', 'ndwi', 'savi', 'ndre', 'salinity', 'ndvi_std', 'veg_fraction', 'ndvi_veg')},
        })
    report = {'requests': requests, 'acquisition_days': len(candidates), 'usable_days': sum(1 for c in candidates if c.get('usable')),
              'months_saved': len(readings), 'reliable': sum(r['reliability'] == 'reliable' for r in readings),
              'limited': sum(r['reliability'] == 'limited' for r in readings),
              'unreliable': sum(r['reliability'] == 'unreliable' for r in readings), 'catalog_error': catalog_error,
              'boundary_area_m2': rep['area_m2']}
    return readings, report
