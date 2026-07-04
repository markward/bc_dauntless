"""Per-tick realization reconciliation for runtime-spawned/removed ships.

Today realization happens only at mission load. QuickBattle's player ship is
created late (StartSimulation2 -> RecreatePlayer destroys+recreates the player),
and reinforcement spawns in other missions add ships after load. Without a
per-tick reconciliation pass those ships never get renderer instances, and ships
removed from the set leak their instances. These tests pin the reconciliation
contract against the same fake-renderer harness used by test_realize_set.py.
"""
import App
from engine.appc.sets import SetClass_Create


class _FakeRenderer:
    """Records create/destroy/load so tests can assert additions, removals,
    and that already-realized ships are not reloaded."""

    def __init__(self):
        self._next = 1
        self.live = set()
        self.load_calls = 0
        self.create_calls = 0
        self.destroyed = []

    def load_model(self, path, search, texture_replacements=None):
        self.load_calls += 1
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        self.create_calls += 1
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.live.discard(iid)
        self.destroyed.append(iid)

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def _make_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def _add_ship(s, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    s.AddObjectToSet(ship, name)
    return ship


def _force_nif(monkeypatch, hl):
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")


def test_reconcile_realizes_ship_added_at_runtime(monkeypatch):
    """A ship that appears in the active set AFTER load gets a renderer
    instance recorded in session.ship_instances on the next tick."""
    from engine import host_loop as hl
    _force_nif(monkeypatch, hl)
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    existing = _add_ship(s, "existing")

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    # Simulate the load-time realization of the pre-existing ship.
    hl.realize_set_objects(sess, s, r)
    assert existing in sess.ship_instances

    # Runtime spawn: a new ship enters the set after load.
    newcomer = _add_ship(s, "newcomer")
    assert newcomer not in sess.ship_instances

    hl._reconcile_runtime_instances(sess, r)

    assert newcomer in sess.ship_instances
    assert len(sess.ship_instances) == 2

    App.g_kSetManager.DeleteAllSets()


def test_reconcile_tears_down_ship_removed_from_set(monkeypatch):
    """A ship removed from the set has its instance destroyed and dropped
    from session.ship_instances on the next tick."""
    from engine import host_loop as hl
    _force_nif(monkeypatch, hl)
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    keep = _add_ship(s, "keep")
    drop = _add_ship(s, "drop")

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)
    drop_iid = sess.ship_instances[drop]
    assert len(r.live) == 2

    # Runtime removal.
    s.RemoveObjectFromSet("drop")

    hl._reconcile_runtime_instances(sess, r)

    assert drop not in sess.ship_instances
    assert keep in sess.ship_instances
    assert drop_iid in r.destroyed
    assert drop_iid not in r.live

    App.g_kSetManager.DeleteAllSets()


def test_reconcile_is_idempotent_no_set_change(monkeypatch):
    """Running reconciliation twice with no set change creates no duplicate
    instances and reloads no models (no-op for steady state / existing
    missions where all ships exist at load)."""
    from engine import host_loop as hl
    _force_nif(monkeypatch, hl)
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    _add_ship(s, "a")
    _add_ship(s, "b")

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)
    creates_after_load = r.create_calls
    loads_after_load = r.load_calls
    assert len(sess.ship_instances) == 2

    hl._reconcile_runtime_instances(sess, r)
    hl._reconcile_runtime_instances(sess, r)

    assert len(sess.ship_instances) == 2
    assert r.create_calls == creates_after_load  # no new instances
    assert r.load_calls == loads_after_load      # no reloaded models
    assert r.destroyed == []                     # nothing torn down

    App.g_kSetManager.DeleteAllSets()


def test_reconcile_retargets_camera_on_player_swap(monkeypatch):
    """When Game.GetPlayer() changes identity (RecreatePlayer destroy+recreate),
    session.player updates to the new ship so the camera (which follows
    session.player) retargets. A camera_retarget callback is invoked with the
    new player."""
    from engine import host_loop as hl
    from engine.core.game import Game, _set_current_game
    _force_nif(monkeypatch, hl)
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    old_player = _add_ship(s, "old_player")

    game = Game()
    game.SetPlayer(old_player)
    _set_current_game(game)

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)
    sess.player = old_player

    # RecreatePlayer: the old player object is replaced by a brand-new one.
    new_player = _add_ship(s, "new_player")
    game.SetPlayer(new_player)

    retargeted = []
    hl._reconcile_runtime_instances(
        sess, r, on_player_change=lambda p: retargeted.append(p))

    assert sess.player is new_player
    assert retargeted == [new_player]
    # The new player is realized like any runtime spawn.
    assert new_player in sess.ship_instances

    _set_current_game(None)
    App.g_kSetManager.DeleteAllSets()


def test_reconcile_applies_qb_federation_default_registry(monkeypatch):
    """In a QuickBattle session the (late-created) Federation player ship gets
    its class-default registry applied and baked in when reconciliation realizes
    it — Galaxy -> Dauntless — so the hull reads a name, not the stock
    Enterprise. Covers the RecreatePlayer late-spawn path."""
    from engine import host_loop as hl
    from engine.core.game import Game, _set_current_game
    from engine.appc import registry_texture
    _force_nif(monkeypatch, hl)
    registry_texture.reset()
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    player = _add_ship(s, "player")
    player.SetScript("ships.Galaxy")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    sess = hl.MissionSession(mission_name="QuickBattle")
    r = _FakeRenderer()
    assert not registry_texture.has_replacements(player)

    hl._reconcile_runtime_instances(sess, r)

    assert player in sess.ship_instances
    reps = registry_texture.replacements_for(player)
    assert len(reps) == 1
    assert reps[0][0] == "ID"
    assert reps[0][1].lower().endswith("dauntless.tga")

    registry_texture.reset()
    _set_current_game(None)
    App.g_kSetManager.DeleteAllSets()


def test_reconcile_no_qb_default_outside_quickbattle(monkeypatch):
    """A non-QuickBattle mission session must NOT auto-apply a registry to its
    Federation player — campaign missions drive registries via scripted
    ReplaceTexture, and the default would override their intent."""
    from engine import host_loop as hl
    from engine.core.game import Game, _set_current_game
    from engine.appc import registry_texture
    _force_nif(monkeypatch, hl)
    registry_texture.reset()
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    player = _add_ship(s, "player")
    player.SetScript("ships.Galaxy")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    sess = hl.MissionSession(mission_name="Maelstrom.E1M1")
    r = _FakeRenderer()

    hl._reconcile_runtime_instances(sess, r)

    assert player in sess.ship_instances
    assert not registry_texture.has_replacements(player)

    registry_texture.reset()
    _set_current_game(None)
    App.g_kSetManager.DeleteAllSets()


def test_reconcile_no_player_change_does_not_call_callback(monkeypatch):
    """If Game.GetPlayer() is unchanged, session.player is left alone and the
    retarget callback is not invoked."""
    from engine import host_loop as hl
    from engine.core.game import Game, _set_current_game
    _force_nif(monkeypatch, hl)
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    player = _add_ship(s, "player")

    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)
    sess.player = player

    retargeted = []
    hl._reconcile_runtime_instances(
        sess, r, on_player_change=lambda p: retargeted.append(p))

    assert sess.player is player
    assert retargeted == []

    _set_current_game(None)
    App.g_kSetManager.DeleteAllSets()
