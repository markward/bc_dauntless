"""Save/load system for headless Phase 1.

Mirrors the UtopiaModule save/load surface (sdk/.../App.py:3218-3225 +
3219-3220):

    g_kUtopiaModule.SaveToFile(filename)            # full game state
    g_kUtopiaModule.LoadFromFile(filename)
    g_kUtopiaModule.SetLoadFromFileName(filename)   # mark file for next load
    g_kUtopiaModule.SetInternalLoadFileName(filename)
    g_kUtopiaModule.GetSaveFilename()
    g_kUtopiaModule.GetLoadFilename()
    g_kUtopiaModule.SaveMissionState()              # current mission only
    g_kUtopiaModule.LoadMissionState(module_name)   # returns 1 if found

Phase 1 storage model: JSON files under the project's ``saves/`` directory.
We serialise the Python-side state we own — captain name, friendly-fire
accumulators, VarManager scopes, difficulty multipliers, current mission
module — but *not* the full ObjectClass/ShipClass graph (Phase 2 work).

This is enough to make ``LoadMissionState`` round-trip test the round-trip:
write a state file mid-mission, restart the harness, read it back to skip
re-initialization.  Real BCS save files use a binary Appc-internal format
that's not part of Phase 1.
"""

import json
import os
from pathlib import Path


def _save_dir() -> Path:
    """Resolve the saves directory.

    SDK callers reference ``saves\\QuickSav.BCS`` or ``saves//<name>.BCS``
    (mixed Windows/Unix slashes) as relative paths.  Anchor everything to
    the project working directory and let the OS handle the slash form.
    """
    base = Path.cwd() / "saves"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _normalize(filename: str) -> Path:
    """Strip leading ``saves/`` or ``saves\\`` and any extension; return
    a project-anchored path under the saves directory."""
    name = filename.replace("\\", "/")
    if name.startswith("saves/"):
        name = name[len("saves/"):]
    # Collapse any leading double-slash that the SDK's "saves//" pattern
    # produces after stripping.
    name = name.lstrip("/")
    return _save_dir() / name


