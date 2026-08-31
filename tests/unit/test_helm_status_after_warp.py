"""The Helm officer's status must return to "Waiting" once a warp engages.

Stock BC does this inside Bridge/HelmMenuHandlers.py:WarpPressed (:871-872):
pressing the warp button sets the Helm status back to "Waiting", clearing the
"ReadyToWarp" that Bridge/HelmCharacterHandlers.py:SetCourse (:209) put there
when the course was picked.

Our CEF Set Course modal replaced BC's SortedRegionMenu, so the host reproduces
BOTH halves itself: engine/bridge_officers.py:announce_course_set fires
ET_SET_COURSE (which sets ReadyToWarp), and host_loop's on_warp_engage
deliberately bypasses WarpPressed entirely -- see the comment at
host_loop.py:6742-6748, which defers WarpPressed's camera/cinematic/control
work to later stages. engine/appc/warp_gates.py reproduces WarpPressed's
GATING, but nothing reproduced this side effect, so the Helm box sat on
"Ready to warp to destination" for the rest of the session -- observed live at
Starbase 12 after a completed warp.

These tests pin both halves, so a regression in either direction fails: the
status must BE ReadyToWarp after a course is set, and must NOT be afterwards.
"""
import App
import pytest

from engine.appc.characters import CharacterClass


@pytest.fixture
def helm():
    """A Helm officer reachable the way the SDK reaches it."""
    from engine.appc.sets import SetClass

    bridge = SetClass()
    bridge.SetName("bridge")
    App.g_kSetManager._sets["bridge"] = bridge

    char = CharacterClass()
    char.SetName("Helm")
    bridge.AddObjectToSet(char, "Helm")
    yield char
    App.g_kSetManager._sets.pop("bridge", None)


def _status(char):
    return str(char.GetStatus())


def test_warp_engage_clears_the_ready_to_warp_status(helm):
    from engine.bridge_officers import announce_warp_engaged

    helm.SetStatus("Ready to warp to destination")
    assert _status(helm) == "Ready to warp to destination"

    announce_warp_engaged()

    assert _status(helm) != "Ready to warp to destination", (
        "Helm still advertises a pending warp after one engaged -- this is the "
        "stale box seen live at Starbase 12")


def test_warp_engage_sets_waiting(helm):
    """BC writes the CharacterStatus.tgl 'Waiting' string. Headless has no TGL,
    so assert the resolved value matches what SetStatus stores for that key
    rather than hard-coding English."""
    from engine.bridge_officers import announce_warp_engaged, _waiting_status

    helm.SetStatus("Ready to warp to destination")
    announce_warp_engaged()

    assert _status(helm) == str(_waiting_status())


def test_warp_engage_is_safe_with_no_bridge_set():
    """on_warp_engage runs on a CEF click; a mission swap can leave no bridge
    set momentarily. It must not raise into the CEF boundary, where a raise is
    swallowed and the warp would silently not happen."""
    from engine.bridge_officers import announce_warp_engaged

    App.g_kSetManager._sets.pop("bridge", None)
    announce_warp_engaged()  # must not raise


def test_warp_engage_does_not_activate_the_officer(helm):
    """BC's WarpPressed also calls pHelm.SetActive(1), cleared later by
    HelmCharacterHandlers.AIDone -- which our warp path never reaches. Setting
    it here would leave the officer highlighted forever: the same class of
    stuck state this fix removes. Deliberately omitted."""
    from engine.bridge_officers import announce_warp_engaged

    helm.SetActive(0)
    announce_warp_engaged()

    assert helm.IsActive() == 0


def test_the_warp_engage_path_actually_calls_it():
    """Guard against dead code: the fix only works if on_warp_engage invokes it.

    on_warp_engage is a closure inside host_loop.run(), so it cannot be imported
    and called directly; this asserts the call site exists next to execute_warp.
    Crude, but it catches the specific failure of shipping a correct function
    nothing ever runs -- which is exactly the shape of the bug being fixed
    (warp_gates faithfully reproduced WarpPressed's gating while its side
    effects were quietly dropped).
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine/host_loop.py").read_text()
    assert "announce_warp_engaged()" in src
    engage = src[src.index("def on_warp_engage"):]
    # Slice on the CALL, not the bare name: the explanatory comment above it
    # also says "execute_warp", and matching that cut the slice too early.
    engage = engage[:engage.index("_w.execute_warp(")]
    assert "announce_warp_engaged()" in engage, (
        "announce_warp_engaged must be called inside on_warp_engage, before "
        "execute_warp -- matching BC's order in WarpPressed")
