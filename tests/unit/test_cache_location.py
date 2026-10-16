"""Icon and hull caches follow paths.cache_dir() (plan Task 7).

The old constants were repo-relative ("<project>/cache/icons/..."), which in an
installed build is read-only. Each cache now resolves at USE from the data dir.
"""
import struct
from pathlib import Path

import pytest

from engine import dev_mode, paths
from engine.ui import damage_icons, icon_tracer, ship_icons, weapon_icons

potrace_required = pytest.mark.skipif(
    not icon_tracer._potrace_available(),
    reason="potrace binary not installed",
)


def _tga(w: int, h: int) -> bytes:
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 0x20)
    px = bytearray()
    for y in range(h):
        for x in range(w):
            px += bytes([255, 255, 255, 255] if (x + y) % 2 == 0 else [0, 0, 0, 0])
    return header + bytes(px)


@potrace_required
@pytest.mark.parametrize("mod,sub", [(weapon_icons, "weapons"),
                                     (damage_icons, "damage")])
def test_weapon_and_damage_traces_land_in_cache_dir(monkeypatch, tmp_path, mod, sub):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    tga = tmp_path / "Synth.tga"
    tga.write_bytes(_tga(8, 8))
    monkeypatch.setattr(mod, "ICON_REGISTRY",
                        {999: icon_tracer.IconSpec(tga="Synth.tga", x=0, y=0, w=8, h=8)})
    monkeypatch.setattr(mod, "_game_icon_file", lambda stem: tga)
    monkeypatch.setattr(mod, "_CURATED_DIR", str(tmp_path / "no_curated"))
    mod.reset_cache()

    svg = mod.icon_svg_for_num(999)

    assert svg is not None
    expected = paths.cache_dir() / "icons" / sub / "999.svg"
    assert expected.is_file()
    mod.reset_cache()


def test_ship_icon_png_written_only_in_dev_mode(monkeypatch, tmp_path):
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    (icons_dir / "Galaxy.tga").write_bytes(_tga(2, 1))
    monkeypatch.setattr(ship_icons, "_game_icon_file",
                        lambda name: icons_dir / (name + ".tga"))
    repo_cache = tmp_path / "repo_cache"
    monkeypatch.setattr(ship_icons, "_CACHE_DIR", str(repo_cache))

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    ship_icons.reset_cache()
    url = ship_icons.icon_path_for_species("Galaxy")
    assert url.startswith("data:image/png;base64,")
    assert not repo_cache.exists()

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    ship_icons.reset_cache()
    assert ship_icons.icon_path_for_species("Galaxy") == url
    assert (repo_cache / "Galaxy.png").is_file()


def test_icon_trace_write_failure_is_reported(monkeypatch, tmp_path, capsys):
    paths._reset_write_failure_reports()
    tga = tmp_path / "Synth.tga"
    tga.write_bytes(_tga(8, 8))
    spec = icon_tracer.IconSpec(tga="Synth.tga", x=0, y=0, w=8, h=8)
    monkeypatch.setattr(weapon_icons, "_trace_to_svg", lambda *a: "<svg/>")
    out = tmp_path / "out"
    out.mkdir()
    (out / "999.svg").mkdir()  # a directory where the file goes: open() fails
    monkeypatch.setattr(weapon_icons, "_needs_rebuild", lambda *a: True)
    weapon_icons.trace_atlas(str(tmp_path), {999: spec}, str(out))
    assert "999.svg" in capsys.readouterr().err


@pytest.mark.parametrize("mod,call", [
    (weapon_icons, lambda m, d: m.trace_atlas(None, {}, d)),
    (damage_icons, lambda m, d: m.trace_all()),
])
def test_unwritable_cache_dir_is_reported(monkeypatch, tmp_path, capsys, mod, call):
    paths._reset_write_failure_reports()
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a dir")
    monkeypatch.setattr(mod, "_svg_cache_dir", lambda: str(blocker))
    with pytest.raises(OSError):
        call(mod, str(blocker))
    err = capsys.readouterr().err
    assert err.count("blocker") == 1


def _smallest_hull() -> Path | None:
    root = paths.game_root()
    ships = Path(root) / "data" / "Models" / "Ships"
    cands = [p for p in ships.glob("*/*.nif")
             if not p.stem.endswith(("Low", "Med", "_vox"))] if ships.is_dir() else []
    return min(cands, key=lambda p: p.stat().st_size) if cands else None


def test_hull_cache_root_round_trips_non_ascii(tmp_path):
    host = pytest.importorskip("_dauntless_host")
    hull = _smallest_hull()
    if hull is None:
        pytest.skip("no BC content to bake a hull from")
    root = tmp_path / "José" / "cache"
    host.hull_volume_set_cache_root(str(root))
    assert host.hull_volume_bake_to_disk(str(hull), 10.0)
    assert list(root.rglob("*.dhv")), "bake must land under the exact UTF-8 root"
