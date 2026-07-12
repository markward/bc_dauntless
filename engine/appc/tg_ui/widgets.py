"""Core TG widgets — state-holding, render-free.

Conventions match engine/appc/characters.py STMenu/STButton: real classes,
(x, y) accepted and stored but never consulted (dauntless re-style decision,
2026-06-03 mirror spec), lenient casts, no _NamedStub leakage.
"""
from engine.appc.events import TGEventHandlerObject

# Monotonic per-process widget ids — used by CEF panels to address snapshot
# nodes back to live widgets. Never persisted.
_next_widget_id = 0


def ensure_widget_id(widget) -> int:
    """Assign (once) and return the widget's stable per-process id.

    Reads via __dict__ — TGObject.__getattr__ returns a _Stub (not raising
    AttributeError) for missing attributes, so a plain getattr-with-default
    would never see the default and would return the stub as the id.
    """
    global _next_widget_id
    wid = widget.__dict__.get("_widget_id")
    if wid is None:
        _next_widget_id += 1
        wid = _next_widget_id
        widget._widget_id = wid
    return wid


# ── Wide-char (WC_*) constants ────────────────────────────────────────────────
# SDK paragraph code points. BC's Appc exports a full table; the shim defines
# only what scripts reference (faithful Unicode code points). WC_CURSOR marks an
# inline child-widget insertion point — BC's real value is engine-internal and
# never displayed, so a Unicode Private-Use-Area sentinel is used.
WC_BACKSPACE = 8
WC_TAB = 9
WC_LINEFEED = 10
WC_RETURN = 13
WC_SPACE = 32
WC_CURSOR = 0xE000

_WC_TO_STR = {
    WC_BACKSPACE: "",
    WC_TAB: "\t",
    WC_LINEFEED: "\n",
    WC_RETURN: "\n",
    WC_SPACE: " ",
    WC_CURSOR: "",
}


def wc_to_str(wc) -> str:
    """Map a WC_* code point to its display string (control codes → '' or
    whitespace; printable code points → the character)."""
    wc = int(wc)
    if wc in _WC_TO_STR:
        return _WC_TO_STR[wc]
    try:
        return chr(wc)
    except (ValueError, OverflowError):
        return ""


