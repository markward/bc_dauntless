"""K2's resting contacts on a shielded target are presented natively at the
drain (spec 2026-11-02 §4.4; plan Task 3).

After the K2 step's DONE, combat_k2_drain presents every queued rest whose
shields answer is True and whose target's instance id and view offset the
kernel knew at contact time: the shield splash beam_contact would push --
anchor = the bubble entry, else the impact point; shifted into VIEW
coordinates (frames.shifted, doubles); minus the instance's double
translation (host_io._instance_relative); then the shield_hit binding's own
body conversion and push. Every other entry comes back from the drain for
the Python batch (_k2_present_batch -> beam_contact).

Each scenario lights the Galaxy's in-arc banks at the Vor'cha by hand (beams
on, no dwell: every contact rests) and runs ONE combat step twice: native
off (the Python step; a host_io.shield_hit spy sees what beam_contact
pushes) and native on (combat_present_capture records what the drain
pushes, or would push headless). Unit tests have no renderer: the shield
pass is absent, so the drain pushes nothing and only the capture shows it
(Review Focus 5).
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k2_drain"),
    reason="native K2 bindings not built")

from engine import host_io  # noqa: E402
from engine.appc import combat  # noqa: E402
from engine.appc import hit_feedback  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.core.tracked_instances import TrackedInstances  # noqa: E402
from engine.systems import frames  # noqa: E402
from tests.helpers.k3_fight import capture_native_shield_hits  # noqa: E402
from tests.unit.test_native_k2_dispatch import (  # noqa: E402
    GALAXY_VORCHA, World, _banks_in_arc, _light)

# The Vor'cha's render instance, far from the origin (a float32 would round
# it: the relative point must be formed in double).
FAR = (1e6 + 0.3, -3e5 + 0.1, 7.5)
# A view shift for the Vor'cha's set (frames.view_offset): not zero.
SHIFT = (0.25, -1.5, 3.0)
HULL_BOX = ((0.0, 0.5, 0.0), (1.2, 2.5, 0.6))


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    _h.combat_present_capture(None)
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()
    passive_state.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


@pytest.fixture
def instance():
    i = _h.create_instance(0)
    _h.set_world_transform(i, [1.0, 0.0, 0.0, FAR[0],
                               0.0, 1.0, 0.0, FAR[1],
                               0.0, 0.0, 1.0, FAR[2],
                               0.0, 0.0, 0.0, 1.0])
    yield i
    _h.destroy_instance(i)


def _hex3(p):
    return None if p is None else tuple(float(c).hex() for c in p)


def _id(iid):
    return None if iid is None else (iid.index, iid.generation)


class Arm:
    """One step of the lit volley, native off or on. `iids` maps ship name
    -> InstanceId; `view` is the Vor'cha set's view offset (None: none) or
    "unknown" (the native arm's kernel is handed no entry for the set; the
    Python arm cannot tell, and needs none); `setup(world, mp)` runs before
    the step; `before_drain(world)` just before the native drain."""

    def __init__(self, mp, native, *, iids, view=None, hull_box=True,
                 setup=None, before_drain=None):
        self.native = native
        tag = "present_%d" % native
        self.w = w = World(mp, native, GALAXY_VORCHA, tag,
                           instances=lambda w: TrackedInstances(
                               {w.ships[n]: i for n, i in iids.items()}))
        self.hits = []          # what host_io.shield_hit received
        self.captured = []      # what the drain pushed natively
        self.drained = []       # what the drain handed back
        try:
            v = w.ships["Vorcha"]
            if hull_box:
                v._shield_hull_box = HULL_BOX
            self._spy(mp, view, before_drain)
            if setup is not None:
                setup(w, mp)
            w.lit = _banks_in_arc(w.ships["Galaxy"], v)
            assert len(w.lit) >= 2, w.lit
            pb = getattr(w, "point_blank", None)
            if pb is not None and pb not in w.lit:
                w.lit.append(pb)
            w.tick(before=self._light)
            self.counts = nc.counts()
            assert not _h.combat_k2_open()
        finally:
            w.close()

    def _light(self, w):
        for bank in w.lit:
            _light(bank, w.ships["Vorcha"], countdown=0.0)
            bank._dwell = 0.0

    def _spy(self, mp, view, before_drain):
        w = self.w
        real_hit = host_io.shield_hit

        def hit_spy(iid, point, rgba=(0.0, 0.0, 0.0, 0.0), intensity=1.0,
                    radius=0.0):
            rel = (host_io._instance_relative(iid, point)
                   if host_io._h is not None else None)
            self.hits.append((_id(iid), _hex3(point), _hex3(rel),
                              tuple(rgba), float(intensity).hex(),
                              float(radius).hex()))
            return real_hit(iid, point, rgba, intensity, radius)
        mp.setattr(host_io, "shield_hit", hit_spy)

        if not self.native:
            if view is not None and view != "unknown":
                real_view = frames.view_offset
                mp.setattr(frames, "view_offset",
                           lambda s: view if s is w.set else real_view(s))
            return
        real_begin = _h.combat_k2_begin

        def begin(handles, dt, t, use_memo, drift, ctx):
            if "view_offsets" in ctx:
                ctx = dict(ctx)
                ctx["view_offsets"] = (
                    {} if view == "unknown"
                    else {h: view for h in ctx["view_offsets"]})
            return real_begin(handles, dt, t, use_memo, drift, ctx)

        capture_native_shield_hits(mp, self.captured.append)
        real_drain = _h.combat_k2_drain

        def drain():
            if before_drain is not None:
                before_drain(w)
            entries = real_drain()
            self.drained.extend(entries)
            return entries
        mp.setattr(_h, "combat_k2_begin", begin)
        mp.setattr(_h, "combat_k2_drain", drain)

    def contacts(self):
        return [c for c in self.w.calls if c[0] == "beam_contact"]

    def as_hits(self):
        """The captured items as the shield_hit spy's rows."""
        return [(_id(iid), _hex3(view), _hex3(rel), tuple(rgba),
                 float(intensity).hex(), float(radius).hex())
                for (_b, _t, iid, view, rel, rgba, intensity, radius)
                in self.captured]


