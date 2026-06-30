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

# Many BC voice lines ship no .LIP (e.g. ~half the XO bank). Per BC's own docs
# (sdk/lipsync.html): "If there is no .LIP file, the game will use some random
# phonemes instead." Mirror that — pick random speaking codes (varied mouth
# shapes) for the line's duration rather than a mechanical open/close. The
# controller's cross-fade smooths the random transitions.
_FLAP_PERIOD_RANGE = (0.10, 0.18)  # seconds per random phoneme


def _random_phoneme_segments(duration: float, rng, codes, period_range=_FLAP_PERIOD_RANGE):
    """Contiguous LipSegments over `duration`, each a random code from `codes`
    with a random length in `period_range` (last segment clamped to fit)."""
    if not codes:
        return []
    segs, t = [], 0.0
    while t < duration - 1e-3:
        d = min(rng.uniform(*period_range), duration - t)
        segs.append(LipSegment(rng.choice(codes), t, d))
        t += d
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
        self._table = load_viseme_table()
        self._ctrl = LipSyncController(sink=self._sink, table=self._table)
        # Codes that actually move the mouth (exclude pure-neutral codes 0/121),
        # drawn from for the random-phoneme no-.LIP fallback.
        self._speaking_codes = [c for c, w in self._table.items()
                                if w != {"neutral": 1.0}]
        self._blink = BlinkScheduler(rng=(rng or random.Random(0xB11E)).random)
        self._flap_rng = random.Random(0xF1A9)  # random-phoneme fallback stream
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
        # A VOICE line with no phoneme data -> random phonemes for its duration
        # (BC's documented fallback, sdk/lipsync.html), so the mouth moves with
        # varied shapes while the officer talks. A text-only line (no wav) never
        # animates the mouth.
        flap = False
        if not segs and wav and duration and duration > 0.0:
            segs = _random_phoneme_segments(
                float(duration), self._flap_rng, self._speaking_codes)
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