class SaveLoadManager:
    """Headless Phase 1 save/load — JSON-backed, Python-state only.

    Stateful so that the in-flight load filename can be queued and read
    back later (BridgeHandlers sets the filename on the menu choice and
    a deferred handler consumes it via GetLoadFilename).
    """
    def __init__(self):
        self._save_filename: str = ""
        self._load_filename: str = ""
        self._internal_load_filename: str = ""
        # Per-mission saved snapshots — keyed by module path so
        # LoadMissionState(module_name) returns the right state.
        self._mission_states: dict = {}

    # ── Filename queue ──────────────────────────────────────────────────────
    def SetLoadFromFileName(self, filename: str) -> None:
        self._load_filename = str(filename)

    def SetInternalLoadFileName(self, filename: str) -> None:
        self._internal_load_filename = str(filename)

    def GetSaveFilename(self):
        from engine.appc.localization import _TGString
        return _TGString(self._save_filename)

    def GetLoadFilename(self):
        from engine.appc.localization import _TGString
        return _TGString(self._load_filename or self._internal_load_filename)

    # ── Whole-game save ─────────────────────────────────────────────────────
    def SaveToFile(self, filename: str) -> int:
        """Snapshot the Python-side game state to a JSON file under saves/.

        Returns 1 on success (file written), 0 on any failure.  SDK callers
        treat the result as a boolean.
        """
        try:
            state = self._build_save_state()
            path = _normalize(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, indent=2, default=str))
            self._save_filename = str(filename)
            return 1
        except Exception:
            return 0

    def LoadFromFile(self, filename: str) -> int:
        """Restore Python-side game state from a JSON file.  Returns 1/0."""
        try:
            path = _normalize(filename)
            if not path.exists():
                return 0
            state = json.loads(path.read_text(encoding="utf-8"))
            self._apply_save_state(state)
            self._load_filename = str(filename)
            return 1
        except Exception:
            return 0

    # ── Mission-state subset ────────────────────────────────────────────────
    def SaveMissionState(self) -> int:
        """Persist mission-scope state for the current mission.

        Stored in-memory keyed by the current mission's module name (set
        by the harness via mission setup) so LoadMissionState can pick
        it up by name.  Also persisted to disk under saves/missions/<name>.json
        so cross-process restarts work.
        """
        try:
            module_name = self._current_mission_module()
            if not module_name:
                return 0
            state = self._build_mission_state()
            self._mission_states[module_name] = state
            path = _save_dir() / "missions" / f"{module_name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, indent=2, default=str))
            return 1
        except Exception:
            return 0

    def LoadMissionState(self, module_name: str) -> int:
        """Look for a stored mission-state snapshot for ``module_name``.

        Returns 1 if a snapshot was found and applied, 0 otherwise.  In
        the headless harness the typical answer is 0 (mission scripts then
        run their normal init flow), but tests can pre-populate the in-memory
        cache to exercise the resume path.
        """
        try:
            state = self._mission_states.get(module_name)
            if state is None:
                path = _save_dir() / "missions" / f"{module_name}.json"
                if not path.exists():
                    return 0
                state = json.loads(path.read_text(encoding="utf-8"))
                self._mission_states[module_name] = state
            self._apply_mission_state(state)
            return 1
        except Exception:
            return 0

    # ── State builders ──────────────────────────────────────────────────────
    def _build_save_state(self) -> dict:
        """Snapshot the Python-side game state we can serialise.

        Excludes ObjectClass/ShipClass graphs (Phase 2 — needs ID
        round-tripping through SetClass + the Appc-equivalent handle table).
        Keeps the things mission scripts read after a save:
        captain name, friendly-fire counters, var-manager scopes,
        difficulty multipliers, current player module reference.
        """
        import App
        from engine.core import game as game_mod
        utopia = App.g_kUtopiaModule
        return {
            "format_version": 1,
            "utopia": {
                "captain_name": utopia._captain_name,
                "friendly_fire": utopia._friendly_fire,
                "friendly_fire_max": utopia._friendly_fire_max,
                "friendly_fire_warning_points": utopia._friendly_fire_warning_points,
                "friendly_tractor_time": utopia._friendly_tractor_time,
            },
            "var_manager": {
                "floats": dict(App.g_kVarManager._floats),
                "strings": dict(App.g_kVarManager._strings),
            },
            "difficulty": {
                "offensive": list(game_mod._difficulty_offensive),
                "defensive": list(game_mod._difficulty_defensive),
            },
            "mission_states": dict(self._mission_states),
        }

    def _apply_save_state(self, state: dict) -> None:
        import App
        from engine.core import game as game_mod
        utopia_state = state.get("utopia", {})
        utopia = App.g_kUtopiaModule
        if "captain_name" in utopia_state:
            utopia._captain_name = utopia_state["captain_name"]
        if "friendly_fire" in utopia_state:
            utopia._friendly_fire = float(utopia_state["friendly_fire"])
        if "friendly_fire_max" in utopia_state:
            utopia._friendly_fire_max = float(utopia_state["friendly_fire_max"])
        if "friendly_fire_warning_points" in utopia_state:
            utopia._friendly_fire_warning_points = float(utopia_state["friendly_fire_warning_points"])
        if "friendly_tractor_time" in utopia_state:
            utopia._friendly_tractor_time = float(utopia_state["friendly_tractor_time"])

        var_state = state.get("var_manager", {})
        # Coerce inner-dict keys/values back to the right types — JSON loses
        # the distinction between int and float keys, which the SDK never
        # actually uses for variable names anyway (they're all strings).
        App.g_kVarManager._floats = {
            scope: {name: float(v) for name, v in scope_dict.items()}
            for scope, scope_dict in var_state.get("floats", {}).items()
        }
        App.g_kVarManager._strings = {
            scope: {name: str(v) for name, v in scope_dict.items()}
            for scope, scope_dict in var_state.get("strings", {}).items()
        }

        diff = state.get("difficulty", {})
        if "offensive" in diff:
            game_mod._difficulty_offensive = [float(x) for x in diff["offensive"]]
        if "defensive" in diff:
            game_mod._difficulty_defensive = [float(x) for x in diff["defensive"]]

        self._mission_states.update(state.get("mission_states", {}))

    def _build_mission_state(self) -> dict:
        """Snapshot mission-specific state.

        Currently the mission group memberships (friendly/enemy/neutral/tractor)
        are the most useful per-mission state — mission scripts read them
        after resume to wire AI for surviving ships.
        """
        import App
        game = App.Game_GetCurrentGame()
        if game is None:
            return {}
        episode = game.GetCurrentEpisode()
        mission = episode.GetCurrentMission() if episode else None
        if mission is None:
            return {}
        return {
            "module": self._current_mission_module(),
            "groups": {
                "friendly": list(mission.GetFriendlyGroup()._names),
                "enemy":    list(mission.GetEnemyGroup()._names),
                "neutral":  list(mission.GetNeutralGroup()._names),
                "tractor":  list(mission.GetTractorGroup()._names),
            },
        }

    def _apply_mission_state(self, state: dict) -> None:
        import App
        game = App.Game_GetCurrentGame()
        if game is None:
            return
        episode = game.GetCurrentEpisode()
        mission = episode.GetCurrentMission() if episode else None
        if mission is None:
            return
        groups = state.get("groups", {})
        for key, group in (
            ("friendly", mission.GetFriendlyGroup()),
            ("enemy",    mission.GetEnemyGroup()),
            ("neutral",  mission.GetNeutralGroup()),
            ("tractor",  mission.GetTractorGroup()),
        ):
            if key in groups:
                group.RemoveAllNames()
                for name in groups[key]:
                    group.AddName(name)

    def _current_mission_module(self) -> str:
        """Best-effort mission-module name for keying mission saves.

        The harness sets ``App._stub_tracker._mission`` to the mission module
        name when profiling — we piggyback on it.  When that's unset (normal
        runs), fall back to an empty string so SaveMissionState reports
        failure rather than silently saving under a bogus key.
        """
        try:
            import App
            return App._stub_tracker._mission or ""
        except Exception:
            return ""
