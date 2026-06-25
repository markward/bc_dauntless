"""CrewSpeechBus -- the one global bridge-speech channel.

Bridge scripts call CharacterClass.SpeakLine / SayLine, which resolve the
line's subtitle text and voice wav and hand them here. The bus owns priority
arbitration (only one crew member talks at a time; a strictly lower-priority
line is dropped while a line is still live) and routes the accepted line to
the subtitle surface (engine/appc/windows._SubtitleWindow) and the audio
subsystem (engine/audio/tg_sound) best-effort.

Spec: docs/superpowers/specs/2026-06-13-bridge-crew-speech-design.md
"""
from __future__ import annotations

import time
from typing import Optional

import engine.dev_mode as dev_mode

_MIN_DURATION_S = 2.0
_MAX_DURATION_S = 8.0
_WORDS_PER_SECOND = 2.5

# Global subtitle display flag (Configuration > Gameplay). Gates on-screen text
# only — line duration + voice playback are unaffected. Default ON; applied live
# by the configuration panel; not persisted across launches.
_subtitles_enabled: bool = True


def set_subtitles_enabled(on: bool) -> None:
    global _subtitles_enabled
    _subtitles_enabled = bool(on)


def subtitles_enabled() -> bool:
    return _subtitles_enabled


# Global "Disable Annoying Dialogue" flag (Configuration > Gameplay). When ON
# (default), any line whose key is in _ANNOYING_LINE_KEYS is dropped entirely in
# emit() — no voice, no subtitle — so the owning CharacterAction completes
# instantly. Applied live by the configuration panel; not persisted.
_annoying_dialogue_disabled: bool = True

# Line keys silenced when _annoying_dialogue_disabled is ON. Extensible: add
# more grating intro/tutorial line keys here as they surface.
_ANNOYING_LINE_KEYS = frozenset({"QBExposition"})


def set_annoying_dialogue_disabled(on: bool) -> None:
    global _annoying_dialogue_disabled
    _annoying_dialogue_disabled = bool(on)


def annoying_dialogue_disabled() -> bool:
    return _annoying_dialogue_disabled


def _estimate_duration(text: Optional[str], wav: Optional[str]) -> float:
    """Coarse reading-speed dwell. Drives both the on-screen time and the
    bus free-up time, so they can never disagree. A voice-only line (no text,
    only a wav path) falls back to the minimum dwell."""
    source = text or wav or ""
    words = max(1, len(source.split()))
    secs = words / _WORDS_PER_SECOND
    return max(_MIN_DURATION_S, min(_MAX_DURATION_S, secs))


