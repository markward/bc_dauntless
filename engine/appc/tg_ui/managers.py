"""TG UI managers — real storage, no rendering, no _NamedStub leakage.

The point is that Icons/FontsAndIcons.py and the LCARS_* loaders run
against real objects so registrations are inspectable and failures loud.
"""
from engine.appc.tg_ui.widgets import TGIconGroup, TGPane


class TGFontHandle:
    """Plausible-metrics font handle: height = point size, fixed advance,
    so SDK layout math produces finite numbers headless."""

    def __init__(self, family: str, size: int):
        self._family = str(family)
        self._size = int(size)

    def GetHeight(self) -> float:
        return float(self._size)

    def GetStringWidth(self, text) -> float:
        # Fixed 0.6em advance per character — plausible, never zero-div.
        return 0.6 * self._size * len(str(text))


class TGFontGroup(TGIconGroup):
    """Font atlas group — CreateFontGroup callers chain both TGIconGroup
    methods (LoadIconTexture) and font accessors (GetFontName/GetFontSize)."""

    def __init__(self, family: str = "", size: int = 0):
        super().__init__("%s%d" % (family, int(size)))
        self._family = str(family)
        self._size = int(size)

    def GetFontName(self) -> str:  return self._family
    def GetFontSize(self) -> int:  return self._size


class TGFontManager:
    def __init__(self):
        # (family, size) -> (registered_name, load_func_name)
        self._fonts: dict = {}
        self._font_groups: dict = {}      # (family, size) -> TGFontGroup
        self._default = ("Crillee", 5)    # first font FontsAndIcons registers

    def RegisterFont(self, family, size, registered_name, load_func_name) -> None:
        self._fonts[(str(family), int(size))] = (str(registered_name),
                                                 str(load_func_name))

    def GetFont(self, family, size) -> TGFontHandle:
        return TGFontHandle(family, int(size))

    # SDK default-font API — called on every menu open/close
    # (Bridge/*MenuHandlers, StylizedWindow.py).
    def SetDefaultFont(self, family, size, *args) -> None:
        self._default = (str(family), int(size))

    def GetDefaultFont(self) -> "TGFontGroup":
        family, size = self._default
        return self._font_groups.get((family, size)) or TGFontGroup(family, size)

    def CreateFontGroup(self, family, size, *args) -> "TGFontGroup":
        return TGFontGroup(family, int(size))

    def AddFontGroup(self, group, *args) -> None:
        self._font_groups[(group.GetFontName(), group.GetFontSize())] = group

    def GetFontGroup(self, family, size) -> "TGFontGroup":
        key = (str(family), int(size))
        return self._font_groups.get(key) or TGFontGroup(str(family), int(size))


class TGIconManager:
    def __init__(self):
        self._registered: dict = {}   # name -> (texture_base, load_func_name)
        self._groups: dict = {}       # name -> TGIconGroup

    def RegisterIconGroup(self, name, texture_base, load_func_name) -> None:
        self._registered[str(name)] = (str(texture_base), str(load_func_name))

    def CreateIconGroup(self, name) -> TGIconGroup:
        return TGIconGroup(str(name))

    def AddIconGroup(self, group: TGIconGroup) -> None:
        self._groups[group.GetName()] = group

    def GetIconGroup(self, name):
        return self._groups.get(str(name))

    # Canned 1024x768 — single source of truth is graphics_mode's singleton;
    # duplicated value here because the SDK asks both objects.
    def GetScreenWidth(self) -> float:  return 1024.0
    def GetScreenHeight(self) -> float: return 768.0


class TGImageManager:
    """Registration sink — SDK registers loose images; nothing reads back."""

    def __init__(self):
        self._images: dict = {}

    def RegisterImage(self, name, path, *args) -> None:
        self._images[str(name)] = str(path)

    def GetImageDetail(self) -> int:
        # Detail index into per-asset path lists (LoadInterface,
        # character NIF selection). 2 = "High", the original default.
        return 2


class TGFocusManager:
    def __init__(self):
        self._focused = None
        self._tab_order: list = []

    def SetFocus(self, widget, *args) -> None:
        self._focused = widget

    def GetFocus(self):
        return self._focused

    # Tab-order bookkeeping — SDK registers every bridge-menu widget
    # (94 AddObjectToTabOrder call sites). Stored, never traversed headless.
    def AddObjectToTabOrder(self, widget, *args) -> None:
        if widget not in self._tab_order:
            self._tab_order.append(widget)

    def RemoveObjectFromTabOrder(self, widget, *args) -> None:
        if widget in self._tab_order:
            self._tab_order.remove(widget)

    def RemoveAllObjectsUnder(self, pane, *args) -> None:
        # SDK calls this on menu teardown with a parent pane; without a
        # rendered hierarchy we conservatively clear everything registered.
        self._tab_order.clear()


# Module-level singletons re-exported by App.py.
g_kFontManager = TGFontManager()
g_kIconManager = TGIconManager()
g_kImageManager = TGImageManager()
g_kFocusManager = TGFocusManager()
g_kRootWindow = TGPane()
