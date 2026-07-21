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
from engine.appc.tg_ui.widgets import TGPane
from engine.appc import crew_speech
from engine.appc.ai import CSP_NORMAL
import engine.dev_mode as dev_mode


# ── Bridge menu primitives ───────────────────────────────────────────────────

class STButton(TGPane):
    """Single menu button — backed by an event that fires on activation.

    Phase 1: stores the button label, event, and visibility/enabled state.
    Mission scripts query buttons via menu.GetButtonW(name) and call
    SetEnabled/SetDisabled/SendActivationEvent on the result.

    Inherits TGPane so that TGPane_Cast(an_STButton) returns the button
    itself — matching the real SDK hierarchy where STButton(TGButtonBase(TGPane)).
    sdk/Build/scripts/App.py:7860 — class STButton(TGButtonBase) where
    TGButtonBase(TGPane) at line 1472.
    """
    # SDK flag constant used in STButton_CreateW calls:
    #   App.STButton_CreateW(label, event, App.STBSF_SIZE_TO_TEXT)
    STBSF_SIZE_TO_TEXT = 1

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
    def SetLabel(self, label) -> None:            self._label = str(label)
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
    def SetChosen(self, value=1) -> None:         self._chosen = bool(value)
    def IsChosen(self) -> int:                    return 1 if self._chosen else 0
    def IsTypeOf(self, type_id) -> int:           return 0  # SDK class-id check; no hierarchy in Phase 1

    def SendActivationEvent(self) -> None:
        if self._event is not None:
            try:
                import App
                App.g_kEventManager.AddEvent(self._event)
            except Exception as _e:
                dev_mode.log_swallowed("character SendActivationEvent", _e)

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
    def SetAutoChoose(self, *args) -> None:        pass
    def SetChoosable(self, *args) -> None:         pass
    def SetUseEndCaps(self, *args) -> None:        pass
    def Layout(self, *args) -> None:               pass
    def SetActivationEvent(self, evt) -> None:
        self._event = evt


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
        self._openable = True
        self._visible = True
        self._focus = False
        # BC puts SetHighlighted on the TGUIObject base (sdk App.py:1293), so
        # submenu rows are highlightable too, not just leaf buttons. Without
        # this, TGObject.__getattr__ answered SetHighlighted() with a silent
        # _Stub and a submenu target could never light up.
        self._highlighted = False
        self._event = None

    def GetLabel(self) -> str:                    return self._label

    def SetActivationEvent(self, evt) -> None:
        self._event = evt

    def SendActivationEvent(self) -> None:
        if self._event is not None:
            try:
                import App
                App.g_kEventManager.AddEvent(self._event)
            except Exception as _e:
                dev_mode.log_swallowed("character SendActivationEvent", _e)
    def AddChild(self, child, *args) -> None:
        self._children.append(child)
        if isinstance(child, STButton):
            self._buttons[child.GetLabel()] = child
        elif isinstance(child, STMenu):
            self._submenus[child.GetLabel()] = child

    def GetButtonW(self, label) -> "STButton | None":
        # Faithful to Appc: return the existing button or None. The SDK relies
        # on None-when-absent as an EXISTENCE CHECK in many places — e.g.
        # HelmMenuHandlers.CreateHailButton (`if pButton: return None` to skip
        # re-adding), the AddHailButton dedupe, ExitedSet's remove path
        # (`if pShipButton: # remove it`), and MissionLib goal buttons. A prior
        # auto-vivifying implementation broke all of those: it never reported a
        # button as absent AND injected empty, event-less stub buttons into the
        # menu — which is exactly why the Helm "Hail" submenu filled with
        # non-hailable junk (one stub per identified object's display name) and
        # clicking them did nothing. Callers that chain on the result already
        # null-guard (grep: no inline `.GetButtonW(x).method()` in the SDK).
        return self._buttons.get(str(label))

    def GetButtonWStrict(self, label) -> "STButton | None":
        """Strict variant — returns None when no button with that label exists."""
        return self._buttons.get(str(label))

    def GetSubmenuW(self, label) -> "STMenu | None":
        # Strict: return the existing submenu or None, matching real Appc.
        # Bridge menu trees are built by explicit Create + AddChild (which
        # registers the child in _submenus by label, above), not by
        # auto-vivifying on lookup. Systems/Utils.py:67 depends on
        # None-when-absent to run its warp-point population loop.
        return self._submenus.get(str(label))

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
    def SetOpenable(self, *args) -> None:         self._openable = True
    def SetNotOpenable(self, *args) -> None:      self._openable = False
    def IsOpenable(self) -> int:                  return 1 if self._openable else 0
    def SetVisible(self, *args) -> None:          self._visible = True
    def SetNotVisible(self, *args) -> None:       self._visible = False
    def IsVisible(self) -> int:                   return 1 if self._visible else 0
    def IsCompletelyVisible(self) -> int:
        # Headless has no partial scroll clipping — visibility is the
        # faithful answer (TacticalControlHandlers.py:183 chains this off
        # GetTacticalMenu before toggling the manual-aim button).
        return self.IsVisible()
    def SetFocus(self, *args) -> None:            self._focus = True
    def SetHighlighted(self, *args) -> None:      self._highlighted = True
    def SetNotHighlighted(self, *args) -> None:   self._highlighted = False
    def IsTypeOf(self, type_id) -> int:           return 0
    def Close(self, *args) -> None:               pass
    # CallNextHandler is inherited from TGEventHandlerObject, which advances
    # the LIFO handler chain (SDK handlers end with pMenu.CallNextHandler to
    # pass control to the next/older handler; e.g. HelmMenuHandlers.AllStop).


