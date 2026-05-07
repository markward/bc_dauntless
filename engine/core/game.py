from engine.core.ids import TGObject
from engine.appc.events import TGEventHandlerObject

_current_game: "Game | None" = None


def Game_GetCurrentGame() -> "Game | None":
    return _current_game


def _set_current_game(game: "Game | None") -> None:
    global _current_game
    _current_game = game


class Mission(TGEventHandlerObject):
    pass


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
