"""Applies a bridge's per-bridge lighting document to the renderer — the
PRODUCTION path (spec 2026-10-08-bridge-emitters §7, §9): at bridge load, on
editor edits, and on alert changes. Never raises into the host loop."""
from typing import Optional

from engine import bridge_lighting, dev_mode, host_io
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import behaviour, glow, lights, materials


class BridgeRuntime:
    def __init__(self, io=host_io, eye=None, alert=None):
        self._io = io
        self._eye = eye
        self._alert = alert
        self._iid = None
        self._doc = None
        self._matched = {}
        self._meshes = []
        self._glow_shapes = []
        self._fade = behaviour.StateFade()
        self._t = 0.0          # the bridge clock (spec §11.3): paused-aware dt
        # The probe scales last pushed; the default until a bridge says otherwise.
        self._probe_scales = bridge_lighting.probe_scales()

    def attach(self, iid):
        """Neither overrides nor spots are cleared by C++ on a mission swap,
        and probe state persists too — so every bridge load pushes fresh
        state for THIS bridge, an empty push when it has no file or no
        matched emitters, never leaving the previous bridge's state live.

        The probe origin/scales (and a capture request) are pushed BEFORE
        the content-hash check and unconditionally: a bridge with no hash
        (not an interior load) still has an eye and must get a fresh
        capture from it, never keep reflecting from whatever bridge was
        attached last.

        The previous bridge's overrides and spots are cleared FIRST, in their
        own guard: if anything after it raises (model_identity, the doc
        load), the old bridge's lights must not stay live on the new one."""
        self._iid, self._doc, self._matched = iid, None, {}
        self._meshes, self._glow_shapes, self._resolved, self._mapped = [], [], {}, frozenset()
        try:
            self._io.set_bridge_material_overrides(None, [])
            self._io.set_bridge_spots([])
            self._io.set_bridge_glow(None, [])
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime attach clear", e)
        try:
            info = self._io.model_identity(iid) or {}
            self._meshes = info.get("meshes", [])
            self._io.set_bridge_probe_origin(tuple(self._eye()))
            self._probe_scales = bridge_lighting.probe_scales()
            self._io.set_bridge_probe_scales(*self._probe_scales)
            h = info.get("content_hash", "")
            if not h:
                self.detach()
                self._io.request_bridge_probe_capture()
                return
            loaded = ld.load(h, info.get("source", ""))
            if loaded.error:
                dev_mode.log_swallowed(
                    "bridge lighting doc load", ld.BridgeLightingError(loaded.error))
            doc = loaded.doc
            matched, warnings = ld.match_shapes(doc, info.get("meshes", []))
            for w in warnings:
                dev_mode.log_swallowed(
                    "bridge lighting doc match_shapes", ld.BridgeLightingError(w))
            # A bridge load shows its alert state settled -- no fade.
            self._fade = behaviour.StateFade(behaviour.state_name(self._alert()))
            self.push(doc, matched)
            # A bridge load always captures (a new room, a new eye), even
            # when the pushed overrides/spots equal the previous bridge's.
            self._io.request_bridge_probe_capture()
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime attach", e)

    def push(self, doc, matched=None):
        """Re-push overrides, the static spot list (geometry + probe-capture
        colours) and the glow table from an edited doc (the live editor, or
        attach()), then this frame's live values; tick() re-pushes the live
        values every frame. Returns warnings: emitter warnings (cap drops by
        name and glows skipped for a missing _emissive map, from
        lights.spots, BEFORE the list ever reaches native), plus a separate
        warning if the renderer itself reports spots dropped as invalid.
        These are two unrelated populations -- lights.spots already caps the
        list at MAX_SPOTS, so whatever set_bridge_spots reports dropped can
        only be non-finite values among the <=32 actually sent, never a
        restatement of the cap count. Builds tuples from a doc that is
        already schema-validated, but the push to the native side still goes
        through a guard -- a value that slips past validation (or a
        stale/garbage instance id) must not raise into the host loop.

        Requests no probe capture itself: BridgePass marks the probes dirty
        when the overrides or spots it is handed DIFFER from what it holds,
        so an editor action that changed nothing (an empty undo, a value set
        to itself) costs no recapture. attach() requests one explicitly."""
        if self._iid is None:
            return []
        self._doc = doc
        if matched is not None:
            self._matched = matched
        warnings = []
        try:
            self._push_probe_scales(doc)
            # Each mesh's material: its object's link, else its texture's.
            self._resolved = ld.resolve(doc, self._meshes, self._matched)
            # Meshes whose texture has an `_emissive` map: an unset emission
            # defaults to the map as painted there (behaviour.output).
            self._mapped = frozenset(m["mesh"] for m in self._meshes
                                     if (m.get("maps") or {}).get("emissive"))
            self._io.set_bridge_material_overrides(
                self._iid, materials.overrides(doc, self._resolved))
            spot_list, warnings = lights.spots(doc, self._matched, self._resolved, self._mapped)
            self._glow_shapes, glow_warnings = glow.glow_objects(
                doc, self._resolved, self._meshes)
            warnings = (ld.link_mismatches(doc, self._meshes, self._matched)
                        + warnings + glow_warnings)
            for w in warnings:
                dev_mode.log_swallowed(
                    "bridge lighting emitters", ld.BridgeLightingError(w))
            dropped = self._io.set_bridge_spots(spot_list)
            if dropped:
                msg = f"{dropped} bridge light(s) dropped as invalid (non-finite values)"
                warnings.append(msg)
                dev_mode.log_swallowed(
                    "bridge lighting spots dropped", ld.BridgeLightingError(msg))
            self._push_live()
        except Exception as e:  # noqa: BLE001 - see docstring
            dev_mode.log_swallowed("bridge runtime push", e)
        return warnings

    def ambient_scale(self, level) -> Optional[float]:
        """The room light for bridge state `level` (0-4): this bridge's own
        (lighting_doc.room_light -- 0 when it defines lights and sets no
        level), or None for the engine default (bridge_lighting)."""
        if self._doc is None:
            return None
        return ld.room_light(self._doc, behaviour.state_name(level))

    def _push_probe_scales(self, doc):
        """The reflection probes are captured under the room light they
        reflect (green probe: green; yellow/red probe: yellow -- as the spot
        capture colours are); recaptured only when that changes."""
        default = bridge_lighting.probe_scales()
        scales = tuple(d if v is None else v for v, d in
                       zip((ld.room_light(doc, "green"), ld.room_light(doc, "yellow")), default))
        if scales != self._probe_scales:
            self._probe_scales = scales
            self._io.set_bridge_probe_scales(*scales)
            self._io.request_bridge_probe_capture()

    def on_alert(self, level):
        """Start the cross-fade to a new bridge state (0-4, spec 2026-10-08-
        bridge-emitters §13.1). The spot list is static -- live colours follow
        on the next tick() -- so nothing is re-pushed and the probes never
        recapture."""
        self._fade.set_state(behaviour.state_name(level))

    def tick(self, dt):
        """Every frame: advance the bridge clock by the paused-aware player
        dt (0 under pause, so pulses and fades freeze) and push this frame's
        glow and live spot colours."""
        if self._iid is None or self._doc is None:
            return
        dt = max(float(dt), 0.0)
        self._t += dt
        self._fade.advance(dt)
        self._push_live()

    def _push_live(self):
        try:
            self._io.set_bridge_glow(
                self._iid, glow.live(self._glow_shapes, self._fade, self._t))
            self._io.set_bridge_spot_colours(
                lights.live_colours(self._doc, self._matched, self._resolved,
                                    self._fade, self._t, self._mapped))
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime live push", e)

    def detach(self):
        """Clear overrides + spots (never cleared by C++ on its own) and drop
        local state, so a push/on_alert arriving after detach (a straggler
        from the panel, a frame in flight) is a no-op rather than acting on
        the instance that just went away."""
        try:
            self._io.set_bridge_material_overrides(None, [])
            self._io.set_bridge_spots([])
            self._io.set_bridge_glow(None, [])
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime detach", e)
        finally:
            self._iid, self._doc, self._matched = None, None, {}
            self._meshes, self._glow_shapes, self._resolved, self._mapped = [], [], {}, frozenset()
