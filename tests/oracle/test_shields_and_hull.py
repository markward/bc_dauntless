"""Bible §5 shields and §6 hull/subsystem damage."""
import pytest

from tests.oracle.conftest import (
    FRONT, REAR, TOP, BOTTOM, PORT, STARBOARD, bible_xfail,
)

HIGH = 2


# ── §5.1 facing selection ───────────────────────────────────────────────────────

@pytest.mark.parametrize("bearing, offset, face", [
    ("front", (0.0, 57.0, 0.0), FRONT),
    ("aft", (0.0, -57.0, 0.0), REAR),
    ("top", (0.0, 0.0, 57.0), TOP),
    ("bottom", (0.0, 0.0, -57.0), BOTTOM),
    ("port", (-57.0, 0.0, 0.0), PORT),
    ("starboard", (57.0, 0.0, 0.0), STARBOARD),
])
def test_s1_s7_facing_index_map(oracle, bearing, offset, face):
    """S1/S7 — `phaser_high_{front,aft,elev*,bottom,port,stbd}_57`: the face
    that drains is the one the shot arrives through: 0 front, 1 rear, 2 top,
    3 bottom, 4 port, 5 starboard.

    Headless there is no hull mesh and no bubble, so a fired beam lands on the
    aim point and cannot exercise the geometry; the rule itself is asserted
    on the chooser with the shot's entry point on each axis of the target,
    which faces +Y with +Z up."""
    from engine.appc.combat import _shield_face_from_hit_point
    from engine.appc.math import TGPoint3
    s = oracle(attacker="KessokHeavy", range_gu=57)
    entry = TGPoint3(*offset)
    assert _shield_face_from_hit_point(s.tgt, entry) == face, bearing


# ── §5.2 absorption ramp ────────────────────────────────────────────────────────

@bible_xfail("S2", "a face at ≥ 0.6 passes nothing; below 0.6 the hull share ramps linearly to 0.6 at f = 0.1",
             "strict cascade: nothing reaches the hull until the face is empty")
def test_s2_weakened_face_lets_damage_through(oracle):
    """S2 — pooled §5.2: at face fraction 0.40–0.45 the hull takes a median
    20 % of each hit while the face still holds most of it."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.preset_face(FRONT, 0.45)
    s.fire("phaser", intensity=HIGH)
    s.run(0.6)                      # 0.45 → ~0.40 on BC's rate
    assert s.face(FRONT) > 0.30 * s.face_max(FRONT), "face emptied"
    assert s.hull_damage() > 0.0


@pytest.mark.parametrize("preset, share", [(0.5, 0.39), (0.25, 0.75)])
@bible_xfail("S3", "front face at 50 % passes 39 % of a volley to the hull; at 25 %, 75 %",
             "strict cascade — the share is whatever is left once the face is empty")
def test_s3_hull_share_of_a_volley_by_face_preset(oracle, preset, share):
    """S3 — `phaser_high_front_57_face{50,25}`: 2015 of 5206 / 4102 of 5485."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.preset_face(FRONT, preset)
    s.fire("phaser", intensity=HIGH)
    s.run(8.0)
    total = s.hull_damage() + (s.face_max(FRONT) * preset - s.face(FRONT))
    assert s.hull_damage() / total == pytest.approx(share, abs=0.05)


# ── §5.3 regeneration ────────────────────────────────────────────────────────────

@bible_xfail("S4", "each face regains 6.15 points every 0.656 s (≈ 9.4/s) at full generator power",
             "11.4/s (hardpoint 11/s × power) on a 0.5 s cadence")
def test_s4_face_regen_rate(oracle):
    """S4 — every capture after firing stops: −6.1/−6.2 steps every 0.656 s."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.preset_face(FRONT, 0.5)
    before = s.face(FRONT)
    s.run(6.0)
    assert (s.face(FRONT) - before) / 6.0 == pytest.approx(9.4, rel=0.05)


@bible_xfail("S5", "regen rate identical at red, yellow and green alert (9.2–9.5/s)",
             "green alert drops the faces to 0 and suppresses regen")
@pytest.mark.parametrize("alert", ["green", "yellow"])
def test_s5_regen_identical_across_alert_levels(oracle, alert):
    """S5 — `regen_{red,yellow,green}_face50`."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    App = s.App
    level = {"green": App.ShipClass.GREEN_ALERT, "yellow": App.ShipClass.YELLOW_ALERT}[alert]
    s.tgt.SetAlertLevel(level)
    s.preset_face(FRONT, 0.5)
    before = s.face(FRONT)
    s.run(6.0)
    assert (s.face(FRONT) - before) / 6.0 == pytest.approx(9.4, rel=0.05)


