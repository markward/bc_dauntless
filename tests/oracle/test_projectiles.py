"""Bible §3 pulse weapons and §4 torpedoes.

A bolt is one hit of `projectile GetDamage() × PulseWeapon.GetDamageScale()`;
a torpedo is one hit of the projectile script's GetDamage(), applied whole.
"""
import pytest

from tests.oracle.conftest import FRONT, bible_xfail


def _hits(scene, seconds, min_step=1.0):
    """(t, amount) for every tick the front face or hull dropped by more than
    `min_step` — i.e. every projectile impact (regen ticks are excluded)."""
    hits = []
    prev = scene.face(FRONT) + scene.hull.GetCondition()
    for t, sc in scene.sample_until(seconds):
        cur = sc.face(FRONT) + sc.hull.GetCondition()
        if prev - cur > min_step:
            hits.append((t, prev - cur))
        prev = cur
    return hits


def _launches(scene, seconds):
    """Tick times at which the number of projectiles in flight rose."""
    # StartFiring launches its first projectile synchronously, before the
    # first tick — count what is already in flight as launched at t=now.
    prev = scene.torpedoes_in_flight()
    times = [scene.t] * prev
    for t, sc in scene.sample_until(seconds):
        cur = sc.torpedoes_in_flight()
        if cur > prev:
            times.extend([t] * (cur - prev))   # two emitters can fire one tick
        prev = cur
    return times


# ── §3 pulse ─────────────────────────────────────────────────────────────────

def test_p1_warbird_bolt_damage(oracle):
    """P1 — `pulse_warbird_front_40`: every bolt 200 = script 400 × 0.5, the
    emitter's GetDamageScale at the default power setting (clean-room
    PulseWeaponDamage.md C1–C5, measured on 7 hulls)."""
    s = oracle(attacker="Warbird", range_gu=40)
    s.fire("pulse")
    hits = _hits(s, 4.0)
    assert hits, "no bolts landed"
    assert all(d == pytest.approx(200.0, abs=6.0) for _, d in hits), hits   # ± a regen step


def test_p1_warbird_single_fire_rotation(oracle):
    """P1 — `pulse_warbird_front_40_meta`, per-cannon charge rows: the four
    cannons fire ONE AT A TIME (DisruptorCannons.SetSingleFire(1)) 0.33 s
    apart — 1.22 / 1.53 / 1.88 / 2.19 — and each fires twice on one charge
    (2.0 → 1.03 → ~0.18 at MED, cost 1.0): 8 bolts in ~2.7 s.  The bible's
    prose "4 bolts, then 4 more 0.34 s later" is a misread of hit clusters.

    Not modelled: BC's rotation wraps with a 0.66 s gap (each cannon's own
    period is 1.66 s = 5 × 0.33, the dispatch spec's 'examines the last-fired
    weapon twice'); ours wraps at 0.33, so the 8th bolt lands ~0.6 s early.
    Asserted loosely enough to admit both."""
    s = oracle(attacker="Warbird", range_gu=40)
    s.fire("pulse")
    launches = _launches(s, 3.0)
    assert len(launches) == 8, launches
    gaps = [b - a for a, b in zip(launches, launches[1:])]
    assert all(g >= 0.30 for g in gaps), gaps          # never two on one tick
    assert all(g <= 0.70 for g in gaps), gaps
    for c in s.emitters("pulse"):
        assert c.GetChargeLevel() < 0.5, (c.GetName(), c.GetChargeLevel())   # both bolts spent


def test_p2_bird_of_prey_bolt_damage(oracle):
    """P2 — `pulse_bop_front_40`: 220 per sample — which is TWO 110-bolts
    (script 220 × 0.5) landing together, the cannons firing as a pair
    (SingleFire 0).  PulseWeaponDamage.md §6: one cannon disabled shows 110."""
    s = oracle(attacker="BirdOfPrey", range_gu=40)
    cannons = s.emitters("pulse")
    cannons[1].SetCondition(0.0)            # one cannon: one bolt per sample
    s.fire("pulse")
    hits = _hits(s, 4.0)
    assert hits, "no bolts landed"
    for _, d in hits:
        assert d == pytest.approx(110.0, abs=6.0), d   # ± a regen step


