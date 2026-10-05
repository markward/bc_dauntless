"""Identity-hiding media (spec: 'Unknown by medium')."""
from engine.appc import sensor_media, sensor_dials
from engine.appc import sensor_detection as sd
import engine.rocks.far_tier as far_tier


class _Obj:
    pass


def test_field_at_or_above_threshold_hides_identity(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.0)
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.5)
    assert sensor_media.medium_unknown(o) is True
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.49)
    assert sensor_media.medium_unknown(o) is False


def test_moderate_nebula_hides_identity(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.0)
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.14)
    assert sensor_media.medium_unknown(o) is True
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.13)
    assert sensor_media.medium_unknown(o) is False


def test_thresholds_are_dials(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.0)
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.3)
    sensor_dials._dials["field_unknown_threshold"] = 0.25
    assert sensor_media.medium_unknown(o) is True


def test_subsystems_hidden_by_medium_or_cloak(monkeypatch):
    o = _Obj()
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 0.0)
    monkeypatch.setattr(sd, "concealment_at", lambda obj: 0.0)
    monkeypatch.setattr(sd, "is_hidden_by_cloak", lambda obj: False)
    assert sensor_media.subsystems_hidden(o) is False
    monkeypatch.setattr(sd, "is_hidden_by_cloak", lambda obj: True)
    assert sensor_media.subsystems_hidden(o) is True
    monkeypatch.setattr(sd, "is_hidden_by_cloak", lambda obj: False)
    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 1.0)
    assert sensor_media.subsystems_hidden(o) is True


def test_none_is_never_medium_unknown():
    assert sensor_media.medium_unknown(None) is False


def test_a_planet_never_raises_and_is_not_medium_unknown():
    """concealment_at/field_strength_at both already guard a Planet (no
    GetContainingSet-shaped surface) down to 0.0 -- medium_unknown must stay
    quiet rather than let a future regression there blow up perception."""
    from engine.appc.planet import Planet
    haven = Planet(90.0, "planet.nif")
    haven.SetName("Haven")
    assert sensor_media.medium_unknown(haven) is False
    assert sensor_media.subsystems_hidden(haven) is False


# ── perception.perceived_by: a known, uncloaked contact in a field ──────────

def test_perception_hides_subsystems_for_known_contact_in_a_field(monkeypatch):
    from engine.appc import contact_index
    from engine.appc.perception import perceived_by
    from engine.appc.sets import SetClass
    from engine.appc.ships import ShipClass_Create
    from engine.appc.subsystems import SensorSubsystem

    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 1.0)

    contact_index.reset()
    pSet = SetClass()
    player = ShipClass_Create("Galaxy")
    player.SetName("player")
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(player, "player")

    enemy = ShipClass_Create("Galaxy")
    enemy.SetName("Enemy")
    enemy.SetTranslateXYZ(10.0, 0.0, 0.0)
    pSet.AddObjectToSet(enemy, "Enemy")
    sensors.AddKnownObject(enemy)   # identified -- cloak/medium is the only gate

    got = perceived_by(player)

    assert len(got) == 1
    assert got[0].identified is True
    assert got[0].subsystems_targetable is False


# ── AI driver: subsystem aim falls back to hull-centre in a field ───────────

def test_ai_subsystem_aim_falls_back_to_hull_in_a_field(monkeypatch):
    from engine.appc.ai import PreprocessingAI, PreprocessingAI_Create
    from engine.appc.ai_driver import _sync_fire_script_target_subsystem
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShieldSubsystem

    class _FireScriptLike:
        def __init__(self, chosen_id):
            self.lWeapons = []
            self.idTargetedSubsystem = None
            self.pCodeAI = None
            self._chosen_id = chosen_id

        def Update(self, dEndTime):
            self.idTargetedSubsystem = self._chosen_id
            return PreprocessingAI.PS_NORMAL

    ours = ShipClass()
    target = ShipClass()
    shield = ShieldSubsystem("Shield")
    shield.SetMaxCondition(500.0)
    target.SetShieldSubsystem(shield)
    ours.SetTarget(target)

    inst = _FireScriptLike(shield.GetObjID())
    pp = PreprocessingAI_Create(ours, "FirePP")
    pp.SetPreprocessingMethod(inst, "Update")
    inst.idTargetedSubsystem = shield.GetObjID()

    monkeypatch.setattr(far_tier, "field_strength_at", lambda obj: 1.0)

    _sync_fire_script_target_subsystem(inst)

    assert ours.GetTargetSubsystem() is None