class TGPane(TGEventHandlerObject):
    """Container widget. Width/height/(x, y) stored, never rendered."""

    def __init__(self, width: float = 0.0, height: float = 0.0):
        super().__init__()
        self._width = float(width)
        self._height = float(height)
        self._children: list = []   # (child, x, y) tuples
        self._visible = True
        self._enabled = True

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))
        # Some SDK call sites add non-TGPane duck-typed panels (e.g.
        # engine/ui/ship_display_panel.py's ShipDisplayPanel) that implement
        # their own SetPosition/GetLeft/Layout and never opt into resolver
        # state. Only seed resolver state on real TGPane widgets — isinstance,
        # not hasattr/getattr, because TGObject.__getattr__ vends a truthy
        # _Stub for missing attributes on other engine base classes too.
        if isinstance(child, TGPane):
            child._ensure_layout_state()
            child._local_left = float(x)
            child._local_top = float(y)

    def GetChildren(self) -> list:
        # Returns (child, x, y) 3-tuples — dauntless-internal convenience,
        # NOT an SDK method. SDK code iterates via GetFirstChild/GetNextChild.
        return list(self._children)

    # ── SDK child-iteration API ──────────────────────────────────────────────
    # StylizedWindow.py walks panes with GetFirstChild/GetNextChild (its local
    # GetChildren helper). These must exist as real methods: a missing name
    # resolves to a truthy _Stub via TGObject.__getattr__ and the SDK's
    # `while pChild:` loop never terminates.

    def GetFirstChild(self):
        return self._children[0][0] if self._children else None

    def GetLastChild(self):
        return self._children[-1][0] if self._children else None

    def GetPrevChild(self, child):
        for i, (c, _x, _y) in enumerate(self._children):
            if c is child:
                return self._children[i - 1][0] if i > 0 else None
        return None

    def GetNextChild(self, child):
        for i, (c, _x, _y) in enumerate(self._children):
            if c is child:
                if i + 1 < len(self._children):
                    return self._children[i + 1][0]
                return None
        return None

    def GetNthChild(self, n):
        n = int(n)
        if 0 <= n < len(self._children):
            return self._children[n][0]
        return None

    def GetNumChildren(self) -> int:
        return len(self._children)

    def InsertChild(self, index, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        """Insert a child at the given list position, shifting later children right."""
        self._children.insert(int(index), (child, float(x), float(y)))

    def DeleteChild(self, child) -> None:
        self._children = [(c, x, y) for (c, x, y) in self._children if c is not child]

    def KillChildren(self) -> None:
        self._children.clear()

    def SetVisible(self, *args) -> None:      self._visible = True
    def SetNotVisible(self, *args) -> None:   self._visible = False
    def IsVisible(self) -> int:               return 1 if self._visible else 0
    def SetEnabled(self, *args) -> None:      self._enabled = True
    def SetDisabled(self, *args) -> None:     self._enabled = False
    def IsEnabled(self) -> int:               return 1 if self._enabled else 0

    def GetWidth(self) -> float:              return self._width
    def GetHeight(self) -> float:             return self._height
    def GetParent(self):
        # Defaults to None (callers null-guard via TGPane_Cast). Nothing
        # sets `_parent` on a TGPane today — this is a plain, harmless
        # fallback, not a load-bearing back-ref for any live caller.
        return self.__dict__.get("_parent")
    def Resize(self, *args) -> None:          pass
    def ResizeUI(self, *args) -> None:        pass
    def RepositionUI(self, *args) -> None:    pass
    def InteriorChangedSize(self, *args) -> None:  pass
    def SetNoFocus(self, *args) -> None:      pass
    def SetFocus(self, *args) -> None:        pass
    # CallNextHandler inherited from TGEventHandlerObject (LIFO chain advance).
    def SetNotMinimized(self, *args) -> None: pass

    # ── Layout resolver state (Task 4/5) ─────────────────────────────────────
    #   _local_left/_top : this widget's position relative to its parent origin
    #   _abs_rect        : resolved absolute Rect (None until Layout runs)
    #   _align_spec      : optional (other, my_anchor, other_anchor) for AlignTo
    def _ensure_layout_state(self):
        # Reads via __dict__, NOT hasattr: TGObject.__getattr__ (engine/core/ids.py)
        # returns a truthy _Stub for any missing attribute instead of raising
        # AttributeError, so hasattr(self, "_local_left") is always True and this
        # guard would never initialize state. See ensure_widget_id() above for
        # the same gotcha on widget ids.
        if "_local_left" not in self.__dict__:
            self._local_left = 0.0
            self._local_top = 0.0
            self._abs_rect = None
            self._align_spec = None

    def SetPosition(self, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._ensure_layout_state()
        self._local_left = float(x)
        self._local_top = float(y)
        self._align_spec = None

    def Move(self, dx: float = 0.0, dy: float = 0.0, *_extra) -> None:
        self._ensure_layout_state()
        self._local_left += float(dx)
        self._local_top += float(dy)

    def AlignTo(self, other, my_anchor, other_anchor, *_extra) -> None:
        # Records an alignment spec resolved at Layout() so my_anchor's point
        # on this widget coincides with other_anchor's point on the
        # already-resolved sibling `other`. See _resolve_child_rect.
        self._ensure_layout_state()
        self._align_spec = (other, int(my_anchor), int(other_anchor))
        self._local_left = 0.0
        self._local_top = 0.0

    def Layout(self, *args) -> None:
        from engine.appc.tg_ui.layout import Rect
        self._ensure_layout_state()
        if self._abs_rect is None:            # root: place at its own local
            self._abs_rect = Rect(self._local_left, self._local_top,
                                  self._width, self._height)
        self._layout_children()

    def _layout_children(self):
        origin_l = self._abs_rect.left
        origin_t = self._abs_rect.top
        for child, _x, _y in self._children:
            if not isinstance(child, TGPane):  # see AddChild note above
                continue
            child._ensure_layout_state()
            child._abs_rect = self._resolve_child_rect(child, origin_l, origin_t)
            child._layout_children()

    def _resolve_child_rect(self, child, origin_l, origin_t):
        from engine.appc.tg_ui.layout import (
            Rect, anchor_point, ANCHOR_FRACTIONS, LayoutNotResolved,
        )
        if child._align_spec is not None:
            other, my_anchor, other_anchor = child._align_spec
            if getattr(other, "_abs_rect", None) is None:
                raise LayoutNotResolved("AlignTo target not yet resolved")
            ox, oy = anchor_point(other._abs_rect, other_anchor)
            mfx, mfy = ANCHOR_FRACTIONS[my_anchor]
            return Rect(ox - mfx * child._width, oy - mfy * child._height,
                        child._width, child._height)
        return Rect(origin_l + child._local_left,
                    origin_t + child._local_top,
                    child._width, child._height)

    def GetLeft(self) -> float:
        # Best-effort, NOT fail-loud: real (read-only) SDK scripts read a
        # sibling's GetLeft()/GetTop() immediately after AddChild/SetPosition
        # — e.g. Bridge/PowerDisplay.py:474 chains
        # `pPowerDisplay.AddChild(pMainRuler, 0.0, pWarpCoreRuler.GetTop(), 0)`
        # with no top-down Layout() pass ever having run. Fall back to the
        # known local placement (never a fabricated 0.0-for-everyone) instead
        # of raising; GetScreenOffset is the strict, fail-loud one (below).
        self._ensure_layout_state()
        if self._abs_rect is not None:
            return self._abs_rect.left
        return self._local_left

    def GetTop(self) -> float:
        self._ensure_layout_state()
        if self._abs_rect is not None:
            return self._abs_rect.top
        return self._local_top

    def GetScreenOffset(self, out=None):
        self._ensure_layout_state()
        if self._abs_rect is None:
            from engine.appc.tg_ui.layout import LayoutNotResolved
            raise LayoutNotResolved("GetScreenOffset before Layout")
        if out is not None:
            if hasattr(out, "x"): out.x = self._abs_rect.left
            if hasattr(out, "y"): out.y = self._abs_rect.top
            return out
        from engine.appc.math import TGPoint3
        return TGPoint3(self._abs_rect.left, self._abs_rect.top, 0.0)


class TGIcon(TGPane):
    """Atlas-icon widget — records (group, icon id, color), draws nothing."""

    def __init__(self, group_name: str = "", icon_id: int = 0, color=None):
        super().__init__()
        self._group_name = str(group_name)
        self._icon_id = int(icon_id)
        self._color = color
        # BC sizes an icon to its artwork on creation, so GetWidth/GetHeight are
        # never 0. Headless has no artwork; use a unit square so SDK ratio math
        # (UIHelpers.CreateCurve: fIWidth / fIHeight) is well-defined (=1.0)
        # rather than a ZeroDivisionError (Resize is inert like all TGPane
        # geometry, so 1.0 is what layout math sees).
        self._width = 1.0
        self._height = 1.0

    def GetIconGroupName(self) -> str:  return self._group_name
    def GetIconID(self) -> int:         return self._icon_id
    def SetColor(self, color) -> None:  self._color = color
    def SetIconNum(self, n) -> None:    self._icon_id = int(n)
    def SizeToArtwork(self, *args) -> None:  pass


class TGParagraph(TGPane):
    """Text widget — holds the string; font/scale/color stored, unused.

    The SDK passes paragraph flags (read-only, word-wrap, …) OR'd together as
    the last arg to TGParagraph_Create/CreateW. They're opaque to us — never
    decoded — so distinct bit values are all that's required."""

    TGPF_READ_ONLY = 0x01
    TGPF_INSERT_MODE = 0x02
    TGPF_WORD_WRAP = 0x04
    TGPF_RECALC_BOUNDS = 0x08
    TGPF_FLAGS_MASK = 0x0F

    def __init__(self, text: str = "", scale: float = 1.0, color=None):
        super().__init__()
        # Ordered content stream: ("text", str) | ("char", int) | ("child", TGParagraph)
        self._segments: list = []
        if text:
            self._segments.append(("text", str(text)))
        self._scale = float(scale)
        self._color = color

    def AppendStringW(self, text) -> None:
        self._segments.append(("text", str(text)))

    # SDK also calls the non-W name in a few places.
    AppendString = AppendStringW

    def AppendChar(self, wc) -> None:
        self._segments.append(("char", int(wc)))

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        # Keep the TGPane container contract (child lands on _children) AND
        # record positionally in the segment stream so inline glyphs render
        # in call order relative to surrounding text.
        super().AddChild(child, x, y)
        self._segments.append(("child", child))

    def iter_segments(self) -> list:
        """dauntless-internal: the ordered (kind, value) content stream."""
        return list(self._segments)

    def GetText(self) -> str:
        out = []
        for kind, val in self._segments:
            if kind == "text":
                out.append(val)
            elif kind == "char":
                out.append(wc_to_str(val))
            elif kind == "child":
                out.append(val.GetText())
        return "".join(out)

    def SetText(self, text) -> None:
        self._segments = [("text", str(text))] if text else []

    # SDK W-variant setter name used by some callers.
    SetStringW = SetText

    def SetFont(self, *args) -> None:   pass
    def SetColor(self, color) -> None:  self._color = color


class TGIconGroup:
    """Texture-atlas icon group. Records SetIconLocation entries verbatim
    so a future renderer (or debug tooling) can read them; draws nothing.
    Asset registry, not a scene widget — no TGObject inheritance on purpose."""

    ROTATE_0, ROTATE_90, ROTATE_180, ROTATE_270 = 0, 1, 2, 3
    MIRROR_NONE, MIRROR_HORIZONTAL, MIRROR_VERTICAL = 0, 1, 2

    def __init__(self, name: str = ""):
        self._name = str(name)
        self._textures: list = []          # loaded texture paths, index = handle
        self._locations: dict = {}         # slot -> (tex, x, y, w, h, rot, mirror)

    def GetName(self) -> str:
        return self._name

    def LoadIconTexture(self, path: str) -> int:
        self._textures.append(str(path))
        return len(self._textures) - 1

    def SetIconLocation(self, slot, texture, x, y, w, h,
                        rotation=ROTATE_0, mirror=MIRROR_NONE) -> None:
        self._locations[int(slot)] = (
            texture, int(x), int(y), int(w), int(h), int(rotation), int(mirror)
        )

    def GetIconLocation(self, slot):
        return self._locations.get(int(slot))

    def GetIconScreenWidth(self, slot) -> float:
        # SDK uses this for pixel layout we never render — 0.0 is fine.
        return 0.0

    def GetIconScreenHeight(self, slot) -> float:
        return 0.0


class _TGRect:
    def GetLeft(self) -> float:   return 0.0
    def GetTop(self) -> float:    return 0.0
    def GetRight(self) -> float:  return 0.0
    def GetBottom(self) -> float: return 0.0


class TGFrame(TGPane):
    """Bordered frame — records colour/stretch; geometry inert like TGPane."""
    NO_STRETCH_LR = 1

    def __init__(self, group_name: str = "", icon_id: int = 0):
        super().__init__()
        self._group_name = str(group_name)
        self._icon_id = int(icon_id)
        self._ni_color = None
        self._edge_stretch = 0

    def GetInnerRect(self) -> _TGRect:       return _TGRect()
    def SetNiColor(self, *rgba) -> None:     self._ni_color = rgba
    def SetEdgeStretch(self, mode) -> None:  self._edge_stretch = int(mode)


class STTiledIcon(TGIcon):
    """Tiling icon widget — records tiling/tile-size per direction; draws nothing."""
    DIRECTION_X = 0
    DIRECTION_Y = 1

    def __init__(self, group_name: str = "", icon_id: int = 0, color=None):
        super().__init__(group_name, icon_id, color)
        self._tiling = {}
        self._tile_size = {}

    def SetTiling(self, direction, n) -> None:
        self._tiling[int(direction)] = n

    def SetTileSize(self, direction, size) -> None:
        self._tile_size[int(direction)] = float(size)


# ── Factories + lenient casts (engine/appc convention) ───────────────────────

def TGPane_Create(width=0.0, height=0.0) -> TGPane:
    return TGPane(width, height)


def TGPane_Cast(obj):
    return obj if isinstance(obj, TGPane) else None


def TGIcon_Create(group_name="", icon_id=0, color=None, *_extra) -> TGIcon:
    return TGIcon(group_name, icon_id, color)


def TGIcon_Cast(obj):
    return obj if isinstance(obj, TGIcon) else None


def TGParagraph_Create(text="", scale=1.0, color=None, *_extra) -> TGParagraph:
    return TGParagraph(text, scale, color)


def TGParagraph_CreateW(text="", scale=1.0, color=None, *_extra) -> TGParagraph:
    return TGParagraph(str(text), scale, color)


def TGParagraph_Cast(obj):
    return obj if isinstance(obj, TGParagraph) else None


def TGFrame_Create(group_name="", icon_id=0) -> TGFrame:
    return TGFrame(group_name, icon_id)


def TGFrame_Cast(obj):
    return obj if isinstance(obj, TGFrame) else None


def STTiledIcon_Create(group_name="", icon_id=0, color=None, *_extra) -> STTiledIcon:
    return STTiledIcon(group_name, icon_id, color)


def STTiledIcon_Cast(obj):
    return obj if isinstance(obj, STTiledIcon) else None
