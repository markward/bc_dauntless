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

    def GetChildren(self) -> list:
        return list(self._children)

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
    def Resize(self, *args) -> None:          pass
    def InteriorChangedSize(self, *args) -> None:  pass
    def SetNoFocus(self, *args) -> None:      pass
    def SetFocus(self, *args) -> None:        pass
    def CallNextHandler(self, _evt) -> None:  pass


class TGIcon(TGPane):
    """Atlas-icon widget — records (group, icon id, color), draws nothing."""

    def __init__(self, group_name: str = "", icon_id: int = 0, color=None):
        super().__init__()
        self._group_name = str(group_name)
        self._icon_id = int(icon_id)
        self._color = color

    def GetIconGroupName(self) -> str:  return self._group_name
    def GetIconID(self) -> int:         return self._icon_id
    def SetColor(self, color) -> None:  self._color = color


class TGParagraph(TGPane):
    """Text widget — holds the string; font/scale/color stored, unused."""

    def __init__(self, text: str = "", scale: float = 1.0, color=None):
        super().__init__()
        self._text = str(text)
        self._scale = float(scale)
        self._color = color

    def GetText(self) -> str:           return self._text
    def SetText(self, text) -> None:    self._text = str(text)
    # SDK W-variant setter name used by some callers.
    def SetStringW(self, text) -> None: self._text = str(text)
    def SetFont(self, *args) -> None:   pass
    def SetColor(self, color) -> None:  self._color = color


class TGIconGroup:
    """Texture-atlas icon group. Records SetIconLocation entries verbatim
    so a future renderer (or debug tooling) can read them; draws nothing."""

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
