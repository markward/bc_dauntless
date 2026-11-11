"""Mission discovery — the stock script listing to a MissionRegistry."""
from __future__ import annotations

from dataclasses import dataclass, field

# Known family roots, in the order they should appear in the picker.
_FAMILY_ROOTS: list[tuple[str, str]] = [
    ("Custom/Tutorial", "Tutorial"),
    ("Maelstrom",       "Maelstrom"),
    ("Multiplayer",     "Multiplayer"),
]


@dataclass
class MissionEntry:
    module_name: str
    dir_name: str
    display_name: str = ""    # filled by name_resolver later


@dataclass
class EpisodeEntry:
    dir_name: str
    missions: list[MissionEntry] = field(default_factory=list)
    display_name: str = ""


@dataclass
class FamilyEntry:
    dir_name: str
    episodes: list[EpisodeEntry] = field(default_factory=list)
    display_name: str = ""


@dataclass
class MissionRegistry:
    families: list[FamilyEntry] = field(default_factory=list)


def discover() -> MissionRegistry:
    """The mission tree from the stock script listing (spec
    2026-11-11-no-sdk-runtime §4.3): a mission is a ``<dir>/<dir>`` module
    under a family root whose ``Initialize`` takes ``pMission`` first. A
    family root with no listed (or fixture) modules is skipped."""
    from engine import stock_scripts

    listed = stock_scripts.modules()
    by_family: dict[str, dict[str, list[MissionEntry]]] = {}

    for family_rel, family_name in _FAMILY_ROOTS:
        prefix = family_rel.casefold() + "/"
        # First pass: every <dir>/<dir> mission script under the family.
        candidates = [
            sf for sf in listed
            if sf.rel.casefold().startswith(prefix) and _names_its_dir(sf.rel)
            and stock_scripts.is_mission_script(sf)
        ]
        # Second pass: drop a candidate whose folder is an ancestor of
        # another candidate's (an episode entry point is never a mission).
        dirs = {_mission_dir(sf.rel).casefold() for sf in candidates}
        for sf in candidates:
            mission_dir = _mission_dir(sf.rel)
            folded = mission_dir.casefold() + "/"
            if any(other.startswith(folded) for other in dirs):
                continue
            parts = mission_dir.split("/")
            entry = MissionEntry(module_name=sf.rel.replace("/", "."),
                                 dir_name=parts[-1])
            by_family.setdefault(family_name, {}).setdefault(
                parts[-2], []).append(entry)

    from engine.missions import name_resolver as nr

    reg = MissionRegistry()
    for family_name, episodes in by_family.items():
        fam = FamilyEntry(dir_name=family_name)
        for episode_dir, missions in episodes.items():
            if family_name == "Maelstrom":
                # Faithful campaign order from the original game's menu table;
                # dir_name is the tiebreaker for any off-table directory.
                ordered = sorted(missions, key=lambda m: (
                    nr.maelstrom_order_index(episode_dir, m.dir_name),
                    m.dir_name,
                ))
            else:
                ordered = sorted(missions, key=lambda m: m.dir_name)
            ep = EpisodeEntry(dir_name=episode_dir, missions=ordered)
            fam.episodes.append(ep)
        fam.episodes.sort(key=lambda e: e.dir_name)
        reg.families.append(fam)
    reg.families.sort(key=lambda f: f.dir_name)

    # Backfill display names. Imported lazily so tests that exercise tree
    # shape only don't have to pay for TGL loading.
    from engine.missions import name_resolver as nr
    for fam in reg.families:
        fam.display_name = nr.resolve_family(fam.dir_name)
        for ep in fam.episodes:
            ep.display_name = nr.resolve_episode(fam.dir_name, ep.dir_name)
            for m in ep.missions:
                m.display_name = nr.resolve_mission(
                    fam.dir_name, ep.dir_name, m.dir_name, m.module_name)
    return reg


def _mission_dir(rel: str) -> str:
    """The folder a ``<dir>/<dir>`` mission script lives in."""
    return rel.rsplit("/", 1)[0]


def _names_its_dir(rel: str) -> bool:
    """Whether the module's last segment repeats its folder's name."""
    parts = rel.split("/")
    return len(parts) >= 3 and parts[-1].casefold() == parts[-2].casefold()
