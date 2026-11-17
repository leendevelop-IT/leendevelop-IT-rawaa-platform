"""Park boundary validity and area."""
import pytest

from rawaa_core import geo


def square(lon, lat, dlon, dlat):
    return {'type': 'Polygon', 'coordinates': [[[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]]}


def test_area_of_known_rectangle():
    # 0.01° x 0.01° at the equator ≈ 1113.2 m x 1105.7 m ≈ 1.2308 km² (spherical)
    a = geo.area_m2(square(0, 0, 0.01, 0.01))
    assert a == pytest.approx(1_236_000, rel=0.01)
    # Same rectangle at Jeddah latitude shrinks with cos(21.5°)
    b = geo.area_m2(square(39.17, 21.5, 0.01, 0.01))
    assert b / a == pytest.approx(0.930, rel=0.01)


def test_hole_is_subtracted():
    g = square(39.17, 21.5, 0.01, 0.01)
    hole = [[39.172, 21.502], [39.172, 21.504], [39.174, 21.504], [39.174, 21.502], [39.172, 21.502]]
    g2 = {'type': 'Polygon', 'coordinates': [g['coordinates'][0], hole]}
    assert geo.area_m2(g2) == pytest.approx(geo.area_m2(g) * 0.96, rel=0.01)


def test_self_intersection_detected():
    bowtie = {'type': 'Polygon', 'coordinates': [[[39.17, 21.5], [39.18, 21.51], [39.18, 21.5], [39.17, 21.51], [39.17, 21.5]]]}
    rep = geo.validate(bowtie)
    assert not rep['valid'] and any('self-intersects' in e for e in rep['errors'])


def test_open_ring_and_swapped_coordinates():
    open_ring = {'type': 'Polygon', 'coordinates': [[[39.17, 21.5], [39.18, 21.5], [39.18, 21.51], [39.17, 21.51]]]}
    assert not geo.validate(open_ring)['valid']
    swapped = square(21.5, 39.17, 0.002, 0.002)  # [lat, lon] by mistake
    rep = geo.validate(swapped)
    assert rep['valid'] and any('outside the Jeddah region' in w for w in rep['warnings'])


def test_placeholder_rectangle_flagged():
    rep = geo.validate(square(39.17, 21.5, 0.002, 0.00136))
    assert rep['placeholder'] and geo.initial_status('approx', True) == 'needs_review'
    assert geo.initial_status('OSM way 123', False) == 'pending_approval'


def test_all_registered_parks_are_valid(core):
    """Every real site: valid polygon, plausible area, OSM outlines not flagged as placeholders."""
    report = []
    for en, ar, cat, _ra, _re, geom, src in core.REAL_SITES:
        rep = geo.validate(geom)
        assert rep['valid'], (en, rep['errors'])
        assert 5_000 < rep['area_m2'] < 500_000, (en, rep['area_m2'])
        assert rep['placeholder'] == (src == 'approx'), en
        report.append((en, src, rep['area_m2'], rep['s2_pixels_10m']))
    # At least the OSM-traced parks have enough Sentinel-2 pixels for statistics.
    assert all(px >= 200 for _en, src, _a, px in report if src.startswith('OSM'))
