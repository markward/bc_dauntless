"""Mission discovery — walks sdk/Build/scripts to a MissionRegistry."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_INITIALIZE_RE = re.compile(rb"^def\s+Initialize\s*\(", re.MULTILINE)

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


def discover(scripts_root: Path | str) -> MissionRegistry:
    scripts_root = Path(scripts_root)
    by_family: dict[str, dict[str, list[MissionEntry]]] = {}

    for family_rel, family_name in _FAMILY_ROOTS:
        family_root = scripts_root / family_rel
        if not family_root.is_dir():
            continue
        # First pass: find every candidate mission dir.
        candidates = [
            d for d in _iter_leaf_dirs(family_root)
            if _maybe_mission(d, scripts_root) is not None
        ]
        # Second pass: drop a candidate if it's an ancestor of another
        # candidate. This filters out episode-init dirs like
        # Custom/Tutorial/Episode/, whose Episode.py also defines
        # Initialize() but is the *episode* entry-point, not a mission.
        candidate_set = {d.resolve() for d in candidates}
        for mission_dir in candidates:
            if any(
                other != mission_dir.resolve()
                and other.is_relative_to(mission_dir.resolve())
                for other in candidate_set
            ):
                continue
            entry = _maybe_mission(mission_dir, scripts_root)
            if entry is None:
                continue
            episode_dir = mission_dir.parent.name
            by_family.setdefault(family_name, {}).setdefault(
                episode_dir, []).append(entry)

    reg = MissionRegistry()
    for family_name, episodes in by_family.items():
        fam = FamilyEntry(dir_name=family_name)
        for episode_dir, missions in episodes.items():
            ep = EpisodeEntry(
                dir_name=episode_dir,
                missions=sorted(missions, key=lambda m: m.dir_name),
            )
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


def _iter_leaf_dirs(root: Path):
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        if any(p.startswith("__") for p in path.parts):
            continue
        yield path


def _maybe_mission(mission_dir: Path,
                   scripts_root: Path) -> MissionEntry | None:
    candidate = mission_dir / f"{mission_dir.name}.py"
    if not candidate.is_file():
        # Case-insensitive fallback for filesystems that preserve case
        # but the on-disk name differs.
        for child in mission_dir.iterdir():
            if (child.is_file()
                    and child.suffix == ".py"
                    and child.stem.lower() == mission_dir.name.lower()):
                candidate = child
                break
        else:
            return None
    try:
        body = candidate.read_bytes()
    except OSError:
        return None
    if not _INITIALIZE_RE.search(body):
        return None

    rel = mission_dir.relative_to(scripts_root)
    module_name = ".".join(rel.parts + (mission_dir.name,))
    return MissionEntry(module_name=module_name, dir_name=mission_dir.name)
