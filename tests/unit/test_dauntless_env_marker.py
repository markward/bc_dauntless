"""App.DAUNTLESS_ENV: the versioned marker emitted hardpoint code guards on
(spec 2026-09-26 section 4.3)."""
import App

from engine.appc import hardpoint_override_writer as w


def test_marker_is_a_real_int_not_a_stub():
    # The App module __getattr__ answers ANY undefined name with a stub, so
    # hasattr alone proves nothing here: the value must be a genuine int.
    assert "DAUNTLESS_ENV" in vars(App)
    assert type(App.DAUNTLESS_ENV) is int
    assert App.DAUNTLESS_ENV >= 1


def test_env_guard_text():
    assert w.env_guard() == 'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:'
    assert w.env_guard(2).endswith(">= 2:")


def test_part_block_uses_the_marker_guard():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [("SetTransitionSeconds", (2.0,))])
    text = w.emit(models)
    assert '    ' + w.env_guard() in text
    assert 'hasattr(App, "ArticulatedPartProperty_Create")' not in text


def test_part_round_trips_through_read_models_with_the_new_guard():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [("SetTransitionSeconds", (2.0,))])
    again = w.read_models_from_source(w.emit(models))
    assert again["birdofprey"]["__parts__"]["left wing"] == [("SetTransitionSeconds", (2.0,))]


class _StockApp:
    """Stock BC's App: no marker, no ArticulatedPartProperty_Create."""
    class g_kModelPropertyManager:
        @staticmethod
        def RegisterLocalTemplate(p):
            raise AssertionError("stock BC must never register a part")


def test_stock_bc_skips_the_part_block():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [("SetTransitionSeconds", (2.0,))])
    ns = {}
    exec(w.emit(models), ns)
    import sys
    prev = sys.modules.get("App")
    sys.modules["App"] = _StockApp
    try:
        ns["_birdofprey"](lambda name: None)     # must not raise
    finally:
        sys.modules["App"] = prev
