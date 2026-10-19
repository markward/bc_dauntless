"""Developer-only shortcut: put any SDK character on the bridge viewscreen.

Some characters only reach the viewscreen deep into a mission (the Kessok is
four systems into E8M1), which makes checking how one renders a long trip.
This stages a character the same way an SDK mission does -- the same three
MissionLib calls (SetupBridgeSet, SetupCharacter, ViewscreenOn) -- so what
shows up is what the mission would show, not a separate render path.

The catalogue is read from the SDK tree at use (never at import, see
engine/paths.py): every Bridge/Characters script with a CreateCharacter, named
by its SetCharacterName, paired with the comm set the SDK's own missions most
often stage it on. A character no mission puts on a viewscreen (the player's
own crew) falls back to the Galaxy bridge comm set; if its CreateCharacter
places it nowhere (the crew's stations are set later, by ConfigureForGalaxy)
it is seated where Zeiss's own script seats her on that set.

Driven from the Developer Options panel's "Characters" tab.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from engine import paths

# The Galaxy bridge comm set, as SDK missions build it (Zeiss, Willis, Yi...),
# and the seat Zeiss.CreateCharacter uses on it.
FALLBACK_SET = ("DBridgeSet", "data/Models/Sets/DBridge/DBridge.nif")
FALLBACK_LOCATION = "GalaxySeated"

_ADD_TO_SET = re.compile(r'AddObjectToSet\(\s*\w+\s*,\s*"([^"]+)"\s*\)')
_CHARACTER_NAME = re.compile(r'SetCharacterName\(\s*"([^"]+)"\s*\)')
_CREATE_BODY = re.compile(r'^def CreateCharacter\(.*?(?=^def |\Z)', re.M | re.S)
_SETUP_SET = re.compile(r'SetupBridgeSet\(\s*"([^"]+)"\s*,\s*"([^"]+)"')
_SETUP_CHAR = re.compile(r'SetupCharacter\(\s*"(Bridge\.Characters\.\w+)"\s*,\s*"([^"]+)"')


@dataclass(frozen=True)
class CharacterEntry:
    name: str        # SetCharacterName: the label, and the panel's key
    module: str      # "Bridge.Characters.<script>"
    set_name: str
    set_model: str
    # Name the character is added to its set under -- what ViewscreenOn looks
    # up. The crew use their station ("XO" is Saffi). None = same as name.
    object_name: Optional[str] = None
    # Seat to give it after creation, or None when it places itself.
    location: Optional[str] = None

    @property
    def set_object_name(self) -> str:
        return self.object_name or self.name


def _read(path: Path) -> str:
    return path.read_text(encoding="latin-1")


def _mission_sets(scripts_root: Path) -> Dict[str, Tuple[str, str]]:
    """module -> (set name, set model) of the set its missions stage it on most.

    A set name is resolved against the SetupBridgeSet in the SAME file: the
    same name can mean a different model in another mission (PBridgeSet is
    both the Ferengi and the Galaxy E-bridge)."""
    counts: Dict[str, Counter] = {}
    for path in sorted(scripts_root.rglob("*.py")):
        if "Bridge/Characters" in path.as_posix():
            continue
        text = _read(path)
        if "SetupCharacter" not in text:
            continue
        models = {}
        for set_name, model in _SETUP_SET.findall(text):
            models.setdefault(set_name, model)
        for module, set_name in _SETUP_CHAR.findall(text):
            if set_name in models:
                counts.setdefault(module, Counter())[(set_name, models[set_name])] += 1
    # most_common keeps first-seen order on ties, and the walk is sorted.
    return {module: c.most_common(1)[0][0] for module, c in counts.items()}


def build_catalogue(scripts_root: Path) -> List[CharacterEntry]:
    """Every SDK character under `scripts_root`, sorted by name."""
    scripts_root = Path(scripts_root)
    sets = _mission_sets(scripts_root)
    out = []
    for path in sorted((scripts_root / "Bridge" / "Characters").glob("*.py")):
        body = _CREATE_BODY.search(_read(path))
        added = body and _ADD_TO_SET.search(body.group(0))
        if not added:
            continue
        object_name = added.group(1)
        named = _CHARACTER_NAME.search(body.group(0))
        name = named.group(1) if named else object_name
        module = "Bridge.Characters." + path.stem
        location = None
        if module in sets:
            set_name, set_model = sets[module]
        else:
            set_name, set_model = FALLBACK_SET
            if "SetLocation(" not in body.group(0):
                location = FALLBACK_LOCATION
        out.append(CharacterEntry(name, module, set_name, set_model,
                                  object_name if object_name != name else None,
                                  location))
    return sorted(out, key=lambda e: e.name.lower())


_cache: Optional[Tuple[str, List[CharacterEntry]]] = None


def catalogue() -> List[CharacterEntry]:
    """The catalogue for the CURRENT SDK root, rebuilt if the root changed."""
    global _cache
    root = str(paths.sdk_scripts())
    if _cache is None or _cache[0] != root:
        _cache = (root, build_catalogue(Path(root)))
    return _cache[1]


def find(name: str) -> Optional[CharacterEntry]:
    for entry in catalogue():
        if entry.name == name:
            return entry
    return None


def show(entry: CharacterEntry) -> bool:
    """Stage `entry` on its comm set and switch the viewscreen to it, looking
    forward at the screen. True once ViewscreenOn has been asked to show it."""
    import MissionLib
    if MissionLib.g_bViewscreenOn:
        # ViewscreenOn would otherwise queue behind the current call.
        MissionLib.ViewscreenOff(None, 0)
    MissionLib.SetupBridgeSet(entry.set_name, entry.set_model)
    character = MissionLib.SetupCharacter(entry.module, entry.set_name)
    if character is None:
        return False
    if entry.location:
        character.SetLocation(entry.location)
    MissionLib.ViewscreenOn(None, entry.set_name, entry.set_object_name, 0, 0, 1)
    return True


def hide() -> None:
    import MissionLib
    MissionLib.ViewscreenOff(None, 1)