def _both(monkeypatch, **kw):
    arms = []
    for native in (False, True):
        with monkeypatch.context() as mp:
            arms.append(Arm(mp, native, **kw))
    return arms


def _native_ran(counts):
    assert counts.get("k2_records", 0) > 0, counts
    assert counts.get("k2_python_steps", 0) == 0, counts


@pytest.mark.parametrize("hull_box", (True, False), ids=("bubble", "impact"))
@pytest.mark.parametrize("view", (None, SHIFT), ids=("no_shift", "shift"))
def test_shielded_rest_presents_natively_bit_exact(monkeypatch, instance,
                                                   hull_box, view):
    """Every rest on the shielded Vor'cha is presented by the drain: the
    captured splash is exactly what beam_contact pushes on the Python path
    (instance, view point, rgba, intensity, radius, by .hex()), and its
    relative point is exactly host_io._instance_relative's. None comes back
    for Python."""
    ref, nat = _both(monkeypatch, iids={"Vorcha": instance}, view=view,
                     hull_box=hull_box)
    _native_ran(nat.counts)
    n = len(ref.hits)
    assert n == len(ref.w.lit) and n == len(ref.contacts()), ref.w.calls
    bubbles = [c[6] is not None for c in ref.contacts()]
    assert all(bubbles) if hull_box else not any(bubbles), bubbles
    assert nat.as_hits() == ref.hits
    assert all(h[2] is not None for h in ref.hits)      # a live instance
    assert [(b, t) for b, t, *_ in nat.captured] == [
        (bank.__dict__["_nslot"], nc.slot(nat.w.ships["Vorcha"]))
        for bank in nat.w.lit]
    assert nat.drained == [] and nat.contacts() == [] and nat.hits == []
    c = nat.counts
    assert (c["k2_present_native"], c["k2_present_python"]) == (n, 0), c
    assert c["k2_batched_contacts"] == n, c


def test_unshielded_and_unknown_go_to_python(monkeypatch, instance):
    """Shields down: every rest comes back from the drain and runs
    beam_contact (the hull flash), exactly as the Python step. A rest whose
    shields the kernel could not answer (no aim direction, and a shield
    subsystem the mirror cannot read) comes back unknown and beam_contact
    evaluates its own -- here the splash, so shield_hit is Python's."""

    def shields_off(w, mp):
        w.ships["Vorcha"].GetShields().TurnOff()

    ref, nat = _both(monkeypatch, iids={"Vorcha": instance},
                     setup=shields_off)
    _native_ran(nat.counts)
    assert ref.contacts() and nat.contacts() == ref.contacts()
    assert all(c[11] == ("bool", False) for c in nat.contacts())
    assert [e[12] for e in nat.drained] == [False] * len(nat.contacts())
    assert nat.captured == [] and ref.hits == nat.hits == []
    c = nat.counts
    assert c["k2_present_native"] == 0, c
    assert c["k2_present_python"] == len(nat.contacts()), c


def test_unknown_shields_rest_goes_to_python(monkeypatch, instance):
    """A point-blank bank (its emit point IS the target point: no aim
    direction) on a target whose shield subsystem the mirror cannot read:
    the kernel cannot answer shields_block, the entry's shields are unknown
    and it comes back from the drain; beam_contact evaluates its own and
    splashes the shield (shield_hit, Python's)."""

    class Shields:
        """A shield generator that is not an engine subsystem (no row)."""

        def HasShields(self):
            return 1

        def IsOn(self):
            return 1

        def IsDisabled(self):
            return 0

        def IsDestroyed(self):
            return 0

    def setup(w, mp):
        g, v = w.ships["Galaxy"], w.ships["Vorcha"]
        bank = g.GetPhaserSystem().GetWeapon(0)
        bank._length = 0.0
        mount = bank.GetWorldLocation()
        v.SetTranslateXYZ(mount.x, mount.y, mount.z)
        v._shield_subsystem = Shields()
        w.point_blank = bank

    ref, nat = _both(monkeypatch, iids={"Vorcha": instance}, setup=setup,
                     hull_box=False)
    _native_ran(nat.counts)
    unknown = [e for e in nat.drained if e[12] is None]
    assert unknown, nat.drained
    bank = nat.w.point_blank.__dict__["_nslot"]
    assert [e[0] for e in unknown] == [bank]
    assert sorted(nat.hits + nat.as_hits()) == sorted(ref.hits)
    assert any(c[3] == "Galaxy" and c[11] == ("bool", True)
               for c in nat.contacts()), nat.contacts()


