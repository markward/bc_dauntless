"""CharacterClass — bridge crew + character query side.

Mirrors sdk/.../App.py:4617-4825.  Mission scripts and bridge handlers
build characters with ``CharacterClass_Create(body_nif, head_nif)``,
register them into the bridge SetClass, and later query them by
name with ``CharacterClass_GetObject(pSet, name)``.

The runtime surface is enormous (60+ Set*/Get*/Is*/Add*/Clear* methods
plus per-character menu state).  Phase 1 model:

* Real ObjectClass subclass (so Set membership works).
* Inherited TGEventHandlerObject.AddPythonFuncHandlerForInstance —
  used by SetupAI / Bridge handlers to wire Python event callbacks
  to the character.
* Explicit methods for the dozen or so most-called accessors
  (GetMenu, GetCharacterName, AddFacialImage, GetYesSir, ...).
* Data-bag fallback for the long tail of setters (SetGender, SetSize,
  SetBlinkChance, SetRandomAnimationChance, ...) so SDK round-trip
  works without per-method boilerplate.

GetMenu returns a STTopLevelMenu instance with real submenu/button
children — the bridge dialog tree is built up by hardpoint scripts
calling AddChild + GetSubmenuW/GetButtonW chains.
"""

from engine.appc.objects import ObjectClass


# ── Bridge menu primitives ───────────────────────────────────────────────────

class STButton(ObjectClass):
    """Single menu button — backed by an event that fires on activation.

    Phase 1: stores the button label, event, and visibility/enabled state.
    Mission scripts query buttons via menu.GetButtonW(name) and call
    SetEnabled/SetDisabled/SendActivationEvent on the result.
    """
    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__()
        self._label = label
        self._event = event
        self._flags = int(flags)
        self._enabled = True
        self._visible = True
        self._highlighted = False
        self._selected = False
        self._chosen = False

    def GetLabel(self) -> str:                    return self._label
    def SetEnabled(self, *args) -> None:          self._enabled = True
    def SetDisabled(self, *args) -> None:         self._enabled = False
    def IsEnabled(self) -> int:                   return 1 if self._enabled else 0
    def SetVisible(self, *args) -> None:          self._visible = True
    def SetNotVisible(self, *args) -> None:       self._visible = False
    def IsVisible(self) -> int:                   return 1 if self._visible else 0
    def SetHighlighted(self, *args) -> None:      self._highlighted = True
    def SetNotHighlighted(self, *args) -> None:   self._highlighted = False
    def SetSelected(self, *args) -> None:         self._selected = True
    def SetNotSelected(self, *args) -> None:      self._selected = False
    def SetChosen(self, *args) -> None:           self._chosen = True
    def IsTypeOf(self, type_id) -> int:           return 0  # SDK class-id check; no hierarchy in Phase 1

    def SendActivationEvent(self) -> None:
        if self._event is not None:
            try:
                import App
                App.g_kEventManager.AddEvent(self._event)
            except Exception:
                pass

    # ── Layout placeholders — bridge UI never queries real values headless ──
    def GetWidth(self) -> float:                  return 0.0
    def GetHeight(self) -> float:                 return 0.0
    def GetScreenOffset(self, out=None):
        # SDK signature: GetScreenOffset(kOffset) — fills the passed point
        # with the button's screen-space offset.  Phase 1 has no screen, so
        # zero out the point if one was supplied (matches Appc behaviour
        # of returning a zero offset for off-screen widgets).
        if out is not None:
            for attr in ("x", "y", "z"):
                if hasattr(out, attr):
                    setattr(out, attr, 0.0)
            return out
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)
    def Resize(self, *args) -> None:              pass
    def SetColorBasedOnFlags(self, *args) -> None: pass
    def SetNormalColor(self, *args) -> None:      pass
    def SetHighlightedColor(self, *args) -> None: pass
    def SetSelectedColor(self, *args) -> None:    pass
    def SetDisabledColor(self, *args) -> None:    pass
    def SetUseUIHeight(self, *args) -> None:      pass
    def SetJustification(self, *args) -> None:    pass


