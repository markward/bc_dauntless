"""Phase-1 shim implementation of BC's TGSound / TGSoundManager.

Delegates to the C++ audio subsystem exposed as _dauntless_host.audio. Surface
matches sdk/Build/scripts/App.py wherever LoadTacticalSounds.py, LoadBridge.py,
or hardpoint files touch it; the rest of the SDK surface stays stubbed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    import _dauntless_host
    _audio = _dauntless_host.audio
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
    """Lightweight handle returned by TGSound.Play(); supports Stop().

    Note on lifetime: callers do NOT need to hold the handle alive. One-shot
    sounds (PlaySound) are fire-and-forget — the C++ AudioSystem reaps them
    after they finish. Looping sources are held alive by the subscriber that
    owns them (e.g. engine_rumble._active[ship]). Do not add __del__ → Stop:
    one-shots are typically returned to locals that go out of scope before
    any audio plays, and a __del__ stop would silently mute every PlaySound.
    """

    __slots__ = ("_pid",)

    def __init__(self, pid: int) -> None:
        self._pid = pid

    def Stop(self) -> None:
        if _audio and self._pid:
            _audio.stop(self._pid)
        self._pid = 0

    def SetPosition(self, x: float, y: float, z: float) -> None:
        if _audio and self._pid:
            _audio.set_position(self._pid, x, y, z)

    def SetGain(self, gain: float) -> None:
        if _audio and self._pid:
            _audio.set_gain(self._pid, float(gain))


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
        self._priority = 0.0
        self._min_dist = 100.0
        self._max_dist = 100000.0
        self._loaded = _audio is not None and _audio.get_sound(name) != 0
        self._active: list[_PlayingSound] = []
        self._region = None  # set by TGSoundRegion.AddSound; gates launch gain

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

    def SetPriority(self, priority) -> None:
        self._priority = float(priority)

    def GetPriority(self) -> float:
        return self._priority

    def SetSFX(self, *_args) -> None:       self._category_tag = "SFX"
    def IsSFX(self) -> int:                  return 1 if self._category_tag == "SFX" else 0
    def SetVoice(self, *_args) -> None:      self._category_tag = "Voice"
    def IsVoice(self) -> int:                return 1 if self._category_tag == "Voice" else 0
    def SetInterface(self, *_args) -> None:  self._category_tag = "Interface"
    def IsInterface(self) -> int:            return 1 if self._category_tag == "Interface" else 0

    def Play(self, attach_node: int = 0, position=None) -> Optional[_PlayingSound]:
        if not _audio or not self._loaded:
            return None
        # Drop handles we explicitly stopped earlier so the list can't grow
        # without bound across repeated one-shot plays.
        self._active = [h for h in self._active if h._pid]
        factor = self._region.filter_factor() if self._region is not None else 1.0
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain * factor,
            category=self._category_tag, attach_node=int(attach_node),
            position=position,
        )
        if pid == 0:
            return None
        handle = _PlayingSound(pid)
        self._active.append(handle)
        if self._positional or attach_node != 0 or position is not None:
            _audio.set_min_max_distance(pid, self._min_dist, self._max_dist)
        return handle

    # No-ops kept for the wider SDK surface (callers exist; behaviour deferred).
    def PlayAndNotify(self, *_args, **_kw): return self.Play()
    def Stop(self):
        """Stop every handle this sound started (real Appc TGSound.Stop).

        Used by region muting and to silence the SDK's load-time AmbBridge
        play when the player isn't on the bridge.
        """
        for h in self._active:
            h.Stop()
        self._active = []
    def Pause(self): pass
    def Unpause(self): pass
    def SetSingleShot(self, *_a): pass
    def IsSingleShot(self): return 0
    def AttachToNode(self, *_a): pass
    def DetachFromNode(self, *_a): pass
    def SetPosition(self, *_a): pass
    def SetOrientation(self, *_a): pass
    def GetDuration(self) -> float:
        if _audio is None:
            return 0.0
        try:
            return float(_audio.get_duration(self._name))
        except Exception:
            return 0.0

    def GetSoundName(self): return self._name
    def GetFileName(self): return self._name
    def Is3D(self): return 1 if self._positional else 0
    def IsStreamed(self): return 0


class TGSoundRegion:
    """Headless shim for Appc's TGSoundRegion.

    A named bucket of sounds with a filter that can mute / muffle the whole
    region. The SDK only ever uses the "bridge" region with FT_NONE
    (LoadBridge.py:353-356), but we honour FT_MUTE/FT_MUFFLE actively so the
    surface behaves like the original.
    """

    # Filter types. Values are ours to define — the SDK references them only
    # symbolically (App.TGSoundRegion.FT_NONE), never as integer literals.
    FT_NONE = 0
    FT_MUTE = 1
    FT_MUFFLE = 2

    # FT_MUFFLE is BC's lowpass; we approximate it with a gain cut.
    _MUFFLE_FACTOR = 0.3

    def __init__(self, name: str) -> None:
        self._name = name
        self._filter = TGSoundRegion.FT_NONE
        self._sounds: list[TGSound] = []

    def filter_factor(self) -> float:
        if self._filter == TGSoundRegion.FT_MUTE:
            return 0.0
        if self._filter == TGSoundRegion.FT_MUFFLE:
            return TGSoundRegion._MUFFLE_FACTOR
        return 1.0

    def SetFilter(self, ft) -> None:
        self._filter = int(ft)
        factor = self.filter_factor()
        for snd in self._sounds:
            for h in snd._active:
                if h._pid:
                    h.SetGain(snd._gain * factor)

    def AddSound(self, snd) -> None:
        if snd is None:  # a failed LoadSoundInGroup returns None
            return
        if snd not in self._sounds:
            self._sounds.append(snd)
        snd._region = self

    def RemoveSound(self, snd) -> None:
        if snd in self._sounds:
            self._sounds.remove(snd)
        if snd is not None and getattr(snd, "_region", None) is self:
            snd._region = None


_regions: dict[str, TGSoundRegion] = {}


def TGSoundRegion_GetRegion(name: str) -> TGSoundRegion:
    r = _regions.get(name)
    if r is None:
        r = TGSoundRegion(name)
        _regions[name] = r
    return r


def TGSoundRegion_Create(name: str) -> TGSoundRegion:
    return TGSoundRegion_GetRegion(name)


class TGSoundManager:
    _instance: "Optional[TGSoundManager]" = None

    def __init__(self) -> None:
        self._sounds: dict[str, TGSound] = {}
        self._groups: dict[str, set[str]] = {}

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

    def LoadSoundInGroup(self, path: str, name: str, group: str) -> Optional[TGSound]:
        """Load a sound and tag it as a member of `group`.

        Mirrors Appc Game.LoadSoundInGroup. Bridge sounds are non-positional,
        so we load them streamed (2D). Returns the TGSound so the SDK can chain
        .SetVolume(); returns None on load failure.
        """
        snd = self.LoadSound(path, name, TGSound.LS_STREAMED)
        if snd is not None:
            self._groups.setdefault(group, set()).add(name)
        return snd

    def DeleteAllSoundsInGroup(self, group: str) -> None:
        for name in self._groups.pop(group, set()):
            snd = self._sounds.pop(name, None)
            if snd is not None:
                snd.Stop()

    def StopAllSoundsInGroup(self, group: str) -> None:
        for name in self._groups.get(group, set()):
            snd = self._sounds.get(name)
            if snd is not None:
                snd.Stop()

    def duration_for(self, name: str) -> float:
        """Real decoded length (seconds) of a loaded sound, else 0.0.

        0.0 covers: no audio backend (tests), sound not loaded, or a
        zero-length/undecodable buffer. Callers treat 0.0 as 'complete inline'.
        """
        if _audio is None:
            return 0.0
        try:
            return float(_audio.get_duration(name))
        except Exception:
            return 0.0

    def GetSound(self, name: str) -> Optional[TGSound]:
        return self._sounds.get(name)

    def PlaySound(self, name: str) -> Optional[_PlayingSound]:
        snd = self._sounds.get(name)
        return None if snd is None else snd.Play()


# Subset of sdk/Build/scripts/LoadTacticalSounds.py + LoadBridge.py LoadSounds()
# that we need on first hearing. Quickbattle's full sound boot is not yet
# wired into our headless host, so init_audio() registers these directly
# until LoadTacticalSounds is properly invoked.
_DEFAULT_3D_SOUNDS: tuple[tuple[str, str], ...] = (
    ("sfx/engine1.wav", "Federation Engines"),
    ("sfx/engine2.wav", "Klingon Engines"),
    ("sfx/engine2.wav", "Romulan Engines"),
    ("sfx/engine2.wav", "Ferengi Engines"),
    ("sfx/engine2.wav", "Cardassian Engines"),
    ("sfx/engine1.wav", "Kessok Engines"),
)
_DEFAULT_2D_SOUNDS: tuple[tuple[str, str], ...] = (
    ("sfx/redalert.wav",       "RedAlertSound"),
    ("sfx/yellowalert.wav",    "YellowAlertSound"),
    ("sfx/greenalert.wav",     "GreenAlertSound"),
    ("sfx/bridge2.loop.wav",   "AmbBridge"),
)


def register_default_sounds() -> None:
    """Register engine + alert sounds with TGSoundManager.

    Idempotent: existing names and missing WAV files are silently skipped.
    Called from host_loop.init_audio() so the SDK names resolve before the
    first ship spawn / alert transition.
    """
    mgr = TGSoundManager.instance()
    for path, name in _DEFAULT_3D_SOUNDS:
        if mgr.GetSound(name) is None:
            mgr.LoadSound(path, name, TGSound.LS_3D)
    for path, name in _DEFAULT_2D_SOUNDS:
        if mgr.GetSound(name) is None:
            # Any loadspec other than LS_3D is treated as non-positional by
            # the shim. LS_STREAMED is the value SDK code happens to use for
            # streamed assets, but here it just means "ambient, not 3D."
            mgr.LoadSound(path, name, TGSound.LS_STREAMED)


# Module-level singleton. App.py imports this name directly, which binds it
# at App's import time — any future production code path that resets
# TGSoundManager._instance must also rebind App.g_kSoundManager (see the
# test helpers below for the pattern).
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
    _regions.clear()
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
    _regions.clear()
    # Mirror init_audio_for_tests: push None into App's namespace so the
    # module-level binding doesn't silently keep a stale manager alive.
    if "App" in sys.modules:
        sys.modules["App"].g_kSoundManager = None
