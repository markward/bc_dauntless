"""TGVarManager — scoped variable storage for episode/mission state.

SDK call sites (sdk/.../Maelstrom/*/Episode*.py, BridgeHandlers.py,
MultiplayerInterfaceHandlers.py) follow the pattern:

    App.g_kVarManager.SetStringVariable("Options", "MissionOverride", "")
    pcOverride = App.g_kVarManager.GetStringVariable("Options", "MissionOverride")
    App.g_kVarManager.SetFloatVariable("global", "PlayedTutorial", 1.0)
    if App.g_kVarManager.GetFloatVariable("global", "PlayedTutorial") == 1.0: ...

The scope ("Options", "global", "Multiplayer", episode-name) keeps unrelated
variables from colliding.  Variables in scope "Options" persist across the
whole session (Maelstrom episode-launch order); scope-named ones live for
the episode's lifetime.

MakeEpisodeEventType(offset) is a third API on the same singleton: it
allocates a new event-type integer.  The offset arg in the SDK lets a
script reserve a stable per-script ID; the headless engine ignores it and
hands back a fresh ID, since save/load consistency isn't relevant in Phase 1.
"""


class TGVarManager:
    def __init__(self, event_type_allocator=None):
        # scope -> {name -> value}.  Float and string namespaces share the
        # same scope dict so that callers can mix get/set arbitrarily —
        # the SDK never reuses a name across types in the same scope.
        self._floats:  dict[str, dict[str, float]] = {}
        self._strings: dict[str, dict[str, str]]   = {}
        # Allocator is a callable returning a fresh int — supplied by App.py
        # so MakeEpisodeEventType shares the same counter as Game_GetNextEventType.
        self._allocator = event_type_allocator

    # ── Float variables ──────────────────────────────────────────────────────
    def SetFloatVariable(self, scope: str, name: str, value: float) -> None:
        self._floats.setdefault(scope, {})[name] = float(value)

    def GetFloatVariable(self, scope: str, name: str) -> float:
        return self._floats.get(scope, {}).get(name, 0.0)

    # ── String variables ─────────────────────────────────────────────────────
    def SetStringVariable(self, scope: str, name: str, value: str) -> None:
        self._strings.setdefault(scope, {})[name] = str(value)

    def GetStringVariable(self, scope: str, name: str) -> str:
        # Returned as the underlying str — SDK callers compare or assign;
        # the few that need TGString-style chaining call .GetCString() but
        # str doesn't have it.  Return _TGString from localization for
        # those cases.
        from engine.appc.localization import _TGString
        return _TGString(self._strings.get(scope, {}).get(name, ""))

    # ── Bulk operations ──────────────────────────────────────────────────────
    def DeleteAllVariables(self) -> None:
        self._floats.clear()
        self._strings.clear()

    def DeleteAllScopedVariables(self, scope: str) -> None:
        self._floats.pop(scope, None)
        self._strings.pop(scope, None)

    # ── Episode event-type allocator ─────────────────────────────────────────
    def MakeEpisodeEventType(self, offset: int = 0) -> int:
        # SDK's offset argument is a per-script stable index used by Appc to
        # round-trip event types through saves.  Phase 1 has no save/load,
        # so we hand back a fresh ID from the same counter Game_GetNextEventType
        # uses — guaranteeing uniqueness across all event-type allocations.
        if self._allocator is not None:
            return self._allocator()
        # Self-contained fallback for unit tests that construct VarManager
        # without an allocator wired in.
        if not hasattr(self, "_local_counter"):
            self._local_counter = 1000
        self._local_counter += 1
        return self._local_counter