class STTopLevelMenu(STMenu):
    """Top-level menu — root of a character's dialog tree."""
    def __init__(self, label: str = ""):
        super().__init__(label)
        self._no_skip_parent = False
        self._owner = None

    def SetNoSkipParent(self, *args) -> None:
        self._no_skip_parent = True

    # ── Owner (CharacterClass / ViewScreenObject) ───────────────────────────
    # sdk/Build/scripts/App.py:7820-7841 binds GetOwner/SetOwner straight to
    # Appc. BridgeHandlers.DropMenusTurnBack (called from
    # MissionLib.StartCutscene) reads GetOwner() off the currently-open menu
    # to find which character/viewscreen to MenuDown(). Set by
    # CharacterClass.SetMenu — the SDK's own attach point
    # (`pHelm.SetMenu(tcw.FindMenu("Helm"))`).
    def SetOwner(self, owner) -> None:
        self._owner = owner

    def GetOwner(self):
        return self._owner


# ── Module-level menu factories used by SDK call sites ───────────────────────

def STButton_CreateW(label="", event=None, flags=0) -> STButton:
    return STButton(str(label), event, flags)


def STButton_Create(label="", event=None, flags=0) -> STButton:
    """Narrow-string sibling of STButton_CreateW — same STButton, plain str label.

    QuickBattle.CreateRegionMenuButton (sdk/.../QuickBattle.py:1100) calls
    App.STButton_Create(sName, pEvent).  Appc's STButton_Create / STButton_CreateW
    differ only in label width; both return the same STButton.  Delegate so there's
    one construction path.
    """
    return STButton_CreateW(label, event, flags)


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


def STMenu_CreateW(label="", *_extra) -> STMenu:
    return STMenu(str(label))


