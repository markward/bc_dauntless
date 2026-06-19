from engine.core.ids import TGObject
from engine.appc.events import TGEventHandlerObject

_current_game: "Game | None" = None


def Game_GetCurrentGame() -> "Game | None":
    return _current_game


def _set_current_game(game: "Game | None") -> None:
    global _current_game
    _current_game = game


class Mission(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._friendly_group = None
        self._enemy_group = None
        self._neutral_group = None
        self._tractor_group = None
        self._script: str = ""
        self._database = None

    def SetDatabase(self, db):
        """Load (or store) this mission's localization database and return it.

        SDK pattern (E1M1.py:260): ``g_pMissionDatabase =
        pMission.SetDatabase("data/TGL/Maelstrom/Episode 1/E1M1.tgl")`` — the
        binding loads the TGL and returns the database, which mission scripts
        keep for line lookups and which ``MissionLib.GetMissionDatabase()``
        re-fetches via ``GetDatabase()``. A string is loaded through
        ``g_kLocalizationManager`` (so mission VO text + voice wavs resolve);
        a pre-built database object is stored as-is. Mirrors
        ``CharacterClass.SetDatabase``. Without this the mission database is an
        unresolved stub, so every mission VO line collapses to zero duration.
        """
        if isinstance(db, str):
            try:
                import App
                self._database = App.g_kLocalizationManager.Load(db)
            except Exception:
                self._database = None
        else:
            self._database = db
        return self._database

    def GetDatabase(self):
        return self._database

    def GetScript(self) -> str:
        """Return the mission's script module name (e.g. 'Maelstrom.M1Basic').

        SDK call sites: MissionLib.py:3426/3455/4757, AI.Compound.CallDamageAI,
        Bridge/BridgeUtils.py, Multiplayer/MissionShared.py, mission scripts.
        Used to look up the active mission's Python module for callbacks like
        ``CallDamage`` referenced from BuilderAI sub-AI nodes.
        """
        return self._script

    def SetScript(self, script: str) -> None:
        self._script = script or ""

    def _make_group(self):
        from engine.appc.objects import ObjectGroup
        return ObjectGroup()

    def GetFriendlyGroup(self):
        if self._friendly_group is None:
            self._friendly_group = self._make_group()
        return self._friendly_group

    def GetEnemyGroup(self):
        if self._enemy_group is None:
            self._enemy_group = self._make_group()
        return self._enemy_group

    def GetNeutralGroup(self):
        if self._neutral_group is None:
            self._neutral_group = self._make_group()
        return self._neutral_group

    def GetTractorGroup(self):
        if self._tractor_group is None:
            self._tractor_group = self._make_group()
        return self._tractor_group

    def GetPrecreatedShip(self, script_name: str):
        return None


class Episode(TGObject):
    def __init__(self):
        super().__init__()
        self._current_mission: Mission | None = None

    def GetCurrentMission(self) -> Mission | None:
        return self._current_mission

    def SetCurrentMission(self, mission: Mission) -> None:
        self._current_mission = mission

    def AddPersistentModule(self, module_name: str) -> None:
        # SDK Episode.AddPersistentModule(name) — prevents module unload between
        # missions (HelmMenuHandlers.py:31, BridgeHandlers.py, et al.).
        # Headless: no module lifecycle management — accept and ignore.
        pass


def Game_GetDifficulty() -> int:
    return 1  # MEDIUM


# ── Difficulty multipliers ─────────────────────────────────────────────────────
# Mission scripts call Game_SetDifficultyMultipliers(off_easy, off_med, off_hard,
# def_easy, def_med, def_hard) at mission init (e.g. E6M1.py:159) to tune damage
# scaling.  Get*DifficultyMultiplier() returns the active value for the current
# Game_GetDifficulty().  Defaults are 1.0 across the board (no scaling) — matches
# Appc's pre-init behaviour from loadspacehelper.py:154-155 which calls these
# unconditionally and would multiply by 1.0 with no SetDifficultyMultipliers call.
_difficulty_offensive: list[float] = [1.0, 1.0, 1.0]
_difficulty_defensive: list[float] = [1.0, 1.0, 1.0]


def Game_SetDifficultyMultipliers(
    off_easy: float, off_med: float, off_hard: float,
    def_easy: float, def_med: float, def_hard: float,
) -> None:
    global _difficulty_offensive, _difficulty_defensive
    _difficulty_offensive = [float(off_easy), float(off_med), float(off_hard)]
    _difficulty_defensive = [float(def_easy), float(def_med), float(def_hard)]


def Game_SetDefaultDifficultyMultipliers() -> None:
    global _difficulty_offensive, _difficulty_defensive
    _difficulty_offensive = [1.0, 1.0, 1.0]
    _difficulty_defensive = [1.0, 1.0, 1.0]


def Game_GetOffensiveDifficultyMultiplier() -> float:
    return _difficulty_offensive[Game_GetDifficulty()]


def Game_GetDefensiveDifficultyMultiplier() -> float:
    return _difficulty_defensive[Game_GetDifficulty()]


class Game(TGObject):
    EASY = 0
    MEDIUM = 1
    HARD = 2

    def __init__(self):
        super().__init__()
        self._current_episode: Episode | None = None
        self._player = None

    def GetCurrentEpisode(self) -> Episode | None:
        return self._current_episode

    def SetCurrentEpisode(self, episode: Episode) -> None:
        self._current_episode = episode

    def GetPlayer(self):
        return self._player

    def SetPlayer(self, player) -> None:
        self._player = player

    # SDK uses both spellings; GetCurrentPlayer is the module-exposed form.
    GetCurrentPlayer = GetPlayer
    SetCurrentPlayer = SetPlayer

    def GetPlayerGroup(self):
        # SDK App.py:3712 — returns an ObjectGroup of ships owned by the player.
        # BridgeHandlers/HelmMenuHandlers.AddFleetCommandHandlers call this to
        # register entered-set event handlers; null-guarded at every call site.
        # Headless: no player group — return None so the if-guards skip cleanly.
        return None

    def LoadSound(self, path: str, name: str, loadspec: int):
        # Late import: engine.audio depends on the native extension which may
        # not be ready at game.py import time.
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadSound(path, name, loadspec)

    def LoadSoundInGroup(self, path: str, name: str, group: str):
        # Late import: engine.audio depends on the native extension which may
        # not be ready at game.py import time.
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadSoundInGroup(path, name, group)


def Game_GetCurrentPlayer():
    """Return the player ship for the current Game, or None.

    SDK call sites (110+ across MissionLib, BridgeHandlers, TacticalInterface*,
    Camera, mission scripts) follow the pattern:
        pPlayer = App.Game_GetCurrentPlayer()
        if pPlayer:
            ...
    Headless harness runs without creating a player ship, so this returns
    None and the guarded branches skip cleanly.
    """
    if _current_game is None:
        return None
    return _current_game.GetCurrentPlayer()


def Game_SetCurrentPlayer(player) -> None:
    if _current_game is not None:
        _current_game.SetCurrentPlayer(player)
