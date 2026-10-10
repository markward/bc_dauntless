"""Bridge Editor -- developer-only bridge editor panel (spec
docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md §4, §7, §8).

Foundation scope: fly camera (hold RMB to look, WASDQE to move, Shift fast,
Alt slow), click-to-pick a NIF shape (Alt+click = the surface behind), a
selection tint, and the per-shape PBR material override (§9.2 source B) saved
to the per-bridge lighting document. The override is rendered by bridge PBR
(`BridgeRuntime` pushes it to `native/src/renderer/bridge_pass.cc` on every
bridge load and on every edit). The panel also places spot lights (§9.6):
pick a fixture, add a light, aim it, and the same runtime push drives the
live GGX shading and probe recapture.

Driven like every dev modal: a pause-menu row opens it, the host keeps the
pause menu open-but-hidden (sim frozen) while it is open, calls handle_input(h)
each frame, and draws the bridge from camera_pose()."""
import copy
import json
import time
from typing import Optional

from engine import dev_mode, host_io
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer as lw
from engine.bridge_editor import lights as bridge_lights
from engine.bridge_editor import profiles
from engine.bridge_editor.fly_camera import FlyCamera
from engine.bridge_editor.picking import PickCycle, identity_for, pick_hit, pick_mesh
from engine.ui.panel import Panel

DOCK_CSS_PX = 360          # width of the docked panel, CSS px (bridge_emitters.css)
CLICK_SLOP_PX = 4.0
DEFAULT_ROUGHNESS = 1.0    # spec §9.2 source C
DEFAULT_METALNESS = 0.0
_CHANNELS = {"roughness": DEFAULT_ROUGHNESS, "metalness": DEFAULT_METALNESS}
_UNDO_LIMIT = 100

# emitter.light defaults (spec §9.6); angles are HALF-angles 0-90, inner<=outer.
_LIGHT_INNER_DEG = 30.0
_LIGHT_OUTER_DEG = 60.0
_LIGHT_RANGE = 200.0
_LIGHT_INTENSITY = bridge_lights.DEFAULT_INTENSITY
_LIGHT_MIN_RANGE = 0.01
_LIGHT_FIELDS = ("inner_deg", "outer_deg", "range", "intensity")
_WAVE_DEFAULTS = {"sine": {"period_s": 2.0, "min": 0.0},
                  "square": {"period_s": 1.0, "min": 0.0, "duty": 0.5, "soft": 0.0}}
