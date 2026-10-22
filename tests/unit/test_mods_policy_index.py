"""build_index applies engine/mod_policy per mod, before files enter the index
(spec 2026-10-16 §5)."""
from pathlib import Path

import pytest

from engine import mod_policy, mods

_LAYOUT = Path(__file__).resolve().parents[1] / "fixtures" / "mod_layouts" / "nanofx_2_0_beta.txt"


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def _touch(p: Path, body: str = "x = 1\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _install_nanofx(mod_dir: Path) -> None:
    for line in _LAYOUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            _touch(mod_dir / line)


def _status(idx, name):
    return {m.name: m for m in idx.mods}[name]


def test_standalone_nanofx_mod_contributes_nothing(tmp_path):
    _install_nanofx(tmp_path / "NanoFX_2.0 BETA")
    idx = mods.build_index(tmp_path)
    st = _status(idx, "NanoFX_2.0 BETA")
    assert st.blocked == mod_policy.REASON_NANOFX_BLOCKED
    assert st.placed == 0
    assert not any(mf.mod_name == "NanoFX_2.0 BETA" for mf in idx.files.values())


def test_bundled_nanofx_files_skipped_rest_loads(tmp_path):
    pack = tmp_path / "BigPack"
    _install_nanofx(pack)
    _touch(pack / "scripts" / "ships" / "MyShip.py")
    idx = mods.build_index(tmp_path)
    st = _status(idx, "BigPack")
    assert st.blocked is None
    assert idx.lookup("ships/MyShip.py") is not None
    assert idx.lookup("Custom/NanoFXv2/NanoFX_Lib.py") is None
    assert idx.lookup("Foundation.py") is None
    assert idx.lookup("Custom/AdvancedTechnologies/Data/ATP_Lib.py") is not None
    reasons = {reason for _rel, reason in st.refused}
    assert reasons == {mod_policy.REASON_NANOFX_BUNDLED, mod_policy.REASON_FOUNDATION}


def test_refused_file_does_not_displace_earlier_mod(tmp_path):
    # "A" sorts before "B": B would normally win. B's copy is Foundation's.
    _touch(tmp_path / "A" / "scripts" / "LoadTacticalSounds.py", "import App\n")
    _touch(tmp_path / "B" / "scripts" / "LoadTacticalSounds.py",
           "import App\nimport Foundation\n")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("LoadTacticalSounds.py")
    assert hit is not None and hit.mod_name == "A"
    assert not idx.conflicts
    assert _status(idx, "B").refused == [("LoadTacticalSounds.py", mod_policy.REASON_FOUNDATION)]


def test_plain_load_tactical_sounds_still_overrides(tmp_path):
    _touch(tmp_path / "A" / "scripts" / "LoadTacticalSounds.py", "import App\n")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("LoadTacticalSounds.py").mod_name == "A"


def test_describe_reports_block_and_refusals(tmp_path):
    _install_nanofx(tmp_path / "NanoFX_2.0 BETA")
    _touch(tmp_path / "Pack" / "scripts" / "Foundation.py")
    _touch(tmp_path / "Pack" / "scripts" / "ships" / "A.py")
    text = mods.describe(mods.build_index(tmp_path))
    assert "NanoFX_2.0 BETA: not loaded -- " + mod_policy.REASON_NANOFX_BLOCKED in text
    assert "refused 1 file(s) -- " + mod_policy.REASON_FOUNDATION + ": Foundation.py" in text


def test_foundation_quickbattle_py_refusal_also_refuses_quickbattlegame(tmp_path):
    _touch(tmp_path / "P" / "scripts" / "QuickBattle" / "QuickBattle.py",
           "import App\nimport FoundationMenu\n")
    _touch(tmp_path / "P" / "scripts" / "QuickBattle" / "QuickBattleGame.py")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("QuickBattle/QuickBattle.py") is None
    assert idx.lookup("QuickBattle/QuickBattleGame.py") is None
