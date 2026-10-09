"""Applies a bridge's per-bridge lighting document to the renderer — the
PRODUCTION path (spec 2026-10-08-bridge-emitters §7, §9): at bridge load, on
editor edits, and on alert changes. Never raises into the host loop."""
from engine import bridge_lighting, dev_mode, host_io
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lights, materials


class BridgeRuntime:
    def __init__(self, io=host_io, eye=None, alert=None):
        self._io = io
        self._eye = eye
        self._alert = alert
        self._iid = None
        self._doc = None
        self._matched = {}

    def attach(self, iid):
        """Neither overrides nor spots are cleared by C++ on a mission swap,
        and probe state persists too — so every bridge load pushes fresh
        state for THIS bridge, an empty push when it has no file or no
        matched emitters, never leaving the previous bridge's state live.

        The probe origin/scales (and a capture request) are pushed BEFORE
        the content-hash check and unconditionally: a bridge with no hash
        (not an interior load) still has an eye and must get a fresh
        capture from it, never keep reflecting from whatever bridge was
        attached last."""
        self._iid, self._doc, self._matched = iid, None, {}
        try:
            info = self._io.model_identity(iid) or {}
            self._io.set_bridge_probe_origin(tuple(self._eye()))
            self._io.set_bridge_probe_scales(*bridge_lighting.probe_scales())
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
            self.push(doc, matched)
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime attach", e)

    def push(self, doc, matched=None):
        """Re-push overrides + spots from an edited doc (the live editor, or
        attach()). Returns spot-count warnings (cap drops by name, plus a
        summary warning if the renderer itself dropped more spots than that
        -- non-finite values slipping past schema validation). Builds tuples
        from a doc that is already schema-validated, but the push to the
        native side still goes through a guard -- a value that slips past
        validation (or a stale/garbage instance id) must not raise into the
        host loop."""
        if self._iid is None:
            return []
        self._doc = doc
        if matched is not None:
            self._matched = matched
        warnings = []
        try:
            self._io.set_bridge_material_overrides(
                self._iid, materials.overrides(doc, self._matched))
            spot_list, warnings = lights.spots(doc, self._matched, self._alert())
            for w in warnings:
                dev_mode.log_swallowed(
                    "bridge lighting too many spots", ld.BridgeLightingError(w))
            dropped = self._io.set_bridge_spots(spot_list)
            if dropped > len(warnings):
                extra = dropped - len(warnings)
                msg = f"{extra} spot(s) dropped by the renderer (non-finite values)"
                warnings.append(msg)
                dev_mode.log_swallowed(
                    "bridge lighting spots dropped", ld.BridgeLightingError(msg))
            self._io.request_bridge_probe_capture()
        except Exception as e:  # noqa: BLE001 - see docstring
            dev_mode.log_swallowed("bridge runtime push", e)
        return warnings

    def on_alert(self, level):
        """Re-push spots only on an alert change -- the probes keep their
        last capture; set_bridge_spots itself marks them dirty for the next
        one (native side), so a follow-up capture call here would be a
        needless extra re-render."""
        if self._iid is None or self._doc is None:
            return
        try:
            spot_list, _ = lights.spots(self._doc, self._matched, level)
            self._io.set_bridge_spots(spot_list)
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime on_alert", e)

    def detach(self):
        """Clear overrides + spots (never cleared by C++ on its own) and drop
        local state, so a push/on_alert arriving after detach (a straggler
        from the panel, a frame in flight) is a no-op rather than acting on
        the instance that just went away."""
        try:
            self._io.set_bridge_material_overrides(None, [])
            self._io.set_bridge_spots([])
        except Exception as e:  # noqa: BLE001 - never let bridge data kill the frame
            dev_mode.log_swallowed("bridge runtime detach", e)
        finally:
            self._iid, self._doc, self._matched = None, None, {}
