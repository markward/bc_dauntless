"""CrewMenuPanel — projects the STTopLevelMenu trees registered on
TacticalControlWindow into CEF, and routes clicks back as SDK events.

Outbound: walk TacticalControlWindow.GetMenuList() once per tick, snapshot
labels/flags/ids, diff, emit setCrewMenus(...). Inbound: resolve clicked id
to the live widget and fire its activation event.

Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.st_widgets import SortedRegionMenu, STWarpButton
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.appc.windows import TacticalControlWindow
from engine.ui import ui_attention
from engine.ui.panel import Panel

_logger = logging.getLogger(__name__)


def _current_player():
    """Return the current player ship, or None.

    Mirrors the established engine/ui/ship_display_panel.py:_get_player()
    pattern: resolve the current game via Game_GetCurrentGame() and return
    game.GetPlayer() if game else None, guarded against any lookup failure.
    """
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


class CrewMenuPanel(Panel):
    def __init__(self, on_set_course=None, on_warp_engage=None):
        super().__init__()
        # Empty-state sentinel (matches SDKMirrorPanel): a quiescent panel
        # emits nothing on the first tick; invalidate() resets to None so
        # the empty state still fires once after a CEF page reload.
        self._last_pushed: Optional[str] = json.dumps({"menus": []})
        self._widgets_by_id: dict = {}
        self._logged_unrecognised: set = set()
        self._open_menu_id: Optional[int] = None
        # Inline accordion expand-state for submenu rows — Python-owned,
        # mirroring TargetListView's per-row `expanded` flag. Cleared
        # whenever the open menu changes (a reopened menu starts collapsed,
        # matching BC).
        self._expanded_ids: set[int] = set()
        # Injected by host_loop: opens the SettingCoursePanel when the Helm
        # Set Course button is clicked. None -> click is a silent no-op
        # (keeps headless construction and existing tests working).
        self._on_set_course = on_set_course
        # Injected by host_loop: engages the warp spine when the SDK Helm
        # "Warp" button (an STWarpButton) is clicked. Stage 1 drives the warp
        # directly through this callback rather than firing the SDK
        # ET_WARP_BUTTON_PRESSED event (whose WarpPressed handler does
        # camera/control work deferred to later stages). None -> no-op.
        self._on_warp_engage = on_warp_engage
        # Set by _officer_for_menu on a label-only resolution miss (broken
        # attach); read back in toggle_menu's unowned-menu branch.
        self._unowned_label_officer = None
        # Guards the panel-mismatch diagnostic in toggle_menu so a
        # never-wire()d panel (e.g. a bare test instance) warns once instead
        # of on every toggle_menu call.
        self._warned_panel_mismatch = False

    @property
    def name(self) -> str:
        return "crew-menu"

    def render_payload(self) -> Optional[str]:
        payload = json.dumps(self.snapshot())
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setCrewMenus(" + payload + ");"

    def snapshot(self) -> dict:
        """Structured (dict) snapshot of the current menu tree.

        Rebuilt fresh on every call — unlike render_payload(), this is NOT
        diff-gated against the last CEF push, so callers (tests, other
        Python-side consumers) always see live state. render_payload() is
        the sole gate protecting the CEF push from the flicker described in
        ui_attention's module docstring: MissionLib's RefreshArrows timer
        calls HidePointerArrows() then re-issues ShowPointerArrow for every
        entry, 8x/second, both inside one tick. Because _snapshot_node reads
        ui_attention state fresh each call and produces the exact same dict
        (and therefore the exact same JSON string) when highlight state is
        unchanged end-to-end, render_payload's string-equality check against
        self._last_pushed absorbs that hide->show cycle as a no-op — CEF
        never sees the transient empty state and the CSS pulse never
        restarts.
        """
        self._widgets_by_id = {}
        menus = []
        for m in TacticalControlWindow.GetInstance().GetMenuList():
            node = self._snapshot_node(m)
            if node is not None:
                node["open"] = (node["id"] == self._open_menu_id)
                menus.append(node)
        return {"menus": menus}

    def _snapshot_node(self, widget) -> Optional[dict]:
        # Set Course (the one SortedRegionMenu) is projected as a leaf
        # button, not an expandable parent — its click opens a modal.
        import App as _App
        if isinstance(widget, _App.EngRepairPaneWidget):
            from engine.ui.eng_repair_pane import repair_pane_snapshot
            wid = ensure_widget_id(widget)
            self._widgets_by_id[wid] = widget
            areas = repair_pane_snapshot(_current_player(), self._widgets_by_id.__setitem__)
            node = {"id": wid, "type": "repair-pane",
                    "label": "Damage Control", "enabled": True,
                    "visible": bool(widget.IsVisible()), **areas}
            ui_attention.apply(node, wid)
            return node
        if isinstance(widget, SortedRegionMenu):
            node_type = "button"
        elif isinstance(widget, STMenu):
            node_type = "menu"
        elif isinstance(widget, STButton):
            node_type = "button"
        else:
            self._log_unrecognised_once(type(widget).__name__)
            return None
        wid = ensure_widget_id(widget)
        self._widgets_by_id[wid] = widget
        node = {
            "id": wid,
            "type": node_type,
            "label": widget.GetLabel(),
            "enabled": bool(widget.IsEnabled()),
            "visible": bool(widget.IsVisible()),
        }
        # Applies to every node type that gets an id — STMenu/submenu rows
        # (the E1M1 "Set Course" target is a submenu, not a leaf) AND
        # STButton leaves alike.
        ui_attention.apply(node, wid)
        if isinstance(widget, STMenu) and not isinstance(widget, SortedRegionMenu):
            node["expanded"] = wid in self._expanded_ids
            node["openable"] = bool(widget.IsOpenable())
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("expand:"):
            try:
                wid = int(action[len("expand:"):])
            except ValueError:
                _logger.info("crew-menu: malformed expand action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                _logger.info("crew-menu: stale expand id %d dropped", wid)
                return True
            if isinstance(widget, STMenu):
                if wid in self._expanded_ids:
                    self._expanded_ids.discard(wid)
                else:
                    self._expanded_ids.add(wid)
                    widget.SendActivationEvent()   # BC broadcasts activation event on open
            return True
        if action.startswith("toggle:"):
            try:
                wid = int(action[len("toggle:"):])
            except ValueError:
                _logger.info("crew-menu: malformed toggle action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                _logger.info("crew-menu: stale toggle id %d dropped", wid)
                return True
            self.toggle_menu(widget)
            return True
        if action.startswith("click:"):
            try:
                wid = int(action[len("click:"):])
            except ValueError:
                _logger.info("crew-menu: malformed click action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                # Menu rebuilt between frames — drop; next snapshot repairs the UI.
                _logger.info("crew-menu: stale click id %d dropped", wid)
                return True
            if not widget.IsEnabled():
                return True
            if isinstance(widget, SortedRegionMenu):
                # Replace inline expand with a modal. The helm menu stays
                # open behind the centred popup (no _open_menu_id reset) so
                # it shows in the background; just open the Set Course modal
                # over it. No SDK event.
                if self._on_set_course is not None:
                    self._on_set_course(widget)
                return True
            if isinstance(widget, STWarpButton):
                # The SDK Helm "Warp" button. Engage the warp spine directly
                # (Stage 1 bypasses the SDK ET_WARP_BUTTON_PRESSED / WarpPressed
                # path, whose camera/control work is deferred to later stages).
                if self._on_warp_engage is not None:
                    self._on_warp_engage(widget)
                return True
            root = self._root_of(wid)
            if isinstance(widget, STButton):
                # Original engine order: per-button activation event, then
                # ET_ST_BUTTON_CLICKED at the owning top-level menu, where the
                # SDK's Bridge.BridgeMenus.ButtonClicked turns the officer back
                # to face front. That handler speaks NOTHING — its per-officer
                # SayLine acks are commented out in stock BC (BridgeMenus.py:84).
                # So we fire no generic acknowledgement on a click either;
                # officers greet only when a menu is opened (see toggle_menu).
                # Buttons that should speak do so through their own SDK handlers
                # (Hail -> Kiska's line, alert -> XO, Scan Area -> Miguel's
                # ScanComplete). Firing a generic ack here doubled up with — and,
                # being single-channel, preempted — that real dialogue.
                widget.SendActivationEvent()
                if root is not None:
                    import App
                    clicked = App.TGEvent_Create()
                    clicked.SetEventType(App.ET_ST_BUTTON_CLICKED)
                    clicked.SetDestination(root)
                    clicked.SetSource(widget)
                    App.g_kEventManager.AddEvent(clicked)
            # Menu nodes open/close client-side in CEF; no SDK event needed.
            return True
        if action.startswith("repair:"):
            try:
                wid = int(action[len("repair:"):])
            except ValueError:
                _logger.info("crew-menu: malformed repair action %r", action)
                return True
            sub = self._widgets_by_id.get(wid)
            player = _current_player()
            bay = player.GetRepairSubsystem() if player is not None else None
            if sub is None or bay is None:
                _logger.info("crew-menu: stale repair id %d dropped", wid)
                return True
            import App
            evt = App.TGObjPtrEvent_Create()
            evt.SetEventType(App.ET_REPAIR_INCREASE_PRIORITY)
            evt.SetDestination(bay)
            evt.SetObjPtr(sub)
            App.g_kEventManager.AddEvent(evt)
            self._last_pushed = None      # force re-render with new order
            return True
        return False

    def _menu_officer(self):
        """The CharacterClass owning the currently-open top-level menu, or None."""
        if self._open_menu_id is None:
            return None
        root = self._root_of(self._open_menu_id)
        if root is None:
            return None
        return self._officer_for_menu(root)

    def open_officer(self):
        """The CharacterClass owning the currently-open top-level menu, or None.
        Public reader — CharacterClass.MenuUp needs it to enforce single-open."""
        return self._menu_officer()

    def is_menu_open(self, menu) -> bool:
        """True when `menu` is the currently-open top-level menu.

        Identity-based, unlike open_officer(), which resolves through the
        5-station label table and therefore cannot see a non-station officer's
        mission-made menu (E8M2's Liu, E3M1's MacCray). MenuUp/MenuDown must gate
        on THIS, or they can neither lower nor supersede such a menu."""
        if menu is None or self._open_menu_id is None:
            return False
        return self._open_menu_id == ensure_widget_id(menu)

    def _resolve_label_character(self, menu):
        """CharacterClass whose STATION LABEL matches `menu`, ignoring ownership.
        None if resolve_character raises or finds nothing. The single call site
        for crew_menu_hotkeys.resolve_character(menu.GetLabel()) — which loads
        and parses a TGL file — so _officer_for_menu and toggle_menu's
        broken-attach warning don't each pay for their own lookup."""
        try:
            from engine.ui import crew_menu_hotkeys
            return crew_menu_hotkeys.resolve_character(menu.GetLabel())
        except Exception:
            return None

    def _officer_for_menu(self, menu):
        """The CharacterClass OWNING `menu`, or None.

        Resolved by label (crew_menu_hotkeys), then confirmed by ownership: the
        SDK attaches a station menu to its officer with
        `pHelm.SetMenu(tcw.FindMenu("Helm"))` (HelmCharacterHandlers:50 and the
        four siblings), so the owner is the officer whose GetMenu() IS this menu.
        The ownership check matters because MenuUp() raises the officer's OWN menu
        (GetMenu()): a label-matching officer holding the NULL menu (never
        attached, or DetachMenuFrom* ran) has nothing to raise, so treating them
        as the owner would make the click a silent dead no-op. Returning None there
        routes toggle_menu down its unowned-menu path, which still opens the view.

        On an ownership-check miss, stashes the label-resolved (but non-owning)
        CharacterClass in `_unowned_label_officer` so toggle_menu's broken-attach
        warning can read WHY ownership failed without re-running
        _resolve_label_character for the same toggle."""
        char = self._resolve_label_character(menu)
        if char is None or char.GetMenu() is not menu:
            self._unowned_label_officer = char
            return None
        return char

    def show_menu(self, menu) -> None:
        """PURE view open: make `menu` the open top-level menu. Idempotent.

        Never calls MenuUp/MenuDown and never acknowledges. CharacterClass.MenuUp
        is BC's canonical primitive and the ONLY caller that should drive this —
        that one-way rule is what makes recursion impossible."""
        wid = ensure_widget_id(menu)
        if self._open_menu_id == wid:
            return                       # already open
        self._open_menu_id = wid
        self._expanded_ids.clear()       # a reopened menu starts collapsed
        try:
            menu.SendActivationEvent()   # BC broadcasts activation on open
        except Exception:
            _logger.debug("crew-menu: activation event failed", exc_info=True)

    def hide_menu(self) -> None:
        """PURE view close. Idempotent. Never calls MenuUp/MenuDown."""
        if self._open_menu_id is None:
            return
        self._open_menu_id = None
        self._expanded_ids.clear()

    def toggle_menu(self, menu) -> None:
        """Open `menu` (closing any other), or close it if already open.
        Single-open invariant shared by hotkeys and CEF title clicks.
        Disabled menus stay closed (stock BC); non-menus are ignored.

        DELEGATES to the officer's MenuUp()/MenuDown() — BC's canonical primitive,
        which drives the view, the turn, and the tutorial event. The spoken
        acknowledgement fires HERE, on the click path only, mirroring BC's
        `if (pCharacter.MenuUp()): CharacterInteraction(pCharacter)` — a SCRIPTED
        AT_MENU_UP must stay silent."""
        from engine.ui import crew_menu_hotkeys
        if crew_menu_hotkeys.get_panel() is not self:
            # MenuUp reaches the view via the globally-wired panel
            # (crew_menu_hotkeys.get_panel()), not via `self`. If wire() never
            # ran (or wired a DIFFERENT panel instance), an owned-menu click
            # below still acks and turns the officer, but nothing shows on
            # screen -- make that loud instead of a silent dead click. Warn
            # once per panel instance: a real misconfiguration is still
            # surfaced, but a never-wire()d test panel doesn't spam every
            # toggle_menu call.
            if not getattr(self, "_warned_panel_mismatch", False):
                self._warned_panel_mismatch = True
                _logger.warning(
                    "crew-menu: toggle_menu called on panel %r but "
                    "crew_menu_hotkeys.get_panel() is %r -- MenuUp will not "
                    "reach this panel's view", self, crew_menu_hotkeys.get_panel())
        if not isinstance(menu, STMenu) or not menu.IsEnabled():
            return
        wid = ensure_widget_id(menu)
        if self._open_menu_id == wid:                 # already open -> close it
            officer = self.open_officer()
            if officer is not None:
                officer.MenuDown()
            else:
                self.hide_menu()                      # unowned menu: view only
            return
        officer = self._officer_for_menu(menu)
        if officer is not None:
            if officer.MenuUp():                      # raises + turns + signals
                self._acknowledge(menu)               # BC: CharacterInteraction
            return
        # Unowned menu: either genuinely unowned (no officer's label matches,
        # silently harmless) or a BROKEN ATTACH — the label resolves to a real
        # officer who simply doesn't hold this menu (configure_bridge_officers
        # swallows per-station ConfigureForShip exceptions, so a station can
        # end up unattached). The latter silently stalls the tutorial's
        # dispatch_character_menu signal for that officer, so make it loud.
        # _officer_for_menu already ran this exact lookup above and stashed the
        # label-only result -- read it instead of re-resolving.
        # _officer_for_menu (patched out in some tests) is the only writer of
        # this attribute; getattr keeps a bypassed-__init__/patched-method
        # panel safe rather than requiring every caller to have run it.
        unowned_by = getattr(self, "_unowned_label_officer", None)
        if unowned_by is not None:
            _logger.warning(
                "crew-menu: menu %r resolves to an officer that does not "
                "own it (broken attach) -- falling back to a view-only open "
                "with no turn/dispatch", menu.GetLabel())
        other = self.open_officer()
        if other is not None:
            other.MenuDown()
        self.show_menu(menu)
        self._acknowledge(menu)

    def _acknowledge(self, menu) -> None:
        """Fire the owning officer's spoken acknowledgement. A resolution miss
        (unknown label / no bridge set) is a silent no-op — menu interaction
        must never break on a speech hiccup."""
        try:
            from engine.ui import crew_menu_hotkeys
            from engine.appc import crew_speech
            char = crew_menu_hotkeys.resolve_character(menu.GetLabel())
            crew_speech.acknowledge(char)
        except Exception:
            _logger.debug("crew-menu ack failed", exc_info=True)

    def open_menu_label(self) -> Optional[str]:
        """Label of the open top-level (station) menu, or None. The open id is
        always a top-level menu (toggle_menu only fires for titles), so its
        root is itself; the label feeds crew_menu_hotkeys.resolve_character."""
        if self._open_menu_id is None:
            return None
        root = self._root_of(self._open_menu_id)
        return root.GetLabel() if root is not None else None

    def has_open_menu(self) -> bool:
        return self._open_menu_id is not None

    def get_open_menu(self):
        """The currently open top-level menu OBJECT, or None. Source of truth
        for App.STTopLevelMenu_GetOpenMenu (engine/appc/characters.py) --
        BridgeHandlers.DropMenusTurnBack reads this to find (via GetOwner())
        which character to MenuDown() at cutscene start."""
        if self._open_menu_id is None:
            return None
        return self._root_of(self._open_menu_id)

    def close_open_menu(self) -> bool:
        """Close any open menu; True if one was open (ESC consumes the press in
        that case — see host_loop's modal ladder). Delegates to the officer's
        MenuDown() (which hides the view, turns them back, and signals)."""
        if self._open_menu_id is None:
            return False
        officer = self.open_officer()
        if officer is not None:
            officer.MenuDown()
        else:
            self.hide_menu()
        return True

    def invalidate(self) -> None:
        self._last_pushed = None
        # Mission swap rebuilds menus with fresh widget ids — a stale open
        # id would keep has_open_menu() True and swallow one ESC press.
        self._open_menu_id = None
        self._expanded_ids.clear()

    def _root_of(self, wid: int):
        """Top-level menu whose subtree contains the widget id, else None."""
        for menu in TacticalControlWindow.GetInstance().GetMenuList():
            if self._contains(menu, wid):
                return menu
        return None

    def _contains(self, widget, wid: int) -> bool:
        # __dict__ read — TGObject.__getattr__ stubs missing attributes.
        if widget.__dict__.get("_widget_id") == wid:
            return True
        if isinstance(widget, STMenu):
            return any(self._contains(c, wid) for c in widget._children)
        return False

    def _log_unrecognised_once(self, type_name: str) -> None:
        if type_name in self._logged_unrecognised:
            return
        self._logged_unrecognised.add(type_name)
        _logger.info("crew-menu: skipping unrecognised child type %s", type_name)