@pytest.mark.parametrize("missing", ("iid", "view_offset"))
def test_missing_iid_or_view_offset_goes_to_python(monkeypatch, instance,
                                                   missing):
    """Review Focus 4. A shielded rest whose target had no instance id, or
    whose set had no view-offset entry, at contact time is neither dropped
    nor presented natively: it comes back from the drain and beam_contact
    presents it (no instance: nothing; an instance: Python's splash)."""
    if missing == "iid":
        # The Galaxy has an instance (so the kernel is handed the view
        # offsets); the Vor'cha has none.
        kw = {"iids": {"Galaxy": instance}}
    else:
        kw = {"iids": {"Vorcha": instance}, "view": "unknown"}
    ref, nat = _both(monkeypatch, **kw)
    _native_ran(nat.counts)
    n = len(ref.contacts())
    assert n == len(ref.w.lit), ref.w.calls
    assert nat.captured == []
    assert len(nat.drained) == n and all(e[12] is True for e in nat.drained)
    if missing == "iid":
        assert all(e[15] is None for e in nat.drained)
        assert ref.hits == nat.hits == []
    else:
        assert all(e[15] is not None and e[16] is None for e in nat.drained)
        assert nat.hits == ref.hits and len(ref.hits) == n
    assert nat.contacts() == ref.contacts()
    c = nat.counts
    assert (c["k2_present_native"], c["k2_present_python"]) == (0, n), c


def test_headless_drops_but_captures(monkeypatch):
    """Review Focus 5. No shield pass (unit tests run headless) and a stale
    instance id: the drain pushes nothing and raises nothing, exactly as the
    shield_hit binding; the capture still records each splash, its relative
    point None (the instance is stale), and nothing goes to Python."""
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    assert _h.instance_translation(stale) is None
    ref, nat = _both(monkeypatch, iids={"Vorcha": stale})
    _native_ran(nat.counts)
    n = len(ref.hits)
    assert n == len(ref.w.lit)
    assert all(h[2] is None for h in ref.hits)
    assert nat.as_hits() == ref.hits
    assert all(item[4] is None for item in nat.captured)
    assert nat.drained == [] and nat.contacts() == []
    assert nat.counts["k2_present_native"] == n


def test_patched_radius_factor_is_read_at_drain(monkeypatch, instance):
    """The splash radius is the bank's own GetDamageRadiusFactor() when it
    is > 0, else the phaser default -- read at the drain (spec §5, Q2): a
    factor changed after the step's DONE, before its drain, is the one
    captured."""
    factor = {}

    def setup(w, mp):
        g = w.ships["Galaxy"].GetPhaserSystem()
        for i in range(g.GetNumWeapons()):
            b = g.GetWeapon(i)
            mp.setattr(b, "GetDamageRadiusFactor",
                       lambda b=b: factor.get(b.GetName(), 0.0))

    def before_drain(w):
        # Half the lit banks get a factor now, after DONE: the rest keep 0.
        for i, bank in enumerate(w.lit):
            if i % 2 == 0:
                factor[bank.GetName()] = 0.375 + i

    with monkeypatch.context() as mp:
        nat = Arm(mp, True, iids={"Vorcha": instance}, setup=setup,
                  before_drain=before_drain)
    _native_ran(nat.counts)
    radii = [item[7] for item in nat.captured]
    want = [0.375 + i if i % 2 == 0 else combat.PHASER_DEFAULT_DAMAGE_RADIUS
            for i in range(len(nat.w.lit))]
    assert [r.hex() for r in radii] == [float(r).hex() for r in want]
    assert {item[6] for item in nat.captured} == {
        hit_feedback.shield_impact_intensity("phaser")}


@pytest.mark.parametrize("exc", (ValueError, KeyboardInterrupt))
def test_raising_radius_factor(monkeypatch, instance, exc):
    """A GetDamageRadiusFactor that raises an Exception sends the entry to
    the Python batch, which calls it again and raises it there (after
    presenting the rest); a KeyboardInterrupt (not an Exception) is never
    cleared: it propagates out of the drain itself, the call made once."""
    calls = []

    def setup(w, mp):
        g = w.ships["Galaxy"].GetPhaserSystem()
        for i in range(g.GetNumWeapons()):
            b = g.GetWeapon(i)

            def factor(b=b):
                calls.append(b.GetName())
                if b is w.lit[0]:
                    raise exc("factor")
                return 0.0
            mp.setattr(b, "GetDamageRadiusFactor", factor)

    with monkeypatch.context() as mp:
        with pytest.raises(exc):
            Arm(mp, True, iids={"Vorcha": instance}, setup=setup)
    first = calls[0]
    assert calls.count(first) == (2 if exc is ValueError else 1), calls
