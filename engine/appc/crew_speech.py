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

_MIN_DURATION_S = 2.0
_MAX_DURATION_S = 8.0
_WORDS_PER_SECOND = 2.5


def _estimate_duration(text: Optional[str], wav: Optional[str]) -> float:
    """Coarse reading-speed dwell. Drives both the on-screen time and the
    bus free-up time, so they can never disagree."""
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
            if snd is None:
                # The wav path doubles as the GetSound name key.
                snd = mgr.LoadSound(wav, wav, TGSound.LS_STREAMED)
            if snd is None:
                return
            snd.SetVoice()
            snd.Play()
        except Exception:
            pass


_bus: Optional[CrewSpeechBus] = None


def bus() -> CrewSpeechBus:
    """Return the process-wide speech bus (created on first use)."""
    global _bus
    if _bus is None:
        _bus = CrewSpeechBus()
    return _bus
