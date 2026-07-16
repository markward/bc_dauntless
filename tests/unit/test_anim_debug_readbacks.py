"""Dev readbacks for the channel binder exist and return the documented shape.
They are dev-mode-gated at the point of USE in the live game; the bindings
themselves return data whenever called (they are read-only introspection)."""
import pytest

_h = pytest.importorskip("_dauntless_host")


def test_debug_readbacks_exist_and_handle_bad_ids():
    assert hasattr(_h, "debug_instance_anim")
    assert hasattr(_h, "debug_bone_palette_row")
    bad = _h.InstanceId()          # default id: never alive
    assert _h.debug_instance_anim(bad) == []
    assert _h.debug_bone_palette_row(bad, "Bip01 Head") is None
