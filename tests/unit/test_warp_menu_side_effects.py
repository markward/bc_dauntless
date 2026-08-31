"""WarpPressed's two menu side effects, which our warp path never reproduced.

Stock BC's Bridge/HelmMenuHandlers.py:WarpPressed does four things after the
gating passes (:855-877):

    pHelmMenu.SetDisabled()                  # <- this file, part 1
    BridgeHandlers.DropMenusTurnBack()       # <- this file, part 2
    ...
    App.TGScriptAction_Create(..., "StartCinematicMode", 0).Play()
    MissionLib.RemoveControl()

Our host's on_warp_engage deliberately bypasses WarpPressed;
engine/appc/warp_gates.py reproduced its GATING and the side effects were
dropped. The last two already happen inside our own warp sequence (verified
live: the player loses control and gets a cinematic exterior shot), but the
two menu effects did not -- verified live: the Helm menu stayed clickable
during a warp, and a menu left open stayed open.

The re-enable half is the one that matters most. BC pairs SetDisabled() with
PostWarpEnableMenu (HelmMenuHandlers.py:918), scheduled INSIDE its warp
sequence (WarpSequence.py:324). Our WarpSequence_Create is our own, so
nothing scheduled it; shipping the disable without the re-enable would leave
the Helm menu dead for the rest of the session -- the same stuck-state class
as the "Ready to warp" status bug this follows.
"""
import App
import pytest

from engine.appc.characters import CharacterClass, STMenu, STTopLevelMenu


@pytest.fixture
def bridge():
    from engine.appc.sets import SetClass

    kset = SetClass()
    kset.SetName("bridge")
    App.g_kSetManager._sets["bridge"] = kset
    yield kset
    App.g_kSetManager._sets.pop("bridge", None)


@pytest.fixture
def helm(bridge):
    """A Helm officer with a menu, reachable the way the SDK reaches it."""
    char = CharacterClass()
    char.SetName("Helm")
    char.SetMenu(STMenu())
    bridge.AddObjectToSet(char, "Helm")
    return char


# ── part 1: the disable/enable pair ────────────────────────────────

def test_engaging_a_warp_disables_the_helm_menu(helm):
    from engine.bridge_officers import disable_helm_menu

    assert helm.GetMenu().IsEnabled(), "precondition: menu starts enabled"
    disable_helm_menu()
    assert not helm.GetMenu().IsEnabled()


def test_the_warp_sequence_re_enables_the_helm_menu(helm):
    """Without this the Helm menu is dead for the rest of the session."""
    from engine.bridge_officers import disable_helm_menu, enable_helm_menu

    disable_helm_menu()
    enable_helm_menu()
    assert helm.GetMenu().IsEnabled()


def test_helm_menu_calls_are_safe_with_no_bridge_set():
    """Both run on paths where a raise is swallowed (a CEF click, and a
    TGAction inside the warp sequence), so a raise would silently drop the
    warp or the re-enable rather than surfacing."""
    from engine.bridge_officers import disable_helm_menu, enable_helm_menu

    App.g_kSetManager._sets.pop("bridge", None)
    disable_helm_menu()   # must not raise
    enable_helm_menu()    # must not raise


def test_the_re_enable_is_scheduled_on_both_warp_paths():
    """WarpSequence_Create has a flythrough branch and a hard-cut branch, and
    the hard-cut branch degrades to "nothing happened" for a falsy
    destination. The menu was disabled at engage time regardless, so every
    path out must re-enable it -- including the degraded one."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine/appc/warp.py").read_text()
    body = src[src.index("def WarpSequence_Create"):src.index("def find_set_course_menu")]
    assert body.count("_EnableHelmMenuAction") == 2, (
        "expected one scheduling per branch (flythrough + hard-cut); found %d"
        % body.count("_EnableHelmMenuAction"))
    # The hard-cut branch must schedule it OUTSIDE the _module_is_empty guard:
    # a falsy destination degrades that path to "nothing happened", but the
    # menu was disabled at engage time either way.
    hard_cut = body[body.rindex("if not _module_is_empty(dest_module):"):]
    for line in hard_cut.splitlines():
        if "_EnableHelmMenuAction" in line:
            assert not line.startswith("        "), (
                "the hard-cut re-enable is indented into the "
                "_module_is_empty guard; an empty destination would leave "
                "the Helm menu disabled for the session")


# ── part 2: drop menus / turn back ─────────────────────────────────

def test_drop_menus_turn_back_turns_turned_characters_back(bridge):
    """BridgeHandlers.py:1038-1041 -- every turned character on the bridge set
    turns back. TurnBack() runs through the animation system, so assert the
    call rather than the flag (headless has no animation to complete it)."""
    from engine.appc.top_window import drop_menus_turn_back

    calls = []

    class _Spy(CharacterClass):
        def TurnBack(self, *a, **k):
            calls.append(self.GetName())
            return 1

    turned = _Spy()
    turned.SetName("Helm")
    turned.SetFlags(CharacterClass.CS_TURNED)
    bridge.AddObjectToSet(turned, "Helm")

    facing = _Spy()
    facing.SetName("XO")
    bridge.AddObjectToSet(facing, "XO")

    drop_menus_turn_back()

    assert calls == ["Helm"], (
        "only already-turned characters turn back (BC guards on IsTurned)")


def test_drop_menus_turn_back_lowers_the_open_menu(bridge, monkeypatch):
    from engine.appc import top_window

    lowered = []

    class _Spy(CharacterClass):
        def MenuDown(self, *a, **k):
            lowered.append(self.GetName())

    officer = _Spy()
    officer.SetName("Helm")
    # STTopLevelMenu, not STMenu: GetOwner/SetOwner live on the top-level
    # subclass (characters.py:263-284), which is also what BC's
    # STTopLevelMenu_GetOpenMenu returns. An STMenu here takes SetOwner
    # through __getattr__ into a silent _Stub, and GetOwner hands back
    # another _Stub -- the drop then does nothing and the test passes on a
    # double that does not mirror the real surface.
    menu = STTopLevelMenu()
    menu.SetOwner(officer)
    officer.SetMenu(menu)
    bridge.AddObjectToSet(officer, "Helm")

    monkeypatch.setattr(App, "STTopLevelMenu_GetOpenMenu", lambda: menu)
    top_window.drop_menus_turn_back()

    assert lowered == ["Helm"]


def test_drop_menus_turn_back_is_safe_with_no_bridge_set():
    from engine.appc.top_window import drop_menus_turn_back

    App.g_kSetManager._sets.pop("bridge", None)
    drop_menus_turn_back()  # must not raise


# ── the call site ──────────────────────────────────────────────────

def test_the_warp_engage_path_calls_both():
    """Guard against dead code: correct functions nothing ever runs is exactly
    the shape of the bug being fixed. on_warp_engage is a closure inside
    host_loop.run() and cannot be imported, so assert the call sites exist
    before execute_warp -- matching BC's order in WarpPressed."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine/host_loop.py").read_text()
    engage = src[src.index("def on_warp_engage"):]
    engage = engage[:engage.index("_w.execute_warp(")]
    assert "disable_helm_menu()" in engage
    assert "drop_menus_turn_back()" in engage
