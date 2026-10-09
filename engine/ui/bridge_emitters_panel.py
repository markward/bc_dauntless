"""Bridge Emitters -- developer-only bridge editor panel (spec
docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md §4, §7, §8).

Foundation scope: fly camera (hold RMB to look, WASDQE to move, Shift fast,
Alt slow), click-to-pick a NIF shape (Alt+click = the surface behind), a
selection tint, and the per-shape PBR material override (§9.2 source B) saved
to the per-bridge lighting document. The override is stored, not yet rendered:
the bridge PBR plan consumes it.

Driven like every dev modal: a pause-menu row opens it, the host keeps the
pause menu open-but-hidden (sim frozen) while it is open, calls handle_input(h)
each frame, and draws the bridge from camera_pose()."""
import copy
import json
import time
from typing import Optional

from engine import host_io
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer as lw
from engine.bridge_editor.fly_camera import FlyCamera
from engine.bridge_editor.picking import PickCycle, identity_for, pick_mesh
from engine.ui.panel import Panel

DOCK_CSS_PX = 360          # width of the docked panel, CSS px (bridge_emitters.css)
CLICK_SLOP_PX = 4.0
DEFAULT_ROUGHNESS = 1.0    # spec §9.2 source C
DEFAULT_METALNESS = 0.0
_CHANNELS = {"roughness": DEFAULT_ROUGHNESS, "metalness": DEFAULT_METALNESS}
_UNDO_LIMIT = 100


