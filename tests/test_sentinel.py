"""Scene-level Sentinel-2 ingestion against a recorded-format fake of the Copernicus Statistical/Catalog APIs."""
import json
from datetime import date

import pytest

from rawaa_core import indices, sentinel

PARK = {'type': 'Polygon', 'coordinates': [[[39.181215, 21.590235], [39.181659, 21.589014], [39.185624, 21.590207],
                                            [39.18501, 21.592798], [39.183229, 21.59248], [39.181215, 21.590235]]]}


def stat(mean, sample=2000, nodata=800, std=0.05):
    return {'bands': {'B0': {'stats': {'min': 0, 'max': 1, 'mean': mean, 'stDev': std, 'sampleCount': sample, 'noDataCount': nodata}}}}


def day(d, ndvi, valid_share, in_poly=1200, sample=2000):
    clear = int(in_poly * valid_share)
    nodata_idx = sample - clear
    return {'interval': {'from': f'{d}T00:00:00Z', 'to': f'{d}T23:59:59Z'},
            'outputs': {'ndvi': stat(ndvi, sample, nodata_idx), 'ndmi': stat(ndvi - 0.2, sample, nodata_idx),
                        'ndwi': stat(-ndvi, sample, nodata_idx), 'savi': stat(ndvi * 0.8, sample, nodata_idx),
                        'ndre': stat(ndvi - 0.15, sample, nodata_idx), 'salinity': stat(0.1, sample, nodata_idx),
                        'veg': stat(0.6, sample, nodata_idx), 'ndvi_veg': stat(ndvi + 0.1, sample, nodata_idx),
                        'valid': stat(valid_share, sample, sample - in_poly)}}


class FakeCopernicus:
    def __init__(self, days, features=None, fail_catalog=False):
        self.days, self.features, self.fail_catalog, self.calls = days, features or [], fail_catalog, []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append((url, payload))
        assert headers['Authorization'] == 'Bearer TOKEN'
        if url == sentinel.STATS_URL:
            assert payload['aggregation']['aggregationInterval']['of'] == 'P1D'
            assert payload['aggregation']['evalscript'] == indices.EVALSCRIPT
            t0 = payload['aggregation']['timeRange']['from'][:10]; t1 = payload['aggregation']['timeRange']['to'][:10]
            return {'data': [d for d in self.days if t0 <= d['interval']['from'][:10] <= t1]}
        if url == sentinel.CATALOG_URL:
            if self.fail_catalog:
                raise RuntimeError('catalog down')
            return {'features': self.features, 'context': {}}
        raise AssertionError(url)


def test_best_clear_acquisition_per_month_with_scene_ids():
    days = [day('2025-03-04', 0.41, 0.55), day('2025-03-14', 0.44, 0.97), day('2025-03-24', 0.20, 0.30),
            day('2025-04-08', 0.43, 0.72), day('2025-05-03', 0.10, 0.10)]
    feats = [{'id': 'S2B_MSIL2A_20250314T073619_N0511_R092_T37QDD_20250314T094210', 'properties': {'datetime': '2025-03-14T07:46:00Z', 'eo:cloud_cover': 3.2}}]
    fake = FakeCopernicus(days, feats)
    readings, rep = sentinel.fetch_readings(fake, 'TOKEN', PARK, date(2025, 3, 1), date(2025, 5, 31), boundary_version=3)
    assert [r['measured_at'] for r in readings] == ['2025-03-14', '2025-04-08', '2025-05-03']
    mar, apr, may = readings
    assert mar['ndvi'] == 0.44 and mar['reliability'] == 'reliable' and mar['scene_ids'].startswith('S2B_MSIL2A_20250314')
    assert apr['reliability'] == 'limited' and may['reliability'] == 'unreliable'
    prov = json.loads(mar['provenance'])
    assert prov['evalscript_sha256'] == indices.EVALSCRIPT_SHA256 and prov['boundary_version'] == 3
    assert prov['candidates_in_month'] == 3 and prov['scl_excluded'] == list(indices.SCL_EXCLUDED)
    assert mar['origin'] == 'satellite' and mar['veg_fraction'] == 0.6
    assert rep['months_saved'] == 3 and rep['reliable'] == 1


def test_partial_swath_coverage_lowers_clear_share():
    days = [day('2025-06-05', 0.4, 0.95, in_poly=1200), day('2025-06-10', 0.42, 1.0, in_poly=500)]
    readings, _ = sentinel.fetch_readings(FakeCopernicus(days), 'TOKEN', PARK, date(2025, 6, 1), date(2025, 6, 30), 1)
    # The 10 June scene covered only 500/1200 park pixels → 41.7 % effective clear share; 5 June wins.
    assert readings[0]['measured_at'] == '2025-06-05'


def test_catalog_failure_keeps_statistics_and_records_error():
    readings, rep = sentinel.fetch_readings(FakeCopernicus([day('2025-03-14', 0.44, 0.97)], fail_catalog=True), 'TOKEN', PARK,
                                            date(2025, 3, 1), date(2025, 3, 31), 1)
    assert len(readings) == 1 and readings[0]['scene_ids'] is None and 'catalog down' in rep['catalog_error']


def test_no_data_saves_nothing_and_invalid_polygon_rejected():
    readings, rep = sentinel.fetch_readings(FakeCopernicus([]), 'TOKEN', PARK, date(2025, 1, 1), date(2025, 12, 31), 1)
    assert readings == [] and rep['requests'] == 4  # 365 days in 120-day chunks
    with pytest.raises(ValueError):
        sentinel.fetch_readings(FakeCopernicus([]), 'TOKEN', {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
                                date(2025, 1, 1), date(2025, 2, 1), 1)
