"""AnimationManager — App.g_kAnimationManager.

Real (no longer a loud stub), mirroring engine/appc/bridge_set.py::ModelManager:
our renderer loads animation NIFs lazily host-side, so the faithful equivalent
of the SDK's g_kAnimationManager.LoadAnimation is to remember the file path the
SDK registers under each animation NAME. The host reads it back with path_for
when it captures an officer's placement clip (see engine/appc/bridge_placement).

Loads nothing into the renderer itself; pure name -> path bookkeeping.
"""


class AnimationManager:
    def __init__(self) -> None:
        self._paths: dict[str, str] = {}   # animation name -> NIF path

    def LoadAnimation(self, path, name) -> None:
        # SDK call shape: kAM.LoadAnimation("data/animations/db_stand_t_l.nif",
        # "db_stand_t_l"). Record name -> path; re-load of a name overwrites.
        self._paths[str(name)] = str(path)

    def FreeAnimation(self, name) -> None:
        # SDK unloads animations by name on bridge teardown; drop the record so
        # the registry stays clean across bridge reloads.
        self._paths.pop(str(name), None)

    def GetAnimationLength(self, name) -> float:
        # Headless: no clip is actually loaded, so report 0.0. The SDK feeds
        # this into Timer durations; 0.0 fires immediately (safe-fail) rather
        # than hanging. (Was previously absorbed by the App-level _NamedStub.)
        return 0.0

    def path_for(self, name) -> "str | None":
        return self._paths.get(str(name))
