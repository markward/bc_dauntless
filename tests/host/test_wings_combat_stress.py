"""combat_stress wing wiring (spec 2026-11-09-wing-leaders-phase-a-design.md
§11 "combat_stress consumer", §13 "Behaviour").

DAUNTLESS_COMBAT_WING_SIZE=N splits each side's ships (creation order) into
wings of N; 0 (default) leaves the mission as it was. Headless, through the
dev loader's own path and the real GameLoop.
"""
import time

import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
from engine.core.loop import GameLoop  # noqa: E402
from tests.helpers import headless_mission  # noqa: E402

TICKS = 18000
SAMPLE_EVERY = 60          # one sample a second at 60 Hz


def _load(monkeypatch, ships, wing_size, wings_on=True):
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", str(ships))
    monkeypatch.setenv("DAUNTLESS_COMBAT_WING_SIZE", str(wing_size))
    if wings_on:
        monkeypatch.delenv("DAUNTLESS_WINGS", raising=False)
    else:
        monkeypatch.setenv("DAUNTLESS_WINGS", "0")
    App.g_kTimerManager._time = 0.0
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")


def _is_wing_tree(ship):
    ai = ship.GetAI()
    return ai is not None and ai.GetName() == "WingPriorityList"


def _set_ships():
    from engine.appc.ship_iter import iter_ships
    return {s.GetName(): s for s in iter_ships()}


def test_wing_size_zero_is_unchanged(monkeypatch):
    _load(monkeypatch, 8, 0)
    from engine.wings import roster
    assert roster.wings() == []
    ships = _set_ships()
    assert not any(_is_wing_tree(s) for s in ships.values())


def test_wing_size_splits_sides(monkeypatch):
    _load(monkeypatch, 16, 4)
    from engine.wings import roster
    ids = sorted(w.wing_id for w in roster.wings())
    assert ids == ["cs:enemy:0", "cs:enemy:1", "cs:friend:0", "cs:friend:1"]
    ships = _set_ships()
    assert roster.wing_of("Player") is None
    for w in roster.wings():
        assert len(w.members) == 4
        side = "Friend" if ":friend:" in w.wing_id else "Enemy"
        assert all(m.startswith(side) for m in w.members)
        assert all(_is_wing_tree(ships[m]) for m in w.members)


def test_wings_disabled_leaves_plain_trees(monkeypatch):
    _load(monkeypatch, 16, 4, wings_on=False)
    from engine.wings import roster
    assert roster.wings() == []
    assert not any(_is_wing_tree(s) for s in _set_ships().values())


def _spread_p90(monkeypatch, wings_on):
    """90th percentile member->commander distance (GU) over the last third.
    Without wings, the same chunks by name (Friend-k/Enemy-k in creation
    order) with the commander taken as each chunk's first ship in ring order;
    with wings, the wing's real commander."""
    _load(monkeypatch, 16, 4, wings_on=wings_on)
    from engine.wings import roster
    if wings_on:
        chunks = [(list(w.members), None) for w in roster.wings()]
    else:
        chunks = []
        for side, n in (("Friend", 8), ("Enemy", 8)):
            names = ["%s-%d" % (side, k + 1) for k in range(n)]
            chunks += [(names[i:i + 4], names[i]) for i in range(0, n, 4)]
    ships = _set_ships()
    loop = GameLoop()
    samples = []
    for t in range(TICKS):
        loop.tick()
        if t >= TICKS * 2 // 3 and t % SAMPLE_EVERY == 0:
            for members, fixed in chunks:
                cmd_name = fixed
                if wings_on:
                    cmd_name = roster.wing_of(members[0]).commander
                cmd = ships.get(cmd_name)
                if cmd is None or cmd.IsDead():
                    continue
                cp = cmd.GetWorldLocation()
                for m in members:
                    s = ships.get(m)
                    if m == cmd_name or s is None or s.IsDead():
                        continue
                    samples.append((s.GetWorldLocation() - cp).Length())
    assert samples, "no live member/commander pairs sampled"
    samples.sort()
    return samples[int(0.9 * (len(samples) - 1))]


def test_wings_keep_formation_together(monkeypatch):
    t0 = time.time()
    on = _spread_p90(monkeypatch, True)
    t_on = time.time() - t0
    t0 = time.time()
    off = _spread_p90(monkeypatch, False)
    t_off = time.time() - t0
    print("\n[wings spread] p90 wings ON %.1f GU (%.0fs), OFF %.1f GU (%.0fs)"
          % (on, t_on, off, t_off))
    # Main claim: wings cut the spread to under 0.6x. The absolute bound is BC's
    # long band (350 GU), not leash + slack (300): the scene is not
    # reproducible run to run (ON p90 seen 240-312 GU), so 300 was flaky.
    assert on < 0.6 * off
    assert on < 350.0