class CrewSpeechBus:
    def __init__(self) -> None:
        self._active_priority: int = -1
        self._active_expiry: float = 0.0
        self._active_handle = None   # _PlayingSound of the line on the channel

    def reset(self) -> None:
        self._stop_active_voice()
        self._active_priority = -1
        self._active_expiry = 0.0

    def _stop_active_voice(self) -> None:
        """Stop whatever voice currently holds the channel (best-effort)."""
        h = self._active_handle
        self._active_handle = None
        if h is not None:
            try:
                h.Stop()
            except Exception:
                pass

    def speak(self, speaker, text, wav, priority, now=None) -> float:
        """Arbitrate one line. Returns its duration in seconds (0.0 if dropped).
        The returned value also drives the subtitle dwell and the bus free-up,
        so they can never disagree, and is what gates the owning action's
        completion."""
        if now is None:
            now = time.monotonic()
        if text is None and wav is None:
            return 0.0  # nothing to say — don't occupy the channel
        priority = int(priority)
        line_live = now < self._active_expiry
        if line_live and priority < self._active_priority:
            return 0.0  # a higher-priority line is still talking
        # If a line is still live, this one preempts it: stop the previous voice
        # so two lines never overlap audibly (BC plays one crew/comm voice at a
        # time — a new equal-or-higher line cuts the old). When the channel is
        # already free (the prior line ended), there is nothing to stop. Within
        # one gated sequence the next line starts exactly as the prior ends, so
        # no real overlap occurs; this only bites when two sequences collide.
        if line_live:
            self._stop_active_voice()
        self._active_priority = priority
        # Real decoded length when the voice is loadable; estimate otherwise.
        real, self._active_handle = self._play_voice(str(wav)) if wav else (0.0, None)
        duration = real if real > 0.0 else _estimate_duration(text, wav)
        self._active_expiry = now + duration
        if text:
            self._route_subtitle(str(speaker), str(text), duration)
        return duration

    # -- Best-effort routing (never raises) ----------------------------------
    def _route_subtitle(self, speaker, text, duration) -> None:
        if not subtitles_enabled():
            return
        try:
            import App
            sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
        except Exception:
            sub = None
        if sub is not None and hasattr(sub, "set_crew_line"):
            sub.set_crew_line(speaker, text, duration)

    def _play_voice(self, wav):
        """Play the voice line. Returns (duration_seconds, playing_handle).
        The handle (tg_sound._PlayingSound or None) lets the bus stop this voice
        if a later line preempts it. Best-effort: (0.0, None) on any failure."""
        try:
            from engine.audio.tg_sound import TGSoundManager, TGSound
            mgr = TGSoundManager.instance()
            snd = mgr.GetSound(wav)
            if snd is None:
                # The wav path doubles as the GetSound name key.
                snd = mgr.LoadSound(wav, wav, TGSound.LS_STREAMED)
            if snd is None:
                return 0.0, None
            snd.SetVoice()
            handle = snd.Play()
            return mgr.duration_for(wav), handle
        except Exception as _e:
            dev_mode.log_swallowed("play crew speech sound", _e)
            return 0.0, None


def emit(speaker, db, line_id, priority) -> float:
    """Resolve a line's subtitle text and voice wav from a localization DB,
    then feed the speech bus. Single home for the HasString gate +
    isinstance(str) stub-DB guards shared by SpeakLine/SayLine and
    CharacterAction speak actions. Subtitle *display* is gated globally by
    subtitles_enabled() inside the bus; text is always resolved here so the
    duration estimate (text-only lines) is unaffected by the toggle."""
    line = str(line_id)
    if annoying_dialogue_disabled() and line in _ANNOYING_LINE_KEYS:
        return 0.0  # silenced annoying line: no voice, no subtitle
    text = None
    if db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None   # drop stub-DB repr
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:         # drop stub-DB / empty
        wav = None
    return bus().speak(speaker, text, wav, int(priority))


def _mission_database():
    """MissionLib.GetMissionDatabase(), best-effort (None if unavailable)."""
    try:
        import MissionLib
        return MissionLib.GetMissionDatabase()
    except Exception:
        return None


def _rand5() -> int:
    """App.g_kSystemWrapper.GetRandomNumber(5) (0..4), best-effort -> 0."""
    try:
        import App
        return int(App.g_kSystemWrapper.GetRandomNumber(5))
    except Exception:
        return 0


def acknowledge(character) -> None:
    """Spoken acknowledgement for a bridge officer (subtitle + best-effort
    voice). Mirrors BridgeHandlers.CharacterInteraction's line selection;
    falls back to a literal 'Aye, Captain.' so the ack is always visible."""
    if character is None:
        return
    from engine.appc.ai import CSP_NORMAL
    name = character.GetCharacterName()
    yes = character.GetYesSir()
    if yes:
        db = _mission_database()
        line = str(yes)
    else:
        db = character.GetDatabase()
        line = name + "Sir" + str(_rand5() + 1)   # 1..5
    text = None
    if db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None
    if not text:
        text = "Aye, Captain."                      # guaranteed-visible fallback
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:
        wav = None
    bus().speak(name, text, wav, CSP_NORMAL)


_bus: Optional[CrewSpeechBus] = None


def bus() -> CrewSpeechBus:
    """Return the process-wide speech bus (created on first use)."""
    global _bus
    if _bus is None:
        _bus = CrewSpeechBus()
    return _bus
