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
