"""Dynamic lights for death-explosion fireballs.

The registry is pure Python with no renderer dependency, so every rule about
WHEN a blast lights and how bright it is can be tested headlessly.
"""
import pytest

from engine.appc import explosion_lights


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Ship:
    """Minimal stand-in: the registry only ever asks for a world position."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self._p = _Pt(x, y, z)

    def move_to(self, x, y, z):
        self._p = _Pt(x, y, z)

    def GetWorldLocation(self):
        return self._p


@pytest.fixture(autouse=True)
def _clean_registry():
    explosion_lights.reset()
    yield
    explosion_lights.reset()


def _register(ship, *, size_gu=10.0, count=4, spacing_s=1.25, life_s=3.0):
    explosion_lights.register(ship, size_gu=size_gu, count=count,
                              spacing_s=spacing_s, life_s=life_s)


# ── the empty case ───────────────────────────────────────────────────────

def test_nothing_registered_means_no_lights():
    assert explosion_lights.render_data() == []


def test_reset_clears_everything():
    _register(_Ship())
    explosion_lights.advance(0.1)
    assert explosion_lights.render_data()
    explosion_lights.reset()
    assert explosion_lights.render_data() == []


# ── the blast schedule ───────────────────────────────────────────────────

def test_first_blast_is_born_at_registration():
    """ship_death's births land at i*spacing, so blast 0 is at t=0 — the
    light must exist on the very first frame after the ship dies, not one
    spacing later."""
    _register(_Ship())
    explosion_lights.advance(1.0 / 60.0)
    assert len(explosion_lights.render_data()) == 1


def test_a_second_blast_arrives_after_one_spacing():
    _register(_Ship(), spacing_s=1.25)
    explosion_lights.advance(1.0 / 60.0)
    assert len(explosion_lights.render_data()) == 1
    explosion_lights.advance(1.25)
    assert len(explosion_lights.render_data()) == 2


def test_exactly_count_blasts_are_ever_born():
    _register(_Ship(), count=4, spacing_s=1.25, life_s=100.0)
    for _ in range(1000):
        explosion_lights.advance(1.0 / 60.0)
    # life_s is long enough that none has expired, so all four are still live.
    assert len(explosion_lights.render_data()) == 4


def test_a_blast_expires_after_its_life():
    _register(_Ship(), count=1, life_s=3.0)
    explosion_lights.advance(1.0 / 60.0)
    assert len(explosion_lights.render_data()) == 1
    explosion_lights.advance(3.0)
    assert explosion_lights.render_data() == []


def test_the_registry_empties_itself_completely():
    """A sequence that has borne every blast and outlived them all must leave
    no residue — this runs every time any ship dies, for the whole session."""
    _register(_Ship(), count=4, spacing_s=1.25, life_s=3.0)
    for _ in range(60 * 20):
        explosion_lights.advance(1.0 / 60.0)
    assert explosion_lights.render_data() == []
    assert not explosion_lights._active
    assert not explosion_lights._sequences


# ── position is captured at birth ────────────────────────────────────────

def test_position_is_captured_at_birth_not_tracked():
    """The hull is removed partway through, and the last blast is anchored at
    the wreck site. Capturing at birth avoids a dangling ship reference, and a
    fireball barely moves relative to its own size."""
    ship = _Ship(100.0, 0.0, 0.0)
    _register(ship, count=1)
    explosion_lights.advance(1.0 / 60.0)
    born_at = explosion_lights.render_data()[0]["position"]
    assert born_at == pytest.approx((100.0, 0.0, 0.0))

    ship.move_to(500.0, 0.0, 0.0)
    explosion_lights.advance(0.1)
    assert explosion_lights.render_data()[0]["position"] == pytest.approx(born_at)


def test_successive_blasts_track_the_tumbling_hull():
    """Each birth reads the ship's position at that moment, so blasts follow
    the coasting hull across the throes."""
    ship = _Ship(0.0, 0.0, 0.0)
    _register(ship, count=2, spacing_s=1.0, life_s=100.0)
    explosion_lights.advance(1.0 / 60.0)
    ship.move_to(50.0, 0.0, 0.0)
    explosion_lights.advance(1.0)

    positions = [e["position"][0] for e in explosion_lights.render_data()]
    assert pytest.approx(0.0) in positions
    assert pytest.approx(50.0) in positions


def test_a_vanished_ship_does_not_raise():
    """The hull is removed after the throes. Every scheduled birth lands while
    it still exists, but a missing one must be survivable rather than take the
    render path down."""
    class _Gone:
        def GetWorldLocation(self):
            return None

    _register(_Gone(), count=2, spacing_s=1.0)
    explosion_lights.advance(1.0 / 60.0)
    explosion_lights.advance(1.0)
    assert explosion_lights.render_data() == []


# ── the intensity envelope ───────────────────────────────────────────────

def test_intensity_rises_then_decays():
    _register(_Ship(), count=1, life_s=3.0)
    explosion_lights.advance(1.0 / 60.0)

    samples = []
    for _ in range(int(3.0 * 60) - 2):
        data = explosion_lights.render_data()
        samples.append(data[0]["intensity"] if data else 0.0)
        explosion_lights.advance(1.0 / 60.0)

    peak = max(samples)
    peak_i = samples.index(peak)
    assert peak > 0.0
    # A fireball blooms fast and fades slow: the peak sits in the first
    # third, not the middle.
    assert peak_i < len(samples) / 3
    assert samples[-1] < peak * 0.25


def test_peak_intensity_respects_the_module_tunable():
    _register(_Ship(), count=1, life_s=3.0)
    explosion_lights.advance(1.0 / 60.0)
    seen = []
    for _ in range(int(3.0 * 60) - 2):
        data = explosion_lights.render_data()
        if data:
            seen.append(data[0]["intensity"])
        explosion_lights.advance(1.0 / 60.0)
    assert max(seen) <= explosion_lights.PEAK_INTENSITY + 1e-6


def test_zero_intensity_entries_are_not_emitted():
    """A light contributing nothing is wasted work in the per-instance top-K
    scan, which runs for every hull on screen."""
    _register(_Ship(), count=1, life_s=3.0)
    for _ in range(int(3.0 * 60) + 10):
        for entry in explosion_lights.render_data():
            assert entry["intensity"] > 0.0
        explosion_lights.advance(1.0 / 60.0)


# ── radius and colour ────────────────────────────────────────────────────

def test_radius_scales_with_the_fireball_size():
    _register(_Ship(), size_gu=10.0, count=1)
    explosion_lights.advance(1.0 / 60.0)
    small = explosion_lights.render_data()[0]["radius"]

    explosion_lights.reset()
    _register(_Ship(), size_gu=40.0, count=1)
    explosion_lights.advance(1.0 / 60.0)
    big = explosion_lights.render_data()[0]["radius"]

    assert big == pytest.approx(small * 4.0)


def test_radius_reaches_beyond_the_sprite():
    """The light must spill onto neighbouring hulls, so its reach exceeds the
    fireball's own drawn size."""
    _register(_Ship(), size_gu=10.0, count=1)
    explosion_lights.advance(1.0 / 60.0)
    assert explosion_lights.render_data()[0]["radius"] > 10.0


def test_colour_is_warm():
    _register(_Ship(), count=1)
    explosion_lights.advance(1.0 / 60.0)
    r, g, b = explosion_lights.render_data()[0]["color"]
    assert r > g > b, "a fireball reads orange: red strongest, blue weakest"


def test_render_data_carries_the_keys_the_renderer_consumes():
    """Mirrors _build_dynamic_light_render_data's descriptor shape; a missing
    key would be a silent no-light at the binding."""
    _register(_Ship(), count=1)
    explosion_lights.advance(1.0 / 60.0)
    entry = explosion_lights.render_data()[0]
    assert set(entry) == {"position", "color", "radius", "intensity"}
    assert len(entry["position"]) == 3
    assert len(entry["color"]) == 3


# ── multiple simultaneous deaths ─────────────────────────────────────────

def test_two_dying_ships_keep_separate_sequences():
    _register(_Ship(0.0, 0.0, 0.0), count=1, life_s=100.0)
    _register(_Ship(200.0, 0.0, 0.0), count=1, life_s=100.0)
    explosion_lights.advance(1.0 / 60.0)
    xs = sorted(e["position"][0] for e in explosion_lights.render_data())
    assert xs == pytest.approx([0.0, 200.0])
