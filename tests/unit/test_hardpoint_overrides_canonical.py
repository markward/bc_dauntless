import engine.appc.hardpoint_overrides as ho
from engine.appc import hardpoint_override_writer as w


def test_file_is_canonical_emitter_output():
    with open(ho.__file__, "r", encoding="utf-8") as fh:
        source = fh.read()
    assert w.emit(w.read_models(ho)) == source


def test_apply_and_overrides_are_intact():
    assert callable(ho.apply)
    assert "galaxy" in ho.OVERRIDES