class STMenu(ObjectClass):
    """Submenu / sortable region menu — holds buttons and child submenus.

    Mirrors STMenu / SortedRegionMenu in sdk/.../App.py.  Phase 1 stores
    children by name so the SDK's tree-walking patterns (FindMenu →
    GetSubmenuW → GetButtonW) round-trip correctly.
    """
    def __init__(self, label: str = ""):
        super().__init__()
        self._label = label
        self._children: list = []
        self._buttons: dict = {}
        self._submenus: dict = {}
        self._enabled = True
        self._visible = True
        self._focus = False

    def GetLabel(self) -> str:                    return self._label
    def AddChild(self, child, *args) -> None:
        self._children.append(child)
        if isinstance(child, STButton):
            self._buttons[child.GetLabel()] = child
        elif isinstance(child, STMenu):
            self._submenus[child.GetLabel()] = child

    def GetButtonW(self, label) -> "STButton | None":
        # Caller passes either str or _TGString; coerce for dict lookup.
        # Auto-vivify a stub button when missing — mirrors GetSubmenuW
        # auto-vivification so mission scripts that chain
        #   pMenu.GetButtonW("Dock").SetEnabled()
        # without null-guarding (E1M1.IntroduceKiska, BridgeUtils.GetDockButton
        # via MissionLib.CallWaiting) don't crash on the empty headless menu.
        key = str(label)
        btn = self._buttons.get(key)
        if btn is None:
            btn = STButton(key)
            self._buttons[key] = btn
            self._children.append(btn)
        return btn

    def GetButtonWStrict(self, label) -> "STButton | None":
        """Strict variant — returns None when no button with that label exists."""
        return self._buttons.get(str(label))

    def GetSubmenuW(self, label) -> "STMenu | None":
        out = self._submenus.get(str(label))
        if out is None:
            # Bridge menus auto-vivify submenus on first lookup so the
            # tree-build patterns in BridgeHandlers don't need to
            # pre-create every node.  Mirrors Appc behaviour.
            out = STMenu(str(label))
            self._submenus[str(label)] = out
            self._children.append(out)
        return out

    def GetSubmenu(self, label) -> "STMenu | None":
        return self.GetSubmenuW(label)

    def DeleteChild(self, child_or_name) -> None:
        if isinstance(child_or_name, str):
            self._buttons.pop(child_or_name, None)
            self._submenus.pop(child_or_name, None)
            self._children = [c for c in self._children
                              if not (hasattr(c, "GetLabel") and c.GetLabel() == child_or_name)]
        else:
            if child_or_name in self._children:
                self._children.remove(child_or_name)

    def KillChildren(self) -> None:
        self._children.clear()
        self._buttons.clear()
        self._submenus.clear()

    def SetEnabled(self, *args) -> None:          self._enabled = True
    def SetDisabled(self, *args) -> None:         self._enabled = False
    def IsEnabled(self) -> int:                   return 1 if self._enabled else 0
    def SetVisible(self, *args) -> None:          self._visible = True
    def SetNotVisible(self, *args) -> None:       self._visible = False
    def IsVisible(self) -> int:                   return 1 if self._visible else 0
    def SetFocus(self, *args) -> None:            self._focus = True
    def IsTypeOf(self, type_id) -> int:           return 0
    def Close(self, *args) -> None:               pass
    def CallNextHandler(self, _evt) -> None:
        # SDK handlers end with pMenu.CallNextHandler(pEvent) for chain
        # propagation (e.g. HelmMenuHandlers.AllStop:1524). No parent
        # window chain headless — explicit no-op instead of __getattr__ stub.
        pass


class STTopLevelMenu(STMenu):
    """Top-level menu — root of a character's dialog tree."""
    def __init__(self, label: str = ""):
        super().__init__(label)
        self._no_skip_parent = False

    def SetNoSkipParent(self, *args) -> None:
        self._no_skip_parent = True


# ── Module-level menu factories used by SDK call sites ───────────────────────

def STButton_CreateW(label="", event=None, flags=0) -> STButton:
    return STButton(str(label), event, flags)


def STMenu_Cast(obj):
    """Return obj as an STMenu, or pass through if it's a duck-typed stub.

    SDK pattern (MissionLib.py:4543): ``pButton = App.STMenu_Cast(pButton)``
    then ``pButton.Close()`` — without null-guarding.  When ``pButton`` came
    from a NamedStub-backed UI lookup chain (renderer side), strict isinstance
    casting would return None and crash the next call.  Pass-through keeps
    the chain alive: real STMenu instances cast cleanly, NamedStub-style
    objects flow through unchanged so their ``__getattr__`` absorbs the
    subsequent ``Close()`` / ``SetDisabled()`` calls.
    """
    if isinstance(obj, STMenu):
        return obj
    if obj is None:
        return None
    # Duck-typed pass-through for renderer-side NamedStubs.
    return obj


