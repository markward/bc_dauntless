"""The clump fbm in system_nebula.frag must stay the function gameplay reads
(engine/appc/nebula_density.py mirrors nebula_volumetric.frag)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHADERS = ROOT / "native" / "src" / "renderer" / "shaders"


def _block(text):
    m = re.search(r"float hash13.*?float fbm\(vec3 p\)\{.*?\}", text, re.S)
    assert m, "fbm block not found"
    return re.sub(r"\s+", " ", m.group(0))


def test_system_nebula_fbm_matches_the_volumetric_fbm():
    a = _block((SHADERS / "nebula_volumetric.frag").read_text())
    b = _block((SHADERS / "system_nebula.frag").read_text())
    assert a == b
