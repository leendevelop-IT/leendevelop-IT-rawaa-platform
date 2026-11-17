"""Spectral index formulas, cloud/shadow masking and the evalscript sent to Copernicus."""
import json
import math
import random
import shutil
import subprocess

import pytest

from rawaa_core import indices


def test_formulas_on_known_reflectances():
    # Healthy grass: red 0.04, NIR 0.40, SWIR1 0.20, red-edge 0.12, NIR narrow 0.38
    assert indices.ndvi(0.04, 0.40) == pytest.approx(0.36 / 0.44)
    assert indices.ndmi(0.40, 0.20) == pytest.approx(0.20 / 0.60)
    assert indices.ndre(0.12, 0.38) == pytest.approx(0.26 / 0.50)
    assert indices.savi(0.04, 0.40) == pytest.approx(1.5 * 0.36 / 0.94)
    assert indices.ndwi(0.06, 0.40) == pytest.approx(-0.34 / 0.46)
    # Bare soil has low NDVI
    assert indices.ndvi(0.25, 0.30) < 0.1
    # Zero denominators never divide by zero
    assert indices.ndvi(0, 0) == 0 and indices.savi(-0.25, -0.25) == 0


def test_masking_excludes_clouds_shadows_water_snow():
    for scl in (0, 1, 2, 3, 6, 8, 9, 10, 11):
        assert not indices.pixel_is_clear(scl)
    for scl in (4, 5, 7):
        assert indices.pixel_is_clear(scl)
    assert not indices.pixel_is_clear(4, data_mask=0)  # outside the polygon


def test_reliability_classes():
    assert indices.classify_reliability('satellite', 95, 500) == 'reliable'
    assert indices.classify_reliability('satellite', 70, 500) == 'limited'
    assert indices.classify_reliability('satellite', 40, 500) == 'unreliable'
    assert indices.classify_reliability('satellite', 99, 5) == 'unreliable'  # too few clear pixels
    assert indices.classify_reliability('imported', 99) == 'unverified'
    assert indices.classify_reliability('manual', 99) == 'unverified'
    assert indices.classify_reliability('demo', 99) == 'demo'


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_evalscript_matches_python_reference():
    """Run the exact evalscript in Node on 400 random pixels and compare with the Python reference."""
    rnd = random.Random(42)
    pixels = []
    for _ in range(400):
        pixels.append({b: round(rnd.uniform(0, 0.6), 4) for b in ('B02', 'B03', 'B04', 'B05', 'B08', 'B8A', 'B11')}
                      | {'SCL': rnd.choice(range(12)), 'dataMask': rnd.choice([1, 1, 1, 0])})
    js = indices.EVALSCRIPT + '\nconst px=' + json.dumps(pixels) + ';\nconsole.log(JSON.stringify(px.map(p=>{const r=evaluatePixel(p);const o={};for(const k in r)o[k]=Number.isNaN(r[k][0])?null:r[k][0];return o;})));'
    out = json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)
    for p, j in zip(pixels, out):
        py = indices.evaluate_pixel(p)
        for k, v in py.items():
            if isinstance(v, float) and math.isnan(v):
                assert j[k] is None, k
            else:
                assert j[k] == pytest.approx(v, abs=1e-9), (k, p)


def test_evalscript_is_versioned_and_hashed():
    assert indices.PROCESSING_VERSION in indices.EVALSCRIPT
    assert len(indices.EVALSCRIPT_SHA256) == 64
    assert '[0,1,2,3,6,8,9,10,11]' in indices.EVALSCRIPT.replace(' ', '')
