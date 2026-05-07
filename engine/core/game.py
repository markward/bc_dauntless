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
