"""Runtime glue for bridge lip-sync.

Wires the model-agnostic `LipSyncController` (engine/lip_sync.py) to the live
engine: subscribes to crew-speech, resolves the speaking officer's render
instance by name, and drives `renderer.set_officer_face` each frame. Idle
blinking is layered on top for non-speaking officers.

Kept separate from `engine/lip_sync.py` so that module stays pure/testable; this
one is the BC-specific sink + cue wiring.
"""
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

from engine.appc import crew_speech
from engine.appc.lip_data import parse_lip, lip_path_for, LipSegment
from engine.appc.lip_visemes import load_viseme_table
from engine.lip_sync import LipSyncController, BlinkScheduler

# Many BC voice lines ship no .LIP (e.g. ~half the XO bank). The original engine
# falls back to a generic open/close "lip flap" for the line's duration. Mirror
# that: alternate an open viseme (code 32 -> 'e') with neutral every half-cycle.
_FLAP_PERIOD = 0.18  # seconds per open or closed half-cycle


def _flap_segments(duration: float):
    segs, t, i = [], 0.0, 0
    while t < duration - 1e-3:
        d = min(_FLAP_PERIOD, duration - t)
        segs.append(LipSegment(32 if (i % 2 == 0) else 0, t, d))
        t += d
        i += 1
    return segs

# crew_speech hands us the DB-stored voice filename, which is game-relative
# (the audio system resolves it under game/, same as engine.audio.tg_sound's
# _resolve_sfx_path). Resolve it the same way before pairing the sibling .LIP.
_GAME_DIR = Path(__file__).resolve().parents[1] / "game"

# Optional diagnostic — set LIPSYNC_DEBUG=1 to print why each line did/didn't
# drive lip-sync (which slots loaded, .LIP vs flap, speaker resolution).
_DEBUG = os.environ.get("LIPSYNC_DEBUG", "0") != "0"


def _abs_sfx(wav: str) -> str:
    p = Path(wav)
    if p.is_absolute() or p.is_file():
        return str(p)
    return str(_GAME_DIR / wav)


class LipSyncRuntime:
    def __init__(self, renderer, get_characters, rng=None):
        self._r = renderer
        self._get_characters = get_characters  # () -> iterable of CharacterClass
        self._ctrl = LipSyncController(sink=self._sink, table=load_viseme_table())
        self._blink = BlinkScheduler(rng=(rng or random.Random(0xB11E)).random)
        self._name_iid: dict = {}   # name -> iid cache (officers are stable per load)
        self._blinking: set = set()  # officers currently mid-blink (for neutral restore)
        crew_speech.add_speech_listener(self._on_speech)

    # -- name -> render instance -------------------------------------------
    def _resolve(self, name):
        iid = self._name_iid.get(name)
        if iid is not None:
            return iid
        for ch in self._get_characters() or ():
            if getattr(ch, "_character_name", None) == name:
                iid = getattr(ch, "_render_instance", None)
                if iid is not None:
                    self._name_iid[name] = iid
                return iid
        return None

    # -- controller sink ----------------------------------------------------
    def _sink(self, name, slot_a, slot_b, mix):
        iid = self._resolve(name)
        if iid is not None:
            self._r.set_officer_face(iid, slot_a, slot_b, mix)

    # -- crew-speech cue ----------------------------------------------------
    def _on_speech(self, speaker, wav, duration, now):
        lip = lip_path_for(_abs_sfx(wav)) if wav else None
        segs = []
        if lip:
            try:
                segs = parse_lip(lip)
            except Exception:
                segs = []
        # A VOICE line with no phoneme data -> generic flap for its duration
        # (BC's fallback), so the mouth still moves while the officer talks. A
        # text-only line (no wav) never animates the mouth.
        flap = False
        if not segs and wav and duration and duration > 0.0:
            segs = _flap_segments(float(duration))
            flap = bool(segs)
        if _DEBUG:
            iid = self._resolve(str(speaker))
            print(f"[lipsync] speak speaker={speaker!r} wav={wav!r} "
                  f"lip={'Y' if lip else ('flap' if flap else 'N')} "
                  f"segs={len(segs)} iid={'Y' if iid is not None else 'N'}",
                  file=sys.stderr)
        if segs:
            self._ctrl.start(str(speaker), segs, now)

    # -- per-frame tick (now = time.monotonic, matching crew_speech) --------
    def update(self, now=None):
        if now is None:
            now = time.monotonic()
        self._ctrl.update(now)
        # Idle blink for placed officers that aren't currently speaking. Only
        # touch the face while a blink is active (or to restore neutral once it
        # ends), so non-blinking idle officers stay on the byte-identical path.
        for ch in self._get_characters() or ():
            name = getattr(ch, "_character_name", None)
            iid = getattr(ch, "_render_instance", None)
            if not name or iid is None or name in self._ctrl._active:
                continue
            slot = self._blink.slot_at(name, now)
            if slot is not None:
                self._r.set_officer_face(iid, slot, slot, 0.0)
                self._blinking.add(name)
            elif name in self._blinking:
                self._r.set_officer_face(iid, "neutral", "neutral", 0.0)
                self._blinking.discard(name)

    def clear(self):
        """Reset on mission swap (officers are rebuilt; caches go stale)."""
        self._ctrl.clear()
        self._name_iid.clear()
        self._blinking.clear()

    def close(self):
        crew_speech.remove_speech_listener(self._on_speech)
