"""App.SetClass_MakeDisplayName — Systems.TGL lookup with a formatted fallback."""
import pytest

import App
from engine.appc.sets import SetClass_MakeDisplayName, _systems_tgl


# --- formatted fallback (region names with no Systems.TGL entry) ------------

def test_fallback_spaces_trailing_digits():
    # Planet regions with no localized name fall back to formatting.
    assert SetClass_MakeDisplayName("Albirea1") == "Albirea 1"
    assert SetClass_MakeDisplayName("OmegaDraconis3") == "OmegaDraconis 3"


def test_fallback_no_digits_unchanged():
    assert SetClass_MakeDisplayName("Zznotasystem") == "Zznotasystem"


def test_always_returns_str():
    assert isinstance(SetClass_MakeDisplayName(12345), str)


def test_exposed_on_App_as_real_callable():
    # Not a _NamedStub fallthrough; uses the deterministic fallback path.
    out = App.SetClass_MakeDisplayName("Albirea1")
    assert out == "Albirea 1"
    assert isinstance(out, str)


# --- authentic TGL names (when Systems.TGL is available) --------------------

def test_tgl_named_regions_when_available():
    db = _systems_tgl()
    if db is None or not db.HasString("Vesuvi4"):
        pytest.skip("Systems.TGL not available (game/ not installed)")
    assert SetClass_MakeDisplayName("Vesuvi4") == "Vesuvi Dust Cloud"
    assert SetClass_MakeDisplayName("Vesuvi6") == "Haven Colony"
    assert SetClass_MakeDisplayName("Multi1") == "Asteroids"
