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
