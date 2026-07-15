# engine/bridge_idle_gestures.py
"""Per-character idle ambient gesture scheduler.

Each visible officer runs an independent random timer. On fire we pick one of
its registered AddRandomAnimation entries (respecting SITTING_ONLY/STANDING_ONLY
mode), call the SDK's CommonAnimations builder to get the gesture's clip list,
and submit it to BridgeCharacterAnimController at idle priority. The clip CHOICES
come entirely from the SDK; we own only the timing.
"""
import importlib

from engine.appc.characters import CharacterClass


def build_sequence_clips(module_path, character, anim_mgr):
    """Resolve "pkg.mod.Func", call Func(character) to get a TGSequence, and
    flatten it to [(nif_path, duration), ...]. Returns [] if anything is
    unavailable (headless-safe).

    The walk is the MissionLib.GetVoiceLinesFromSequence idiom: cast each
    entry (TGSequence_Cast to recurse, CharacterAction_Cast + GetActionType
    filter to read a detail) and bound by GetNumActions — the native engine
    has no other sequence introspection. Durations have no native getter on
    CharacterAction; TGAnimAction's GetDuration IS real surface
    (TGTimedAction, sdk App.py:2474). The clip-name → NIF-path mapping is
    ours: natively these sequences just Play, so flattening for the anim
    controller is a Dauntless-side mechanism by construction."""
    try:
        mod_name, func_name = module_path.rsplit(".", 1)
        func = getattr(importlib.import_module(mod_name), func_name)
        seq = func(character)
    except Exception:
        return []
    from engine.appc.actions import TGAnimAction, TGSequence_Cast
    from engine.appc.ai import CharacterAction, CharacterAction_Cast

    def _path(name):
        return anim_mgr.path_for(name) if anim_mgr is not None else None

    clips = []

    def _walk(seq):
        n = seq.GetNumActions() if hasattr(seq, "GetNumActions") else 0
        for i in range(n):
            action = seq.GetAction(i)
            sub = TGSequence_Cast(action)
            if sub is not None:
                _walk(sub)
                continue
            if isinstance(action, TGAnimAction):
                path = _path(action._clip)
                if path:
                    # The SDK's explicit per-action SetDuration, or 0.0 if the
                    # action set none — the controller resolves a 0 to the
                    # clip's real length. NOT a fixed 1.0s fallback (that
                    # ignored both the SDK duration and the clip's natural
                    # length, so every gesture flashed for 1s).
                    clips.append((path, float(action.GetDuration())))
                continue
            ca = CharacterAction_Cast(action)
            if ca is not None and \
                    ca.GetActionType() == CharacterAction.AT_PLAY_ANIMATION_FILE:
                # Detail is a bare clip name registered via LoadAnimation
                # (see CharacterAction._queue_play_animation); no native
                # duration exists — 0.0 resolves to the clip's real length.
                path = _path(ca.GetDetail())
                if path:
                    clips.append((path, 0.0))

    _walk(seq)
    return clips


def _mode_ok(entry, character) -> bool:
    """entry = AddRandomAnimation arg-tuple; arg[1] (optional) is the posture
    mode. SITTING_ONLY skips standing officers; STANDING_ONLY skips seated."""
    if len(entry) < 2 or entry[1] is None:
        return True
    mode = entry[1]
    standing = bool(character.IsStanding())
    if mode == CharacterClass.SITTING_ONLY:
        return not standing
    if mode == CharacterClass.STANDING_ONLY:
        return standing
    return True


class IdleGestureScheduler:
    def __init__(self, rng, *, interval=(8.0, 20.0)):
        self._rng = rng
        self._lo, self._hi = interval
        self._timers = {}           # id(character) -> seconds until next gesture

    def _next_delay(self) -> float:
        return self._rng.uniform(self._lo, self._hi)

    def reset(self) -> None:
        self._timers = {}

    def update(self, dt, characters, *, renderer, anim_mgr, controller) -> None:
        for ch in characters:
            if getattr(ch, "_render_instance", None) is None:
                continue
            if ch.IsHidden():
                continue
            if ch.IsMenuUp():
                continue                     # attending the captain — no idle
            key = id(ch)
            t = self._timers.get(key)
            if t is None:
                # Initialise timer but still apply this tick's dt below.
                t = self._next_delay()
                self._timers[key] = t
            if controller.is_busy(ch):
                continue
            t -= dt
            if t > 0.0:
                self._timers[key] = t
                continue
            self._timers[key] = self._next_delay()
            entries = [e for e in getattr(ch, "_random_animations", [])
                       if e and _mode_ok(e, ch)]
            if not entries:
                continue
            entry = entries[self._rng.randrange(len(entries))]
            clips = build_sequence_clips(entry[0], ch, anim_mgr)
            if clips:
                controller.submit(ch, clips, priority=0)
