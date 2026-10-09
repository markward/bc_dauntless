"""No per-draw Material temporaries in native/src.

assets::Material carries a std::string (base_texture_name), so the old idiom
`idx >= 0 ? model.materials[idx] : assets::Material{}` copies the whole
Material into a temporary -- a possible heap allocation -- on every mesh draw
(a conditional with a prvalue arm yields a prvalue). Use
assets::material_or_default(model, idx), which returns a reference (pinned by
a static_assert in native/tests/assets/cpu/model_build_test.cc)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_TEMPORARY = re.compile(r":\s*(assets::)?Material\s*(\{\s*\}|\(\s*\))\s*\)?\s*;")


def test_no_conditional_with_a_material_temporary_arm():
    hits = []
    for p in sorted((ROOT / "native" / "src").rglob("*.cc")):
        text = p.read_text(errors="replace")
        for m in _TEMPORARY.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{p.relative_to(ROOT)}:{line}")
    assert not hits, "use assets::material_or_default: " + ", ".join(hits)
