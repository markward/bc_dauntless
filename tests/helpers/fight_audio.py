"""Isolate a differential arm's hit audio from wall-clock speed and from the
fights before it.

A hit sound's pick (LoadTacticalSounds.GetRandomSound) draws on the
presentation generator now (engine/appc/presentation_rng.py), so it no longer
moves a gameplay roll; but an officer's call-out still plays an animation and
a line pick inside gameplay SDK handlers, which draw on the SDK RNG, so
whether one happens must not differ between two arms of a native-vs-Python
differential. What decided it beyond the fight itself:

* the SDK's recent-sound memory (``LoadTacticalSounds.g_dRecentSounds``):
  each pick is narrowed by it, and no mission load resets it;
* hit_feedback's audio edge stamps (keyed by ``id(ship)``: a ship of this arm
  can reuse a freed id of the last; they run on game time already);
* the WALL clock crew_speech / speak_queue's speech expiry runs on: a slower
  arm keeps an officer talking longer;
* the bridge crew's announcement throttles (``reset_crew_timestamps``).

``isolate_fight_audio(mp)`` clears both memories, runs the speech clocks on
the game clock and resets the crew's throttles, through the given monkeypatch
context (so the real values come back when it closes). Used by the K1, K2 and
K3 differentials' scenes and the K3 dispatch test.
"""
import types

import App


def isolate_fight_audio(mp) -> None:
    import LoadTacticalSounds
    from engine.appc import crew_speech, hit_feedback, speak_queue

    LoadTacticalSounds.g_dRecentSounds.clear()
    hit_feedback.reset_audio_throttle()
    clock = types.SimpleNamespace(
        monotonic=lambda: App.g_kTimerManager.get_time())
    for module in (crew_speech, speak_queue):
        mp.setattr(module, "time", clock)
    reset_crew_timestamps(mp)


def reset_crew_timestamps(mp) -> None:
    """The bridge crew's announcement throttles back at their SDK values.

    Bridge.EngineerCharacterHandlers (and its siblings) keep module globals
    such as ``g_fLastAnnounceSpecificShield``: the game time the officer last
    called out a shield change, compared against the CURRENT game time. A
    second mission load in the same process keeps the module, so the second
    arm starts at game time 0 with the first arm's last stamp (~10 s): its
    officer stays quiet where the first arm's spoke, and the animation the
    call-out plays draws on the SDK RNG -- every later draw (hit sounds, the
    death cascade's blasts) then differs between the arms. Each arm gets the
    SDK's initial 0 back, through `mp` (restored when it closes). A module
    not imported yet starts at its SDK value anyway."""
    import sys
    for name, mod in list(sys.modules.items()):
        if not (name.startswith("Bridge.") and name.endswith("Handlers")):
            continue
        for attr, value in list(vars(mod).items()):
            if (attr.startswith(("g_fLast", "g_fCommunicate", "g_fTargetSet"))
                    and type(value) in (int, float)):
                mp.setattr(mod, attr, type(value)(0))
