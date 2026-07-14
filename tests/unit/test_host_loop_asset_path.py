"""The host's game-asset resolver must tolerate BC's extension-less clip paths.

Bridge/Characters/CommonAnimations.py:647,655 (the console-gesture builders)
register their clip with a hand-concatenated path and NO file extension:

    kAM.LoadAnimation("data/animations/" + pcAnimName, pcAnimName)

The real file on disk is "DB_E_pushing_buttons_A.NIF" - uppercase extension.
BC's own file loader resolves the extension, so the ENGINE must too, at LOAD
time (here), not by mangling the registry (see test_animation_manager.py:
LoadAnimation is last-write-wins and must stay that way).

Resolution must be case-INSENSITIVE about the extension: synthesising a
lowercase ".nif" would work on macOS and silently break on Linux.
"""
from pathlib import Path

from engine.host_loop import _resolve_asset_path


def test_extension_less_path_resolves_to_the_real_uppercase_nif(tmp_path):
    anims = tmp_path / "data" / "animations"
    anims.mkdir(parents=True)
    real = anims / "DB_E_pushing_buttons_A.NIF"
    real.write_bytes(b"")

    resolved = _resolve_asset_path("data/animations/DB_E_pushing_buttons_A", tmp_path)

    assert resolved == str(real)
    assert Path(resolved).exists()


def test_extension_less_path_resolves_to_a_lowercase_nif_too(tmp_path):
    anims = tmp_path / "data" / "animations"
    anims.mkdir(parents=True)
    real = anims / "db_stand_t_l.nif"
    real.write_bytes(b"")

    resolved = _resolve_asset_path("data/animations/db_stand_t_l", tmp_path)

    assert resolved == str(real)


def test_a_path_that_already_has_an_extension_is_returned_untouched(tmp_path):
    # The overwhelmingly common case: the SDK registered a real, extensioned
    # path. No probe, no rewriting - even if the file is absent (the game/ tree
    # is gitignored and simply not there in CI).
    resolved = _resolve_asset_path("data/animations/DB_Camera_Sit_Down.nif", tmp_path)
    assert resolved == str(tmp_path / "data" / "animations" / "DB_Camera_Sit_Down.nif")


def test_a_genuinely_missing_file_degrades_without_raising(tmp_path):
    # No such directory at all: fall back to the naive join (the downstream
    # loader then fails softly -> GetAnimationLength 0.0), never raise.
    resolved = _resolve_asset_path("data/animations/nope_not_here", tmp_path)
    assert resolved == str(tmp_path / "data" / "animations" / "nope_not_here")


def test_empty_path_is_none(tmp_path):
    assert _resolve_asset_path("", tmp_path) is None
    assert _resolve_asset_path(None, tmp_path) is None


def test_probe_result_is_cached(tmp_path, monkeypatch):
    anims = tmp_path / "data" / "animations"
    anims.mkdir(parents=True)
    (anims / "Foo.NIF").write_bytes(b"")

    first = _resolve_asset_path("data/animations/Foo", tmp_path)

    # Second call must not touch the filesystem: delete the whole tree and the
    # answer must still come back (this resolver runs per clip load).
    (anims / "Foo.NIF").unlink()
    second = _resolve_asset_path("data/animations/Foo", tmp_path)

    assert second == first
    assert first.endswith("Foo.NIF")
