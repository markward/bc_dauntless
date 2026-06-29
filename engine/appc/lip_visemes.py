"""BC lip-sync viseme table: phoneme ``code`` -> weights over the texture basis.

A ``.LIP`` segment carries a phoneme ``code`` (see :mod:`engine.appc.lip_data`).
This module maps each code to **weights over the authentic face-texture basis**
``{neutral, a, e, u}`` (the ``SpeakA/E/U`` images + the neutral head). Weights
(rather than a single pick) let the controller blend a continuous mouth from the
3 textures BC ships, exploiting the 35-code richness the original discarded.

The mapping is *data* (``lip_visemes.json``); the values shipped today are a
placeholder that ``tools/recover_lip_visemes.py`` replaces with the
reverse-engineered exact table. This module is model-agnostic — it knows nothing
about textures or GL; :func:`dominant_pair` is the only adapter toward the
renderer sink (collapse weights to the two strongest + a blend factor).
"""
from __future__ import annotations

import json
from pathlib import Path

#: Face-texture basis, in canonical order.
BASIS = ("neutral", "a", "e", "u")

_DEFAULT_PATH = Path(__file__).with_name("lip_visemes.json")

_NEUTRAL: dict[str, float] = {"neutral": 1.0}


def _normalize(raw: dict) -> dict[str, float]:
    """Keep only positive basis weights and normalize them to sum 1. An empty
    or all-zero entry collapses to neutral."""
    w = {k: float(raw[k]) for k in raw if k in BASIS and float(raw[k]) > 0.0}
    total = sum(w.values())
    if total <= 0.0:
        return dict(_NEUTRAL)
    return {k: v / total for k, v in w.items()}


def load_viseme_table(path=None) -> dict[int, dict[str, float]]:
    """Load the code->weights table. Keys beginning with ``_`` (``_comment``,
    ``_basis``) are metadata and ignored. Each entry is normalized at load."""
    p = Path(path) if path else _DEFAULT_PATH
    raw = json.loads(p.read_text())
    table: dict[int, dict[str, float]] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        table[int(key)] = _normalize(value)
    return table


def viseme_weights(table: dict[int, dict[str, float]], code: int) -> dict[str, float]:
    """Normalized basis weights for ``code``; unknown codes -> neutral."""
    return table.get(code, dict(_NEUTRAL))


def dominant_pair(weights: dict[str, float]) -> tuple[str, str, float]:
    """Collapse basis weights to the renderer sink's 2-texture blend.

    Returns ``(tex_a, tex_b, mix)`` where ``tex_a`` is the strongest basis
    texture, ``tex_b`` the second strongest, and ``mix in [0, 1]`` the fraction
    toward ``tex_b`` (``0`` == fully ``tex_a``). The sink draws
    ``lerp(tex_a, tex_b, mix)``.
    """
    w = {k: float(weights.get(k, 0.0)) for k in BASIS}
    order = sorted(BASIS, key=lambda k: w[k], reverse=True)
    a, b = order[0], order[1]
    denom = w[a] + w[b]
    mix = (w[b] / denom) if denom > 0.0 else 0.0
    return a, b, mix
