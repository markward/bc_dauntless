"""Phase-1 shim implementation of BC's TGSound / TGSoundManager / TGSoundAction.

Delegates to the C++ audio subsystem exposed as _open_stbc_host.audio. Surface
matches sdk/Build/scripts/App.py wherever LoadTacticalSounds.py, LoadBridge.py,
or hardpoint files touch it; the rest of the SDK surface stays stubbed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    import _open_stbc_host
    _audio = _open_stbc_host.audio
except (ImportError, AttributeError):
    _audio = None  # tests can still import the module shape


_GAME_DIR_ENV = "OPEN_STBC_GAME_DIR"


def _resolve_sfx_path(rel: str) -> str:
    base = os.environ.get(_GAME_DIR_ENV)
    if base:
        return str(Path(base) / rel)
    # Fallback to project-relative game/ directory.
    return str(Path(__file__).resolve().parents[2] / "game" / rel)


class _PlayingSound:
    """Lightweight handle returned by TGSound.Play(); supports Stop()."""

    __slots__ = ("_pid",)

    def __init__(self, pid: int) -> None:
        self._pid = pid

    def Stop(self) -> None:
        if _audio and self._pid:
            _audio.stop(self._pid)
        self._pid = 0


class TGSound:
    # Loadspec constants (match App.py).
    LS_3D = 0
    LS_STREAMED = 1
    LS_DELAY_LOADING = 2
    # Status (return values for GetStatus).
    SS_PLAYING = 0
    SS_STOPPED = 1
    SS_UNLOADED = 2
    SS_UNKNOWN = 3

    def __init__(self, name: str, positional: bool) -> None:
        self._name = name
        self._positional = positional
        self._looping = False
        self._gain = 1.0
        self._category_tag = "SFX"
        self._min_dist = 100.0
        self._max_dist = 100000.0
        self._loaded = _audio is not None and _audio.get_sound(name) != 0

    def IsLoaded(self) -> int:
        return 1 if self._loaded else 0

    def GetStatus(self) -> int:
        return TGSound.SS_STOPPED  # one-shots aren't tracked back to TGSound

    def SetLooping(self, looping) -> None:
        self._looping = bool(looping)

    def GetLooping(self) -> int:
        return 1 if self._looping else 0

    def SetVolume(self, gain) -> None:
        self._gain = float(gain)

    def GetVolume(self) -> float:
        return self._gain

    def SetMinMaxDistance(self, mn, mx) -> None:
        self._min_dist, self._max_dist = float(mn), float(mx)

    def SetSFX(self, *_args) -> None:       self._category_tag = "SFX"
    def IsSFX(self) -> int:                  return 1 if self._category_tag == "SFX" else 0
    def SetVoice(self, *_args) -> None:      self._category_tag = "Voice"
    def IsVoice(self) -> int:                return 1 if self._category_tag == "Voice" else 0
    def SetInterface(self, *_args) -> None:  self._category_tag = "Interface"
    def IsInterface(self) -> int:            return 1 if self._category_tag == "Interface" else 0

    def Play(self, attach_node: int = 0, position=None) -> Optional[_PlayingSound]:
        if not _audio or not self._loaded:
            return None
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain,
            category=self._category_tag, attach_node=int(attach_node),
            position=position,
        )
        if pid == 0:
            return None
        if self._positional or attach_node != 0 or position is not None:
            _audio.set_min_max_distance(pid, self._min_dist, self._max_dist)
        return _PlayingSound(pid)

    # No-ops kept for the wider SDK surface (callers exist; behaviour deferred).
    def PlayAndNotify(self, *_args, **_kw): return self.Play()
    def Stop(self): pass
    def Pause(self): pass
    def Unpause(self): pass
    def SetSingleShot(self, *_a): pass
    def IsSingleShot(self): return 0
    def AttachToNode(self, *_a): pass
    def DetachFromNode(self, *_a): pass
    def SetPosition(self, *_a): pass
    def SetOrientation(self, *_a): pass
    def GetSoundName(self): return self._name
    def GetFileName(self): return self._name
    def Is3D(self): return 1 if self._positional else 0
    def IsStreamed(self): return 0


class TGSoundManager:
    _instance: "Optional[TGSoundManager]" = None

    def __init__(self) -> None:
        self._sounds: dict[str, TGSound] = {}

    @classmethod
    def instance(cls) -> "TGSoundManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def LoadSound(self, path: str, name: str, loadspec: int) -> Optional[TGSound]:
        if _audio is None:
            return None
        full = _resolve_sfx_path(path) if not os.path.isabs(path) else path
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return None
        positional = (loadspec == TGSound.LS_3D)
        ok = _audio.load_sound(path=full, name=name, wav=data, positional=positional)
        if not ok:
            return None
        snd = TGSound(name, positional)
        self._sounds[name] = snd
        return snd

    def GetSound(self, name: str) -> Optional[TGSound]:
        return self._sounds.get(name)

    def PlaySound(self, name: str) -> Optional[_PlayingSound]:
        snd = self._sounds.get(name)
        return None if snd is None else snd.Play()


class TGSoundAction:
    """SDK-style action object: Play() fires the named sound."""

    def __init__(self, name: str) -> None:
        self._name = name

    def Play(self) -> None:
        TGSoundManager.instance().PlaySound(self._name)

    def Stop(self): pass
    def SetName(self, n): self._name = n


def TGSoundAction_Create(name: str) -> TGSoundAction:
    return TGSoundAction(name)


# Module-level singleton, exported as App.g_kSoundManager
g_kSoundManager = TGSoundManager.instance()


# Test helpers (NOT for production code).
def init_audio_for_tests() -> None:
    """Init the C++ audio subsystem with the null backend."""
    import sys
    if _audio is None:
        return
    _audio.init(backend="null")
    # Fresh manager state per-test.
    TGSoundManager._instance = TGSoundManager()
    global g_kSoundManager
    g_kSoundManager = TGSoundManager._instance
    # Keep App.g_kSoundManager in sync — it was bound at import time via
    # `from engine.audio.tg_sound import g_kSoundManager` so we must push
    # the new reference into the App module's namespace directly.
    if "App" in sys.modules:
        sys.modules["App"].g_kSoundManager = g_kSoundManager


def shutdown_audio_for_tests() -> None:
    import sys
    if _audio is None:
        return
    _audio.shutdown()
    TGSoundManager._instance = None
    global g_kSoundManager
    g_kSoundManager = None
    if "App" in sys.modules:
        sys.modules["App"].g_kSoundManager = None
