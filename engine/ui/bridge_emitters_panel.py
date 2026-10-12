"""Bridge Editor -- developer-only bridge editor panel (spec
docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md §4, §13).

A top-left bar is the editor's chrome -- its presence IS bridge editing mode:
the five bridge-state squares (the preview state; the game is never changed),
the preview clock, Undo / Revert / Save and ✕. The side panel appears only
while an object (one NIF shape) is selected, with two tabs:

- **Object**: the material it links to from the bridge's library (used-by
  count, New, Duplicate, unlink) and its Lights;
- **Material**: the linked material's finish, emission, fade and its stack of
  scoped Emitter / Animation modifiers -- shared by every object that links it.

Hold Shift to fly (mouse-look + WASDQE, scroll sets the speed); click picks an
object (Alt+click = the surface behind), clicking empty space deselects. Every
edit is one undo step through `engine.bridge_editor.editing` and is pushed
live through the production `BridgeRuntime`.

Driven like every dev modal: a pause-menu row opens it, the host keeps the
pause menu open-but-hidden (sim frozen) while it is open, calls handle_input(h)
each frame, and draws the bridge from camera_pose()."""
import copy
import json
import time
from typing import Optional

from engine import dev_mode, host_io
from engine.bridge_editor import behaviour
from engine.bridge_editor import editing
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer as lw
from engine.bridge_editor.fly_camera import FlyCamera
from engine.bridge_editor.picking import PickCycle, identity_for, pick_hit, pick_mesh
from engine.ui.panel import Panel

DOCK_CSS_PX = 360          # width of the docked panel, CSS px (bridge_emitters.css)
BAR_CSS_W = 560            # the top-left .be-top block, CSS px (bridge_emitters.css)
BAR_CSS_H = 120            # bar + hint + hover/status; .be-top's max-height
CLICK_SLOP_PX = 4.0
DEFAULT_ROUGHNESS = 1.0    # spec §9.2 source C
DEFAULT_METALNESS = 0.0
_CHANNELS = {"roughness": DEFAULT_ROUGHNESS, "metalness": DEFAULT_METALNESS}
_UNDO_LIMIT = 100
HINT = ("Hold Shift: fly · WASD · Q/E · scroll: speed · click: select · "
        "Alt+click: surface behind · materials layer over the object's texture")
# Actions that are not document edits and need no loaded document.
_VIEW_ACTIONS = ("state:", "preview-toggle", "tab:", "expand:", "deselect")
_EDIT_PREFIXES = ("material", "light", "finish", "emission-source:", "mod")


