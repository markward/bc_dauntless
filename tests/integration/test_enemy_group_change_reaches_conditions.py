"""A ship added to a mission's enemy group after a range condition was built
is seen by that condition.

Quick Battle fills its enemy group by name when the simulation starts
(QuickBattle.py, `pEnemies.AddName(sShipName)`), after DynamicMusic's
StandardCombatMusic built its "enemies within 400" ConditionInRange on the
mission's enemy group. The SDK condition sets ObjectGroup.GROUP_CHANGED on the
group and re-aims its proximity check on ET_OBJECT_GROUP_CHANGED
(Conditions/ConditionInRange.py GroupChanged). With no such event, the
condition kept watching an empty group: the music never left
"Starting Ambient" in a fight (user report 2026-11-06)."""
import App

from tests.helpers import headless_mission


def _tick(seconds):
    from engine.core.loop import GameLoop
    loop = GameLoop()
    for _ in range(int(seconds * 30)):
        loop.tick()


def test_an_enemy_added_after_the_condition_is_in_range():
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    import loadspacehelper, MissionLib
    player = App.Game_GetCurrentPlayer()
    pSet = player.GetContainingSet()
    group = App.ObjectGroup()
    cond = App.ConditionScript_Create("Conditions.ConditionInRange", "ConditionInRange",
                                      400, player.GetName(), group)
    enemy = loadspacehelper.CreateShip("Galor", pSet, "Late Enemy", None)
    p = player.GetWorldLocation()
    enemy.SetTranslateXYZ(p.x + 100.0, p.y, p.z)
    _tick(1.0)
    assert not cond.GetStatus()                 # not in the group yet
    group.AddName("Late Enemy")
    _tick(2.0)
    assert cond.GetStatus()


def test_removing_the_enemy_from_the_group_clears_it():
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    import loadspacehelper
    player = App.Game_GetCurrentPlayer()
    pSet = player.GetContainingSet()
    group = App.ObjectGroup()
    cond = App.ConditionScript_Create("Conditions.ConditionInRange", "ConditionInRange",
                                      400, player.GetName(), group)
    enemy = loadspacehelper.CreateShip("Galor", pSet, "Late Enemy", None)
    p = player.GetWorldLocation()
    enemy.SetTranslateXYZ(p.x + 100.0, p.y, p.z)
    group.AddName("Late Enemy")
    _tick(2.0)
    assert cond.GetStatus()
    group.RemoveName("Late Enemy")
    _tick(2.0)
    assert not cond.GetStatus()


def test_the_combat_music_starts_when_an_enemy_joins_the_enemy_group():
    """The Quick Battle order: music first, then the enemy group is filled."""
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    import importlib, loadspacehelper, MissionLib, DynamicMusic
    game = App.Game_GetCurrentGame()
    importlib.import_module("Maelstrom.Maelstrom").SetupMusic(game)
    machine = DynamicMusic.pStateMachine
    player = App.Game_GetCurrentPlayer()
    enemy = loadspacehelper.CreateShip("Galor", player.GetContainingSet(), "Late Enemy", None)
    p = player.GetWorldLocation()
    enemy.SetTranslateXYZ(p.x + 100.0, p.y, p.z)
    _tick(1.0)
    assert not machine.GetMusicState().startswith("Combat")
    MissionLib.GetMission().GetEnemyGroup().AddName("Late Enemy")
    _tick(2.0)
    assert machine.GetMusicState().startswith("Combat")


class _Count:
    def __init__(self):
        self.n = 0

    def Changed(self, pEvent):
        self.n += 1


def _counted_group(flag=True):
    c = _Count()
    w = App.TGPythonInstanceWrapper()
    w.SetPyWrapper(c)
    g = App.ObjectGroup()
    if flag:
        g.SetEventFlag(App.ObjectGroup.GROUP_CHANGED)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_CHANGED, w, "Changed", g)
    return g, c, w


def test_group_changed_follows_the_original():
    """The original's rules (stbc-oracle music probe on Windows, ev_* marks):
    delivered after the edit, one event for edits in one frame, none for a
    name already present, one for removing an absent name, none without
    GROUP_CHANGED."""
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    g, c, _w = _counted_group()
    g.AddName("A")
    assert c.n == 0                     # not inside AddName
    _tick(0.1)
    assert c.n == 1
    g.AddName("A")
    _tick(0.1)
    assert c.n == 1                     # already in the group: nothing
    g.AddName("B")
    g.AddName("C")
    _tick(0.1)
    assert c.n == 2                     # two adds in one frame: one event
    g.RemoveName("Not There")
    _tick(0.1)
    assert c.n == 3                     # a remove posts even for an absent name
    g.RemoveAllNames()
    _tick(0.1)
    assert c.n == 4
    h, ch, _wh = _counted_group(flag=False)
    h.AddName("A")
    _tick(0.1)
    assert ch.n == 0                    # no GROUP_CHANGED flag: no event


def test_a_repeated_registration_is_called_twice():
    """The original calls a broadcast method handler once per registration
    (ev_dup_broadcast_method_total calls_for_one_add=2)."""
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    g, c, w = _counted_group()
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_CHANGED, w, "Changed", g)
    g.AddName("A")
    _tick(0.1)
    assert c.n == 2


def test_group_changed_doubles_per_event_and_coalesces_per_tick(monkeypatch):
    """The original, measured (stbc-oracle music probe A1, native Windows):
    ConditionInRange.GroupChanged runs SetObjects, which registers the group
    handlers again, and a repeated registration is called again, so one
    name added per frame gives GroupChanged calls 1, 2, 4, 8, 16, 32
    (cumulative 63, SetObjects 64 with the constructor's), the condition
    still watching the same group. Edits within one tick post one event."""
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    import Conditions.ConditionInRange as CIR
    C = CIR.ConditionInRange
    calls = {"gc": 0, "so": 0}
    real_gc, real_so = C.GroupChanged, C.SetObjects

    def gc(self, ev):
        calls["gc"] += 1
        return real_gc(self, ev)

    def so(self, *a):
        calls["so"] += 1
        return real_so(self, *a)

    monkeypatch.setattr(C, "GroupChanged", gc)
    monkeypatch.setattr(C, "SetObjects", so)
    player = App.Game_GetCurrentPlayer()
    group = App.ObjectGroup()
    App.ConditionScript_Create("Conditions.ConditionInRange", "ConditionInRange",
                               400, player.GetName(), group)
    assert calls == {"gc": 0, "so": 1}
    seen = []
    for i in range(6):
        group.AddName("Zed %d" % i)
        _tick(0.1)
        seen.append(calls["gc"])
    assert seen == [1, 3, 7, 15, 31, 63]
    assert calls["so"] == 64
    before = calls["gc"]
    group.AddName("Pair A")
    group.AddName("Pair B")                 # same tick: one event
    _tick(0.1)
    assert calls["gc"] - before == 64       # one event, called once per registration (64)
