"""Bible §15 — nebulae (E1, `docs/results/nebula/*`).

A `SetupDamage(hull, shields)` nebula raises ET_ENVIRONMENT_DAMAGE 16 times a
second on every ship inside it, but the only DAMAGE is one hit — to a ship
that is already inside when the nebula is created — of `shields / 16` to every
face if the shields are up (discarded when ≤ 100 per face), else `hull / 16`
to the hull.  A ship that flies into an existing nebula takes nothing.  Not at
easy difficulty.  The stock Vesuvi 4 cloud therefore never damages the player,
who warps in after the set is built.
"""
import pytest

from tests.oracle.conftest import FRONT

MEDIUM, EASY = 1, 0


def _set_difficulty(level):
    from engine.core import game
    game.Game_SetDifficulty(level)


@pytest.fixture(autouse=True)
def _medium_difficulty():
    from engine.core import game
    before = game.Game_GetDifficulty()
    game.Game_SetDifficulty(MEDIUM)
    yield
    game.Game_SetDifficulty(before)


def test_e1_creation_hit_to_every_shield_face_once(oracle):
    """E1 — `n5000`: a parked Galaxy with shields up inside a
    SetupDamage(5000, 5000) nebula at creation loses 312.5 on every face at
    the first tick and nothing more over 5 s (regen climbs back); the hull
    is never touched."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    faces_before = s.faces()
    s.build_nebula(radius=1500.0, hull=5000.0, shields=5000.0)
    s.step(2)
    for i in range(6):
        assert faces_before[i] - s.face(i) == pytest.approx(312.5, abs=6.0), i   # ± a regen step
    assert s.hull_damage() == 0.0
    low = s.faces()
    s.run(5.0)
    for i in range(6):
        assert s.face(i) >= low[i] - 0.5, i          # only regen from here
    assert s.hull_damage() == 0.0


def test_e1_creation_hit_to_hull_when_shields_are_down(oracle):
    """E1 — `n5000_ns`: shields down ⇒ `hull / 16` = 312.5 to the hull, once."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    s.zero_shields()
    s.tgt.SetAlertLevel(s.App.ShipClass.GREEN_ALERT)   # shields lowered
    s.build_nebula(radius=1500.0, hull=5000.0, shields=5000.0)
    s.step(2)
    assert s.hull_damage() == pytest.approx(312.5, abs=1.0)
    s.run(3.0)
    assert s.hull_damage() <= 312.5 + 0.5              # repair only


@pytest.mark.parametrize("shields_arg, per_face", [(1600.0, 0.0), (1700.0, 106.25)])
def test_e1_shield_hit_at_or_below_100_per_face_is_discarded(oracle, shields_arg, per_face):
    """E1 — `n1600` / `n1700`: 1600/16 = 100.0 does nothing; 1700/16 = 106.25
    lands.  The hull has no such threshold."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    before = s.face(FRONT)
    s.build_nebula(radius=1500.0, hull=5000.0, shields=shields_arg)
    s.step(2)
    assert before - s.face(FRONT) == pytest.approx(per_face, abs=6.0)   # ± a regen step


def test_e1_entering_an_existing_nebula_takes_nothing(oracle):
    """E1 — `n_enter*`: a ship that flies into a nebula built elsewhere —
    even SetupDamage(5000, 5000) with shields down — is not damaged."""
    s = oracle(attacker="KessokHeavy", range_gu=2000)     # attacker off the path
    s.zero_shields()
    s.tgt.SetAlertLevel(s.App.ShipClass.GREEN_ALERT)
    # Nebula 600 GU ahead of the target, radius 300: nobody inside at creation.
    s.build_nebula(radius=300.0, hull=5000.0, shields=5000.0, centre=(0.0, 600.0, 0.0))
    s.step(2)
    assert s.hull_damage() == 0.0
    s.full_impulse(ship=s.tgt)                          # 6.3 GU/s toward it
    s.run(90.0)                                          # well inside by then
    assert s.hull_damage() == 0.0


def test_e1_no_creation_hit_at_easy_difficulty(oracle):
    """E1 — `n5000_ns_d0`: at difficulty 0 not even the creation hit lands."""
    _set_difficulty(EASY)
    s = oracle(attacker="KessokHeavy", range_gu=300)
    before = s.faces()
    s.build_nebula(radius=1500.0, hull=5000.0, shields=5000.0)
    s.step(2)
    assert s.faces() == pytest.approx(before, abs=0.5)
    assert s.hull_damage() == 0.0


def test_e1_environment_damage_event_16_per_second_while_inside(oracle):
    """E1 — the engine raises ET_ENVIRONMENT_DAMAGE on a contained ship 16
    times a second for as long as it is inside (296 in 18.5 s), whether or
    not any damage lands."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    App = s.App
    handler_name = "tests.oracle.test_nebula._count_env_damage"
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_ENVIRONMENT_DAMAGE, s.mission, handler_name)
    _ENV_EVENTS.clear()
    # Armed (SetupDamage) but with a shield hit under the 100/face threshold,
    # so the events come and no damage lands — the stock Vesuvi 4 case.
    s.build_nebula(radius=1500.0, hull=0.0, shields=1600.0)
    s.run(5.0)
    on_target = [e for e in _ENV_EVENTS if e[1] is s.tgt]
    assert len(on_target) == pytest.approx(80, abs=4)         # 16/s × 5 s


_ENV_EVENTS = []


def _count_env_damage(obj, event):
    _ENV_EVENTS.append((obj, event.GetDestination()))


def test_e1_one_argument_setup_damage_does_nothing(oracle):
    """E1 — the Multi6 form `SetupDamage(x)` does nothing measurable."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    s.zero_shields()
    s.tgt.SetAlertLevel(s.App.ShipClass.GREEN_ALERT)
    s.build_nebula(radius=1500.0, hull=5000.0)          # one-argument form
    s.step(2)
    assert s.hull_damage() == 0.0
    assert all(f >= 0.0 for f in s.faces())              # regen only
