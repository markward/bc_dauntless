"""Wing Phase B behaviour (spec 2026-11-09-wing-leaders-phase-b-design.md):
protect, rotate and withdraw seen in a real headless fight.

combat_stress through the dev loader's own path and the real GameLoop, as
tests/host/test_wings_combat_stress.py runs it (and, like it, with
OPEN_STBC_HOST_HEADLESS pinned unset). The trigger of each behaviour is
forced so it is the same every run -- a laid-out scene, a held shield or hull
fraction, a fixed focus of fire -- but the fight around it is not
reproducible run to run (an engine property), so every bound is generous and
its margin is documented beside it."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
from engine.core.loop import GameLoop  # noqa: E402
from engine.wings import assess, roster, service  # noqa: E402
from tests.host.test_wings_combat_stress import _load, _set_ships  # noqa: E402

HZ = 60


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _place(ship, xyz):
    ship.SetTranslateXYZ(*xyz)
    ship.UpdateNodeOnly()


def _centroid(ships):
    pts = [_pos(s) for s in ships if s is not None and not s.IsDead()]
    if not pts:
        return None
    return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))


def _wing(wid):
    return next(w for w in roster.wings() if w.wing_id == wid)


def _set_shields(ship, frac):
    shields = ship.GetShields()
    for i in range(App.ShieldClass.NUM_SHIELDS):
        shields.SetCurShields(i, frac * shields.GetMaxShields(i))


# ── (a) protect: a guard body-blocks a focus-fired member ───────────────────

def test_guard_moves_between_protectee_and_attacker(monkeypatch):
    _load(monkeypatch, 8, 4)
    ships = _set_ships()
    fw, ew = _wing("cs:friend:0"), _wing("cs:enemy:0")
    cmd = fw.commander
    others = sorted(n for n in fw.members if n != cmd)
    protectee, far = others[0], others[1:]
    enemies = sorted(ew.members)
    # The enemy wing's brain stops, and its target group is the protectee
    # alone: all four enemies' stock SelectTarget focus their fire on it.
    service._armed.remove(ew)
    for n in ew.target_group.GetNameTuple():
        ew.target_group.RemoveName(n)
    ew.target_group[protectee] = {"Priority": 1.0}
    # Laid out: commander at the origin, the protectee 40 GU ahead, the
    # enemies ~30 GU beyond it, the guard candidates ~90 GU from the
    # protectee->attacker midpoint (behind the commander, either side).
    _place(ships["Player"], (0.0, -3000.0, 0.0))
    _place(ships[cmd], (0.0, 0.0, 0.0))
    _place(ships[protectee], (40.0, 0.0, 0.0))
    for n, (y, z) in zip(enemies, ((8, 8), (-8, 8), (8, -8), (-8, -8))):
        _place(ships[n], (70.0, float(y), float(z)))
        ships[n].SetTarget(protectee)
    _place(ships[far[0]], (-30.0, 30.0, 0.0))
    _place(ships[far[1]], (-30.0, -30.0, 0.0))

    loop = GameLoop()
    best, start, decided = {}, {}, False
    for t in range(10 * HZ):
        loop.tick()
        if t % 6:
            continue
        decided = decided or fw.decision == "protect"
        p = ships[protectee]
        if p.IsDead():
            break
        atk = [ships[n] for n in enemies if not ships[n].IsDead()
               and ships[n].GetTarget() is not None
               and ships[n].GetTarget().GetName() == protectee]
        if not atk:
            continue
        a = min(atk, key=lambda s: assess.dist(_pos(s), _pos(p)))
        mid = tuple((x + y) / 2.0 for x, y in zip(_pos(p), _pos(a)))
        for n in far:
            d = assess.dist(_pos(ships[n]), mid)
            start.setdefault(n, d)
            if fw.members[n].guard:
                best[n] = min(best.get(n, d), d)
    print("\n[protect] start %s best guard %s decision %s"
          % ({n: round(d, 1) for n, d in start.items()},
             {n: round(d, 1) for n, d in best.items()}, fw.decision))
    assert decided
    # A far member was picked as guard, and while it was one it came within
    # 60 GU of the midpoint (from ~90). Seen 48-53 GU. The attack AI alone
    # brings the far members to 59.5-65.6 GU in 10 s (guard_count 0, 2026-11-09),
    # so the distance bound alone barely separates the two: the guard pick is
    # what this test pins, the distance that the guard moves in.
    assert best, "no guard picked from the far members"
    assert min(best.values()) < 60.0


# ── (b) rotate: a shield-less member falls back behind its commander ───────

def test_shieldless_member_falls_back_behind_commander(monkeypatch):
    _load(monkeypatch, 8, 4)
    # Protect stays on: the enemy wing swarms the weakest ship, which makes
    # the faller the protectee too, and a member protectee still falls back
    # (ruling 2026-11-09) with its guard covering its retreat.
    ships = _set_ships()
    fw, ew = _wing("cs:friend:0"), _wing("cs:enemy:0")
    cmd = fw.commander
    faller, *rest = sorted(n for n in fw.members if n != cmd)
    enemies = [ships[n] for n in sorted(ew.members)]
    # Laid out: the enemies ~100 GU ahead (+x) of the commander, the faller
    # 60 GU nearer them than the commander, the other two beside it.
    _place(ships["Player"], (0.0, -3000.0, 0.0))
    _place(ships[cmd], (0.0, 0.0, 0.0))
    _place(ships[faller], (60.0, 20.0, 0.0))
    _place(ships[rest[0]], (0.0, 30.0, 0.0))
    _place(ships[rest[1]], (0.0, -30.0, 0.0))
    for s, (y, z) in zip(enemies, ((10, 10), (-10, 10), (10, -10), (-10, -10))):
        _place(s, (100.0, float(y), float(z)))

    loop = GameLoop()
    first, fell, trace, guarded = None, False, [], False
    for t in range(15 * HZ):
        _set_shields(ships[faller], 0.1)           # held: it stays down
        loop.tick()
        fell = fell or fw.members[faller].fallback_since is not None
        guarded = guarded or fw.guarded == faller
        if t % 30:
            continue
        cen = _centroid(enemies)
        d_f = assess.dist(_pos(ships[faller]), cen)
        d_c = assess.dist(_pos(ships[cmd]), cen)
        trace.append((round(t / HZ, 1), round(d_f, 1), round(d_c, 1)))
        if first is None and d_f > d_c:
            first = t / HZ
    print("\n[rotate] faller %s cmd %s farther at %s s; guarded as "
          "protectee %s; (t, faller, cmd) %s"
          % (faller, cmd, first, guarded, trace[::4] + trace[-1:]))
    assert fell
    # Seen farther than the commander at 8.5-9.5 s in every run (window 15 s),
    # with Protect on and the faller guarded as the protectee in every run
    # (2026-11-09, 6 runs); with rotate off (rotate_out_shield 0, protect on,
    # 2 runs) it never was: it closed to 24.7-29.2 GU.
    assert first is not None


# ── (c) withdraw: a battered two-ship wing opens the range ──────────────────

def _pair_vs_eight(monkeypatch, withdraw_on):
    """The wing's mean distance (GU) from the enemy centroid at the start,
    every 2 s, and after 20 s."""
    _load(monkeypatch, 16, 2)
    from engine.wings import dials
    if not withdraw_on:
        monkeypatch.setitem(dials._dials, "withdraw_odds", 0.0)
    ships = _set_ships()
    fw = _wing("cs:friend:0")
    pair = [ships[n] for n in sorted(fw.members)]
    enemies = [s for n, s in ships.items() if n.startswith("Enemy")]
    assert len(pair) == 2 and len(enemies) == 8
    # Laid out: the pair side by side at the origin, the eight enemies in a
    # cluster ~60 GU ahead (+x), every other friendly ship (and the player)
    # 3000 GU away, out of every enemy wing's leash: two against eight.
    _place(ships["Player"], (0.0, -3000.0, 0.0))
    _place(pair[0], (0.0, 10.0, 0.0))
    _place(pair[1], (0.0, -10.0, 0.0))
    for k, s in enumerate(enemies):
        _place(s, (60.0 + 10.0 * (k // 4), 20.0 * (k % 2) - 10.0,
                   20.0 * ((k // 2) % 2) - 10.0))
    others = [s for n, s in ships.items()
              if n.startswith("Friend") and s not in pair]
    for k, s in enumerate(others):
        _place(s, (-3000.0, 20.0 * k, 0.0))

    def held():
        for s in pair:
            s.GetHull().SetConditionPercentage(0.3)

    def mean_dist():
        cen = _centroid(enemies)
        live = [s for s in pair if not s.IsDead()]
        return sum(assess.dist(_pos(s), cen) for s in live) / len(live)

    held()
    d0 = mean_dist()
    loop = GameLoop()
    withdrew, trace = False, []
    for t in range(20 * HZ):
        held()
        loop.tick()
        withdrew = withdrew or fw.withdraw_since is not None
        if t % 120 == 0:
            trace.append(round(mean_dist(), 1))
    return withdrew, d0, mean_dist(), trace


def test_battered_pair_withdraws_from_eight(monkeypatch):
    withdrew, d0, d1, trace = _pair_vs_eight(monkeypatch, True)
    c_withdrew, c0, c1, c_trace = _pair_vs_eight(monkeypatch, False)
    print("\n[withdraw] mean %.1f -> %.1f GU %s; control (withdraw off) "
          "%.1f -> %.1f GU %s" % (d0, d1, trace, c0, c1, c_trace))
    assert withdrew and not c_withdrew
    # The wing's mean distance from the enemy centroid over 20 s. Bound:
    # grows by >= 30 GU and ends beyond the control's (same layout, withdraw
    # dialled off). Seen 65.8 -> 120.0-125.6 GU (+54 to +60); control
    # 65.8 -> 69.3-79.8 GU (2026-11-09, 3 runs).
    assert d1 >= d0 + 30.0
    assert d1 > c1