_MIN_PERIOD_S = 0.05
_EMITTER_PREFIXES = ("glow", "profile", "state", "fade:", "phase:", "tab:", "preview-")


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
        self._tab = "green"            # the Profile state tab == the preview alert
        self._preview_playing = True

    # ── Panel ────────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "bridge-emitters"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._reset_session()
        try:
            self._tab = profiles.state_name(self._alert()) if self._alert else "green"
        except Exception as e:  # noqa: BLE001 - a bad provider must not block the editor
            dev_mode.log_swallowed("bridge editor alert provider", e)
            self._tab = "green"
        self._last_pushed = None
        self.visible = True

    def close(self) -> None:
        h = self._h_for_release
        if self._rmb and h is not None:
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
        self._selected = None if mesh is None else identity_for(self._info, mesh)
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
        # Preview actions (spec §12.2) need no document: the tab previews an
        # alert even before anything is picked.
        if action.startswith("tab:") or action == "preview-toggle":
            self._emitter_action(action)
            self._last_pushed = None
            return True
        if self._doc is None:
            return (action in ("save", "revert", "undo")
                    or action.startswith(("material", "light", *_EMITTER_PREFIXES)))
        if action == "save":
            self._save()
        elif action == "revert":
            self._attach_reload()
        elif action == "undo":
            if self._undo:
                self._doc = self._undo.pop()
            self._after_change()
        elif action.startswith("material:"):
            self._edit_material(action[len("material:"):])
            self._after_change()
        elif action.startswith("material-clear:"):
            self._clear_material(action[len("material-clear:"):])
            self._after_change()
        elif action == "light-add":
            self._light_add()
            self._after_change()
        elif action == "light-remove":
            self._light_remove()
            self._after_change()
        elif action == "light-aim":
            self._light_aim()
            self._after_change()
        elif action == "light-place":
            self._light_place()
            self._after_change()
        elif action.startswith("light:"):
            self._light_field(action[len("light:"):])
            self._after_change()
        elif self._emitter_action(action):
            self._after_change()
        else:
            return False
        self._last_pushed = None
        return True

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

    def _snapshot(self):
        self._undo.append(copy.deepcopy(self._doc))
        del self._undo[:-_UNDO_LIMIT]

    # ── light (emitter.light) actions ───────────────────────────────────
    def _light_entry(self):
        if self._selected is None or self._doc is None:
            return None
        return (self._doc["shapes"].get(self._selected.key, {})
                .get("emitter", {}).get("light"))

    def _light_add(self):
        if self._selected is None or self._last_hit is None:
            return
        self._snapshot()
        point, normal = self._last_hit
        entry = ld.shape_entry(self._doc, self._selected.block, self._selected.name)
        entry.setdefault("emitter", {})["light"] = {
            "position": list(point), "direction": list(normal),
            "inner_deg": _LIGHT_INNER_DEG, "outer_deg": _LIGHT_OUTER_DEG,
            "range": _LIGHT_RANGE, "intensity": _LIGHT_INTENSITY,
        }

    def _light_remove(self):
        if self._selected is None or self._doc is None:
            return
        entry = self._doc["shapes"].get(self._selected.key)
        if not entry or "light" not in entry.get("emitter", {}):
            return
        self._snapshot()
        entry = self._doc["shapes"][self._selected.key]
        del entry["emitter"]["light"]
        if not entry["emitter"]:
            del entry["emitter"]
        if set(entry) == {"block", "name"}:
            del self._doc["shapes"][self._selected.key]

    def _light_aim(self):
        light = self._light_entry()
        if light is None or self._camera is None:
            return
        self._snapshot()
        light["direction"] = list(self._camera.forward())

    def _light_place(self):
        light = self._light_entry()
        if light is None or self._last_hit is None:
            return
        self._snapshot()
        light["position"] = list(self._last_hit[0])

    def _light_field(self, arg):
        field, _, raw = arg.partition(":")
        light = self._light_entry()
        if field not in _LIGHT_FIELDS or light is None:
            return
        try:
            v = float(raw)
        except ValueError:
            return
        if field in ("inner_deg", "outer_deg"):
            v = min(90.0, max(0.0, v))
        elif field == "range":
            v = max(_LIGHT_MIN_RANGE, v)
        elif field == "intensity":
            v = max(0.0, v)
        if light.get(field) == v:
            return
        self._snapshot()
        light[field] = v
        if field == "inner_deg" and light.get("outer_deg", 90.0) < v:
            light["outer_deg"] = v
        elif field == "outer_deg" and v < light.get("inner_deg", 0.0):
            light["inner_deg"] = v

    # ── preview (spec 2026-10-08-bridge-emitters §12.2) ───────────────────
    def preview_alert(self):
        """The alert level the bridge shows while the editor is open -- the
        state tab; None when closed (the player's alert then)."""
        return profiles.STATES.index(self._tab) if self._visible else None

    def preview_dt(self, player_dt, frame_dt):
        """The bridge clock's dt: the player's (paused-aware) when closed;
        while open the real frame time, or 0 when the preview is paused."""
        if not self._visible:
            return player_dt
        return frame_dt if self._preview_playing else 0.0

    # ── glow + profile (spec 2026-10-08-bridge-emitters §12) ──────────────
    def _edit(self, fn):
        """Run one document edit as one undo step: snapshot, mutate, and keep
        the snapshot only if the document changed (a no-op adds none)."""
        before = copy.deepcopy(self._doc)
        fn()
        if self._doc != before:
            self._undo.append(before)
            del self._undo[:-_UNDO_LIMIT]

    def _emitter(self, create=False):
        if self._selected is None or self._doc is None:
            return None
        if create:
            entry = ld.shape_entry(self._doc, self._selected.block, self._selected.name)
            return entry.setdefault("emitter", {})
        return self._doc["shapes"].get(self._selected.key, {}).get("emitter")

    def _drop_empty(self):
        entry = self._doc["shapes"].get(self._selected.key) if self._selected else None
        if entry is None:
            return
        if entry.get("emitter") == {}:
            del entry["emitter"]
        if set(entry) == {"block", "name"}:
            del self._doc["shapes"][self._selected.key]

    def _profile_name(self):
        return (self._emitter() or {}).get("profile")

    def _has_emissive_map(self):
        return bool(((self._selected_mesh_info() or {}).get("maps") or {}).get("emissive"))

    @staticmethod
    def _num(raw, lo=None, hi=None):
        try:
            v = float(raw)
        except ValueError:
            return None
        if v != v or v in (float("inf"), float("-inf")):
            return None
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def _emitter_action(self, action) -> bool:
        """Glow / profile / state / preview actions; False for anything else."""
        if action == "preview-toggle":
            self._preview_playing = not self._preview_playing
            return True
        if action.startswith("tab:"):
            if action[4:] in profiles.STATES:
                self._tab = action[4:]
            return True
        if self._selected is None:
            return action.startswith(_EMITTER_PREFIXES)
        if action == "glow-on":
            def on():
                em = self._emitter(create=True)
                em.setdefault("glow", {"src": "emissive" if self._has_emissive_map()
                                       else "texture"})
            self._edit(on)
        elif action == "glow-off":
            def off():
                em = self._emitter()
                if em is not None:
                    em.pop("glow", None)
                    self._drop_empty()
            self._edit(off)
        elif action.startswith("glow:"):
            field, _, raw = action[5:].partition(":")
            g = (self._emitter() or {}).get("glow")
            if g is None:
                return True
            if field == "src" and raw in ld.GLOW_SRCS and (
                    raw != "emissive" or self._has_emissive_map()):
                self._edit(lambda: g.__setitem__("src", raw))
            elif field == "scale":
                v = self._num(raw, lo=0.0)
                if v is not None:
                    self._edit(lambda: g.__setitem__("scale", v))
        elif action.startswith("profile-select:"):
            name = action[len("profile-select:"):]
            if name and name not in self._doc["profiles"]:
                return True
            def select():
                if name:
                    self._emitter(create=True)["profile"] = name
                else:
                    em = self._emitter()
                    if em is not None:
                        em.pop("profile", None)
                        self._drop_empty()
            self._edit(select)
        elif action == "profile-new":
            def new():
                n = 1
                while f"profile {n}" in self._doc["profiles"]:
                    n += 1
                cur = self._profile_name()
                src = self._doc["profiles"].get(cur) if cur else None
                data = copy.deepcopy(src) if src is not None else {
                    "fade_s": profiles.DEFAULT_FADE_S,
                    **copy.deepcopy(profiles.STEADY_WHITE)}
                self._doc["profiles"][f"profile {n}"] = data
                self._emitter(create=True)["profile"] = f"profile {n}"
            self._edit(new)
        elif action.startswith("profile-rename:"):
            self._rename(action[len("profile-rename:"):].strip())
        elif action.startswith(("state-on:", "state-off:", "state:", "fade:", "phase:")):
            self._state_action(action)
        else:
            return False
        return True

    def _rename(self, new):
        old = self._profile_name()
        if old is None:
            return
        if not new:
            self._status = "Rename refused: empty name"
            return
        if new in self._doc["profiles"]:
            if new != old:
                self._status = f"Rename refused: a profile named {new!r} exists"
            return
        def rename():
            self._doc["profiles"][new] = self._doc["profiles"].pop(old)
            for entry in self._doc["shapes"].values():
                em = entry.get("emitter")
                if em is not None and em.get("profile") == old:
                    em["profile"] = new
        self._edit(rename)
        self._status = f"Renamed {old!r} to {new!r}"

    def _state_action(self, action):
        name = self._profile_name()
        prof = self._doc["profiles"].get(name) if name else None
        if action.startswith("phase:"):
            v = self._num(action[6:], 0.0, 1.0)
            if v is not None and self._emitter() is not None:
                self._edit(lambda: self._emitter().__setitem__("phase", v))
            return
        if prof is None:
            return
        if action.startswith("fade:"):
            v = self._num(action[5:], lo=0.0)
            if v is not None:
                self._edit(lambda: prof.__setitem__("fade_s", v))
            return
        if action.startswith(("state-on:", "state-off:")):
            on, _, s = action.partition(":")
            if s not in profiles.STATES:
                return
            if on == "state-on":
                self._edit(lambda: prof.setdefault(s, {"tint": [1, 1, 1], "level": 1.0}))
            else:
                self._edit(lambda: prof.pop(s, None))
            return
        _, s, rest = action.split(":", 2) if action.count(":") >= 2 else ("", "", "")
        st = prof.get(s)
        if s not in profiles.STATES or st is None:
            return
        field, _, raw = rest.partition(":")
        if field == "tint":
            try:
                rgb = [max(0.0, float(c)) for c in raw.split(",")]
            except ValueError:
                return
            if len(rgb) != 3 or any(c != c or c == float("inf") for c in rgb):
                return
            m = max(rgb)
            rgb = [round(c / m, 4) for c in rgb] if m > 0 else [0.0, 0.0, 0.0]
            self._edit(lambda: st.__setitem__("tint", rgb))
        elif field == "level":
            v = self._num(raw, lo=0.0)
            if v is not None:
                self._edit(lambda: st.__setitem__("level", v))
        elif field == "wave":
            self._wave_field(st, raw)

    def _wave_field(self, st, arg):
        field, _, raw = arg.partition(":")
        wave = st.get("wave")
        if field == "shape":
            if raw == "steady":
                self._edit(lambda: st.pop("wave", None))
            elif raw in _WAVE_DEFAULTS:
                new = dict(_WAVE_DEFAULTS[raw], shape=raw)
                for k in ("period_s", "min", "duty", "soft"):
                    if wave and k in wave and k in new:
                        new[k] = wave[k]
                self._edit(lambda: st.__setitem__("wave", new))
            return
        if wave is None:
            return
        if field == "period_s":
            v = self._num(raw, lo=_MIN_PERIOD_S)
        elif field == "min" or (field in ("duty", "soft") and wave["shape"] == "square"):
            v = self._num(raw, 0.0, 1.0)
        else:
            return
        if v is not None:
            self._edit(lambda: wave.__setitem__(field, v))

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

    def _material_state(self):
        entry = self._doc["shapes"].get(self._selected.key, {}) if self._doc else {}
        mat = entry.get("material", {})
        mesh_info = self._selected_mesh_info()
        maps = (mesh_info or {}).get("maps", {})
        out = {}
        for ch, default in _CHANNELS.items():
            if maps.get(ch):
                out[ch] = {"value": default, "source": "map"}
            elif ch in mat:
                out[ch] = {"value": mat[ch], "source": "override"}
            else:
                out[ch] = {"value": default, "source": "default"}
        return out

    def _light_payload(self):
        light = self._light_entry()
        return None if light is None else dict(light)

    def _glow_payload(self):
        g = (self._emitter() or {}).get("glow")
        return None if g is None else dict(g)

    def _profile_payload(self):
        name = self._profile_name()
        prof = self._doc["profiles"].get(name) if name else None
        return None if prof is None else copy.deepcopy(prof)

    def _profiles_payload(self):
        if self._doc is None:
            return []
        used = {}
        for entry in self._doc["shapes"].values():
            n = (entry.get("emitter") or {}).get("profile")
            if n is not None:
                used[n] = used.get(n, 0) + 1
        return [{"name": n, "used_by": used.get(n, 0)} for n in sorted(self._doc["profiles"])]

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
                       "material": self._material_state(),
                       "light": self._light_payload(),
                       "glow": self._glow_payload(),
                       "has_emissive_map": self._has_emissive_map(),
                       "profile": self._profile_name(),
                       "profile_data": self._profile_payload(),
                       "phase": float((self._emitter() or {}).get("phase", 0.0))}
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
                "status": self._status_text(),
                "profiles": self._profiles_payload(),
                "tab": self._tab,
                "preview_playing": self._preview_playing,
            }
        js = "setBridgeEmitters(" + json.dumps(state) + ");"
        if js == self._last_pushed:
            return None
        self._last_pushed = js
        return js
