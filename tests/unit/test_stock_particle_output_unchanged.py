# tests/unit/test_stock_particle_output_unchanged.py
"""Production particle output is byte-identical across the legacy FX API work
(spec 2026-10-16 §9 guard). Drives the stock Effects helpers the engine calls,
plus direct CreateTarget on the stock sheets, and compares every descriptor
with a golden captured BEFORE the particle changes.

Regenerate ONLY on purpose: UPDATE_STOCK_PARTICLE_GOLDEN=1 uv run pytest <this file>.
Keys added later must hold their documented defaults on this path."""
import json
import os
from pathlib import Path

import pytest

import App
from engine.appc import particles as P

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "stock_particle_descriptors.json"

# Descriptor keys introduced by the legacy FX API work, and the value each
# must hold for every stock caller.
NEW_KEY_DEFAULTS = {"playback": 0, "fps": 0.0, "pivot": [0.0, 0.0],
                    "orient": 0, "roll_rate": 0.0}


def _direct(path):
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(path)
    c.AddColorKey(0.0, 1.0, 0.5, 0.25)
    c.AddAlphaKey(0.0, 1.0)
    c.AddSizeKey(0.0, 2.0)
    P.EffectAction_Create(c).Start()


def _cases():
    import Effects
    return {
        "smoke_high": lambda: Effects.CreateSmokeHigh(2.0, 1.5, 0.6, object(), None, None, object()).Start(),
        "debris_smoke": lambda: Effects.CreateDebrisSmoke(5.0, 0.8, object(), 0, object()).Start(),
        "debris_sparks": lambda: Effects.CreateDebrisSparks(3.0, object(), 0, object()).Start(),
        "explosion_a": lambda: _direct("data/Textures/Effects/ExplosionA.tga"),
        "explosion_b": lambda: _direct("data/Textures/Effects/ExplosionB.tga"),
        "explosion_a_case": lambda: _direct("Data\\Textures\\Effects\\EXPLOSIONA.TGA"),
        "rough": lambda: _direct("data/rough.tga"),
        "unknown": lambda: _direct("data/Textures/whatever.tga"),
    }


def _snapshot(monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    out = {}
    for name, run in _cases().items():
        P.reset()
        run()
        descs = P.snapshot_descriptors()
        for d in descs:
            d.pop("seed", None)
        out[name] = json.loads(json.dumps(descs))
    P.reset()
    return out


def test_stock_particle_descriptors_unchanged(monkeypatch):
    got = _snapshot(monkeypatch)
    if os.environ.get("UPDATE_STOCK_PARTICLE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
        pytest.skip("golden regenerated")
    want = json.loads(GOLDEN.read_text())
    assert set(got) == set(want)
    for case, descs in want.items():
        assert len(got[case]) == len(descs), case
        for i, (g, w) in enumerate(zip(got[case], descs)):
            for k, v in w.items():
                assert g.get(k) == v, f"{case}[{i}].{k}: {g.get(k)!r} != {v!r}"
            for k in set(g) - set(w):
                assert k in NEW_KEY_DEFAULTS, f"{case}[{i}] unexpected new key {k}"
                assert g[k] == NEW_KEY_DEFAULTS[k], f"{case}[{i}].{k} = {g[k]!r}"