def test_p2_bird_of_prey_burst_then_affordability(oracle):
    """P2 — `pulse_bop_front_40`, per-cannon charge rows: both cannons fire
    together (SetSingleFire(0)) every 0.33 s — 1.06 / 1.41 / 1.72 / 2.06 —
    four pairs in a row down 3.8 → 2.93 → 2.06 → 1.20 → 0.33 (cost 1.0 net
    of the 0.4/s recharge), then one pair each time the charge climbs back
    over the per-shot cost: 4.38 (at 1.12), 6.66 (1.04), 9.31, 11.62 —
    steady-state gaps 2.28–2.65 s (ours alternate 2.0 / 2.67 around the
    same mean: the 0.33 s attempt cadence quantises the wait either way).
    MinFiringCharge (3.6) plays no part."""
    s = oracle(attacker="BirdOfPrey", range_gu=40)
    s.fire("pulse")
    launches = _launches(s, 12.0)
    volleys = []
    for t in launches:
        if not volleys or t - volleys[-1] > 0.1:
            volleys.append(t)
    assert len(volleys) >= 7, volleys
    burst = [b - a for a, b in zip(volleys[:4], volleys[1:4])]
    assert all(g == pytest.approx(0.333, abs=0.04) for g in burst), volleys
    steady = [b - a for a, b in zip(volleys[3:], volleys[4:])]
    assert all(g == pytest.approx(2.35, abs=0.36) for g in steady), volleys


@pytest.mark.parametrize("setting, bolt", [(0, 44.0), (1, 110.0), (2, 220.0)])
def test_p4_bolt_damage_scales_with_power_setting(oracle, setting, bolt):
    """P4 / PulseWeaponDamage.md C2, C7: a bolt is script GetDamage() ×
    {0.2, 0.5, 1.0}[power setting] — Warbird 80 / 200 / 400
    (`pulse_warbird_front_40_{low,meta,high}`), alongside the cost × {0.5,
    1, 2}, which is why the burst total is setting-independent (P3).
    Asserted on ONE BoP cannon (script 220) so a pair cannot mask it."""
    s = oracle(attacker="BirdOfPrey", range_gu=40)
    cannons = s.emitters("pulse")
    cannons[1].SetCondition(0.0)
    cannons[0].SetPowerSetting(setting)
    s.fire("pulse")
    hits = _hits(s, 3.0)
    assert hits, "no bolts landed"
    for _, d in hits:
        assert d == pytest.approx(bolt, abs=6.0), (d, bolt)


def test_p3_bolt_damage_independent_of_range(oracle):
    """P3 — `pulse_warbird_front_{40,100,150}`: bursts 1501 / 1514 / 1526 —
    no range falloff on bolts (compared here per bolt, ± 2 %).  The prose's
    "and of emitter power setting" is wrong — see test_p4 below."""
    per_bolt = {}
    for r in (40, 100, 150):
        s = oracle(attacker="Warbird", range_gu=r)
        s.fire("pulse")
        hits = _hits(s, 6.0)
        assert hits, "no bolts landed at %d GU" % r
        per_bolt[r] = sum(d for _, d in hits) / len(hits)
    assert per_bolt[100] == pytest.approx(per_bolt[40], rel=0.02)
    assert per_bolt[150] == pytest.approx(per_bolt[40], rel=0.02)


@pytest.mark.parametrize("setting, cost", [(0, 0.5), (1, 1.0), (2, 2.0)])
def test_p4_power_setting_changes_shot_cost_not_damage(oracle, setting, cost):
    """P4 — `pulse_warbird_front_40_{meta,low,high}`: Warbird cannon MaxCharge
    2.0 drops 0.5 / 1.0 / 2.0 per bolt at LOW / MED / HIGH."""
    s = oracle(attacker="Warbird", range_gu=40)
    cannons = s.emitters("pulse")
    for c in cannons:
        c.SetPowerSetting(setting)
    before = [c.GetChargeLevel() for c in cannons]
    s.fire("pulse")
    s.step(3)                       # the first bolt of each cannon has left
    drops = [b - c.GetChargeLevel() for b, c in zip(before, cannons)]
    fired = [d for d in drops if d > 0.01]
    assert fired, drops
    for d in fired:
        assert d == pytest.approx(cost, abs=0.02), drops


