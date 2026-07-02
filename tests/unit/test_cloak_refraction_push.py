"""Phase E — per-frame cloak refraction wiring (_push_cloak_refraction).

The GL refraction + chromatic-dispersion + glow-keyed translucent-hull pass
itself is validated by the native build (the Pipeline constructor compiles
cloak_refraction.{vert,frag}) and is verified visually in the live GUI. This
pins the Python side that feeds it: for each cloak-capable ship, hide the opaque
hull the moment cloaking begins (frac > 0) — the translucent cloak shell then
owns the hull for the whole transition so its opacity fades gradually — and push
a (instance_id, frac) shell entry for transitioning ships and the player's own
cloaked ship, while a fully-cloaked enemy is hidden and NOT pushed (invisible).
"""
import App  # noqa: F401  (loads the engine shim)

from engine.host_loop import _push_cloak_refraction
from engine.appc.subsystems import CloakingSubsystem


class _FakeRenderer:
    def __init__(self):
        self.visible = {}
        self.cloak_ships = None

    def set_visible(self, iid, vis):
        self.visible[iid] = bool(vis)

    def set_cloak_ships(self, ships):
        self.cloak_ships = list(ships)


class _FakeShip:
    def __init__(self, cloak=None):
        self._cloak = cloak

    def GetCloakingSubsystem(self):
        return self._cloak


class _FakeSession:
    def __init__(self, mapping):
        self.ship_instances = mapping


def _decloaked():
    return CloakingSubsystem("Cloak")


def _cloaking_half():
    c = CloakingSubsystem("Cloak")
    c.StartCloaking()
    c.Update(c._transition_duration * 0.5)
    return c


def _fully_cloaked():
    c = CloakingSubsystem("Cloak")
    c.InstantCloak()
    return c


def test_decloaked_ship_visible_and_not_pushed():
    r = _FakeRenderer()
    ship = _FakeShip(_decloaked())
    session = _FakeSession({ship: 11})
    _push_cloak_refraction(r, session, player=None)
    assert r.visible[11] is True
    assert r.cloak_ships == []


def test_cloaking_ship_hidden_and_pushed_with_frac():
    r = _FakeRenderer()
    ship = _FakeShip(_cloaking_half())
    session = _FakeSession({ship: 7})
    _push_cloak_refraction(r, session, player=None)
    # Opaque hull leaves the render as soon as cloaking begins; the cloak shell
    # now draws the (fading) hull for the whole transition.
    assert r.visible[7] is False
    assert len(r.cloak_ships) == 1
    iid, frac = r.cloak_ships[0]
    assert iid == 7
    assert 0.4 < frac < 0.6                      # ~0.5 through the transition


def test_fully_cloaked_enemy_hidden_and_not_pushed():
    r = _FakeRenderer()
    enemy = _FakeShip(_fully_cloaked())
    session = _FakeSession({enemy: 5})
    _push_cloak_refraction(r, session, player=object())  # player is someone else
    assert r.visible[5] is False                 # hull hidden
    assert r.cloak_ships == []                    # truly invisible — no shell


def test_fully_cloaked_player_hidden_but_shimmer_pushed():
    r = _FakeRenderer()
    player = _FakeShip(_fully_cloaked())
    session = _FakeSession({player: 3})
    _push_cloak_refraction(r, session, player=player)
    assert r.visible[3] is False                 # hull hidden
    assert r.cloak_ships == [(3, 1.0)]            # faint shimmer for the pilot


def test_ship_without_cloak_is_untouched():
    r = _FakeRenderer()
    plain = _FakeShip(None)
    session = _FakeSession({plain: 9})
    _push_cloak_refraction(r, session, player=None)
    assert 9 not in r.visible                     # visibility never touched
    assert r.cloak_ships == []


def test_none_session_is_safe():
    r = _FakeRenderer()
    _push_cloak_refraction(r, None, player=None)  # must not raise
    assert r.cloak_ships is None                  # nothing pushed
