"""Developer Options -> "Hull damage": the value-cycling rows' model
(engine/dev_hull_damage_tuning.py; spec 2026-10-22-layered-damage-p4-finish
§2.5).

Each row cycles 5 presets around its default and writes through the SAME
path its owner already uses: the plating rows through plating_dials (so the
/ L O dial group and the row stay in sync), the Python knobs straight onto
hull_wear / death_cascade (read at use), the rooms near distance through the
renderer setter. "Reset hull damage dials" restores every row.
"""
import pytest

from engine import dev_hull_damage_tuning as tuning
from engine import dev_mode, renderer
from engine.appc import death_cascade, hull_wear, plating_dials

PLATING_ROWS = {
    "hull_strip_wear": "strip_wear",
    "hull_breach_wear": "breach_wear",
    "hull_deck_break_wear": "deck_break_wear",
    "hull_toughness_spread": "toughness_spread",
    "hull_breach_lumps": "breach_lumps",
    "hull_soot": "soot",
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    pushed = []
    monkeypatch.setattr(renderer, "set_plating_params",
                        lambda params: pushed.append(list(params)))
    near = []
    monkeypatch.setattr(renderer, "set_interior_near_gu", near.append,
                        raising=False)
    plating_dials.reset()
    tuning.reset()
    pushed.clear()
    near.clear()
    yield pushed, near
    tuning.reset()
    plating_dials.reset()


def _row(key):
    return next(r for r in tuning.rows() if r["key"] == key)


def test_rows_in_order_with_the_brief_labels():
    keys = [r["key"] for r in tuning.rows()]
    assert keys == [
        "hull_strip_wear", "hull_breach_wear", "hull_deck_break_wear",
        "hull_toughness_spread", "hull_breach_lumps", "hull_soot",
        "hull_phaser_rate", "hull_collision_min", "hull_big_blast_chance",
        "hull_interior", "hull_near_gu", "hull_reset",
    ]
    assert _row("hull_reset")["label"] == "Reset hull damage dials"
    assert _row("hull_reset")["kind"] == "action"
    assert _row("hull_interior")["kind"] == "toggle"
    assert _row("hull_strip_wear")["kind"] == "value"


def test_debug_only_dials_are_not_rows():
    labels = " ".join(r["key"] for r in tuning.rows())
    for name in ("force_program", "debug", "enabled"):
        assert name not in labels


@pytest.mark.parametrize("key,dial", sorted(PLATING_ROWS.items()))
def test_plating_presets_are_default_times_the_five_factors(key, dial):
    d = plating_dials.defaults()[dial]
    assert tuning.presets(key) == tuple(
        round(d * f, 4) for f in (0.5, 0.75, 1.0, 1.5, 2.0))


def test_python_knob_and_near_presets():
    assert tuning.presets("hull_phaser_rate") == (0.5, 0.75, 1.0, 1.5, 2.0)
    assert tuning.presets("hull_collision_min") == (50.0, 75.0, 100.0, 150.0, 200.0)
    assert tuning.presets("hull_big_blast_chance") == (0.05, 0.075, 0.1, 0.15, 0.2)
    assert tuning.presets("hull_near_gu") == (10.0, 15.0, 20.0, 30.0, 40.0)


def test_cycling_a_plating_row_pushes_through_the_dial_path(_clean):
    pushed, _ = _clean
    assert tuning.cycle("hull_breach_wear") == 6.75
    assert plating_dials.current()["breach_wear"] == 6.75
    slot = plating_dials.DIAL_ORDER.index("breach_wear")
    assert pushed[-1][slot] == 6.75
    assert tuning.cycle("hull_breach_wear") == 9.0
    assert tuning.cycle("hull_breach_wear") == 2.25    # wraps
    assert _row("hull_breach_wear")["value"] == "2.25"


def test_a_dial_step_and_the_row_stay_in_sync():
    tuning.cycle("hull_strip_wear")                     # 0.5 -> 0.75
    plating_dials._step("strip_wear", +1)               # dial keys: 0.85
    assert _row("hull_strip_wear")["value"] == "0.85"
    # off-preset: the next press goes to the first preset above it
    assert tuning.cycle("hull_strip_wear") == 1.0


def test_python_knobs_write_the_module_values():
    assert tuning.cycle("hull_phaser_rate") == 1.5
    assert hull_wear.PHASER_RATE == 1.5
    assert tuning.cycle("hull_collision_min") == 150.0
    assert hull_wear.COLLISION_MIN_HULL_DAMAGE == 150.0
    assert _row("hull_collision_min")["value"] == "150 hull"


def test_big_blast_chance_retunes_the_tiers_and_keeps_them_summing_to_one():
    assert tuning.cycle("hull_big_blast_chance") == 0.15
    tiers = death_cascade.BLAST_SIZE_TIERS
    assert tiers[-1] == (0.15, 1.8, 2.6)
    assert tiers[1] == (0.30, 1.0, 1.6)
    assert tiers[0][1:] == (0.7, 1.0)
    assert sum(p for p, _lo, _hi in tiers) == pytest.approx(1.0)
    assert _row("hull_big_blast_chance")["value"] == "15%"


def test_interior_toggle_flips_the_plating_dial(_clean):
    pushed, _ = _clean
    assert tuning.toggle("hull_interior") is False
    assert plating_dials.current()["interior"] == 0.0
    assert pushed[-1][plating_dials.DIAL_ORDER.index("interior")] == 0.0
    assert _row("hull_interior")["value"] is False
    assert tuning.toggle("hull_interior") is True
    assert plating_dials.current()["interior"] == 1.0


def test_near_distance_calls_the_renderer_setter(_clean, monkeypatch):
    _, near = _clean
    monkeypatch.setattr(renderer, "interior_near_gu", lambda: near[-1],
                        raising=False)
    assert tuning.cycle("hull_near_gu") == 30.0
    assert near == [30.0]
    assert _row("hull_near_gu")["value"] == "30 GU"


def test_a_host_without_the_near_binding_does_not_crash(monkeypatch):
    def _missing(v):
        raise AttributeError("set_interior_near_gu")
    monkeypatch.setattr(renderer, "set_interior_near_gu", _missing,
                        raising=False)
    monkeypatch.setattr(renderer, "interior_near_gu", _missing, raising=False)
    tuning.cycle("hull_near_gu")
    assert _row("hull_near_gu")["value"] == "20 GU"


def test_reset_restores_every_row(_clean):
    pushed, near = _clean
    for r in tuning.rows():
        if r["kind"] == "value":
            tuning.cycle(r["key"])
    tuning.toggle("hull_interior")
    tuning.reset()
    d = plating_dials.defaults()
    cur = plating_dials.current()
    for dial in PLATING_ROWS.values():
        assert cur[dial] == d[dial]
    assert cur["interior"] == d["interior"]
    assert pushed[-1] == plating_dials.params()
    assert hull_wear.PHASER_RATE == hull_wear.DEFAULT_PHASER_RATE == 1.0
    assert (hull_wear.COLLISION_MIN_HULL_DAMAGE
            == hull_wear.DEFAULT_COLLISION_MIN_HULL_DAMAGE == 100.0)
    assert death_cascade.BLAST_SIZE_TIERS == death_cascade.DEFAULT_BLAST_SIZE_TIERS
    assert near[-1] == tuning.DEFAULT_NEAR_GU == 20.0


def test_reset_leaves_debug_dials_alone():
    plating_dials.set_value("force_program", 1.0)
    tuning.reset()
    assert plating_dials.current()["force_program"] == 1.0


def test_dispatch_routes_actions_and_toggles():
    assert tuning.dispatch("action:hull_soot") is True
    assert plating_dials.current()["soot"] == 1.125
    assert tuning.dispatch("toggle:hull_interior") is True
    assert plating_dials.current()["interior"] == 0.0
    assert tuning.dispatch("action:hull_reset") is True
    assert plating_dials.current()["soot"] == 0.75
    assert tuning.dispatch("action:hull_bogus") is False
    assert tuning.dispatch("action:quick_repair") is False


def test_nothing_outside_developer_mode(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    assert tuning.rows() == []
    assert tuning.dispatch("action:hull_soot") is False
    assert plating_dials.current()["soot"] == 0.75
