"""Beam-timing helpers for tests that assert damage ROUTING on a single
combat tick.

A lit phaser bank neither drains nor damages for the 0.66 s beam-on delay,
and then flushes damage only once its dwell exceeds 0.5 s (stbc-oracle bible
§2.2, engine.appc.weapon_subsystems.BEAM_ON_DELAY_S / BEAM_DWELL_FLUSH_S).
Tests about *where* the damage goes, not *when*, call `prime_lit_banks` after
StartFiring so the very next `_advance_combat` tick flushes one pulse.
"""
from engine.appc.weapon_subsystems import BEAM_DWELL_FLUSH_S


def prime_lit_banks(weapon_system) -> int:
    """Skip every lit bank past its beam-on delay and bank a flush-ready
    dwell.  Returns how many banks were primed."""
    n = 0
    for i in range(weapon_system.GetNumWeapons()):
        bank = weapon_system.GetWeapon(i)
        if bank is None or not bank.IsFiring():
            continue
        bank._beam_on_countdown = 0.0
        bank._dwell = BEAM_DWELL_FLUSH_S + 0.1
        n += 1
    return n
