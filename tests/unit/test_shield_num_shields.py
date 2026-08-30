"""ShieldSubsystem.GetNumShields — real Appc surface (SWIG-bound at
sdk/Build/scripts/App.py:6364 `ShieldClass.GetNumShields`), a fixed 6.

It was missing, so TGObject.__getattr__ handed back a truthy _Stub and every
`int(shields.GetNumShields())` collapsed to 0 -- the numeric-coercion stub
class the heatmap tracks. Live telemetry (stub_hits.jsonl) recorded it on
ShieldSubsystem. The visible damage: the AI inspector's export reported
`shield_percent_by_facing: []` for every ship, including a player with shields
up, because `range(0)` is empty. Silent -- no exception, no log line.
"""
from engine.appc.subsystems import ShieldSubsystem
from engine.ui.ai_inspector_model import _defence_report


def test_get_num_shields_is_six():
    assert ShieldSubsystem("X").GetNumShields() == 6


def test_get_num_shields_survives_int_coercion():
    """The stub failure mode was int()-collapse, not an exception."""
    assert int(ShieldSubsystem("X").GetNumShields()) == 6


class _Ship:
    def __init__(self, shields):
        self._shields = shields

    def GetShields(self):
        return self._shields

    def GetAlertLevel(self):
        return 2


def test_defence_report_lists_every_facing():
    ss = ShieldSubsystem("X")
    ss.TurnOn()
    for f in range(6):
        ss.SetMaxShields(f, 100.0)
        ss.SetCurrentShields(f, 50.0)

    report = _defence_report(_Ship(ss))

    assert report["shield_percent_by_facing"] == [0.5] * 6, (
        "inspector reported %r" % (report["shield_percent_by_facing"],)
    )
