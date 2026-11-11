"""A set's textures are searched in its LoadModel env, then beside its NIF.

A bridge script names a texture folder per detail level
("data/Models/Sets/intrepidbridge/High/"), but packs often ship the textures
flat beside the NIF (the Intrepid Bridge 2.0 pack has no High/ folder at
all), and BC still found them. Ships already search the NIF's own folder
after the tier folder (host_loop._ship_texture_search); sets must too.

The stock tier folder stays LAST: the interior sibling policy reads "the
last search dir" as the stock folder (model_build.cc sibling_dirs_for), and
the project's PBR overlay maps hang off that.
"""
from engine import host_loop


def _fake_dirs(monkeypatch):
    monkeypatch.setattr(host_loop._paths, "game_asset_dirs",
                        lambda rel: [f"mod:{rel}", f"stock:{rel}"])


def test_a_flat_pack_is_searched_beside_its_nif(monkeypatch):
    _fake_dirs(monkeypatch)
    dirs = host_loop._set_texture_dirs(
        "data/Models/Sets/intrepidbridge/intrepidbridge.nif",
        "data/Models/Sets/intrepidbridge/High/")
    assert dirs == [
        "mod:data/Models/Sets/intrepidbridge/High",
        "mod:data/Models/Sets/intrepidbridge",
        "stock:data/Models/Sets/intrepidbridge",
        "stock:data/Models/Sets/intrepidbridge/High",
    ]


def test_no_env_falls_back_to_the_given_folder(monkeypatch):
    _fake_dirs(monkeypatch)
    dirs = host_loop._set_texture_dirs(
        "data/Models/Sets/X/XViewScreen.nif", None,
        fallback="data/Models/Sets/DBridge/High")
    assert dirs[0] == "mod:data/Models/Sets/DBridge/High"
    assert dirs[-1] == "stock:data/Models/Sets/DBridge/High"
    assert "stock:data/Models/Sets/X" in dirs


def test_no_env_and_no_fallback_uses_the_nif_high_folder(monkeypatch):
    _fake_dirs(monkeypatch)
    dirs = host_loop._set_texture_dirs("data/Models/Sets/Comm/comm.nif", None)
    assert dirs[-1] == "stock:data/Models/Sets/Comm/High"


def test_backslashed_nif_paths_resolve_their_folder(monkeypatch):
    _fake_dirs(monkeypatch)
    dirs = host_loop._set_texture_dirs(
        "data\\Models\\Sets\\intrepidbridge\\intrepidbridge.nif", None)
    assert "stock:data/Models/Sets/intrepidbridge" in dirs


def test_stock_bridge_keeps_its_tier_folder_last(monkeypatch):
    _fake_dirs(monkeypatch)
    dirs = host_loop._set_texture_dirs(
        "data/Models/Sets/DBridge/DBridge.nif", "data/Models/Sets/DBridge/High")
    assert dirs[0] == "mod:data/Models/Sets/DBridge/High"
    assert dirs[-1] == "stock:data/Models/Sets/DBridge/High"
