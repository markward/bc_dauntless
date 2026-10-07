"""Every entry in native/assets/dialogue/patches.json points at real
content: the TGL exists, anchors and inserted keys are in their databases,
replacement sounds exist."""
import json

import pytest

from engine import paths
from engine.appc import dialogue_patches as dp
from engine.appc.localization import _resolve_tgl_path
from engine.missions.tgl_reader import read_tgl


def _raw():
    return json.loads(dp.patches_path().read_text(encoding="utf-8"))


def _strings(tgl):
    path = _resolve_tgl_path(tgl)
    if path is None:
        try:
            paths.game_root()
        except paths.PathsUnresolved:
            pytest.skip("BC content not configured")
    assert path is not None, "TGL not found: %s" % tgl
    return read_tgl(path).strings


def test_the_file_is_well_formed():
    assert dp.validate_shape(_raw()) == []


def test_every_anchor_and_insert_exists():
    for tgl, entry in _raw().items():
        strings = _strings(tgl)
        added = set(entry.get("replace", {}))
        for anchor, inserts in entry.get("insert_after", {}).items():
            assert anchor in strings or anchor in added, (tgl, anchor)
            for ins in inserts:
                own = _strings(ins["tgl"]) if ins.get("tgl") else strings
                assert ins["key"] in own or ins["key"] in added, (tgl, ins)


def test_every_replacement_sound_exists_and_new_keys_are_complete():
    for tgl, entry in _raw().items():
        strings = _strings(tgl)
        for key, rep in entry.get("replace", {}).items():
            if "sound" in rep:
                assert paths.game_asset(rep["sound"]).is_file(), (tgl, key, rep["sound"])
            if key not in strings:
                assert set(rep) == {"text", "sound"}, (tgl, key)


def test_every_replacement_takes_effect_through_the_real_loader():
    """Load each patched TGL the way a mission does and check every
    `replace` entry reached the database."""
    from engine.appc.localization import TGLocalizationManager
    for tgl, entry in _raw().items():
        if not entry.get("replace"):
            continue
        _strings(tgl)
        db = TGLocalizationManager().Load(tgl)
        for key, rep in entry["replace"].items():
            if "text" in rep:
                assert db.GetString(key) == rep["text"], (tgl, key)
            if "sound" in rep:
                assert db.GetFilename(key) == rep["sound"], (tgl, key)