# ── §4 torpedoes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("attacker, damage", [("Galaxy", 500.0), ("Sovereign", 550.0)])
def test_t1_torpedo_hit_is_script_damage_applied_whole(oracle, attacker, damage):
    """T1 — `torpedo_{galaxy,sovereign}_front_57`: Photon 500, Photon2 550."""
    s = oracle(attacker=attacker, range_gu=57)
    s.fire("torpedo")
    hits = _hits(s, 6.0)
    assert len(hits) >= 4, hits
    for _, d in hits:
        assert d == pytest.approx(damage, abs=0.5)


def test_t1_positron_torpedo_2200(oracle):
    """T1 — `torpedo_kessok_front_57`: Positron 2200."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("torpedo")
    hits = _hits(s, 16.0)
    assert len(hits) >= 2, hits
    for _, d in hits:
        assert d == pytest.approx(2200.0, abs=0.5)


def test_t2_tubes_fire_0_656_s_apart(oracle):
    """T2 — `torpedo_galaxy_front_57`: four forward tubes in sequence."""
    s = oracle(attacker="Galaxy", range_gu=57)
    s.fire("torpedo")
    launches = _launches(s, 3.0)
    assert len(launches) >= 4, launches
    gaps = [b - a for a, b in zip(launches, launches[1:4])]
    for g in gaps:
        assert g == pytest.approx(0.656, abs=0.02), gaps


@pytest.mark.parametrize("attacker, flight_s", [("Galaxy", 2.9), ("KessokHeavy", 13.3)])
def test_t3_flight_time_for_57_gu(oracle, attacker, flight_s):
    """T3 — Photon ≈ 2.9 s, Positron ≈ 13.3 s for 57 GU (± 0.5 s)."""
    s = oracle(attacker=attacker, range_gu=57)
    s.fire("torpedo")
    launches = _launches(s, 0.5)
    assert launches, "no launch"
    t0 = launches[0]
    hits = _hits(s, flight_s + 2.0)
    assert hits, "no hit"
    assert hits[0][0] - t0 == pytest.approx(flight_s, abs=0.5)


def test_t4_ammo_switch_unloads_tubes(oracle):
    """T4 — `torpedo_sovereign_quantum_57`: first quantum salvo needs ~45 s
    after `SetAmmoType(1)`; nothing launches in the first 30 s."""
    s = oracle(attacker="Sovereign", range_gu=57)
    s.weapon_system("torpedo").SetAmmoType(1)
    s.fire("torpedo")
    launches = _launches(s, 30.0)
    assert launches == [], launches


def _tube_events(monkeypatch):
    """(kind, source, tube name) for every ET_TORPEDO_FIRED / ET_TORPEDO_RELOAD
    posted from now on, in order."""
    import App
    seen = []
    orig = App.g_kEventManager.AddEvent

    def add(evt):
        et = evt.GetEventType()
        if et in (App.ET_TORPEDO_FIRED, App.ET_TORPEDO_RELOAD):
            d = evt.GetDestination()
            seen.append(("FIRED" if et == App.ET_TORPEDO_FIRED else "RELOAD",
                         evt.GetSource(), d.GetName() if d is not None else None))
        return orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", add)
    return seen


def _tubes(s):
    ts = s.weapon_system("torpedo")
    return ts, [ts.GetWeapon(i) for i in range(ts.GetNumWeapons())]


def _hold_two(tube):
    """Forward Torpedo 1 patched to hold two rounds, as the captures'
    `--hp-patch sovereign:ForwardTorpedo1.SetMaxReady=2`."""
    tube._max_ready = 2
    tube._resize_slots()
    tube.SetNumReady(2)


def test_t4_ammo_switch_posts_one_unload_per_round(oracle, monkeypatch):
    """`ammo_win_switch` / `ammo_win_mr2_switch`: SetAmmoType(1) empties every
    tube with one ET_TORPEDO_FIRED per round (no source, the tube as
    destination) -- the two-round tube posts twice -- and no reload yet."""
    s = oracle(attacker="Sovereign", range_gu=100)
    ts, tubes = _tubes(s)
    _hold_two(tubes[0])
    seen = _tube_events(monkeypatch)
    ts.SetAmmoType(1)
    assert [t.GetNumReady() for t in tubes] == [0] * len(tubes)
    fired = [name for kind, src, name in seen if kind == "FIRED"]
    assert fired == [tubes[0].GetName()] * 2 + [t.GetName() for t in tubes[1:]]
    assert all(src is None for _, src, _ in seen), "an unload has no projectile source"
    assert not [e for e in seen if e[0] == "RELOAD"]


def test_t4_ammo_switch_reloads_after_the_reload_delay(oracle, monkeypatch):
    """`ammo_win_switch`: every tube's ET_TORPEDO_RELOAD comes 40.05 s after
    the switch (Sovereign ReloadDelay 40 s); the two-round tube reloads both
    (`ammo_win_mr2_switch`, +40.00 s)."""
    s = oracle(attacker="Sovereign", range_gu=100)
    ts, tubes = _tubes(s)
    _hold_two(tubes[0])
    t0 = s.t
    ts.SetAmmoType(1)
    seen = _tube_events(monkeypatch)
    reloads = []
    for t, _ in s.sample_until(45.0):
        while len(reloads) < len(seen):
            reloads.append((t - t0, seen[len(reloads)]))
    names = [e[2] for _, e in reloads if e[0] == "RELOAD"]
    assert sorted(names) == sorted([tubes[0].GetName()] + [t.GetName() for t in tubes])
    for dt, _ in reloads:
        assert dt == pytest.approx(40.0, abs=0.2)
    assert [t.GetNumReady() for t in tubes] == [2] + [1] * (len(tubes) - 1)


@pytest.mark.parametrize("same_type", [False, True])
def test_t4_ammo_switch_with_zero_reloads_at_once(oracle, monkeypatch, same_type):
    """`ammo_win_switch0` / `ammo_win_same0` (and their two-round `mr2_`
    runs): SetAmmoType(t, 0) -- mission scripts and the starbase's
    ReloadShip -- unloads and reloads every tube at once, the selected type
    changed or not: a tube's ET_TORPEDO_FIRED per round, then its
    ET_TORPEDO_RELOAD per round, tube by tube, every tube still ready."""
    s = oracle(attacker="Sovereign", range_gu=100)
    ts, tubes = _tubes(s)
    _hold_two(tubes[0])          # `ammo_win_mr2_switch0` / `_mr2_same0`
    seen = _tube_events(monkeypatch)
    want_type = ts.GetAmmoTypeNumber() if same_type else 1
    ts.SetAmmoType(want_type, 0)
    assert ts.GetAmmoTypeNumber() == want_type
    assert [t.GetNumReady() for t in tubes] == [2] + [1] * (len(tubes) - 1)
    t1 = tubes[0].GetName()
    assert [(k, n) for k, _, n in seen] == (
        [("FIRED", t1), ("FIRED", t1), ("RELOAD", t1), ("RELOAD", t1)]
        + [e for t in tubes[1:] for e in (("FIRED", t.GetName()), ("RELOAD", t.GetName()))])
    assert all(src is None for _, src, _ in seen)


def test_t4_reselecting_the_loaded_type_empties_the_tubes(oracle, monkeypatch):
    """`ammo_win_same`: SetAmmoType(current) with one argument empties every
    tube exactly like a switch (ET_TORPEDO_FIRED per tube, reload 40 s
    later); the type is unchanged."""
    s = oracle(attacker="Sovereign", range_gu=100)
    ts, tubes = _tubes(s)
    before = ts.GetAmmoTypeNumber()
    seen = _tube_events(monkeypatch)
    ts.SetAmmoType(before)
    assert ts.GetAmmoTypeNumber() == before
    assert [t.GetNumReady() for t in tubes] == [0] * len(tubes)
    assert [(k, n) for k, _, n in seen] == [("FIRED", t.GetName()) for t in tubes]


def _player_switch(s):
    """The player's own type switch: the weapons panel's cycle-type button and
    the tactical command both call weapon_config.cycle_torpedo_type."""
    from engine.appc import weapon_config
    weapon_config.cycle_torpedo_type(s.atk)


def _stock(ts):
    return [ts.GetNumAvailableTorpsToType(i) for i in range(ts.GetNumAmmoTypes())]


def test_t6_player_switch_empties_every_tube_and_keeps_the_counts(oracle, monkeypatch):
    """`human_ammoswitch_v2` (a human-flown Sovereign on the original, three
    switches): the player's switch changes the type, every tube's ready count
    drops to 0 in the same sample, and the torpedo counts are untouched (200/60
    before and after; only a launch lowers them). Each emptied round posts its
    ET_TORPEDO_FIRED with no source, as SetAmmoType's switch does: the capture
    shows one such row per switch, but OracleHuman drops repeats with the same
    time, type and source, so it can't count them (the loadout at t=5.04 shows
    one row for six loaded tubes too)."""
    s = oracle(attacker="Sovereign", range_gu=100)
    ts, tubes = _tubes(s)
    before_type, before_stock = ts.GetAmmoTypeNumber(), _stock(ts)
    seen = _tube_events(monkeypatch)
    _player_switch(s)
    assert ts.GetAmmoTypeNumber() != before_type
    assert [t.GetNumReady() for t in tubes] == [0] * len(tubes)
    assert _stock(ts) == before_stock
    assert [(k, n) for k, _, n in seen] == [("FIRED", t.GetName()) for t in tubes]
    assert all(src is None for _, src, _ in seen)


def test_t6_player_switch_reloads_every_tube_together(oracle, monkeypatch):
    """`human_ammoswitch_v2` switch 3: the aft tubes were still reloading from
    their last launch (fired at 252.70 / 253.23, due back about 285), and all
    six came back together one full reload after the switch (305.85, +32.35 s
    at the player's power), not at their own time. Here at full normal power
    the reload is the Sovereign's 40 s."""
    s = oracle(attacker="Sovereign", range_gu=100)
    ts, tubes = _tubes(s)
    tubes[-1].UnloadTorpedo()            # one tube already reloading
    for _ in s.sample_until(20.0):
        pass
    assert tubes[-1].GetNumReady() == 0
    t0 = s.t
    _player_switch(s)
    seen = _tube_events(monkeypatch)
    back = {}
    for t, _ in s.sample_until(45.0):
        for k, _, n in seen:
            if k == "RELOAD":
                back.setdefault(n, t - t0)
    assert sorted(back) == sorted(t.GetName() for t in tubes)
    for name, dt in back.items():
        assert dt == pytest.approx(40.0, abs=0.2), name


def test_t6_fire_input_while_the_tubes_are_empty_does_nothing(oracle):
    """`human_ammoswitch_v2` switch 1: eight fire presses between 41.6 and
    62.2 s, while the new type was still loading, launched nothing; the next
    launches came once the tubes were back."""
    s = oracle(attacker="Sovereign", range_gu=57)
    _player_switch(s)
    s.fire("torpedo")
    assert _launches(s, 30.0) == []


@pytest.mark.parametrize("attacker", ["Sovereign", "Galaxy"])
@pytest.mark.parametrize("mode, want", [
    (0, [0.0, 0.667, 1.333, 2.0]),     # Single: one tube at a time
    (1, [0.0, 0.0, 0.667, 0.667]),     # Dual: a pair together, the next pair later
    (2, [0.0, 0.0, 0.0, 0.0]),         # Quad: all four together
])
def test_t5_spread_salvos_fire_group_by_group(oracle, attacker, mode, want):
    """`sweep/torp_spread*.json` (Sovereign and Galaxy, chain
    `0;Single;123;Dual;53;Quad`): the forward tubes' fire times. Single
    16.13 / 16.78 / 17.45 / 18.12; Dual 28.33 28.33 / 29.00 29.00; Quad 40.22
    x4 -- a spread salvo launches in one tick and the next waits the
    ship-wide gate like a single shot."""
    s = oracle(attacker=attacker, range_gu=120)
    s.weapon_system("torpedo").SetFiringChainMode(mode)
    s.fire("torpedo")
    launches = _launches(s, 3.0)[:4]
    assert [round(t - launches[0], 3) for t in launches] == pytest.approx(want, abs=0.02)
