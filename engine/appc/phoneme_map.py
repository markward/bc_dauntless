"""PhonemeMap: BC .LIP phoneme code -> discrete Viseme (openness + texture).

BC drives the jaw bone (Bip01 Ponytail1) and the SpeakA/E/U face texture from
ONE discrete openness signal with three authored jaw levels. This map is the
shared/global default phoneme group (BC's is compiled in; AddPhoneme/
UsePhonemeGroup are never called). See project_lipsync_re_findings.
"""
from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

Viseme = namedtuple("Viseme", "name openness texture")

_PATH = Path(__file__).with_name("lip_phonemes.json")
_CLOSED = Viseme("closed", 0.0, "neutral")


class PhonemeMap:
    def __init__(self, raw: dict):
        specs = raw.get("_visemes", {})
        self._visemes = {
            name: Viseme(name, float(s["openness"]), str(s["texture"]))
            for name, s in specs.items()
        }
        self._by_code = {}
        for key, name in raw.items():
            if key.startswith("_"):
                continue
            self._by_code[int(key)] = self._visemes.get(name, _CLOSED)

    def viseme_for(self, code: int) -> Viseme:
        return self._by_code.get(int(code), _CLOSED)


_default = None


def default_phoneme_map() -> PhonemeMap:
    global _default
    if _default is None:
        _default = PhonemeMap(json.loads(_PATH.read_text()))
    return _default