def STTopLevelMenu_CreateW(label="") -> STTopLevelMenu:
    return STTopLevelMenu(str(label))


def STTopLevelMenu_Cast(obj):
    """Same lenient pass-through as STMenu_Cast — see its docstring."""
    if isinstance(obj, STTopLevelMenu):
        return obj
    if obj is None:
        return None
    return obj


# ── CharacterClass ───────────────────────────────────────────────────────────

class CharacterClass(ObjectClass):
    # State constants from sdk/.../App.py:4617-4660.  These drive
    # IsStanding / IsTurned / IsHidden / etc. boolean queries.
    CS_IDLE             = 0
    CS_STANDING         = 1
    CS_GLANCING         = 2
    CS_TURNED           = 3
    CS_UI_DISABLED      = 4
    CS_HIDDEN           = 5
    CS_INITIATIVE       = 6
    CS_MIDDLE           = 7
    CS_SEATED           = 8
    CS_VISIBLE          = 9
    CS_CLEAR_GLANCE     = 10
    CS_CLEAR_TURNED     = 11
    CS_UI_ENABLED       = 12
    CS_STOP_INITIATIVE  = 13

    # EST_* — "execute ship task" subtype carried in bridge-menu TGIntEvents
    # (BridgeUtils.CreateBridgeMenuButton SetInt payload). Sequential ints in
    # SDK declaration order (sdk/.../App.py CharacterClass_EST_* bindings).
    EST_ALERT_GREEN                       = 0
    EST_ALERT_YELLOW                      = 1
    EST_ALERT_RED                         = 2
    EST_REPORT_OVERVIEW                   = 3
    EST_REPORT_ENGINES                    = 4
    EST_REPORT_WEAPONS                    = 5
    EST_REPORT_SHIELDS                    = 6
    EST_REPORT_REPAIR                     = 7
    EST_REPORT_SENSORS                    = 8
    EST_REPORT_DESTINATION                = 9
    EST_REPORT_SPEED                      = 10
    EST_REPORT_ETA                        = 11
    EST_SHIP_STATUS                       = 12
    EST_TARGET_STATUS                     = 13
    EST_TRANSFER_POWER_WEAPONS            = 14
    EST_TRANSFER_POWER_SHIELDS_FORE       = 15
    EST_TRANSFER_POWER_SHIELDS_AFT        = 16
    EST_TRANSFER_POWER_SHIELDS_PORT       = 17
    EST_TRANSFER_POWER_SHIELDS_STARBOARD  = 18
    EST_TRANSFER_POWER_SHIELDS_DORSAL     = 19
    EST_TRANSFER_POWER_SHIELDS_VENTRAL    = 20
    EST_TRANSFER_POWER_SENSORS            = 21
    EST_TRANSFER_POWER_ENGINES            = 22
    EST_REPAIR_PHASERS                    = 23
    EST_REPAIR_TORPEDO_TUBES              = 24
    EST_REPAIR_SENSORS                    = 25
    EST_REPAIR_IMPULSE_ENGINES            = 26
    EST_REPAIR_WARP_ENGINES               = 27
    EST_REPAIR_TRACTOR_BEAM               = 28
    EST_REPAIR_ENGINEERING                = 29
    EST_SET_COURSE_TO_MISSION_AREA        = 30
    EST_SET_COURSE_TO_PLANET              = 31
    EST_SET_COURSE_INTERCEPT              = 32
    EST_SET_COURSE_FOLLOW                 = 33
    EST_SCAN_OBJECT                       = 34
    EST_SCAN_AREA                         = 35
    EST_ATTACK_BEAM_WEAPON                = 36
    EST_ATTACK_WARHEAD                    = 37
    EST_ATTACK_IMPULSE_ENGINES            = 38
    EST_ATTACK_WARP_ENGINES               = 39
    EST_ATTACK_SENSORS                    = 40
    EST_ATTACK_ENGINEERING                = 41
    EST_ATTACK_TRACTOR_BEAM               = 42

    # Animation-type bitmask constants.
    CAT_BREATHE             = 1
    CAT_INTERRUPTABLE       = 2
    CAT_NON_INTERRUPTABLE   = 4
    CAT_TURN                = 8
    CAT_TURN_BACK           = 16
    CAT_GLANCE              = 32
    CAT_GLANCE_BACK         = 64

    # Phoneme-channel constants.
    CPT_DEFAULT = 0
    CPT_BLINK   = 1
    CPT_SPEAK   = 2
    CPT_EYEBROW = 3

    # Audio-mode constants (set by SetAudioMode).
    CAM_MUTE             = 0
    CAM_EXTREMELY_VOCAL  = 1
    CAM_VOCAL            = 2
    CAM_REDUCED          = 3

    # Gender / size enums.
    MALE         = 0
    FEMALE       = 1
    MAX_GENDERS  = 2

    SMALL        = 0
    MEDIUM       = 1
    LARGE        = 2
    MAX_SIZES    = 3

    # Posture mode for SetStanding(BOTH/SITTING_ONLY/STANDING_ONLY).
    BOTH           = 0
    SITTING_ONLY   = 1
    STANDING_ONLY  = 2

    def __init__(self, body_nif: str = "", head_nif: str = ""):
        super().__init__()
        self._body_nif = body_nif
        self._head_nif = head_nif
        self._character_name = ""
        self._yes_sir_audio: str = ""
        self._database = None
        self._menu: "STTopLevelMenu | None" = None
        self._facial_images: dict = {}    # type -> filename
        self._animations: list = []       # (anim_type, anim_name)
        self._random_animations: list = []
        self._phonemes: list = []
        self._states: set = set()         # CS_* flags currently set
        self._location_name: str = ""
        # Remaining SDK setter surface goes through the data-bag below.
        self._data: dict = {}

    # ── Identity ────────────────────────────────────────────────────────────
    def GetBodyNIF(self) -> str:                  return self._body_nif
    def GetHeadNIF(self) -> str:                  return self._head_nif

    def SetCharacterName(self, name) -> None:     self._character_name = str(name)
    def GetCharacterName(self) -> str:            return self._character_name

    # ── YesSir audio key ────────────────────────────────────────────────────
    def SetYesSir(self, sound) -> None:           self._yes_sir_audio = str(sound)
    def GetYesSir(self) -> str:                   return self._yes_sir_audio

    # ── Database (localization) ─────────────────────────────────────────────
    def SetDatabase(self, db) -> None:            self._database = db
    def GetDatabase(self):                        return self._database

    # ── Menu ────────────────────────────────────────────────────────────────
    def SetMenu(self, menu) -> None:              self._menu = menu

    def GetMenu(self) -> STTopLevelMenu:
        # Auto-vivify so the SDK pattern
        #   pCharacter.GetMenu().GetSubmenuW("Helm")
        # works on a freshly-created character without an explicit SetMenu.
        if self._menu is None:
            self._menu = STTopLevelMenu(self._character_name)
        return self._menu

    # ── Body/face/animation registration ────────────────────────────────────
    def ReplaceBodyAndHead(self, body_nif: str, head_nif: str) -> None:
        self._body_nif = str(body_nif)
        self._head_nif = str(head_nif)

    def AddFacialImage(self, image_type, filename) -> None:
        self._facial_images[image_type] = filename

    def AddAnimation(self, *args) -> None:
        self._animations.append(args)

    def AddRandomAnimation(self, *args) -> None:
        self._random_animations.append(args)

    def AddPhoneme(self, *args) -> None:
        self._phonemes.append(args)

    def ClearAnimations(self) -> None:
        self._animations.clear()

    def ClearAnimationsOfType(self, anim_type) -> None:
        self._animations = [a for a in self._animations if not (a and a[0] == anim_type)]

    def ClearExtraAnimations(self) -> None:
        self._random_animations.clear()

    # ── State flags ─────────────────────────────────────────────────────────
    @staticmethod
    def _coerce_state(state):
        """Accept either an int (CS_*) or a string label.

        SDK Bridge handlers call ``SetStatus("Waiting")`` / ``SetStatus("Ready
        to Advise")`` with the per-character status display string rather
        than an enum.  We hash both representations into the same set and
        look them up uniformly.
        """
        if isinstance(state, str):
            return state
        try:
            return int(state)
        except (TypeError, ValueError):
            return state

    def SetStatus(self, state) -> None:
        # SDK SetStatus (sometimes called SetState) toggles a flag on.
        self._states.add(self._coerce_state(state))

    def ClearStatus(self, state) -> None:
        self._states.discard(self._coerce_state(state))

    def IsStateSet(self, state) -> int:
        return 1 if self._coerce_state(state) in self._states else 0

    def SetHidden(self, *args) -> None:           self._states.add(self.CS_HIDDEN)
    def IsHidden(self) -> int:                    return 1 if self.CS_HIDDEN in self._states else 0
    def SetStanding(self, value=None) -> None:
        # SetStanding(SITTING_ONLY) etc. — also toggles CS_STANDING when called bare.
        if value is None:
            self._states.add(self.CS_STANDING)
        else:
            self._data["StandingMode"] = int(value)
    def IsStanding(self) -> int:                  return 1 if self.CS_STANDING in self._states else 0
    def IsTurned(self) -> int:                    return 1 if self.CS_TURNED in self._states else 0
    def IsGlancing(self) -> int:                  return 1 if self.CS_GLANCING in self._states else 0
    def IsUIDisabled(self) -> int:                return 1 if self.CS_UI_DISABLED in self._states else 0
    def IsActive(self) -> int:                    return 1 if self._data.get("Active", True) else 0
    def SetActive(self, *args) -> None:           self._data["Active"] = True

    # ── Location / placement ────────────────────────────────────────────────
    def SetLocation(self, location) -> None:
        # Two SDK forms: SetLocation(Location-object) and SetLocation(name-str).
        # Either way we capture the value; the location node lookup is a Phase 2
        # bridge-renderer concern.
        self._data["Location"] = location
    def SetLocationName(self, name) -> None:
        self._location_name = str(name)
    def GetLocation(self):
        return self._data.get("Location")

    # ── Speak/animate verbs (no-op in headless) ─────────────────────────────
    def SpeakLine(self, *args) -> None:           pass
    def SayLine(self, *args) -> None:             pass
    def Breathe(self, *args) -> None:             pass
    def Blink(self, *args) -> None:               pass
    def MoveTo(self, *args) -> None:              pass
    def TurnTowards(self, *args) -> None:         pass
    def TurnBack(self, *args) -> None:            pass
    def GlanceAt(self, *args) -> None:            pass
    def GlanceAway(self, *args) -> None:          pass
    def PlayAnimation(self, *args) -> None:       pass
    def PlayAnimationFile(self, *args) -> None:   pass
    def LookAtMe(self, *args) -> None:            pass

    # ── Speaking-state queries (Phase 1: never speaking) ────────────────────
    def IsSpeaking(self) -> int:                  return 0
    def IsReadyToSpeak(self) -> int:              return 1
    def IsAnimating(self) -> int:                 return 0
    def IsGoingToAnimate(self) -> int:            return 0
    def IsAnimatingInterruptable(self) -> int:    return 0
    def IsAnimatingNonInterruptable(self) -> int: return 0
    def IsRandomAnimationEnabled(self) -> int:
        return 1 if self._data.get("RandomAnimationEnabled", True) else 0
    def IsMenuEnabled(self) -> int:
        return 1 if self._data.get("MenuEnabled", True) else 0
    def IsInitiativeOn(self) -> int:
        return 1 if self._data.get("InitiativeOn", False) else 0
    def IsAnExtra(self) -> int:                   return 1 if self._data.get("AsExtra", False) else 0
    def IsMenuUp(self) -> int:                    return 1 if self._data.get("MenuUp", False) else 0
    def UsesAnimatedSpeaking(self) -> int:
        return 1 if self._data.get("AnimatedSpeaking", False) else 0

    def MenuUp(self, *args) -> None:              self._data["MenuUp"] = True
    def MenuDown(self, *args) -> None:            self._data["MenuUp"] = False

    # ── Data-bag fallback for the long tail of setters/getters ──────────────
    # Catches SetGender, SetSize, SetBlinkChance, SetRandomAnimationChance,
    # SetBlinkStages, SetAnimatedSpeaking, SetAudioMode, SetCurrentAnimation,
    # SetAnimationDoneEvent, SetCurrentAnimation, SetFlags, ClearFlags,
    # MorphBody, AddSoundToQueue, AddPositionZoom, GetPositionZoom, etc.
    # Returns hard zeros / empty for layout-style getters where Phase 1
    # has no real value.
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        data = self._data
        if name.startswith("Set") or name.startswith("Add"):
            field = name[3:]
            def setter(*args, **kwargs):
                data[field] = args[0] if len(args) == 1 else args
            return setter
        if name.startswith("Get"):
            field = name[3:]
            return lambda *args, **kwargs: data.get(field)
        if name.startswith("Is"):
            field = name[2:]
            return lambda *args, **kwargs: 1 if data.get(field) else 0
        # Methods like ToolTip, MorphBody, etc. — silent no-op.
        return lambda *args, **kwargs: None


