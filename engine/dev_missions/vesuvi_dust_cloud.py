"""Developer "Vesuvi Dust Cloud" mission -- perf baseline B3, run unattended.

The player Galaxy parked at Vesuvi4's own "Player Start", 335 GU outside the
cloud's MetaNebula sphere and facing into it, so the exterior camera looks
past the hull into the system nebula and dust passes. No NPCs and no
scripted events: the only rocks are Vesuvi4_S's stock asteroids plus what
the Vesuvi radial profile adds, far fewer than B1's belt at Haven.

The player is made immune to damage with BC's own SetInvincible. The God
Mode cheat would not do: the radiation drain and the nebula hits gate on
IsImmuneToDamage, not on combat.apply_hit's cheat check.

SETTLE_S after Initialize the run prints a `settled` line (the start of the
measured window) and, with DAUNTLESS_DEV_VIEW=exterior, switches to the
exterior view. With DAUNTLESS_DEV_AUTOQUIT=1 it then quits MEASURE_S later.
Without it the mission plays on, so it is safe to load from the dev mission
picker. DAUNTLESS_DEV_SCREENSHOT=<path.png> writes one frame SCREENSHOT_AFTER_S
into the measured window, so before/after builds picture the same moment.

    DAUNTLESS_MISSION=engine.dev_missions.vesuvi_dust_cloud DAUNTLESS_DEV_AUTOQUIT=1 \\
        DAUNTLESS_DEV_VIEW=exterior \\
        DAUNTLESS_PROFILE_FRAMES=100000000 ./build/dauntless --developer

Each step prints a `[vesuvi_dust_cloud]` line, which marks it in a profiler
log. See docs/reference/engine/perf-register.md (B3).
"""
import os

import App
import MissionLib

from engine import dev_scripted_run
from engine.dev_missions.felix_destroy import autoquit_enabled, wants_exterior_view

PLAYER_SHIP = "Galaxy"
# Long enough for the bridge, the sibling Vesuvi regions (system_loader, first
# tick) and the first nebula frames to be up before the measured window.
SETTLE_S = 5.0
MEASURE_S = 60.0
SCREENSHOT_AFTER_S = 5.0


def _log(msg: str) -> None:
    print("[vesuvi_dust_cloud] " + msg, flush=True)


def PreLoadAssets(pMission):
    import importlib
    try:
        mod = importlib.import_module("ships." + PLAYER_SHIP)
        if hasattr(mod, "PreLoadModel"):
            mod.PreLoadModel()
    except Exception:
        pass


def Initialize(pMission):
    dev_scripted_run.clear_quit_request()

    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    import Systems.Vesuvi.Vesuvi4
    Systems.Vesuvi.Vesuvi4.Initialize()
    pSet = App.g_kSetManager.GetSet("Vesuvi4")

    pPlayer = MissionLib.CreatePlayerShip(PLAYER_SHIP, pSet, "player",
                                          "Player Start")
    pPlayer.SetInvincible(1)

    pSeq = App.TGSequence_Create()
    pSeq.AppendAction(App.TGScriptAction_Create(__name__, "SettledAction"),
                      SETTLE_S)
    pSeq.Play()

    _log("player %s parked at Vesuvi4 Player Start, invincible; settle %.0f s, "
         "measure %.0f s; autoquit=%s"
         % (PLAYER_SHIP, SETTLE_S, MEASURE_S,
            "on" if autoquit_enabled() else "off"))


def screenshot_path(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get(dev_scripted_run.SCREENSHOT_ENV, "").strip() or None


def SettledAction(pAction):
    if wants_exterior_view():
        App.TopWindow_GetTopWindow().ForceTacticalVisible()
        _log("view exterior")
    _log("settled; measuring %.0f s" % MEASURE_S)
    if autoquit_enabled():
        dev_scripted_run.request_quit(MEASURE_S,
                                      "measured %.0f s" % MEASURE_S)
    if screenshot_path() is not None:
        pSeq = App.TGSequence_Create()
        pSeq.AppendAction(App.TGScriptAction_Create(__name__, "ScreenshotAction"),
                          SCREENSHOT_AFTER_S)
        pSeq.Play()
    return 0


def ScreenshotAction(pAction):
    import engine.renderer as r
    path = screenshot_path()
    r.request_frame_png(path)
    _log("screenshot %s, %.0f s after settled" % (path, SCREENSHOT_AFTER_S))
    return 0