class BridgeEmittersPanel(Panel):
    def __init__(self, pose_provider, instance_provider, in_bridge_provider,
                 clock=time.monotonic, io=host_io, runtime=None):
        super().__init__()
        self._pose = pose_provider
        self._iid = instance_provider
        self._in_bridge = in_bridge_provider
        self._clock = clock
        self._io = io
        self._runtime = runtime
        self._visible = False
        self._last_pushed = None
        self._reset_session()

    def _reset_session(self):
        self._camera = None
        self._last_t = None
        self._rmb = False
        self._left = False
        self._press_xy = None
        self._press_alt = False
        self._drag = 0.0
        self._info = None
        self._attached_iid = None
        self._load = None
        self._doc = None
        self._saved_text = None
        self._undo = []
        self._selected = None          # ShapeIdentity
        self._hover_mesh = -1
        self._cycle = PickCycle()
        self._status = ""
        self._pushed_highlight = None
        self._h_for_release = None

    # ── Panel ────────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "bridge-emitters"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._reset_session()
        self._last_pushed = None
        self.visible = True

    def close(self) -> None:
        h = self._h_for_release
        if self._rmb and h is not None:
            h.set_cursor_locked(False)
        self._io.set_bridge_highlight(None, -1, -1)
        self._reset_session()
        self.visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def invalidate(self) -> None:
        self._last_pushed = None

    def camera_pose(self):
        return self._camera.pose() if (self._visible and self._camera) else None

    # ── per-frame input ──────────────────────────────────────────────────
    def handle_input(self, h) -> None:
        if not self._visible:
            return
        self._h_for_release = h
        if not self._in_bridge():
            self._unlock_cursor(h)
            self._camera = None
            return
        iid = self._iid()
        if iid is None:
            self._unlock_cursor(h)
            return
        if self._camera is None:
            eye, target, _up, _fov = self._pose()
            self._camera = FlyCamera.from_pose(eye, target)
        if self._info is None or iid != self._attached_iid:
            # First frame, or the bridge was swapped under an open panel
            # (QuickBattle DBridge -> EBridge): a different NIF, a different
            # document. The old selection means nothing on the new model.
            self._attach(iid)
            self._selected = None
            self._cycle.reset()

        now = self._clock()
        dt = 0.0 if self._last_t is None else min(max(now - self._last_t, 0.0), 0.1)
        self._last_t = now
        keys = h.keys

        rmb = bool(h.mouse_button_state(keys.MOUSE_BUTTON_RIGHT))
        if rmb and not self._rmb:
            h.set_cursor_locked(True)
            h.consume_mouse_delta()
        elif not rmb and self._rmb:
            h.set_cursor_locked(False)
        self._rmb = rmb
        if rmb:
            dx, dy = h.consume_mouse_delta()
            self._camera.look(dx, dy)
            ks = h.key_state
            self._camera.move(
                dt,
                forward=int(ks(keys.KEY_W)) - int(ks(keys.KEY_S)),
                strafe=int(ks(keys.KEY_D)) - int(ks(keys.KEY_A)),
                lift=int(ks(keys.KEY_E)) - int(ks(keys.KEY_Q)),
                fast=ks(keys.KEY_LEFT_SHIFT) or ks(keys.KEY_RIGHT_SHIFT),
                slow=ks(keys.KEY_LEFT_ALT) or ks(keys.KEY_RIGHT_ALT))
            self._push_highlight(iid)
            return

        x, y = h.cursor_pos()
        fb = h.framebuffer_size()
        over_dock = x >= fb[0] - DOCK_CSS_PX * self._dsf(h, fb)
        trace = lambda o, d, m, ex: self._io.ray_trace_mesh_pick(iid, o, d, m, ex)
        pose = self._camera.pose()
        hover = None if over_dock else pick_mesh(trace, (x, y), fb, pose)
        self._hover_mesh = -1 if hover is None else hover

        left = bool(h.mouse_button_state(keys.MOUSE_BUTTON_LEFT))
        if left and not self._left:                      # press edge
            # A press that starts over the dock is the panel's, never a pick.
            self._press_xy = None if over_dock else (x, y)
            self._press_alt = bool(h.key_state(keys.KEY_LEFT_ALT)
                                   or h.key_state(keys.KEY_RIGHT_ALT))
            self._drag = 0.0
        elif left and self._press_xy is not None:        # held: measure drag
            self._drag = max(self._drag, abs(x - self._press_xy[0]) + abs(y - self._press_xy[1]))
        elif not left and self._left and self._press_xy is not None:   # release
            if self._drag <= CLICK_SLOP_PX:
                self._click(trace, (x, y), fb, pose)
            self._press_xy = None
        self._left = left
        self._push_highlight(iid)

    def _unlock_cursor(self, h):
        """Release RMB-fly cursor lock when the view/instance disappears out
        from under it. Without this, leaving the bridge (or the instance
        vanishing) while RMB is held strands the cursor locked forever --
        handle_input returns before the normal rmb-edge-release code below
        ever runs again, since there is no live camera/iid to fly."""
        if self._rmb:
            h.set_cursor_locked(False)
            self._rmb = False

    @staticmethod
    def _dsf(h, fb):
        try:
            _w, win_h = h.window_size()
            return float(fb[1]) / float(win_h) if win_h > 0 else 1.0
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            return 1.0

    def _attach(self, iid):
        self._attached_iid = iid
        self._info = self._io.model_identity(iid) or {"source": "", "content_hash": "", "meshes": []}
        h = self._info["content_hash"]
        if not h:
            self._status = "This bridge has no content hash (not an interior load); nothing can be saved."
            self._load = ld.LoadResult(ld.empty_doc(self._info["source"]), None, "no content hash")
        else:
            self._load = ld.load(h, self._info["source"])
            self._status = self._load.error or ""
            if not self._load.error:
                _m, warnings = ld.match_shapes(self._load.doc, self._info["meshes"])
                if warnings:
                    self._status = "; ".join(warnings)
        self._doc = self._load.doc
        self._saved_text = lw.dumps(self._doc)
        self._undo = []

    def _click(self, trace, xy, fb, pose):
        if self._press_alt:
            mesh = self._cycle.alt_pick(
                lambda ex: pick_mesh(trace, xy, fb, pose, ex), xy)
        else:
            self._cycle.reset()
            mesh = pick_mesh(trace, xy, fb, pose)
        self._selected = None if mesh is None else identity_for(self._info, mesh)

    def _push_highlight(self, iid):
        sel = self._selected.mesh if self._selected else -1
        state = (iid, sel, self._hover_mesh)
        if state != self._pushed_highlight:
            self._io.set_bridge_highlight(iid, sel, self._hover_mesh)
            self._pushed_highlight = state

    # ── actions ──────────────────────────────────────────────────────────
    def dispatch_event(self, action: str) -> bool:
        if action == "close":
            self.close()
            return True
        if self._doc is None:
            return action in ("save", "revert", "undo") or action.startswith("material")
        if action == "save":
            self._save()
        elif action == "revert":
            self._attach_reload()
        elif action == "undo":
            if self._undo:
                self._doc = self._undo.pop()
        elif action.startswith("material:"):
            self._edit_material(action[len("material:"):])
        elif action.startswith("material-clear:"):
            self._clear_material(action[len("material-clear:"):])
        else:
            return False
        self._last_pushed = None
        return True

    def _snapshot(self):
        self._undo.append(copy.deepcopy(self._doc))
        del self._undo[:-_UNDO_LIMIT]

    def _edit_material(self, arg):
        ch, _, raw = arg.partition(":")
        if ch not in _CHANNELS or self._selected is None:
            return
        try:
            v = float(raw)
        except ValueError:
            return
        v = min(1.0, max(0.0, v))
        current = (self._doc["shapes"].get(self._selected.key, {})
                   .get("material", {}).get(ch))
        if current == v:
            return
        self._snapshot()
        entry = ld.shape_entry(self._doc, self._selected.block, self._selected.name)
        entry.setdefault("material", {})[ch] = v

    def _clear_material(self, ch):
        if ch not in _CHANNELS or self._selected is None:
            return
        entry = self._doc["shapes"].get(self._selected.key)
        if not entry or ch not in entry.get("material", {}):
            return
        self._snapshot()
        entry = self._doc["shapes"][self._selected.key]
        del entry["material"][ch]
        if not entry["material"]:
            del entry["material"]
        if set(entry) == {"block", "name"}:
            del self._doc["shapes"][self._selected.key]

    def _can_save(self):
        return bool(self._info and self._load and self._load.error is None
                    and self._info["content_hash"])

    def _save(self):
        if not self._can_save():
            self._status = "Save refused: " + (self._load.error if self._load else "no document")
            return
        path = lw.target_path(self._load.path, self._info["content_hash"])
        try:
            lw.save(self._doc, path)
        except (OSError, ld.BridgeLightingError) as e:
            self._status = f"Save failed: {e}"
            return
        self._load = ld.LoadResult(self._doc, path, None)
        self._saved_text = lw.dumps(self._doc)
        self._status = f"Saved {path.name}"

    def _attach_reload(self):
        iid = self._iid()
        if iid is None:
            # No instance to re-attach to (e.g. the bridge view/instance has
            # gone away under an open panel) -- leave _info/_doc untouched
            # rather than nulling _info and stranding render_payload's
            # _can_save() indexing into None.
            return
        sel = self._selected
        self._info = None
        self._attach(iid)
        self._selected = sel

    # ── payload ──────────────────────────────────────────────────────────
    def _material_state(self):
        entry = self._doc["shapes"].get(self._selected.key, {}) if self._doc else {}
        mat = entry.get("material", {})
        return {ch: ({"value": mat[ch], "source": "override"} if ch in mat
                     else {"value": default, "source": "default"})
                for ch, default in _CHANNELS.items()}

    def render_payload(self) -> Optional[str]:
        if not self._visible:
            state = {"visible": False}
        else:
            sel = None
            if self._selected is not None and self._doc is not None:
                sel = {"key": self._selected.key, "block": self._selected.block,
                       "name": self._selected.name,
                       "display_name": self._selected.display_name,
                       "node_chain": list(self._selected.node_chain),
                       "textures": list(self._selected.textures),
                       "material": self._material_state()}
            hover = None
            if self._info and self._hover_mesh >= 0:
                ident = identity_for(self._info, self._hover_mesh)
                hover = ident.display_name if ident else None
            state = {
                "visible": True,
                "in_bridge": bool(self._in_bridge()),
                "selected": sel,
                "hover": hover,
                "dirty": (self._doc is not None and lw.dumps(self._doc) != self._saved_text),
                "can_save": self._can_save(),
                "can_undo": bool(self._undo),
                "status": self._status,
            }
        js = "setBridgeEmitters(" + json.dumps(state) + ");"
        if js == self._last_pushed:
            return None
        self._last_pushed = js
        return js