def STMenu_Create(label="", *_extra) -> STMenu:
    return STMenu(str(label))


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
    # CS_* state flags — a BITFIELD (m_flags @ +0x80). Values from
    # stbc_constants.csv; bit meanings from CharacterClass.md §3. 0x10/0x100
    # are NOT stored — they toggle the model-cull (hidden) state.
    CS_IDLE             = 0x0
    CS_STANDING         = 0x1
    CS_GLANCING         = 0x2
    CS_TURNED           = 0x4
    CS_UI_DISABLED      = 0x8      # busy / menu-suppressed (MoveTo sets this)
    CS_HIDDEN           = 0x10     # not stored: hidden-state ON  (cull)
    CS_INITIATIVE       = 0x20
    CS_MIDDLE           = 0x40
    CS_SEATED           = 0x80
    CS_VISIBLE          = 0x100    # not stored: hidden-state OFF (show)
    CS_CLEAR_GLANCE     = 0x200
    CS_CLEAR_TURNED     = 0x400
    CS_UI_ENABLED       = 0x800
    CS_STOP_INITIATIVE  = 0xFD8    # composite clear-mask

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

    # Animation-category constants. BC's are plain ordinals, NOT a bitmask —
    # proven from the binary's own predicates: IsAnimatingInterruptable
    # (0x0066A5D0) accepts {0,1,5,6}; IsAnimatingNonInterruptable (0x0066A630)
    # tests == 2. (BC's CS_ state flags ARE a bitmask; we had the two backwards.)
    CAT_BREATHE             = 0
    CAT_INTERRUPTABLE       = 1
    CAT_NON_INTERRUPTABLE   = 2
    CAT_TURN                = 3
    CAT_TURN_BACK           = 4
    CAT_GLANCE              = 5
    CAT_GLANCE_BACK         = 6

    _INTERRUPTABLE_CATEGORIES = (CAT_BREATHE, CAT_INTERRUPTABLE,
                                 CAT_GLANCE, CAT_GLANCE_BACK)

    # Phoneme-channel constants (values from stbc_constants.csv).
    CPT_DEFAULT = -1
    CPT_BLINK   = 0
    CPT_SPEAK   = 1
    CPT_EYEBROW = 2

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
        # Texture paths are supplied separately via ReplaceBodyAndHead (the SDK
        # passes the body/head TEXTURE paths there, not NIFs). Keep distinct
        # from the NIF paths above so SP3 appearance assembly has all four.
        self._body_tex = ""
        self._head_tex = ""
        self._character_name = ""
        self._yes_sir_audio: str = ""
        self._database = None
        self._menu: "STTopLevelMenu | None" = None
        self._facial_images: dict = {}    # type -> filename
        self._animations: list = []       # (anim_type, anim_name)
        self._random_animations: list = []
        self._phonemes: list = []
        self._flags: int = 0              # CS_* bitfield (m_flags @ +0x80)
        self._hidden: bool = False        # CS_HIDDEN/CS_VISIBLE cull toggle
        self._status: dict = {}           # tooltip display strings (SP4 -> StatusMap)
        self._location_name: str = ""
        # ── Animation queue (SP2 — the CAT_* record queue; brain) ──────────
        self._anim_current = None        # AnimRec | None (BC +0x15C)
        self._anim_pending = []          # list[AnimRec] FIFO (BC +0x164 head)
        self._target_name = None         # move/back-to target (BC +0xa0)
        self._glance_name = None         # glance target (BC +0xa4)
        # ── Owner sub-component slots (filled by later sub-projects) ────────
        # SP1's _anim_queue placeholder is superseded by the real queue state
        # above (_anim_current/_anim_pending); kept as a deprecated alias so
        # it stays None and does not dangle.
        self._anim_queue = None       # deprecated: see _anim_current/_anim_pending
        self._speak_queue = None      # SP3: SpeakQueue (wraps crew_speech)
        self._position_zoom = None    # SP4: PositionZoomTable
        self._menu_state = None       # SP4: MenuState (formalizes _menu)
        # Remaining SDK setter surface goes through the data-bag below.
        self._data: dict = {}
        # RE'd constructor defaults (CharacterClass.md §4.1; field names from
        # stbc_constants.csv). Seeded into the data-bag so the existing Get*
        # accessors report BC's defaults on a fresh character. NOTE: Active is
        # intentionally NOT seeded here — SetActive/IsActive faithfulness
        # (arg-honoring + clear-interruptable-anims + inactive default) is
        # coupled to SP2's animation queue and lands there.
        self._data.setdefault("Gender", self.FEMALE)
        self._data.setdefault("Size", self.SMALL)
        self._data.setdefault("AudioMode", self.CAM_VOCAL)
        self._data.setdefault("BlinkStages", -1)
        self._data.setdefault("RandomAnimationEnabled", True)

    # ── Identity ────────────────────────────────────────────────────────────
    def GetBodyNIF(self) -> str:                  return self._body_nif
    def GetHeadNIF(self) -> str:                  return self._head_nif

    def SetCharacterName(self, name) -> None:     self._character_name = str(name)
    def GetCharacterName(self) -> str:            return self._character_name

    # ── YesSir audio key ────────────────────────────────────────────────────
    def SetYesSir(self, sound) -> None:           self._yes_sir_audio = str(sound)
    def GetYesSir(self) -> str:                   return self._yes_sir_audio

    # ── Database (localization) ─────────────────────────────────────────────
    def SetDatabase(self, db):
        # SDK passes a TGL path string (e.g. "data/TGL/Bridge Crew General.tgl");
        # load it into a real localization DB so GetDatabase() callers
        # (acknowledge/emit) get HasString/GetFilename. A DB object (or any
        # non-string) is stored as-is. Best-effort: a load failure stores None.
        # Returns the stored DB — the SWIG CharacterClass_SetDatabase binding
        # returns the loaded database (App.py:4707).
        if isinstance(db, str):
            try:
                import App
                self._database = App.g_kLocalizationManager.Load(db)
            except Exception:
                self._database = None
        else:
            self._database = db
        return self._database
    def GetDatabase(self):                        return self._database

    # ── Menu ────────────────────────────────────────────────────────────────
    def SetMenu(self, menu) -> None:
        # The SDK's own attach point (`pHelm.SetMenu(tcw.FindMenu("Helm"))`,
        # HelmCharacterHandlers:50 and its 4 siblings). Stamp the reverse
        # link too — STTopLevelMenu.GetOwner() is how BridgeHandlers.
        # DropMenusTurnBack() finds the character to MenuDown() when it
        # drops whatever menu is open. Skip the shared NULL-menu sentinel
        # (DetachMenuFrom* assigns it) so many characters detaching don't
        # all stamp their identity onto one global singleton.
        self._menu = menu
        if isinstance(menu, STTopLevelMenu) and menu is not _NULL_MENU:
            menu.SetOwner(self)

    def GetMenu(self):
        # Faithful to Appc: an unattached character holds a NULL menu handle —
        # a SWIG wrapper that is FALSY in `if (pChar.GetMenu()):` yet still
        # dereferenceable. Both properties are load-bearing in the SDK:
        # AttachMenuTo* uses the falsiness to skip its self-detach on a fresh
        # character (the old auto-vivified orphan was truthy, so re-attach
        # after DetachCrewMenus took the detach branch against an empty orphan
        # and crashed on the missing "Orbit Planet" submenu), while
        # MissionLib.DetachCrewMenus calls DetachMenuFrom* UNCONDITIONALLY and
        # those bodies call pMenu.RemoveHandlerForInstance / GetSubmenuW on
        # whatever GetMenu returned — so a bare None crashes them.
        return self._menu if self._menu is not None else _NULL_MENU

    # ── Body/face/animation registration ────────────────────────────────────
    def ReplaceBodyAndHead(self, body_tex: str, head_tex: str) -> None:
        # SDK passes TEXTURE paths here (e.g. FedFemRed_body.tga); the NIFs
        # came from CharacterClass_Create. Keep them distinct.
        self._body_tex = str(body_tex)
        self._head_tex = str(head_tex)

    def appearance(self) -> dict:
        return {
            "body_nif": self._body_nif, "head_nif": self._head_nif,
            "body_tex": self._body_tex, "head_tex": self._head_tex,
        }

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
        # BC keys this on the animation's CAT_ category, which our AddAnimation
        # registry (name -> python path) does not carry. Zero SDK call sites, so
        # rather than invent a category per registration we record it and no-op.
        from engine.core import stub_telemetry
        stub_telemetry.record_attr("CharacterClass", "ClearAnimationsOfType")

    def ClearExtraAnimations(self) -> None:
        self._random_animations.clear()

    def _anim_count(self) -> int:
        return (1 if self._anim_current is not None else 0) + len(self._anim_pending)

    def set_current_animation(self, name, category) -> None:
        """Mark this character as playing *name* in category *category* (a CAT_).

        BC keeps the playing animation in a record on the character; the SDK
        reads it back through IsAnimatingNonInterruptable() to refuse a second
        gesture on a busy officer. The verb dispatch (CharacterAction) is the
        only thing that starts these, so it owns setting and clearing this.

        Interim shim over the SP2 queue fields (_anim_current/_anim_pending):
        Tasks 3-5 replace this with the real enqueue/Classify pipeline.
        """
        from engine.appc.character_anim_queue import AnimRec
        self._anim_current = AnimRec(category=int(category), name=str(name))

    def clear_current_animation(self) -> None:
        self._anim_current = None

    def GetCurrentAnimation(self) -> str:
        return self._anim_current.name if self._anim_current else ""

    # ── State flags: the faithful CS_* bitfield (CharacterClass.md §4.3) ─────
    def SetFlags(self, mask) -> None:
        mask = int(mask)
        if mask == 0:
            return
        if mask == self.CS_HIDDEN:        # 0x10 — not stored; hide (pull model)
            self._hidden = True
            return
        if mask == self.CS_VISIBLE:       # 0x100 — not stored; show
            self._hidden = False
            return
        self._flags |= mask
        # BC menu suppression: becoming busy (0x8) drops an open menu.
        if (self._flags & self.CS_UI_DISABLED) and self.IsMenuUp():
            self.MenuDown()

    def ClearFlags(self, mask) -> None:
        mask = int(mask)
        if mask == 0:
            return
        if mask == self.CS_HIDDEN:        # ClearFlags(0x10) -> show
            self._hidden = False
            return
        if mask == self.CS_VISIBLE:       # ClearFlags(0x100) -> hide
            self._hidden = True
            return
        self._flags &= ~mask

    def IsStateSet(self, mask) -> int:
        mask = int(mask)
        return 1 if (self._flags & mask) == mask else 0

    # ── Tooltip status strings — SEPARATE from the flag bitfield ────────────
    # SDK calls SetStatus with a localized display string
    # (pMiguel.SetStatus(db.GetString("Waiting"))). Stored under a single
    # interim key; SP4 replaces this with the real keys-0..5 StatusMap widgets.
    def SetStatus(self, state, *args) -> None:
        self._status["text"] = state

    def ClearStatus(self, state=None, *args) -> None:
        self._status.pop("text", None)

    def GetStatusText(self, key="text"):
        return self._status.get(key)

    # ── Visibility (pull model): mutate _hidden; host loop culls per-frame ──
    def SetHidden(self, hidden=1) -> None:
        self._hidden = bool(hidden)
    def IsHidden(self) -> int:                    return 1 if self._hidden else 0

    def SetStanding(self, value=None) -> None:
        if value is None:
            self.SetFlags(self.CS_STANDING)
        else:
            self._data["StandingMode"] = int(value)
    def IsStanding(self) -> int:                  return self.IsStateSet(self.CS_STANDING)

    def SetInitiative(self, on=1) -> None:
        if on:
            self.SetFlags(self.CS_INITIATIVE)
        else:
            self.ClearFlags(self.CS_INITIATIVE)
    def IsInitiativeOn(self) -> int:              return self.IsStateSet(self.CS_INITIATIVE)

    def IsTurned(self) -> int:                    return self.IsStateSet(self.CS_TURNED)
    def IsGlancing(self) -> int:                  return self.IsStateSet(self.CS_GLANCING)
    def IsUIDisabled(self) -> int:                return self.IsStateSet(self.CS_UI_DISABLED)
    def IsActive(self) -> int:                    return 1 if self._data.get("Active", True) else 0
    def SetActive(self, *args) -> None:           self._data["Active"] = True

    def ProcessEvent(self, event) -> None:
        # BC's native engine consumes ET_CHARACTER_ANIMATION_DONE (fired by every
        # SDK move builder's completed-event, e.g. PicardAnimations.MoveFromPToL1)
        # and applies the carried CS_* state to this character — that is how an
        # officer HIDES after walking into the turbolift. Must never raise: a
        # malformed event (missing int, unknown state) degrades quietly and falls
        # through to the normal instance-handler chain.
        import App
        try:
            et = event.GetEventType()
        except Exception:
            et = None
        if et == App.ET_CHARACTER_ANIMATION_DONE:
            try:
                state = int(event.GetInt())
            except Exception:
                state = None
            if state == self.CS_HIDDEN:
                self.SetHidden(1)
            elif state == self.CS_STANDING:
                self.SetHidden(0)
                self.SetStanding()
            elif state == self.CS_SEATED:
                self.SetHidden(0)
                self.ClearFlags(self.CS_STANDING)
            return
        super().ProcessEvent(event)

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
    def SpeakLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_) -> None:
        # SDK call shape is uniformly SpeakLine(db, lineID, priority) (or the
        # 2-arg form with the default priority); no addressee arg.
        db = pDatabase if pDatabase is not None else self._database
        crew_speech.emit(self._character_name, db, lineID, priority)

    def SayLine(self, pDatabase=None, lineID="", _addressee=None,
                _flag=None, priority=CSP_NORMAL, *_) -> None:
        # SDK SayLine has a 4-arg and a (dominant) 5-arg form:
        #   SayLine(db, lineID, "Captain", 1)                       -> default priority
        #   SayLine(db, lineID, "Captain", 1, App.CSP_SPONTANEOUS)  -> explicit priority
        # arg3 is the addressee and arg4 a flag; both are meaningless headless.
        # The real priority is the OPTIONAL 5th arg.
        db = pDatabase if pDatabase is not None else self._database
        crew_speech.emit(self._character_name, db, lineID, priority)

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

    def GetAnimNode(self):
        # A real anim node so the SDK builders' TGAnimActions are tagged as
        # targeting the CHARACTER (kind="character") — distinguishable from a
        # bridge-set node (kind="object"). A multi-action TurnCaptain sequence
        # interleaves the officer's body clip (character node) with the chair
        # clip (bridge node); capture picks the character action. (__dict__.get
        # avoids TGObject.__getattr__ returning a truthy _Stub for the unset
        # attribute.)
        node = self.__dict__.get("_anim_node")
        if node is None:
            from engine.appc.anim_node import TGAnimNode
            node = TGAnimNode(owner=self, kind="character")
            self._anim_node = node
        return node

    # ── Speaking-state queries (Phase 1: never speaking) ────────────────────
    # NOTE: this explicit method must exist — the Get* data-bag in __getattr__
    # (below) would otherwise intercept GetLastTalkTime and return None, so the
    # SDK idiom `GetGameTime() - GetLastTalkTime()` becomes `float - None`
    # (TypeError, swallowed by event dispatch) and the idle-chatter gate is
    # silently defeated. The bus stamps _last_talk on every accepted line.
    def GetLastTalkTime(self) -> float:
        from engine.appc import crew_speech
        return crew_speech.last_talk_time(self._character_name)

    # Explicit numeric getters. WITHOUT these the __getattr__ data-bag returns
    # None for a never-set field, and `GetGameTime() - GetBlinkChance()` becomes
    # `float - None` (TypeError, swallowed by event dispatch). BC's defaults:
    # BlinkChance 0.1f (ctor), RandomAnimationChance per-character (0.75 for
    # station officers, 0.01 for guests/extras — MissionLib.py:1578).
    def GetBlinkChance(self) -> float:
        return float(self._data.get("BlinkChance", 0.1))

    def GetRandomAnimationChance(self) -> float:
        return float(self._data.get("RandomAnimationChance", 0.0))

    def IsSpeaking(self) -> int:
        from engine.appc import crew_speech
        return 1 if crew_speech.is_speaking(self._character_name) else 0
    def IsReadyToSpeak(self) -> int:              return 1
    def IsAnimating(self) -> int:                 return 1 if self._anim_current is not None else 0
    def IsGoingToAnimate(self) -> int:            return 1 if self._anim_current is not None else 0
    def IsAnimatingInterruptable(self) -> int:
        if self._anim_current is None:
            return 0
        return 1 if self._anim_current.category in self._INTERRUPTABLE_CATEGORIES else 0
    def IsAnimatingNonInterruptable(self) -> int:
        if self._anim_current is None:
            return 0
        return 1 if self._anim_current.category == self.CAT_NON_INTERRUPTABLE else 0
    def IsRandomAnimationEnabled(self) -> int:
        return 1 if self._data.get("RandomAnimationEnabled", True) else 0
    def IsMenuEnabled(self) -> int:
        return 1 if self._data.get("MenuEnabled", True) else 0
    def IsAnExtra(self) -> int:                   return 1 if self._data.get("AsExtra", False) else 0
    def IsMenuUp(self) -> int:                    return 1 if self._data.get("MenuUp", False) else 0
    def UsesAnimatedSpeaking(self) -> int:
        return 1 if self._data.get("AnimatedSpeaking", False) else 0

    def MenuUp(self, *args) -> int:
        """Raise this officer's menu. BC's canonical primitive: BridgeHandlers'
        click seam does `if (pCharacter.MenuUp()): CharacterInteraction(...)` and
        QuickBattle does `g_pXO.MenuUp()` to bring Saffi's menu up. It drives the
        panel view, sets the state flag, and turns the officer to the captain.

        It does NOT acknowledge — BC plays the "Yes sir" line in
        CharacterInteraction, on the CLICK path only, so a scripted AT_MENU_UP
        stays silent. Returns 1 when the menu was raised, 0 when there was
        nothing to raise (no menu / disabled).

        Idempotent: calling MenuUp() again while THIS MENU is already the open
        one must not re-drive the view, re-request the turn, or re-dispatch the
        tutorial open event — it just re-affirms 1. Gated on
        panel.is_menu_open(menu) (menu IDENTITY), not officer identity: the
        officer-identity check (`panel.open_officer() is self`) resolves through
        a 5-station label table and cannot see a non-station officer's
        mission-made menu (E8M2's Liu, E3M1's MacCray), which would make this
        idempotency check always miss for them."""
        menu = self.GetMenu()
        if not menu or not menu.IsEnabled():
            return 0                         # stock BC: nothing to raise
        panel = _get_menu_panel()
        if self._data.get("MenuUp") and (panel is None or panel.is_menu_open(menu)):
            return 1                         # already up: idempotent raise
        if panel is not None:
            other = panel.open_officer()     # still officer-based: the only way
            if other is not None:            # to turn the PREVIOUS officer back
                other.MenuDown()             # single-open: close + turn them back
            panel.show_menu(menu)
        self._data["MenuUp"] = True
        self._notify_menu(turn=True)         # turn-to-captain (None-ctrl guarded)
        dispatch_character_menu(self, is_open=True)
        return 1

    def MenuDown(self, *args) -> None:
        """Lower this officer's menu (BC's MenuDown). Hides the view only if this
        officer's menu is the open one, clears the flag, turns them back, and
        fires the tutorial close signal.

        Idempotent w.r.t. this officer's own state: the SDK calls MenuDown()
        defensively (ContactStarfleet, DockStarbase12, and others) even when
        this officer's menu was never up. Before this primitive existed that
        was a harmless no-op; now it must stay one — early-return with no
        flag write, no turn-back, and no dispatch, so a defensive MenuDown()
        never fires an unpaired close event.

        Gates the view-hide on panel.is_menu_open(self.GetMenu()) — menu
        IDENTITY — not `panel.open_officer() is self`. The officer-identity
        check resolves the open menu's label against a 5-station table and
        looks the officer up in the "bridge" set, so it can never resolve a
        non-station officer with a mission-made menu (E8M2's Liu holding
        "ChooseBattleGroup", E3M1's MacCray). With the old check, AT_MENU_DOWN
        on such an officer cleared the flag/turned them back/fired the close
        event while the menu view stayed pinned on screen for the rest of the
        mission — a real stuck-UI bug."""
        if not self._data.get("MenuUp"):
            return                            # menu wasn't up: pure no-op
        panel = _get_menu_panel()
        if panel is not None and panel.is_menu_open(self.GetMenu()):
            panel.hide_menu()
        self._data["MenuUp"] = False
        self._notify_menu(turn=False)
        dispatch_character_menu(self, is_open=False)

    def _notify_menu(self, turn) -> None:
        try:
            from engine.bridge_character_anim import get_controller
            ctrl = get_controller()
            if ctrl is None:
                return
            if turn:
                ctrl.request_turn(self)
            else:
                ctrl.request_turn_back(self)
        except Exception:
            pass

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
        from engine.core import stub_telemetry
        stub_telemetry.record_attr("CharacterClass", name)
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

