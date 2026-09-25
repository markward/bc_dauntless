"""BC's warp button event (spec §1).

In BC a click on the Helm "Warp" button sends ET_WARP_BUTTON_PRESSED to the
button; its instance handlers run newest-first (engine/appc/events.py), the
missions' first and HelmMenuHandlers.WarpPressed last, and a handler that does
not CallNextHandler stops the warp. The warp itself was then built in C++
(inferred: nothing in the SDK builds it). Here the engine step takes
WarpPressed's place at the bottom of the chain: it runs our port of
WarpPressed's checks (warp_gates) and builds the warp from the whole button.
WarpPressed itself is not run -- its pre-warp camera cutscene would fight the
flythrough (spec §1, out of scope).
"""
import App

ENGINE_STEP = "engine.appc.warp_button.engine_warp_step"
_WARP_PRESSED_SUFFIX = "HelmMenuHandlers.WarpPressed"

# Tests replace the engine step's body; production leaves this None.
_engage_override = None


def is_warp_replaced(qualified_name) -> bool:
    return str(qualified_name).endswith(_WARP_PRESSED_SUFFIX)


def ensure_engine_step(button) -> None:
    """Make the engine step the OLDEST handler (index 0 == runs last)."""
    et = App.ET_WARP_BUTTON_PRESSED
    chain = button._handlers.setdefault(et, [])
    if ENGINE_STEP in chain:
        chain.remove(ENGINE_STEP)
    chain.insert(0, ENGINE_STEP)


def press(button) -> None:
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_WARP_BUTTON_PRESSED)
    evt.SetSource(button)
    evt.SetDestination(button)
    App.g_kEventManager.AddEvent(evt)


def engine_warp_step(button, event) -> None:
    if _engage_override is not None:
        _engage_override(button)
        return
    engage(button)


def is_warp_active(player) -> bool:
    eng = player.GetWarpEngineSubsystem() if hasattr(
        player, "GetWarpEngineSubsystem") else None
    return bool(eng is not None and eng.GetWarpSequence() is not None)


def engage(button) -> None:
    """The body of the former host_loop.engage_warp, moved here so the engine
    step and headless tests share it. See that function's history for why
    each guard exists (destination guard: a course-less click greyed the Helm
    menu for good).

    Deliberately does NOT bail on a None player before the gate: BC's own
    warp_gate degrades to a silent refusal for a None ship, and
    test_warp_menu_side_effects.py exercises this path with no player set up
    at all (only the gate is mocked) -- an explicit `player is None: return`
    here would skip the menu side effects that test asserts run. The ONLY
    early-return this adds over the ported checks is `is_warp_active`, which
    reads False for a None player by construction (see above).
    """
    from engine import dev_mode
    from engine.appc import warp as _w
    from engine.appc import warp_gates as _wg
    if not button or not button.GetDestination():
        if dev_mode.is_enabled():
            print("[warp] ignored: no course set", flush=True)
        return
    player = App.Game_GetCurrentPlayer()
    if player is None and _w._player_hook is not None:
        player = _w._player_hook()
    if is_warp_active(player):
        return
    result = _wg.warp_gate(player)
    if not result.allowed:
        if dev_mode.is_enabled():
            print("[warp] gated: %s (line=%s)" % (
                result.reason or "unknown", result.deny_line or "-"), flush=True)
        if result.deny_line is not None:
            _wg.speak_deny(player, result.deny_line)
        return
    # Clear Helm's "ReadyToWarp" the way SDK WarpPressed does
    # (HelmMenuHandlers.py:871-872). announce_course_set put it there;
    # bypassing WarpPressed meant nothing ever took it away, so the Helm box
    # advertised a pending warp for the rest of the session. Before
    # execute_warp, matching BC's order.
    try:
        from engine.bridge_officers import announce_warp_engaged
        announce_warp_engaged()
    except Exception as _e:
        dev_mode.log_swallowed("announce warp engaged", _e)
    # WarpPressed's other two menu side effects, in its order
    # (HelmMenuHandlers.py:862-864): grey out the Helm menu for the duration
    # of the warp, then drop any open bridge menu and turn its officers back.
    # Both were missing -- verified live: the Helm menu stayed clickable
    # mid-warp and an open menu stayed open. The matching re-enable is
    # scheduled inside the warp sequence (_EnableHelmMenuAction); without it
    # the menu never comes back -- see the destination guard above.
    try:
        from engine import bridge_officers
        from engine.appc.top_window import drop_menus_turn_back
        bridge_officers.disable_helm_menu()
        drop_menus_turn_back()
    except Exception as _e:
        dev_mode.log_swallowed("warp menu side effects", _e)
    _w.execute_warp(button)
