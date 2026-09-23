"""Nothing keeps emitting from a part that has physically left the ship.

Cast LIGHT already dies, because emitter intensity is gated on the parent
subsystem's condition and severance zeroes it. Particles had no such gate:
a controller emitting from a wing cannon kept streaming from a wing that
was no longer attached.
"""
from engine.appc import part_severance as ps
from engine.appc import particles


class _Sub:
    def __init__(self, name, pos):
        self._name = name
        self._pos = pos
        self.condition = 100.0

    def GetName(self):
        return self._name

    def GetPosition(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(*self._pos)

    def SetCondition(self, c):
        self.condition = float(c)

    def GetCondition(self):
        return self.condition

    def GetMaxCondition(self):
        return 100.0

    def IsDisabled(self):
        return False

    def IsDestroyed(self):
        return self.condition <= 0.0


class _Ship:
    def __init__(self, subs):
        self._articulation_leaf = "birdofprey"
        self._articulation_deflection = 0.0
        self._subs = list(subs)

    def GetArticulationDeflection(self):
        return self._articulation_deflection

    def _iter_subsystems(self):
        return list(self._subs)


STAR_CANNON = (1.008, 0.450, -0.670)     # authored mount, starboard wing
WARP_CORE = (0.0, -0.33, 0.0)            # body


def test_the_fixture_mounts_attribute_as_this_file_assumes():
    """Guard. If these two mounts stop attributing as expected, every test
    below would pass or fail for the wrong reason."""
    assert ps.part_for_point("birdofprey", STAR_CANNON) == "left wing01"
    assert ps.part_for_point("birdofprey", WARP_CORE) != "left wing01"


def test_a_particle_controller_on_the_severed_part_stops():
    particles.reset()
    star = _Sub("Star Cannon", STAR_CANNON)
    ship = _Ship([star])
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(star)
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert not c.is_emitting(), (
        "a controller emitting from a subsystem on the severed wing must "
        "stop — the wing it streams from is no longer attached")


def test_a_controller_elsewhere_keeps_emitting():
    """The other half, and the one a weak test would miss: severance must not
    silence the whole ship."""
    particles.reset()
    star = _Sub("Star Cannon", STAR_CANNON)
    core = _Sub("Warp Core", WARP_CORE)
    ship = _Ship([star, core])
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(core)
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert c.is_emitting(), "the body's emitters are untouched"


def test_silencing_matches_by_IDENTITY_not_by_name():
    """Two ships in one battle carry identically named subsystems. Matching
    on GetName() would silence the other Bird of Prey's cannon too."""
    particles.reset()
    mine = _Sub("Star Cannon", STAR_CANNON)
    theirs = _Sub("Star Cannon", STAR_CANNON)
    ship = _Ship([mine])
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(theirs)
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert c.is_emitting(), (
        "another ship's identically named cannon must keep emitting")


def test_a_ship_attached_emitter_positioned_on_the_wing_stops_when_severed():
    """Built the way production actually builds a hull-hit smoke emitter
    (Effects.CreateSmokeHigh / hull_hit_smoke._emit_smoke): `SetEmitFromObject`
    gets the SHIP, never a subsystem, and the impact location travels
    separately via `SetEmitPositionAndDirection` in body-frame MODEL units.
    Identity matching on `_emit_from` alone can never catch this — it always
    matches the ship, not any subsystem."""
    particles.reset()
    ship = _Ship([])
    model_point = tuple(v / ps.MODEL_TO_SHIP for v in STAR_CANNON)
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection(model_point, (0.0, 0.0, 1.0))
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert not c.is_emitting(), (
        "a ship-attached smoke emitter positioned on the wing must stop "
        "when the wing detaches, even though _emit_from is the ship")


def test_a_ship_attached_emitter_positioned_on_the_body_keeps_emitting():
    particles.reset()
    ship = _Ship([])
    model_point = tuple(v / ps.MODEL_TO_SHIP for v in WARP_CORE)
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection(model_point, (0.0, 0.0, 1.0))
    particles.register(c)

    ps.sever(ship, None, "left wing01")

    assert c.is_emitting(), "a body-positioned ship emitter is untouched"


def test_position_match_converts_MODEL_units_not_SHIP_units():
    """This shipped inert once already: `_emit_pos` is body-frame MODEL
    units (`host_io.world_to_body`'s native output, same as `record_hit`
    receives), while `part_for_point` works in SHIP units. Checked in BOTH
    directions so this test fails whether the MODEL_TO_SHIP conversion is
    missing OR applied twice: the correctly-scaled MODEL-units point must
    silence the emitter, and the same raw numbers -- which are actually the
    SHIP-units mount, so multiplying by MODEL_TO_SHIP collapses them to
    near the origin -- must NOT."""
    particles.reset()
    ship = _Ship([])
    model_point = tuple(v / ps.MODEL_TO_SHIP for v in STAR_CANNON)

    c_model = particles.AnimTSParticleController_Create()
    c_model.SetEmitFromObject(ship)
    c_model.SetEmitPositionAndDirection(model_point, (0.0, 0.0, 1.0))
    particles.register(c_model)

    c_raw = particles.AnimTSParticleController_Create()
    c_raw.SetEmitFromObject(ship)
    c_raw.SetEmitPositionAndDirection(STAR_CANNON, (0.0, 0.0, 1.0))
    particles.register(c_raw)

    ps.sever(ship, None, "left wing01")

    assert not c_model.is_emitting(), (
        "the properly-scaled MODEL-units wing point must silence")
    assert c_raw.is_emitting(), (
        "the raw SHIP-units mount, misread as MODEL units and scaled down "
        "again, lands near the origin and must NOT silence -- proves the "
        "conversion is applied exactly once")


def test_cast_light_from_the_severed_part_goes_dark():
    """PIN. This already works — emitter intensity reads the parent
    subsystem's glow state and severance zeroes its condition — but nothing
    asserted it, so either half could be changed without noticing."""
    from engine.appc import light_emitters, subsystem_glow
    star = _Sub("Star Cannon", STAR_CANNON)
    ship = _Ship([star])
    assert subsystem_glow.glow_state(star) != subsystem_glow.DESTROYED

    ps.sever(ship, None, "left wing01")

    assert subsystem_glow.glow_state(star) == subsystem_glow.DESTROYED
    assert light_emitters.resolve_emitter_intensity(
        {"intensity": 1.0}, star, 0.0) is None


# ── Attribution in the LIVE pose ────────────────────────────────────────────
#
# A point on the OUTER half of a wing, in SHIP units. At rest it attributes
# to "left wing" outright; once the wings deflect, the SAME piece of hull is
# at (-1.2843, 0.0, 0.1136), which is inside NO box and only 3.8x nearer the
# wing than the body -- inside ATTRIBUTION_MARGIN (5.0), so part_for_point
# answers None. Both numbers were computed against the real rig, not guessed.
WING_TIP = (-1.0, 0.0, -0.7)


def _posed(point, node, deflection):
    """`point` where it is DRAWN once `node` sits at `deflection`."""
    from engine.appc import articulation
    part = next(p for p in articulation.rig_for("birdofprey")
                if p.node == node)
    return articulation.point_at_deflection(part, point, deflection)


def test_the_live_pose_fixture_point_attributes_as_this_file_assumes():
    """Guard for the three tests below, and a direct statement of the bug:
    the posed wingtip is exactly the point today's rest-space primitive
    cannot place."""
    posed = _posed(WING_TIP, "left wing", 1.0)
    assert ps.part_for_point("birdofprey", WING_TIP) == "left wing"
    assert ps.part_for_point("birdofprey", posed) is None, (
        "if this ever resolves, the live-pose function is no longer needed "
        "for this point and these tests stop pinning anything")


def test_a_posed_wingtip_attributes_to_its_wing():
    """THE BUG. `_emit_pos` is a POSED body point (host_io.world_to_body of
    a live impact), but PART_BOXES are authored REST-pose -- so a smoke plume
    on the outer half of a deflected wing was never silenced when that wing
    came off. Only inboard plumes, whose posed position still happens to land
    in the rest box, ever were."""
    ship = _Ship([])
    ship._articulation_deflection = 1.0
    posed = _posed(WING_TIP, "left wing", 1.0)
    assert ps.part_for_live_point(ship, posed) == "left wing"


def test_a_body_point_still_attributes_as_it_does_today():
    ship = _Ship([])
    ship._articulation_deflection = 1.0
    assert (ps.part_for_live_point(ship, WARP_CORE)
            == ps.part_for_point("birdofprey", WARP_CORE))


def test_at_deflection_zero_it_agrees_with_part_for_point_exactly():
    """Byte-identical at rest, which is the pose the model ships in and the
    one combat runs in. Swept across representative points rather than
    asserted on one, so a rule that only coincides at the origin fails."""
    ship = _Ship([])
    ship._articulation_deflection = 0.0
    points = [WING_TIP, WARP_CORE, STAR_CANNON, (0.0, 0.5, 0.0),
              (0.2, -0.2, 0.05), (-1.2843, 0.0, 0.1136), (5.0, 5.0, 5.0)]
    for p in points:
        assert (ps.part_for_live_point(ship, p)
                == ps.part_for_point("birdofprey", p)), p


def test_an_emitter_on_a_DEFLECTED_wingtip_stops_when_that_wing_is_severed():
    """End to end, through the path production actually takes: the plume is
    ship-attached with its location carried in body-frame MODEL units, and
    the wings are down when the wing shears off."""
    particles.reset()
    ship = _Ship([])
    ship._articulation_deflection = 1.0
    posed = _posed(WING_TIP, "left wing", 1.0)
    model_point = tuple(v / ps.MODEL_TO_SHIP for v in posed)
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection(model_point, (0.0, 0.0, 1.0))
    particles.register(c)

    ps.sever(ship, None, "left wing")

    assert not c.is_emitting(), (
        "a plume on the outer half of a deflected wing must be silenced "
        "when that wing detaches")