def CharacterClass_Create(body_nif: str = "", head_nif: str = "", *_extra) -> CharacterClass:
    # Some SDK character modules (Kiska, Saffi) pass a 3rd positional arg
    # (a quality/female flag in the original Appc). Accept and ignore it.
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


def _get_menu_panel():
    """The wired CrewMenuPanel, or None (headless / no UI). The seam MenuUp uses
    to reach the view without engine.appc importing the UI at module load."""
    try:
        from engine.ui import crew_menu_hotkeys
        return crew_menu_hotkeys.get_panel()
    except Exception:
        return None


def STTopLevelMenu_GetOpenMenu():
    """The currently open top-level bridge menu, or None.

    sdk/Build/scripts/App.py:11897 binds this straight to
    Appc.STTopLevelMenu_GetOpenMenu. BridgeHandlers.DropMenusTurnBack (called
    once, at the right moment, by MissionLib.StartCutscene) reads it to close
    whatever menu is open before a cutscene's own script goes on to raise a
    new one.

    Before this was implemented, App's module __getattr__ handed back a
    fresh _NamedStub for the undefined name on every access. A _NamedStub is
    TRUTHY, so DropMenusTurnBack's `if (pOpenMenu):` guard always passed, but
    `pOpenMenu.GetOwner()` was itself another _NamedStub — so the drop
    silently did nothing (the recurring "undefined App.* -> _NamedStub ->
    silently wrong" bug class). That's what let a same-tick scripted MenuUp()
    (E1M1 ExplainWarp's Kiska AT_MENU_UP) collide with a since-deleted
    host-loop clamp that tried to paper over the gap at end-of-tick.

    Delegates to the wired CrewMenuPanel — the single source of truth for
    which menu is open (see CrewMenuPanel.get_open_menu). None (not a stub)
    both when nothing is open and when no panel is wired (headless)."""
    panel = _get_menu_panel()
    if panel is None:
        return None
    return panel.get_open_menu()


