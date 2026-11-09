"""A phaser's beam reaches its target when its beam-on delay ends.

A lit bank neither drains nor damages for BEAM_ON_DELAY_S (0.66 s), then
flushes one pulse each time its dwell passes BEAM_DWELL_FLUSH_S. Measured on
the original with stbc-oracle (the four Galaxy/Sovereign AI duels, CombatTap
WeaponHitHandler rows against each bank's IsFiring in the telemetry): every
firing that lasts gives ONE zero-damage weapon hit -- the shield impact --
0.50-0.52 s before the first damaging one, at every range from 21 to 176 GU.
So the impact lands as the delay ends, not when the bank lights, and not
after a travel time. A firing that ends inside the delay shows no impact.

Dauntless ran the resting contact (hit_feedback.beam_contact: the shield
splash, the hull glow and the sparks) on every tick a bank was lit,
including the delay: a shield lit up for a beam that had not reached it, and
for one whose target left the arc before it ever did. Both paths, the Python
loop and the native K2 kernel, are checked by the K2 dispatch harness.
"""
from engine.appc import weapon_subsystems as ws
from tests.unit.test_native_k2_dispatch import (
    GALAXY_VORCHA, _banks_in_arc, _both, _calls, _native_ran)

_DELAY_TICKS = 40          # BEAM_ON_DELAY_S at 60 Hz (two 0.33 s thresholds)


def _light(w, bank, target):
    bank._target = target
    bank._firing = True
    bank._beam_on_countdown = ws.BEAM_ON_DELAY_S


def test_no_contact_until_the_beam_is_on(monkeypatch):
    """A bank lit at tick 1 shows nothing on its target until its delay has
    run out; then it rests on the target as before."""
    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            _light(w, _banks_in_arc(g, v)[0], v)

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 90)
    for w in (ref, nat):
        contacts = _calls(w, "beam_contact")
        assert contacts, "the beam never rested on its target"
        first = min(c[1] for c in contacts)
        assert first > _DELAY_TICKS - 2, (
            "a contact at tick %d, inside the %d-tick beam-on delay"
            % (first, _DELAY_TICKS))
        assert first <= _DELAY_TICKS + 2, first
        shields = [c for c in w.calls if c[0] == "shield_hit"]
        assert not shields or min(c[1] for c in shields) >= first
    _native_ran(counts)


def test_a_beam_cut_off_inside_its_delay_never_lands(monkeypatch):
    """The target leaves the bank's arc while the beam is still coming on:
    the bank stops, and the target shows no impact and takes no damage."""

    def script(w, t):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        if t == 0:
            _light(w, _banks_in_arc(g, v)[0], v)
        elif t == 20:
            v.SetTranslateXYZ(-15.0, -240.0, 10.0)      # swept astern

    ref, nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 90)
    for w in (ref, nat):
        assert _calls(w, "beam_contact") == []
        assert [c for c in w.calls if c[0] == "shield_hit"] == []
        assert _calls(w, "apply_hit") == []
    assert counts["k2_logged_bank_stop"] > 0, counts
    _native_ran(counts)


def test_a_full_volley_still_lands(monkeypatch):
    """With the delay run out, a volley rests on its target and flushes
    damage pulses exactly as before."""

    def script(w, t):
        if t == 0:
            w.ships["Galaxy"].GetPhaserSystem().SetSingleFire(0)
            w.ships["Galaxy"].GetPhaserSystem().StartFiring(w.ships["Vorcha"])

    ref, _nat, counts = _both(monkeypatch, GALAXY_VORCHA, script, 160)
    assert _calls(ref, "beam_contact") and _calls(ref, "apply_hit")
    first_hit = min(c[1] for c in _calls(ref, "apply_hit"))
    first_contact = min(c[1] for c in _calls(ref, "beam_contact"))
    assert first_contact < first_hit
    _native_ran(counts)
