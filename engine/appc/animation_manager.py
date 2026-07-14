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
        self._paths: dict[str, str] = {}        # animation name -> NIF path
        self._durations: dict[str, float] = {}  # animation name -> clip length (s)
        self._duration_provider = None          # (path) -> float, injected by the host

    def LoadAnimation(self, path, name) -> None:
        # SDK call shape: kAM.LoadAnimation("data/animations/db_stand_t_l.nif",
        # "db_stand_t_l"). Record name -> path; a re-load of a name OVERWRITES
        # (LAST-write-wins). A re-load can point the same NAME at a DIFFERENT
        # clip (bridge/mission reload against the process-lifetime
        # g_kAnimationManager singleton), so any cached duration measured
        # against the OLD path is now stale and must be dropped.
        #
        # LAST-write-wins is LOAD-BEARING — do not "optimise" it into
        # first-write-wins (that was tried, in 20c62e96, and broke E1M1's
        # entire opening). BC re-registers a name precisely in order to
        # CORRECT it. Measured on a real LoadBridge.Load("GalaxyBridge"),
        # exactly two names are registered twice with different paths:
        #
        #   DBCameraSitDown  1st 'data/animations/DB_Camera_Sit_Downp.nif'
        #                        <- GalaxyBridge.py:193, a TYPO ("Downp"):
        #                           no such file exists
        #                    2nd 'data/animations/DB_Camera_Sit_Down.nif'
        #                        <- the animation builder's CORRECT path
        #   H_Talk_E_M       1st 'data/animations/DB_C_Talk_E_M.NIF'
        #                    2nd 'data/animations/DB_C_Talk_S_M.NIF'
        #                        <- BC's known cross-registration defect
        #
        # Let the typo win and the captain's sit/stand camera clip becomes
        # unloadable: GetAnimationLength returns 0.0, every sequence delay of
        # the form `GetAnimationLength(x) - 1.7` goes NEGATIVE, TGSequence
        # fires it immediately, and the whole scene collapses to t=0.
        #
        # The other re-registration in play — CommonAnimations.py:647,655's
        # console-gesture builders registering an extension-less path
        # ("data/animations/DB_E_pushing_buttons_A", no ".NIF") — is BC content
        # too, and is tolerated where BC tolerates it: in the FILE LOADER. See
        # engine/host_loop.py::_resolve_asset_path, which probes the directory
        # case-insensitively for the real ".NIF"/".nif" file. Fixing it here,
        # in the registry, is what broke DBCameraSitDown.
        self._paths[str(name)] = str(path)
        self._durations.pop(str(name), None)

    def FreeAnimation(self, name) -> None:
        # SDK unloads animations by name on bridge teardown; drop the record so
        # the registry stays clean across bridge reloads.
        self._paths.pop(str(name), None)
        self._durations.pop(str(name), None)

    def set_duration_provider(self, fn) -> None:
        """Host-injected clip measurer. AnimationManager itself loads nothing;
        the host owns the renderer that can read a NIF's keyframe times."""
        self._duration_provider = fn
        self._durations.clear()

    def GetAnimationLength(self, name) -> float:
        """The clip's real length in seconds, or 0.0 when it cannot be measured.

        The SDK schedules the walk-off lift door at `GetAnimationLength(walk) - 1.25`
        (PicardAnimations.py:145), so a 0.0 here makes the door fire 1.25s BEFORE the
        sequence starts. Headless (no provider) still returns 0.0 - safe-fail, and
        the door simply fires at the sequence root.
        """
        key = str(name)
        if key in self._durations:
            return self._durations[key]
        path = self._paths.get(key)
        if not path or self._duration_provider is None:
            return 0.0
        try:
            length = float(self._duration_provider(path))
        except Exception:
            # Do NOT cache this 0.0: the provider RAISED (e.g. renderer not
            # ready yet), so it is not a real measurement, and poisoning the
            # cache would make it wrong for the process lifetime. The cost is
            # that a failing provider is re-queried on every call until it
            # succeeds - cheap next to silently mistiming the walk-off door
            # forever. A provider that returns a genuine 0.0 (no exception)
            # IS cached below, same as any other length.
            return 0.0
        self._durations[key] = length
        return length

    def path_for(self, name) -> "str | None":
        return self._paths.get(str(name))
