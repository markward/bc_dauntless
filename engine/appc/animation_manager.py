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
        # "db_stand_t_l").
        #
        # FIRST REGISTRATION WINS while a name is still registered. This
        # mirrors BC's own TGAnimationManagerClass, which exposes
        # IsLoaded(name) precisely so callers can skip a redundant reload —
        # the SDK's gesture builders call LoadAnimation on EVERY gesture
        # build (hundreds of times per mission), so a real engine reloading
        # the NIF from disk each time would be absurd.
        #
        # This is also load-bearing correctness, not just an optimisation:
        # Bridge/Characters/CommonAnimations.py's ConsoleSlide/PushingButtons
        # re-register the SAME name on every build with a path built by
        # string concatenation and NO file extension (a real SDK content
        # bug — e.g. "data/animations/DB_E_pushing_buttons_A", no ".NIF").
        # GalaxyBridge.PreloadAnimations already registered that exact name
        # against the correct, extensioned path. Under last-write-wins the
        # extension-less path clobbered the good one and the renderer could
        # never load the clip — 16 of 199 registered clip names ended up
        # unloadable, all console-interaction gestures. BC plainly still
        # plays these gestures, so its LoadAnimation cannot be clobbering
        # the preload either.
        #
        # Do NOT "fix" this by appending a synthesised extension to bare
        # paths instead: the real files are ".NIF" (uppercase); a lowercase
        # ".nif" suffix would work on macOS's case-insensitive filesystem
        # and silently break on Linux. Preserving the SDK's original literal
        # path — by not touching an already-registered name at all — is the
        # only case-correct fix.
        #
        # The re-point-across-bridge-reload case still works: LoadBridge.Load
        # calls the OUTGOING bridge module's UnloadAnimations() (->
        # FreeAnimation per name) before the new bridge's PreloadAnimations()
        # runs, so by the time a name is re-registered for a new bridge it
        # has genuinely been freed first, not merely reloaded in place.
        key = str(name)
        if key in self._paths:
            return
        self._paths[key] = str(path)
        self._durations.pop(key, None)

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
