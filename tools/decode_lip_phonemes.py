"""Empirically decode BC `.LIP` phoneme codes -> ARPABET phonemes / mouth shapes.

BC's `.LIP` files store a per-segment integer `code` that is a Microsoft LISET /
MS Agent (SAPI 4) phoneme id (see `sdk/lipsync.html`). The numbering does NOT
match the public SAPI 5.4 table, so this recovers the mapping from BC's OWN data:

  1. read each crew line's TEXT from the TGL localization (the `.LIP`/`.mp3`
     basename is the TGL key, e.g. `gf020`);
  2. phonemize the text with CMUdict (word -> ARPABET);
  3. proportionally align each line's non-silence code sequence to its phoneme
     sequence and accumulate a code<->phoneme co-occurrence count;
  4. the dominant phoneme per code (25-41% share over ~40 phonemes; chance
     ~2.5%) is its identity.

Output: the code->phoneme table, plus a mouth-shape frequency ranking that marks
which shapes the BC `SpeakA/E/U` art cannot represent (closed-lips M/B/P is the
most frequent gap, then F/V). See memory `project_lipsync_re_findings`.

Run from the repo root (needs `game/` assets present):
    uv run python tools/decode_lip_phonemes.py
CMUdict is downloaded once to the OS temp dir and cached.
"""
from __future__ import annotations

import collections
import glob
import os
import re
import struct
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.missions.tgl_reader import read_tgl  # noqa: E402

CMUDICT_URL = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"


def load_cmudict() -> dict[str, list[str]]:
    cache = os.path.join(tempfile.gettempdir(), "cmudict.dict")
    if not os.path.isfile(cache):
        sys.stderr.write(f"downloading CMUdict -> {cache}\n")
        urllib.request.urlretrieve(CMUDICT_URL, cache)
    cmu: dict[str, list[str]] = {}
    for ln in open(cache):
        p = ln.split()
        if p:
            cmu.setdefault(p[0].split('(')[0], [re.sub(r'\d', '', x) for x in p[1:]])
    return cmu


def load_text() -> dict[str, str]:
    text: dict[str, str] = {}
    for tgl in glob.glob(os.path.join(ROOT, "game/data/TGL/**/*.[tT][gG][lL]"), recursive=True):
        try:
            for k, v in read_tgl(tgl).strings.items():
                if k not in text and isinstance(v, str) and v.strip():
                    text[k] = v
        except Exception:
            pass
    return text


def codes(lip: str) -> list[int]:
    d = open(lip, 'rb').read()
    return [struct.unpack_from('<iff', d, i * 12)[0] for i in range(len(d) // 12)]


# ARPABET phoneme -> mouth-shape class; '*' = NOT representable by the a/e/u art.
SHAPE = {}
for grp, name in [("AA AE AH AY", "A  open (jaw down)"),
                  ("EH EY ER", "E  mid/spread"),
                  ("IH IY", "EE wide/smile"),
                  ("AO OW OY AW", "O  rounded-open"),
                  ("UW UH W", "U  rounded-small"),
                  ("M B P", "*MBP lips CLOSED"),
                  ("F V", "*FV lip-to-teeth"),
                  ("L TH DH", "L/TH tongue-tip"),
                  ("T D N S Z K G NG R SH CH JH Y HH ZH", "cons (neutral-ish)")]:
    for p in grp.split():
        SHAPE[p] = name
COVERED = {"A  open (jaw down)", "E  mid/spread", "EE wide/smile", "O  rounded-open",
           "U  rounded-small", "cons (neutral-ish)", "L/TH tongue-tip"}


def main() -> int:
    text = load_text()
    cmu = load_cmudict()
    lips = {os.path.splitext(os.path.basename(f))[0]: f
            for f in glob.glob(os.path.join(ROOT, "game/sfx/Bridge/Crew/**/*.LIP"), recursive=True)}
    if not lips:
        sys.stderr.write("no .LIP files under game/sfx/Bridge/Crew — is game/ present?\n")
        return 1

    co = collections.defaultdict(collections.Counter)
    ctot = collections.Counter()
    used = 0
    for key, lip in lips.items():
        if key not in text:
            continue
        words = re.findall(r"[a-z']+", text[key].lower())
        if not words or any(w not in cmu for w in words):   # only fully-known lines
            continue
        ph = [p for w in words for p in cmu[w]]
        c = [x for x in codes(lip) if x != 0]                # drop silence
        if not ph or not c:
            continue
        used += 1
        for j, code in enumerate(c):
            ctot[code] += 1
            co[code][ph[min(len(ph) - 1, int((j + 0.5) / len(c) * len(ph)))]] += 1

    dom = {code: co[code].most_common(1)[0][0] for code in co}
    print(f"# decoded from {used} fully-CMUdict crew lines\n")
    print("=== code -> phoneme (dominant) ===")
    for code in sorted(co, key=lambda c: -ctot[c]):
        top = "  ".join(f"{p}:{n*100//sum(co[code].values())}%" for p, n in co[code].most_common(3))
        print(f"  code {code:>3} ({ctot[code]:>4})  {dom[code]:<3} [{SHAPE.get(dom[code],'?')}]   {top}")

    shape_freq = collections.Counter()
    for code, n in ctot.items():
        shape_freq[SHAPE.get(dom.get(code, '?'), '? unknown')] += n
    print("\n=== mouth-shape frequency (corpus), * = MISSING from SpeakA/E/U art ===")
    for shp, n in shape_freq.most_common():
        mark = "" if shp in COVERED else "   <<< MISSING FROM ART"
        print(f"  {n:>5}  {shp}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
