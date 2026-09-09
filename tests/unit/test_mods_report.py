import os
from pathlib import Path

from engine import mods


def _touch(p: Path, body: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _roots(tmp_path):
    game = tmp_path / "stock_game"
    sdk = tmp_path / "stock_sdk"
    game.mkdir(); sdk.mkdir()
    return game, sdk


def test_pure_addition_is_neither_override_nor_conflict(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "M" / "Data" / "new.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == []
    assert idx.conflicts == []


def test_stock_override_is_detected(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(game / "data" / "shared.nif", "stock")
    _touch(tmp_path / "mods" / "M" / "Data" / "shared.nif", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["data/shared.nif"]


def test_sdk_override_is_detected(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(sdk / "loadspacehelper.py", "stock")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "loadspacehelper.py", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["loadspacehelper.py"]


def test_mod_conflict_names_loser_and_winner(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "a.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    assert idx.conflicts == [("data/a.nif", "Alpha", "Bravo")]


def test_describe_reports_counts_and_warns_on_conflict(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Alpha" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "Bravo" / ".DS_Store")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)
    assert "Alpha" in text and "Bravo" in text
    assert "conflict" in text.lower()


def test_describe_is_empty_with_no_mods(tmp_path):
    game, sdk = _roots(tmp_path)
    idx = mods.build_index(tmp_path / "absent")
    mods.classify(idx, game, sdk)
    assert mods.describe(idx) == ""


def test_describe_distinguishes_zero_placed_files(tmp_path):
    """A mod with a content root but zero placed files (all ignored) is legible."""
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Empty" / "Data" / ".DS_Store")
    _touch(tmp_path / "mods" / "Empty" / "readme.txt")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)
    # Should have "Empty" in the output and show the ignored count
    assert "Empty" in text
    # With 2 ignored files, the line should show that
    assert "2 ignored" in text


def test_describe_flags_read_failure_explicitly(tmp_path, monkeypatch):
    """A mod whose walk hit an unreadable directory must be flagged with
    explicit problem language.

    Driven through os.walk's onerror callback -- the real mechanism -- rather
    than by making the walk itself raise. Path.rglob() never raised here at
    all: it swallows a permission error and simply does not descend, which is
    exactly why this reported "0 files" and no problem for the commonest real
    failure."""
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Broken" / "Data" / "file.nif")
    _touch(tmp_path / "mods" / "Broken" / "Data" / "Sub" / "buried.nif")

    original_scandir = os.scandir

    def mock_scandir(path=".", *args, **kwargs):
        if "Broken" in str(path) and str(path).endswith("Sub"):
            raise PermissionError("Permission denied")
        return original_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    text = mods.describe(idx)

    status = {m.name: m for m in idx.mods}["Broken"]
    assert status.read_error is True
    # The readable half of the mod is still indexed, and still counted.
    assert status.placed == 1
    assert idx.lookup("data/file.nif") is not None
    # Must contain the explicit problem language
    assert "Broken" in text
    assert "could not read mod contents" in text


def test_stock_override_is_detected_when_the_mod_matches_stock_case(tmp_path):
    """classify() stats the mod author's OWN spelling, not just the folded
    one. A stock BC install spells data/Icons/Ships/Galaxy.tga with capitals;
    statting only "data/icons/ships/galaxy.tga" finds nothing on a
    case-sensitive filesystem, so the commonest override of all -- a ship
    icon replacement -- was reported as a pure addition."""
    game, sdk = _roots(tmp_path)
    _touch(game / "data" / "Icons" / "Ships" / "Galaxy.tga", "stock")
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Galaxy.tga", "modded")
    idx = mods.build_index(tmp_path / "mods")
    mf = idx.lookup("data/Icons/Ships/Galaxy.tga")
    # The un-folded spelling is kept alongside the folded index key.
    assert mf.rel == "data/icons/ships/galaxy.tga"
    assert mf.raw_rel == "Data/Icons/Ships/Galaxy.tga"
    mods.classify(idx, game, sdk)
    assert idx.overrides == ["data/icons/ships/galaxy.tga"]
    assert "1 stock file(s) overridden" in mods.describe(idx)


class _CaseSensitiveRoot:
    """A stand-in stock root whose exists() is case-SENSITIVE.

    APFS (and NTFS) are case-insensitive, so on this machine the folded and
    the raw spelling answer the same question and no real-filesystem test can
    tell them apart. Linux is the platform the fold exists for, and this is
    how a stock root behaves there.
    """

    def __init__(self, present):
        self._present = set(present)
        self._rel = ""

    def __truediv__(self, rel):
        child = _CaseSensitiveRoot(self._present)
        child._rel = f"{self._rel}/{rel}" if self._rel else str(rel)
        return child

    def exists(self):
        return self._rel in self._present


def test_stock_override_survives_a_case_sensitive_filesystem(tmp_path):
    """The un-folded-stat fix, proved without depending on the host FS."""
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Galaxy.tga")
    idx = mods.build_index(tmp_path / "mods")
    # Stock ships the capitalised spelling and ONLY that one, as BC does.
    game = _CaseSensitiveRoot({"Data/Icons/Ships/Galaxy.tga"})
    mods.classify(idx, game, _CaseSensitiveRoot(set()))
    assert idx.overrides == ["data/icons/ships/galaxy.tga"]


def test_a_pure_addition_is_still_not_an_override_under_case_sensitivity(tmp_path):
    """The other direction: statting two spellings must not invent overrides."""
    _touch(tmp_path / "mods" / "M" / "Data" / "Icons" / "Ships" / "Fsteamr.tga")
    idx = mods.build_index(tmp_path / "mods")
    game = _CaseSensitiveRoot({"Data/Icons/Ships/Galaxy.tga"})
    mods.classify(idx, game, _CaseSensitiveRoot(set()))
    assert idx.overrides == []


# ── Why a ship did not appear ───────────────────────────────────────────────
# Two real cases from the six-mod corpus, both of which left the player with
# no explanation at all:
#
#   VoyagerCubeHP ships ships/Hardpoints/VoyagerCube.py and NO ship script.
#   Its readme requires "Voyager Borg Cube installed" -- it upgrades a ship
#   from another mod. Absent that mod, the cube cannot appear, and nothing
#   said so.
#
#   CGSovereign ships ships/Sovereign.py over the stock one. It REPLACES the
#   stock Sovereign rather than adding a ship, so there is deliberately no
#   new row in the picker -- which looks identical to "the mod didn't load".

def _hardpoint(root, name):
    _touch(root / "Scripts" / "ships" / "Hardpoints" / (name + ".py"))


def test_hardpoint_without_a_ship_script_is_reported(tmp_path):
    game, sdk = _roots(tmp_path)
    _hardpoint(tmp_path / "mods" / "CubeHP", "VoyagerCube")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    status = {m.name: m for m in idx.mods}["CubeHP"]
    assert status.orphan_hardpoints == ["VoyagerCube"]
    text = mods.describe(idx)
    assert "VoyagerCube" in text and "no ship script" in text


_SHIP_STATS = '''
def GetShipStats():
	return {
		"Name": "%s",
		"HardpointFile": "%s",
	}
'''


def _ship_script(root, script_name, hardpoint_name):
    """A ship script that NAMES its hardpoint, which is the real link.

    The hardpoint file need not share the ship script's name: stock
    Galaxy.py declares "galaxy", but the LC Intrepid pack's LCintrepidZZ.py
    declares "LCintrepidHP". Assuming the stock convention was a law produced
    a false orphan report against a pack that works perfectly.
    """
    _touch(root / "Scripts" / "ships" / (script_name + ".py"),
           _SHIP_STATS % (script_name, hardpoint_name))


def test_a_hardpoint_whose_ship_the_same_mod_ships_is_not_orphaned(tmp_path):
    game, sdk = _roots(tmp_path)
    root = tmp_path / "mods" / "Whole"
    _hardpoint(root, "NewShip")
    _ship_script(root, "NewShip", "NewShip")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    assert {m.name: m for m in idx.mods}["Whole"].orphan_hardpoints == []


def test_a_hardpoint_named_differently_from_its_ship_is_not_orphaned(tmp_path):
    """The LC Intrepid case, verbatim: LCintrepidZZ.py declares
    HardpointFile "LCintrepidHP". Nothing links them by filename."""
    game, sdk = _roots(tmp_path)
    root = tmp_path / "mods" / "LC Intrepid Pack"
    _hardpoint(root, "LCintrepidHP")
    _ship_script(root, "LCintrepidZZ", "LCintrepidHP")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    status = {m.name: m for m in idx.mods}["LC Intrepid Pack"]
    assert status.orphan_hardpoints == []


def test_single_quoted_hardpoint_declarations_are_read_too(tmp_path):
    game, sdk = _roots(tmp_path)
    root = tmp_path / "mods" / "Quoted"
    _hardpoint(root, "OddHP")
    _touch(root / "Scripts" / "ships" / "Odd.py",
           "def GetShipStats():\n\treturn {'HardpointFile': 'OddHP'}\n")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    assert {m.name: m for m in idx.mods}["Quoted"].orphan_hardpoints == []


def test_a_hardpoint_whose_ship_ANOTHER_mod_ships_is_not_orphaned(tmp_path):
    """The base mod being installed is exactly the case this must not flag."""
    game, sdk = _roots(tmp_path)
    _hardpoint(tmp_path / "mods" / "CubeHP", "VoyagerCube")
    _ship_script(tmp_path / "mods" / "CubeBase", "VoyagerCube", "VoyagerCube")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    assert {m.name: m for m in idx.mods}["CubeHP"].orphan_hardpoints == []


def test_a_hardpoint_upgrading_a_STOCK_ship_is_not_orphaned(tmp_path):
    """A hardpoint-only upgrade to a stock hull is a normal, working mod."""
    game, sdk = _roots(tmp_path)
    _touch(sdk / "ships" / "Galaxy.py", "stock")
    _hardpoint(tmp_path / "mods" / "GalaxyHP", "Galaxy")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    assert {m.name: m for m in idx.mods}["GalaxyHP"].orphan_hardpoints == []


def test_replacing_a_stock_ship_script_is_reported(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(sdk / "ships" / "Sovereign.py", "stock")
    _touch(tmp_path / "mods" / "CGSov" / "Scripts" / "ships" / "Sovereign.py")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    status = {m.name: m for m in idx.mods}["CGSov"]
    assert status.replaces_ships == ["Sovereign"]
    assert "replaces stock ship" in mods.describe(idx)


def test_adding_a_new_ship_script_is_not_a_replacement(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(sdk / "ships" / "Sovereign.py", "stock")
    _touch(tmp_path / "mods" / "Additive" / "Scripts" / "ships" / "LCintrepidZZ.py")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    status = {m.name: m for m in idx.mods}["Additive"]
    assert status.replaces_ships == []
    assert "replaces stock ship" not in mods.describe(idx)


def test_a_hardpoint_replacement_is_not_reported_as_a_ship_replacement(tmp_path):
    """ships/Hardpoints/X.py lives under ships/ too -- it must not be read as
    a replacement of the ship script X."""
    game, sdk = _roots(tmp_path)
    _touch(sdk / "ships" / "Hardpoints" / "Galaxy.py", "stock")
    _hardpoint(tmp_path / "mods" / "GalaxyHP", "Galaxy")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    assert {m.name: m for m in idx.mods}["GalaxyHP"].replaces_ships == []


def test_a_mod_with_neither_condition_gains_no_extra_report_text(tmp_path):
    game, sdk = _roots(tmp_path)
    _touch(tmp_path / "mods" / "Plain" / "Data" / "thing.nif")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)

    text = mods.describe(idx)
    assert "no ship script" not in text
    assert "replaces stock ship" not in text