def dispatch_character_menu(character, is_open) -> None:
    """Send ET_CHARACTER_MENU through a bridge officer's instance handler
    chain on menu open/close.

    Missions listen for this to track crew-menu interaction: E1M1 registers
    HandleMenuEvent on every officer (E1M1.py:905-910) and advances the
    character-selection tutorial when it sees a menu CLOSE (``GetBool()==0``)
    with the officer as the event destination. Without this dispatch the
    tutorial never progresses and player control is never returned.

    ``destination`` and the bool mirror what HandleMenuEvent reads
    (``GetDestination()`` / ``GetBool()``); ``is_open`` True -> 1 (opening),
    False -> 0 (closing). A None character (unresolved menu) is a no-op.
    """
    if character is None:
        return
    import App
    ev = App.TGBoolEvent_Create()
    ev.SetEventType(App.ET_CHARACTER_MENU)
    ev.SetSource(character)
    ev.SetDestination(character)
    ev.SetBool(1 if is_open else 0)
    character.ProcessEvent(ev)


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
            # BC-faithful: a real set with no character under this name returns
            # NULL, exactly like Appc's CharacterClass_GetObject. This is what
            # makes the ubiquitous SDK get-or-create idiom work —
            #     pChar = App.CharacterClass_GetObject(pSet, name)
            #     if not pChar: pChar = <Module>.CreateCharacter(pSet); ...
            # (e.g. E1M2.CreatePicard). Vivifying a blank CharacterClass here
            # returned a truthy placeholder that defeated the `if not pChar`
            # guard, so the real create+SetLocation never ran and the character
            # rendered as a hollow, unplaced object (Picard never appeared).
            return None
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


class _NullMenuClass(STTopLevelMenu):
    """The NULL menu handle — falsy like a SWIG null pointer, but with the
    full (inert) menu surface so SDK code that dereferences it without a
    null-check (DetachMenuFrom*'s RemoveHandlerForInstance / GetSubmenuW
    chains) no-ops instead of crashing. See CharacterClass.GetMenu."""

    def __bool__(self) -> bool:
        return False

    def GetSubmenuW(self, label):
        return self          # chainable: null menu's submenus are null menus

    GetSubmenu = GetSubmenuW

    def GetButtonW(self, label):
        return None


_NULL_MENU = _NullMenuClass("<null menu>")


def STTopLevelMenu_CreateNull():
    """SDK: DetachMenuFrom* assigns this via SetMenu to drop a character's
    menu pointer ("this doesn't destroy the menu, just removes the
    character's pointer to it")."""
    return _NULL_MENU