class BridgeEmittersPanel(Panel):
    def __init__(self, pose_provider, instance_provider, in_bridge_provider,
                 clock=time.monotonic, io=host_io, runtime=None, alert_provider=None):
        super().__init__()
        self._pose = pose_provider
        self._iid = instance_provider
        self._in_bridge = in_bridge_provider
        self._clock = clock
        self._io = io
        self._runtime = runtime
        self._alert = alert_provider
        self._visible = False
        self._last_pushed = None
        self._reset_session()

    def _reset_session(self):
        self._camera = None
        self._last_t = None
        self._shift = False
        self._left = False
        self._press_xy = None
        self._press_alt = False
        self._drag = 0.0
        self._info = None
        self._attached_iid = None
        self._load = None
        self._doc = None
        self._saved_text = None
        self._saved_doc = None         # deep copy of the last saved/loaded doc
        self._undo = []
        self._selected = None          # ShapeIdentity
        self._last_hit = None          # (point, normal) from the last CLICK trace
        self._hover_mesh = -1
        self._cycle = PickCycle()
        self._status = ""
        self._push_warnings = []       # REPLACED by each push, never accumulated
        self._pushed_highlight = None
        self._h_for_release = None
        self._state = "green"          # the previewed bridge state (§13.1)
        self._preview_playing = True
        self._tab = "object"
        self._expanded = set()

    # ── Panel ────────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "bridge-emitters"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._reset_session()
        try:
            self._state = behaviour.state_name(self._alert()) if self._alert else "green"
        except Exception as e:  # noqa: BLE001 - a bad provider must not block the editor
            dev_mode.log_swallowed("bridge editor alert provider", e)
            self._state = "green"
        self._last_pushed = None
        self.visible = True

    def close(self) -> None:
        h = self._h_for_release
        if self._shift and h is not None:
            h.set_cursor_locked(False)
        self._io.set_bridge_highlight(None, -1, -1)
        self._revert_unsaved_render()
        self._reset_session()
        self.visible = False

    def _revert_unsaved_render(self):
        """Unsaved edits are pushed live (_after_change); closing without
        saving must not leave them rendered until the editor reopens or the
        bridge reloads. Re-push the last SAVED/loaded document instead. The
        live doc is mutated in place, so the snapshot is a deep copy."""
        if (self._runtime is None or not self._info or self._doc is None
                or self._saved_doc is None
                or lw.dumps(self._doc) == self._saved_text):
            return
        matched = ld.match_shapes(self._saved_doc, self._info["meshes"])[0]
        self._runtime.push(copy.deepcopy(self._saved_doc), matched)

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def invalidate(self) -> None:
        self._last_pushed = None

    def camera_pose(self):
        return self._camera.pose() if (self._visible and self._camera) else None

    # ── preview (spec 2026-10-08-bridge-emitters §12.2, §13.3) ────────────
    def preview_alert(self):
        """The bridge state (0-4) the bridge shows while the editor is open --
        the bar's selected square; None when closed (the game's state then)."""
        return behaviour.state_index(self._state) if self._visible else None

    def preview_dt(self, player_dt, frame_dt):
        """The bridge clock's dt: the player's (paused-aware) when closed;
        while open the real frame time, or 0 when the preview is paused."""
        if not self._visible:
            return player_dt
        return frame_dt if self._preview_playing else 0.0

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
        ks = h.key_state

        # Hold Shift to fly (spec §13.3): mouse-look + WASDQE; scroll sets
        # the speed. Never while a text field has focus -- the KeyGate masks
        # every key then, Shift included.
        shift = bool(ks(keys.KEY_LEFT_SHIFT) or ks(keys.KEY_RIGHT_SHIFT))
        if shift and not self._shift:
            h.set_cursor_locked(True)
            h.consume_mouse_delta()
        elif not shift and self._shift:
            h.set_cursor_locked(False)
        self._shift = shift
        if shift:
            dx, dy = h.consume_mouse_delta()
            self._camera.look(dx, dy)
            scroll = getattr(h, "consume_scroll_y", None)
            if scroll is not None:
                notches = scroll()
                if notches:
                    self._camera.adjust_speed(notches)
            self._camera.move(
                dt,
                forward=int(ks(keys.KEY_W)) - int(ks(keys.KEY_S)),
                strafe=int(ks(keys.KEY_D)) - int(ks(keys.KEY_A)),
                lift=int(ks(keys.KEY_E)) - int(ks(keys.KEY_Q)))
            self._push_highlight(iid)
            return

        x, y = h.cursor_pos()
        fb = h.framebuffer_size()
        dsf = self._dsf(h, fb)
        over_ui = ((self._selected is not None and x >= fb[0] - DOCK_CSS_PX * dsf)
                   or (x < BAR_CSS_W * dsf and y < BAR_CSS_H * dsf))
        trace = lambda o, d, m, ex: self._io.ray_trace_mesh_pick(iid, o, d, m, ex)
        pose = self._camera.pose()
        hover = None if over_ui else pick_mesh(trace, (x, y), fb, pose)
        self._hover_mesh = -1 if hover is None else hover

        left = bool(h.mouse_button_state(keys.MOUSE_BUTTON_LEFT))
        if left and not self._left:                      # press edge
            # A press that starts over the bar or the dock is the page's.
            self._press_xy = None if over_ui else (x, y)
            self._press_alt = bool(ks(keys.KEY_LEFT_ALT) or ks(keys.KEY_RIGHT_ALT))
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
        """Release the fly cursor lock when the view/instance disappears out
        from under it. Without this, leaving the bridge (or the instance
        vanishing) while Shift is held strands the cursor locked forever --
        handle_input returns before the normal release code runs again."""
        if self._shift:
            h.set_cursor_locked(False)
            self._shift = False

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
        self._saved_doc = copy.deepcopy(self._doc)
        self._undo = []
        self._after_change()

    def _click(self, trace, xy, fb, pose):
        # Capture the full hit (point, normal) of whichever trace call ends
        # up producing the final accepted mesh -- the last call a PickCycle
        # makes always corresponds to its returned mesh, in both the plain
        # and Alt+click (step-deeper) cases, so overwriting on every call
        # leaves the right one behind.
        captured = {}

        def _pick(exclude):
            hit = pick_hit(trace, xy, fb, pose, exclude)
            if hit is not None:
                captured["hit"] = hit
            return None if hit is None else int(hit[3])

        if self._press_alt:
            mesh = self._cycle.alt_pick(_pick, xy)
        else:
            self._cycle.reset()
            mesh = _pick(())
        # A miss deselects (spec §13.3: the dock shows only with a selection).
        self._selected = None if mesh is None else identity_for(self._info, mesh)
        self._last_hit = None
        if mesh is not None and "hit" in captured:
            point, normal = captured["hit"][0], captured["hit"][1]
            self._last_hit = (tuple(point), tuple(normal))

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
        if action.startswith(_VIEW_ACTIONS):
            self._view_action(action)
            self._last_pushed = None
            return True
        if self._doc is None:
            return action in ("save", "revert", "undo") or action.startswith(_EDIT_PREFIXES)
        if action == "save":
            self._save()
        elif action == "revert":
            self._attach_reload()
        elif action == "undo":
            if self._undo:
                self._doc = self._undo.pop()
            self._after_change()
        elif action.startswith(_EDIT_PREFIXES):
            if self._selected is not None:
                self._edit_action(action)
                self._after_change()
        else:
            return False
        self._last_pushed = None
        return True

    def _view_action(self, action):
        """Bar / panel state that is not a document edit (no undo step)."""
        if action.startswith("state:"):
            if action[6:] in ld.STATES:
                self._state = action[6:]
        elif action == "preview-toggle":
            self._preview_playing = not self._preview_playing
        elif action.startswith("tab:"):
            if action[4:] in ("object", "material"):
                self._tab = action[4:]
        elif action.startswith("expand:"):
            self._expanded ^= {action[7:]}
        elif action == "deselect":
            self._selected = None
            self._last_hit = None

    def _edit(self, fn):
        """Run one document edit as one undo step: snapshot, mutate, and keep
        the snapshot only if the document changed (a no-op adds none)."""
        before = copy.deepcopy(self._doc)
        fn()
        if self._doc != before:
            self._undo.append(before)
            del self._undo[:-_UNDO_LIMIT]

    def _object(self):
        return self._doc["objects"].get(self._selected.key)

    def _linked(self):
        return (self._object() or {}).get("material")

    def _texture(self):
        return ld.mesh_texture(self._selected_mesh_info() or {})

    def _material_name(self):
        """The selected object's material as it renders: its link, else its
        texture's material (Mark 2026-10-11: each TGA is a material); None
        when neither exists yet."""
        tex = self._texture()
        return self._linked() or (self._doc.get("textures", {}).get(ld.texture_key(tex))
                                  if tex else None)

    def _ensure_material(self):
        """The material to edit, made if need be -- the texture's (never a
        link), or a new linked one for an object with no texture. Call only
        inside an _edit, so the creation is part of that undo step."""
        name = self._material_name()
        if name is not None:
            return name
        tex = self._texture()
        if tex:
            return editing.texture_material(self._doc, tex)
        return editing.new_material(self._doc, self._selected.block, self._selected.name)

    def _edit_action(self, action):
        b, n = self._selected.block, self._selected.name
        head, _, rest = action.partition(":")
        if action == "material-new":
            self._edit(lambda: editing.new_material(self._doc, b, n, texture=self._texture()))
        elif action == "material-duplicate":
            self._edit(lambda: editing.duplicate(self._doc, b, n,
                                                 current=self._ensure_material()))
        elif head == "material-link":
            if rest and not ld.fits(self._doc, rest, self._selected_mesh_info() or {}):
                self._status = (f"{rest!r} is a material for another texture; "
                                "a material belongs to one TGA")
                return
            self._edit(lambda: editing.link(self._doc, b, n, rest))
        elif head == "material-rename":
            result = {}

            def rename():
                result["old"] = old = self._ensure_material()
                result["err"] = editing.rename(self._doc, old, rest)
            self._edit(rename)
            if result.get("err"):
                self._status = result["err"]
            elif rest.strip() != result.get("old"):   # the button after Enter re-commits: no-op
                self._status = f"Renamed {result.get('old')!r} to {rest.strip()!r}"
        elif action == "light-add":
            if self._last_hit is not None:
                pos, normal = self._last_hit
                self._edit(lambda: editing.add_light(self._doc, b, n, pos, normal))
        elif head in ("light-remove", "light-place", "light-aim", "light"):
            self._light_action(head, rest)
        elif head == "mod-add":
            def add():
                editing.add_modifier(self._doc["materials"][self._ensure_material()],
                                     rest, self._state)
            self._edit(add)
        else:
            self._material_action(head, rest)

    def _light_action(self, head, rest):
        idx, _, tail = rest.partition(":")
        try:
            i = int(idx)
        except ValueError:
            return
        lights = (self._object() or {}).get("lights", [])
        if not 0 <= i < len(lights):
            return
        light = lights[i]
        if head == "light-remove":
            b, n = self._selected.block, self._selected.name
            self._edit(lambda: editing.remove_light(self._doc, b, n, i))
        elif head == "light-place":
            if self._last_hit is not None:
                pos = list(self._last_hit[0])
                self._edit(lambda: light.__setitem__("position", pos))
        elif head == "light-aim":
            if self._camera is not None:
                fwd = list(self._camera.forward())
                self._edit(lambda: light.__setitem__("direction", fwd))
        else:
            field, _, raw = tail.partition(":")
            self._edit(lambda: editing.set_light(light, field, raw))

    def _material_action(self, head, rest):
        # Setting a value may make the texture's material; clearing or
        # editing a modifier needs one that exists.
        if self._material_name() is None and head not in ("finish", "emission-source"):
            return

        def mat():
            return self._doc["materials"][self._ensure_material()]
        if head == "finish":
            ch, _, raw = rest.partition(":")
            self._edit(lambda: editing.set_finish(mat(), ch, raw))
        elif head == "finish-clear":
            self._edit(lambda: editing.clear_finish(mat(), rest))
        elif head == "emission-source":
            self._edit(lambda: editing.set_emission_source(mat(), rest))
        elif head == "mod-remove":
            try:
                i = int(rest)
            except ValueError:
                return
            self._edit(lambda: editing.remove_modifier(mat(), i))
        elif head == "mod":
            idx, _, tail = rest.partition(":")
            field, _, raw = tail.partition(":")
            try:
                i = int(idx)
            except ValueError:
                return
            if field == "scope":
                self._edit(lambda: editing.toggle_scope(mat(), i, raw))
            else:
                self._edit(lambda: editing.set_modifier(mat(), i, field, raw))

    def _after_change(self):
        """Re-push the live doc through the production BridgeRuntime after
        every edit, so the editor's result is visible the same frame (the
        bridge still draws while the editor is paused). Never raises --
        BridgeRuntime.push() already guards itself; this only has to guard
        the lack of a runtime/attached model.

        `_push_warnings` is REPLACED by this call's result, never appended:
        a persistent condition (too many spot lights, a non-finite value)
        would otherwise re-announce itself on every subsequent edit and grow
        the status line without bound. The current push's warnings, not a
        history of every past one, is what `_status_text()` shows."""
        self._push_warnings = []
        if self._runtime and self._info:
            matched = ld.match_shapes(self._doc, self._info["meshes"])[0]
            self._push_warnings = self._runtime.push(self._doc, matched)

    def _status_text(self):
        extra = "; ".join(self._push_warnings)
        if self._status and extra:
            return f"{self._status}; {extra}"
        return self._status or extra

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
        self._saved_doc = copy.deepcopy(self._doc)
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
    def _selected_mesh_info(self):
        if self._selected is None or not self._info:
            return None
        for m in self._info.get("meshes", ()):
            if m["mesh"] == self._selected.mesh:
                return m
        return None

    def _maps(self):
        return (self._selected_mesh_info() or {}).get("maps") or {}

    def _usage(self):
        """{material: meshes rendering with it} over the whole bridge, and
        the meshes with no link (which follow their texture's material)."""
        meshes = (self._info or {}).get("meshes", [])
        matched = ld.match_shapes(self._doc, meshes)[0]
        resolved = ld.resolve(self._doc, meshes, matched)
        counts = {}
        for name in resolved.values():
            counts[name] = counts.get(name, 0) + 1
        linked = {matched[k] for k in matched if self._doc["objects"][k].get("material")}
        return counts, [m for m in meshes if m["mesh"] not in linked]

    def _texture_material(self):
        """The selected object's texture's material name -- or the name it
        will get when first edited; None for an object with no texture."""
        tex = self._texture()
        if not tex:
            return None
        return (self._doc.get("textures", {}).get(ld.texture_key(tex))
                or ld.free_name(self._doc, ld.texture_stem(tex)))

    def _material_payload(self, counts, unlinked):
        name = self._material_name()
        tex = self._texture()
        if name is None and not tex:
            return None
        kind = "linked" if self._linked() else "texture"
        if name is None:               # the texture's material, not made yet
            key = ld.texture_key(tex)
            name, mat = self._texture_material(), {}
            used = sum(1 for m in unlinked
                       if ld.mesh_texture(m) and ld.texture_key(ld.mesh_texture(m)) == key)
        else:
            mat, used = self._doc["materials"][name], counts.get(name, 0)
        maps = self._maps()
        finish = {}
        for ch, default in _CHANNELS.items():
            if maps.get(ch):
                finish[ch] = {"value": default, "source": "map"}
            elif ch in mat:
                finish[ch] = {"value": mat[ch], "source": "material"}
            else:
                finish[ch] = {"value": default, "source": "default"}
        # Emission (spec §14): unlike roughness/metalness the material's level
        # still applies over a map -- the map says what glows, the level how
        # much; unset, a map glows as painted (1) and no map glows nothing.
        if "emission" in mat:
            finish["emission"] = {"value": mat["emission"], "source": "material"}
        elif maps.get("emissive"):
            finish["emission"] = {"value": 1.0, "source": "map"}
        else:
            finish["emission"] = {"value": 0.0, "source": "default"}
        return {"name": name, "kind": kind, "used_by": used, "finish": finish,
                "emission_source": mat.get("emission_source", "texture"),
                "modifiers": copy.deepcopy(mat.get("modifiers", []))}

    def _selected_payload(self):
        if self._selected is None or self._doc is None:
            return None
        counts, unlinked = self._usage()
        textured = set(self._doc.get("textures", {}).values())
        obj = self._object() or {}
        return {"key": self._selected.key, "block": self._selected.block,
                "name": self._selected.name,
                "display_name": self._selected.display_name,
                "node_chain": list(self._selected.node_chain),
                "textures": list(self._selected.textures),
                "tab": self._tab, "expanded": sorted(self._expanded),
                "has_emission_map": bool(self._maps().get("emissive")),
                "material": self._material_name(),
                "linked": bool(obj.get("material")),
                "texture_material": self._texture_material(),
                # A material belongs to one texture: only this one's are offered.
                "library": [{"name": m, "used_by": counts.get(m, 0), "texture": m in textured}
                            for m in sorted(self._doc["materials"])
                            if ld.fits(self._doc, m, self._selected_mesh_info() or {})],
                "lights": copy.deepcopy(obj.get("lights", [])),
                "material_data": self._material_payload(counts, unlinked)}

    def render_payload(self) -> Optional[str]:
        if not self._visible:
            state = {"visible": False}
        else:
            hover = None
            if self._info and self._hover_mesh >= 0:
                ident = identity_for(self._info, self._hover_mesh)
                hover = ident.display_name if ident else None
            state = {
                "visible": True,
                "in_bridge": bool(self._in_bridge()),
                "state": self._state,
                "playing": self._preview_playing,
                "selected": self._selected_payload(),
                "hover": hover,
                "hint": HINT,
                "dirty": (self._doc is not None and lw.dumps(self._doc) != self._saved_text),
                "can_save": self._can_save(),
                "can_undo": bool(self._undo),
                "status": self._status_text(),
            }
        js = "setBridgeEmitters(" + json.dumps(state) + ");"
        if js == self._last_pushed:
            return None
        self._last_pushed = js
        return js
