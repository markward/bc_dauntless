"""Posed ships run natively and bit-identically to the Python in a real
fight (native combat posed parts, Task 5; spec
docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md §5;
plan docs/superpowers/plans/2026-11-01-native-combat-posed-parts.md).

Two fresh loads of combat_stress -- the Python reference
(``DAUNTLESS_NATIVE_COMBAT=0``) and native (``=1``: K1 fire control, K2
beams, K3 torpedoes and K4 under them) -- grown into the posed fight
tests/helpers/posed_fight.py describes: two scripted Birds of Prey, one
settled in cruise and one forever mid-transition (and a Galaxy whose
phaser banks ride parts forced by name -- one of them identity only to
`is_identity`'s 1e-9 -- and whose Phasers system shares a bank's point on
another part), fired at with phasers,
pulse and torpedoes by Federation ships locking their subsystems, firing
their own cannons and tubes back, the player in Manual Aim on a posed wing,
two physical-parent changes and a preview overlay bumping the part-map
generation, and a wing severed by a weapon hit in the middle of a step.

Headless: no render instance, so every beam lands on its aim point and every
torpedo hit on its fallback tier, every ship at combat_stress's nominal 4 GU.
The Bird of Prey's per-part boxes are tests/conftest.py's (the derived boxes
of its model), so the box rule attributes points as it does live.

Per tick the arms must be equal in everything k3_fight's Recorder records
plus every weapon's fire-control state, every posed ship's poses, every one
of its mount positions and every one of its emitters' arc direction, arc
test and strip emit point (Python's; the native arm asks the kernel's
`mount_position`, `_emitter_forward_world`, `_emitter_in_arc` and
`strip_emit_position` for each, which must give the same bits). The native arm
must show no posed hand-back at all -- posed_ship / posed_target retired at
0, part_stale 0 (every slot resolved at the step boundaries) -- and every
posed branch run natively: a posed ship walked, a Fire aimed at a posed
target's offset, a posed ship's banks beamed, a lock on a posed ship, a
torpedo steered at one. A picked spot (a Manual Aim pick, a re-targeted
stored offset) is a plain body point in both arms (fire control native
only, M5): no hand-back of any kernel for it.
"""
import time

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import native_combat as nc
from tests.helpers import bc_assets
from tests.helpers.posed_fight import both, check_posed, report

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_set_part_slot"),
    reason="native posed-parts bindings not built")

SEED = 20261105


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()


@pytest.mark.parametrize("ticks_per_frame", (1, 4))
def test_posed_fight_matches_python(monkeypatch, ticks_per_frame):
    t0 = time.perf_counter()
    ref, nat = both(monkeypatch, ticks_per_frame, SEED)
    report("posed headless differential", ticks_per_frame,
           time.perf_counter() - t0, ref, nat)
    check_posed(ref, nat)