# ── Factories ────────────────────────────────────────────────────────────────

def CharacterClass_Create(body_nif: str = "", head_nif: str = "") -> CharacterClass:
    return CharacterClass(body_nif, head_nif)


def CharacterClass_CreateNull() -> CharacterClass:
    """Return a sentinel CharacterClass marked as "null".

    SDK iteration loops (MissionLib.HideCharacters) assign the result of
    CreateNull to the loop variable when wrap-around is detected — the
    next ``App.IsNull(pObject)`` check then sees the null marker and exits.
    """
    char = CharacterClass()
    char._is_null = True
    return char


def CharacterClass_Cast(obj) -> "CharacterClass | None":
    return obj if isinstance(obj, CharacterClass) else None


def CharacterClass_GetObject(pSet, name) -> "CharacterClass | None":
    """Look up a character by name within a SetClass.

    SDK pattern (MissionLib.py:2712, BridgeHandlers): bridge characters are
    added to the "bridge" set under names like "Tactical", "Helm", "XO" — so
    the lookup is just a SetClass.GetObject filtered to CharacterClass.

    Auto-vivification: mission scripts assert that bridge characters exist
    (``assert pKiska`` in MissionLib.GetSystemOrRegionMenu) and chain
    ``GetMenu()``, ``ClearAnimations()``, ``AddPythonFuncHandlerForInstance()``
    on the result without null-guarding.  In the headless harness, the
    bridge set is rarely populated — so we hand back a real CharacterClass
    even when:

    * the set is None or a NamedStub (free-floating character),
    * the set has nothing under the name (vivify into the set),
    * the set has a stub or non-Character squatting the name (vivify standalone).

    The cached _bridge_characters dict guarantees subsequent calls for the
    same name return the same instance — handler registrations stick across
    re-lookups.

    Callers that explicitly want a null result use ``GetObjectStrict``.
    """
    name_str = str(name)
    real_set = pSet is not None and isinstance(pSet, _real_set_type())
    if real_set:
        obj = pSet.GetObject(name_str)
        if isinstance(obj, CharacterClass):
            return obj
        if obj is None:
            char = CharacterClass()
            char.SetCharacterName(name_str)
            pSet.AddObjectToSet(char, name_str)
            return char
        # Non-Character squats the name; don't overwrite, return cached/free.
    # Free-floating character — cache by name so repeat lookups stick.
    cached = _free_characters.get(name_str)
    if cached is not None:
        return cached
    char = CharacterClass()
    char.SetCharacterName(name_str)
    _free_characters[name_str] = char
    return char


_free_characters: dict = {}


def _real_set_type():
    """Lazy import to avoid module-load circularity."""
    from engine.appc.sets import SetClass
    return SetClass


def CharacterClass_GetObjectStrict(pSet, name) -> "CharacterClass | None":
    """Strict lookup — returns None when no character is registered."""
    if pSet is None or not hasattr(pSet, "GetObject"):
        return None
    obj = pSet.GetObject(str(name))
    return obj if isinstance(obj, CharacterClass) else None


_volume_for_line_type: dict = {}


def CharacterClass_SetVolumeForLineType(line_type, volume) -> None:
    """Module-level audio mixing setter (no instance receiver).

    SDK App.py:11079 binds this directly to Appc — used by Bridge sound
    setup to scale the volume of certain VO line categories.  Headless:
    record the value for round-trip.
    """
    _volume_for_line_type[int(line_type)] = float(volume)


def CharacterClass_GetVolumeForLineType(line_type) -> float:
    return _volume_for_line_type.get(int(line_type), 1.0)
