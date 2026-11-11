"""A claim may map one dotted name to ONE .py file (spec
2026-11-09-wing-leaders-phase-a-design.md §11): the wing library modules
(DauntlessWings, AI.PlainAI.WingRejoin, Conditions.ConditionWing) are served
that way, so no project-root AI/ or Conditions/ package shadows the SDK's.

The claims here are temporary ones to tmp files, never the real library."""
import importlib
import sys

import pytest

from engine.compat import claimed

_NAME = "DauntlessWingsClaimProbe"


@pytest.fixture
def probe_claim(tmp_path, monkeypatch):
    f = tmp_path / "Probe.py"
    f.write_text("MARK = 42\n")
    claims = dict(claimed._CLAIMS)
    claims[_NAME.lower()] = f
    monkeypatch.setattr(claimed, "_CLAIMS", claims)
    sys.modules.pop(_NAME, None)
    yield f
    sys.modules.pop(_NAME, None)


def test_single_file_claim_imports(probe_claim):
    m = importlib.import_module(_NAME)
    assert m.MARK == 42
    assert m.__file__ == str(probe_claim)


def test_single_file_claim_matches_case_folded_exact_name_only(probe_claim):
    spec = claimed.claimed_spec(_NAME.upper())
    assert spec is not None and spec.origin == str(probe_claim)
    assert claimed.claimed_spec(_NAME + ".Sub") is None
    assert claimed.claimed_spec(_NAME + "X") is None


def test_single_file_claim_with_no_file_is_not_claimed(tmp_path, monkeypatch):
    claims = dict(claimed._CLAIMS)
    claims["dauntlesswingsmissing"] = tmp_path / "Missing.py"
    monkeypatch.setattr(claimed, "_CLAIMS", claims)
    assert claimed.claimed_spec("DauntlessWingsMissing") is None


def test_directory_claim_still_serves_its_prefix(probe_claim):
    spec = claimed.claimed_spec("Custom.NanoFXv2.NanoFX_Config")
    assert spec is not None
    assert spec.origin.replace("\\", "/").endswith("fx_api/NanoFX_Config.py")
