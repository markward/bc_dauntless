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

import logging
import time
from typing import Optional

# TEMP DIAGNOSTIC (crew-voice verification) — remove once audio is confirmed.
_diag = logging.getLogger("crew_speech.diag")

_MIN_DURATION_S = 2.0
_MAX_DURATION_S = 8.0
_WORDS_PER_SECOND = 2.5


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

    def reset(self) -> None:
        self._active_priority = -1
        self._active_expiry = 0.0

    def speak(self, speaker, text, wav, priority, now=None) -> bool:
        """Arbitrate one line. Returns True if accepted, False if dropped."""
        if now is None:
            now = time.monotonic()
        if text is None and wav is None:
            return False  # nothing to say — don't occupy the channel
        priority = int(priority)
        line_live = now < self._active_expiry
        if line_live and priority < self._active_priority:
            return False  # a higher-priority line is still talking
        duration = _estimate_duration(text, wav)
        self._active_priority = priority
        self._active_expiry = now + duration
        if text:
            self._route_subtitle(str(speaker), str(text), duration)
        if wav:
            self._play_voice(str(wav))
        return True

    # -- Best-effort routing (never raises) ----------------------------------
    def _route_subtitle(self, speaker, text, duration) -> None:
        try:
            import App
            sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
        except Exception:
            sub = None
        if sub is not None and hasattr(sub, "set_crew_line"):
            sub.set_crew_line(speaker, text, duration)

    def _play_voice(self, wav) -> None:
        try:
            from engine.audio.tg_sound import TGSoundManager, TGSound
            mgr = TGSoundManager.instance()
            snd = mgr.GetSound(wav)
            _diag.warning("play_voice: wav=%r cached=%s", wav, snd is not None)  # TEMP DIAGNOSTIC
            if snd is None:
                # The wav path doubles as the GetSound name key.
                snd = mgr.LoadSound(wav, wav, TGSound.LS_STREAMED)
                _diag.warning("play_voice: LoadSound -> %s", snd is not None)  # TEMP DIAGNOSTIC
            if snd is None:
                _diag.warning("play_voice: NO SOUND for wav=%r (file missing/undecodable?)", wav)  # TEMP DIAGNOSTIC
                return
            snd.SetVoice()
            handle = snd.Play()
            _diag.warning("play_voice: Play -> handle=%r", handle)  # TEMP DIAGNOSTIC
        except Exception:
            _diag.exception("play_voice: EXCEPTION for wav=%r", wav)  # TEMP DIAGNOSTIC


def emit(speaker, db, line_id, priority, *, voice_only) -> None:
    """Resolve a line's subtitle text (unless voice_only) and voice wav from a
    localization DB, then feed the speech bus. Single home for the HasString
    gate + isinstance(str) stub-DB guards shared by SpeakLine/SayLine and
    CharacterAction speak actions."""
    line = str(line_id)
    text = None
    if not voice_only and db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None   # drop stub-DB repr
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:         # drop stub-DB / empty
        wav = None
    bus().speak(speaker, text, wav, int(priority))


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
    # TEMP DIAGNOSTIC (crew-voice verification) — remove once audio is confirmed.
    _diag.warning("acknowledge: speaker=%r line=%r db=%s text=%r wav=%r",
               name, line, type(db).__name__, text, wav)
    bus().speak(name, text, wav, CSP_NORMAL)


_bus: Optional[CrewSpeechBus] = None


def bus() -> CrewSpeechBus:
    """Return the process-wide speech bus (created on first use)."""
    global _bus
    if _bus is None:
        _bus = CrewSpeechBus()
    return _bus