@bible_xfail("S5", "regen unchanged at 50 % generator power wanted",
             "regen scales with GetNormalPowerPercentage()")
def test_s5_regen_independent_of_generator_power_wanted(oracle):
    """S5 — `regen_power50_face50`."""
    full = oracle(attacker="KessokHeavy", range_gu=57)
    full.preset_face(FRONT, 0.5)
    b = full.face(FRONT); full.run(6.0)
    r_full = (full.face(FRONT) - b) / 6.0
    half = oracle(attacker="KessokHeavy", range_gu=57)
    half.shields.SetPowerPercentageWanted(0.5)
    half.preset_face(FRONT, 0.5)
    b = half.face(FRONT); half.run(6.0)
    r_half = (half.face(FRONT) - b) / 6.0
    assert r_half == pytest.approx(r_full, rel=0.05)


@pytest.mark.parametrize("condition", [0.5, 0.2])
def test_s6_disabled_generator_no_regen(oracle, condition):
    """S6 — `regen_gen{50,20}_face50`: generator below DisabledPercentage
    (0.75) ⇒ nothing regenerates."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    gen = s.shields
    gen.SetCondition(gen.GetMaxCondition() * condition)
    s.preset_face(FRONT, 0.5)
    before = s.face(FRONT)
    s.run(4.0)
    assert s.face(FRONT) <= before


@bible_xfail("S6", "generator below DisabledPercentage ⇒ every face drops to 0 immediately",
             "the faces keep their charge; only regen stops")
@pytest.mark.parametrize("condition", [0.5, 0.2])
def test_s6_disabled_generator_drops_every_face(oracle, condition):
    """S6 — `regen_gen{50,20}_face50`: all six faces read 0 with the
    generator at 50 % or 20 % condition."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    gen = s.shields
    gen.SetCondition(gen.GetMaxCondition() * condition)
    s.run(1.0)
    assert s.faces() == [0.0] * 6


# ── §6 hull and subsystem routing ─────────────────────────────────────────────────

def test_h1_hull_and_every_overlapping_subsystem_take_full_amount(oracle):
    """H1 — `phaser_high_front_57_noshields`: hull 5571, sensor array 5402,
    every forward tube destroyed — each takes the WHOLE post-shield amount,
    independently.  Headless there is no hull mesh, so the hit lands on the
    aim point and the overlapping set is not BC's; what is asserted is the
    routing rule: whatever a subsystem took equals what the hull took (or its
    max, if destroyed)."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.zero_shields()
    s.fire("phaser", intensity=HIGH)
    s.run(2.0)
    hull_taken = s.hull_damage()
    assert hull_taken > 0.0
    from engine.appc.combat import _iter_subsystems
    hit = []
    for sub in _iter_subsystems(s.tgt):
        if sub.GetNumChildSubsystems() > 0:
            continue                # a parent's condition is the sum of its children
        taken = sub.GetMaxCondition() - sub.GetCondition()
        if taken > 0.5:
            hit.append((sub.GetName(), taken, sub.GetMaxCondition()))
    assert hit, "no subsystem overlapped the hit"
    for name, taken, mx in hit:
        assert taken == pytest.approx(min(hull_taken, mx), rel=0.05), (name, taken, hull_taken)


def test_h1_bare_hull_takes_the_volley_total(oracle):
    """H1 — the unshielded hull number equals the volley total (5 400–5 600
    in BC).  Asserted relative to this build's own volley (B1 owns the
    absolute) so this stays a routing test, not a second B1."""
    shielded = oracle(attacker="KessokHeavy", range_gu=57)
    shielded.fire("phaser", intensity=HIGH)
    shielded.run(8.0)
    volley = shielded.face_damage(FRONT) + shielded.hull_damage()
    bare = oracle(attacker="KessokHeavy", range_gu=57)
    bare.zero_shields()
    bare.fire("phaser", intensity=HIGH)
    bare.run(8.0)
    assert bare.hull_damage() == pytest.approx(volley, rel=0.05)
