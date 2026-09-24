"""The three cloud profiles used by system-scale nebula/debris volumes.

Each profile is a params dict of four numbers: visibility_gu, sensor_density,
damage_hull_per_s, damage_shield_per_s -- the same four keys as
tools/systems/survey.py's SurveyedRegion.nebula, in the same order.

debris and nebula carry BC's own authored numbers, read verbatim out of the
SDK's static-placement scripts:

* "debris" is Vesuvi4 (Systems/Vesuvi/Vesuvi4_S.py):
      App.MetaNebula_Create(155/255, 90/255, 185/255, 145.0, 10.5, ...)
      pNebula.SetupDamage(150.0, 20.0)

* "nebula" is Belaruz1 (Systems/Belaruz/Belaruz1_S.py):
      App.MetaNebula_Create(100/255, 99/255, 146/255, 200.0, 6.5, ...)
  Belaruz1_S.py never calls SetupDamage at all. Its zero damage rates are a
  real authored choice -- BC deliberately set up no damage for this cloud --
  not a default or a parse placeholder. See survey._nebula and
  test_absent_setup_damage_is_a_real_zero for the same distinction on the
  survey side.

tests/tools/test_system_survey.py::test_the_bc_profiles_match_what_the_sdk_actually_says
re-derives both of the above straight from the SDK scripts and compares
against this module, so PROFILES cannot silently drift from BC's numbers.

"mist" is OURS, not BC's -- named in the design doc, its numbers deliberately
deferred. All four ship at 0.0, which renders and does nothing: that is the
behaviour this module ships today. When mist is tuned later, the binding
constraint from the design is that it must be survivable at sustained
exposure, because it will cover most of a system with no route around it.
"""
from __future__ import annotations

PROFILES = {
    "debris": {
        "visibility_gu": 145.0,
        "sensor_density": 10.5,
        "damage_hull_per_s": 150.0,
        "damage_shield_per_s": 20.0,
    },
    "nebula": {
        "visibility_gu": 200.0,
        "sensor_density": 6.5,
        "damage_hull_per_s": 0.0,
        "damage_shield_per_s": 0.0,
    },
    "mist": {
        "visibility_gu": 0.0,
        "sensor_density": 0.0,
        "damage_hull_per_s": 0.0,
        "damage_shield_per_s": 0.0,
    },
}


def params_for(profile: str) -> dict:
    """Return a copy of the named profile's params so callers cannot mutate
    the shared table."""
    return dict(PROFILES[profile])
