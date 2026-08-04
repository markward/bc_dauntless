// Ship Property Viewer overlay. Global entry called from Python render_payload
// via cef_execute_javascript:
//   setShipPropertyViewer({visible: true, pin_count: N, selected: {...}|null});
//   setShipPropertyViewer({visible: false});
// Close button fires dauntlessEvent('ship-property-viewer/cancel') which
// routes through PanelRegistry to ShipPropertyViewerPanel.dispatch_event.
// Reuses the cp-* classes from css/configuration_panel.css and the
// ship_property_viewer.css overlay styles.
// Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md

function escapeHtmlSPV(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

window.setShipPropertyViewer = function (data) {
    var root = document.getElementById('spv-root');
    if (!root) return;
    if (!data || data.visible !== true) {
        root.style.display = 'none';
        // The panel can close (Cancel / mission swap / Task 5 Fix 2) while a
        // context menu / modal is still up; leaving that chrome's inline
        // display untouched means it reappears, already open, next time the
        // viewer opens. Force every overlay closed alongside the root.
        spvHideOverlaysNoEvent();
        var bar0 = document.getElementById('spv-savebar');
        if (bar0) bar0.style.display = 'none';
        return;
    }
    root.style.display = 'block';

    var count = document.getElementById('spv-pincount');
    if (count) {
        count.textContent = (data.pin_count || 0) + ' subsystems';
    }

    var glowBtn = document.getElementById('spv-toggle-glow');
    if (glowBtn) {
        glowBtn.classList.toggle('active', data.show_glow === true);
    }
    var arcsBtn = document.getElementById('spv-toggle-arcs');
    if (arcsBtn) {
        arcsBtn.classList.toggle('active', data.show_arcs === true);
    }
    // Hull-texture toggle: active = real hull textures, inactive = hologram
    // (the default).
    var hullBtn = document.getElementById('spv-toggle-hull');
    if (hullBtn) {
        hullBtn.classList.toggle('active', data.show_hull === true);
    }

    // Transform-tools row: mutually-exclusive radio, active tool carries
    // .active per data.active_tool ('transform'|'rotate'|'scale'|null).
    var transformBtn = document.getElementById('spv-tool-transform');
    if (transformBtn) {
        transformBtn.classList.toggle('active', data.active_tool === 'transform');
    }
    var rotateBtn = document.getElementById('spv-tool-rotate');
    if (rotateBtn) {
        rotateBtn.classList.toggle('active', data.active_tool === 'rotate');
    }
    var scaleBtn = document.getElementById('spv-tool-scale');
    if (scaleBtn) {
        scaleBtn.classList.toggle('active', data.active_tool === 'scale');
    }

    // Action-tools row: Undo / Pipette / Mirror. Undo/Mirror disable without
    // an undo entry / selection; Pipette shows .active while armed and stays
    // enabled with a selection (to arm) or while already armed (to cancel).
    var undoBtn = document.getElementById('spv-action-undo');
    if (undoBtn) {
        undoBtn.disabled = data.can_undo !== true;
        undoBtn.classList.toggle('spv-tool--disabled', data.can_undo !== true);
    }
    var pipetteBtn = document.getElementById('spv-action-pipette');
    if (pipetteBtn) {
        pipetteBtn.classList.toggle('active', data.pipette_armed === true);
        var pipDisabled = data.has_selection !== true && data.pipette_armed !== true;
        pipetteBtn.disabled = pipDisabled;
        pipetteBtn.classList.toggle('spv-tool--disabled', pipDisabled);
    }
    var mirrorBtn = document.getElementById('spv-action-mirror');
    if (mirrorBtn) {
        mirrorBtn.disabled = data.has_selection !== true;
        mirrorBtn.classList.toggle('spv-tool--disabled', data.has_selection !== true);
    }

    // Transform coordinate panel (top-right): visible only while
    // data.transform_coords is non-null (Transform tool active + a
    // subsystem/light selected). Mirrors the XYZ position and the
    // clipboard-gated Paste button.
    var coords = data.transform_coords;
    var coordsEl = document.getElementById('spv-coords');
    if (coordsEl) {
        if (coords) {
            document.getElementById('spv-coord-x').textContent = coords.x.toFixed(3);
            document.getElementById('spv-coord-y').textContent = coords.y.toFixed(3);
            document.getElementById('spv-coord-z').textContent = coords.z.toFixed(3);
            var pasteBtn = document.getElementById('spv-coord-paste');
            pasteBtn.disabled = !coords.has_clipboard;
            pasteBtn.classList.toggle('spv-coords__btn--disabled', !coords.has_clipboard);
            coordsEl.style.display = 'block';
        } else {
            coordsEl.style.display = 'none';
        }
    }

    // Scale panel (top-right): visible only while data.scale_values is
    // non-null (Scale tool active + a subsystem/light selected). Rows are
    // shape-aware (built from scale_values.fields — X/Y/Z, Radius, Length),
    // and the same top-right slot is shared with #spv-coords (radio: never
    // both are shown at once).
    var scale = data.scale_values;
    var scaleEl = document.getElementById('spv-scale');
    if (scaleEl) {
        if (scale) {
            var rows = scale.fields.map(function (f, i) {
                return '<div class="spv-coords__row">'
                     + '<span class="spv-coords__axis">' + escapeHtmlSPV(f.label) + '</span>'
                     + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',-0.1)">&minus;0.1</button>'
                     + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',-0.01)">&minus;0.01</button>'
                     + '<span class="spv-coords__val">' + f.value.toFixed(3) + '</span>'
                     + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',0.01)">+0.01</button>'
                     + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',0.1)">+0.1</button>'
                     + '</div>';
            }).join('');
            document.getElementById('spv-scale-rows').innerHTML = rows;
            var sp = document.getElementById('spv-scale-paste');
            sp.disabled = !scale.can_paste;
            sp.classList.toggle('spv-coords__btn--disabled', !scale.can_paste);
            scaleEl.style.display = 'block';
        } else {
            scaleEl.style.display = 'none';
        }
    }

    // Rotate panel (top-right): visible only while data.rotate_values is
    // non-null (Rotate tool active + a cylinder light volume selected).
    // Fixed X/Y/Z degree rows (no innerHTML rebuild needed), and the same
    // top-right slot is shared with #spv-coords/#spv-scale (radio: never
    // more than one shown at once).
    var rotate = data.rotate_values;
    var rotateEl = document.getElementById('spv-rotate');
    if (rotateEl) {
        if (rotate) {
            document.getElementById('spv-rotate-x').textContent = rotate.fields[0].value.toFixed(1) + '°';
            document.getElementById('spv-rotate-y').textContent = rotate.fields[1].value.toFixed(1) + '°';
            document.getElementById('spv-rotate-z').textContent = rotate.fields[2].value.toFixed(1) + '°';
            var rp = document.getElementById('spv-rotate-paste');
            rp.disabled = !rotate.can_paste;
            rp.classList.toggle('spv-coords__btn--disabled', !rotate.can_paste);
            rotateEl.style.display = 'block';
        } else {
            rotateEl.style.display = 'none';
        }
    }

    renderSPVSubsystemList(data.subsystems || [],
        (typeof data.selected_index === 'number') ? data.selected_index : null,
        (typeof data.selected_light_index === 'number') ? data.selected_light_index : null,
        data.selected_emitter || null);

    // Save bar: surfaces the staged-edit count (data.pending_count); hidden
    // while nothing is pending.
    var bar = document.getElementById('spv-savebar');
    var n = data.pending_count || 0;
    var saveCount = document.getElementById('spv-savecount');
    if (saveCount) saveCount.textContent = n;
    if (bar) bar.style.display = n > 0 ? 'block' : 'none';

    // Keep the confirm modal's pending-edits list in sync with the panel
    // (populated into #spv-confirm-body when the Save bar opens it).
    spvPendingEdits = data.pending || [];

    // Server-driven ESC: the raw-GLFW modal-ESC router calls the panel's
    // handle_key_esc() independent of CEF focus, so the panel (not this JS)
    // owns "did ESC close an overlay or the whole panel" to avoid a race.
    // One-shot data.close_overlays === true means ESC just closed an
    // overlay — hide the overlay chrome WITHOUT re-firing overlay:0 (the
    // panel already cleared _overlay_open itself).
    if (data.close_overlays === true) {
        spvHideOverlaysNoEvent();
    }

    var pop = document.getElementById('spv-popover');
    if (!pop) return;
    // The property popover and the transform coord / scale / rotate panels
    // share the top-right corner; while any of them is up (data.transform_coords,
    // data.scale_values, or data.rotate_values non-null) the opaque popover
    // would paint over it and swallow its clicks, so suppress the popover
    // during transform/scale/rotate.
    if (data.selected && !data.transform_coords && !data.scale_values && !data.rotate_values) {
        var sel = data.selected;
        var p = sel.properties || {};
        var rows = Object.keys(p).map(function (k) {
            return '<div class="spv-row">'
                 +   '<span class="spv-k">' + escapeHtmlSPV(k) + '</span>'
                 +   '<span class="spv-v">' + escapeHtmlSPV(String(p[k])) + '</span>'
                 + '</div>';
        }).join('');
        pop.innerHTML = '<div class="spv-pop-title">' + escapeHtmlSPV(sel.name || '') + '</div>'
                      + rows;
        pop.style.display = 'block';
        // Capture the selected subsystem's radius so the context-menu modal
        // can pre-fill from it (the row payload itself carries no radius).
        if (p.radius !== undefined && typeof data.selected_index === 'number') {
            spvRowRadii[data.selected_index] = parseFloat(p.radius);
        }
    } else {
        pop.style.display = 'none';
        pop.innerHTML = '';
    }
};

// ── Context menu / radius modal / Save bar wiring (Task 5) ─────────────────
// Right-click a subsystem row -> context menu -> "Set Radius..." -> numeric
// modal -> Apply stages the edit via 'set_radius:<json>'. The Save bar opens
// an amend-confirm modal; confirming fires 'save'. All overlays notify the
// host via 'overlay:1'/'overlay:0' so 3D orbit-drag is suppressed while an
// overlay has mouse focus.
//
// ESC is deliberately NOT handled here. It's read raw (GLFW), independent of
// CEF focus, by host_loop's modal-ESC router, which calls the panel's
// handle_key_esc() — the single owner of "does ESC close the overlay or the
// panel" (a JS keydown listener racing that would double-handle the same
// key-press). The panel signals "ESC just closed an overlay" back to this
// JS one-shot via payload.close_overlays (see setShipPropertyViewer above).
var spvCtxIndex = null, spvCtxRadius = 0, spvRowRadii = {}, spvPendingEdits = [];
var spvRowLight = {};   // index -> light_region spec (or true) for light rows
var spvLight = null;    // working spec while the modal is open
var spvLightMode = 'edit';   // 'edit' (set_light) or 'add' (add_light) — which
                              // action the shared shape-picker modal's Apply fires

// A light-volume node's working seed lives on the row (row.light_region), keyed
// by its parent subsystem index (row.light_of). Track the right-clicked node so
// the context menu knows which items to show.
var spvCtxLightOf = null;           // parent subsystem index for a light node

// ── Light Emitter modal state (Task 10) ─────────────────────────────────────
// Independent subsystem-child emitters, addressed positionally by (i, j) —
// see engine/ui/ship_property_viewer_panel.py's _effective_emitters. A row's
// working spec is cached by 'i/j' key (spvRowEmitter), mirroring spvRowLight.
var spvEmitterMode = 'add';         // 'add' | 'edit'
var spvEmitterTarget = null;        // {i} for add, {i, j} for edit
var spvEmitter = null;              // {kind, hue, sat, intensity} while the modal is open
var spvRowEmitter = {};             // 'i/j' -> emitter_spec, cached from the tree payload
var spvCtxEmitterOf = null;         // parent subsystem index for a right-clicked emitter node
var spvCtxEmitterIndex = null;      // emitter index within that subsystem

// Hide the overlay chrome without telling the host — used when the panel
// itself already knows the overlay closed (ESC via close_overlays, or the
// whole panel closing per Fix 2) so we don't double-fire overlay:0.
function spvHideOverlaysNoEvent() {
    ['spv-ctxmenu', 'spv-radius', 'spv-light', 'spv-emitter', 'spv-confirm'].forEach(function (id) {
        var el = document.getElementById(id); if (el) el.style.display = 'none';
    });
}
function spvHideOverlays() {
    spvHideOverlaysNoEvent();
    dauntlessEvent('ship-property-viewer/overlay:0');
}
document.addEventListener('click', function (e) {
    var menu = document.getElementById('spv-ctxmenu');
    if (menu && menu.style.display !== 'none' && !menu.contains(e.target)) {
        menu.style.display = 'none';
        if (document.getElementById('spv-radius').style.display === 'none'
            && document.getElementById('spv-confirm').style.display === 'none') {
            dauntlessEvent('ship-property-viewer/overlay:0');
        }
    }
});

// Light node row click: select this light (or deselect if already selected).
window.shipPropertyViewerLightRow = function (lightOf, chosen) {
    dauntlessEvent('ship-property-viewer/' +
                   (chosen ? 'deselect' : ('select_light:' + lightOf)));
};

// Right-click a subsystem row: Set Radius always; Add Light Volume only when the
// subsystem has no light yet; Add Light Emitter always (a subsystem may hold
// any number of independent emitters).
window.shipPropertyViewerRowMenu = function (event, index, hasLight) {
    event.preventDefault(); event.stopPropagation();
    spvCtxIndex = index; spvCtxLightOf = null;
    spvCtxEmitterOf = null; spvCtxEmitterIndex = null;
    spvCtxRadius = (spvRowRadii[index] !== undefined) ? spvRowRadii[index] : 0;
    spvShowMenuItems({radius: true, addlight: !hasLight, light: false, removelight: false,
                       addemitter: true, editemitter: false, removeemitter: false});
    spvOpenMenuAt(event);
    return false;
};

// Right-click a light node: Edit + Remove.
window.shipPropertyViewerLightMenu = function (event, lightOf) {
    event.preventDefault(); event.stopPropagation();
    spvCtxLightOf = lightOf; spvCtxIndex = lightOf;
    spvCtxEmitterOf = null; spvCtxEmitterIndex = null;
    spvShowMenuItems({radius: false, addlight: false, light: true, removelight: true,
                       addemitter: false, editemitter: false, removeemitter: false});
    spvOpenMenuAt(event);
    return false;
};

// Right-click an emitter node: Edit + Remove (mirrors shipPropertyViewerLightMenu).
window.shipPropertyViewerEmitterMenu = function (event, emitterOf, emitterIndex) {
    event.preventDefault(); event.stopPropagation();
    spvCtxEmitterOf = emitterOf; spvCtxEmitterIndex = emitterIndex;
    spvCtxIndex = emitterOf; spvCtxLightOf = null;
    spvShowMenuItems({radius: false, addlight: false, light: false, removelight: false,
                       addemitter: false, editemitter: true, removeemitter: true});
    spvOpenMenuAt(event);
    return false;
};

function spvShowMenuItems(show) {
    var map = {radius: 'spv-ctx-radius', addlight: 'spv-ctx-addlight',
               light: 'spv-ctx-light', removelight: 'spv-ctx-removelight',
               addemitter: 'spv-ctx-addemitter', editemitter: 'spv-ctx-editemitter',
               removeemitter: 'spv-ctx-removeemitter'};
    Object.keys(map).forEach(function (k) {
        var el = document.getElementById(map[k]);
        if (el) el.style.display = show[k] ? 'block' : 'none';
    });
}
function spvOpenMenuAt(event) {
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
}

// Add Light Volume (subsystem context) → open the same shape-picker modal as
// Edit Light, defaulted from the subsystem's own light child if it has one
// (mirrors shipPropertyViewerCtxLight's open path exactly).
window.shipPropertyViewerCtxAddLight = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvLightMode = 'add';
    document.getElementById('spv-light-title').textContent = 'Add Light';
    spvLight = spvLightDefaults();
    var seed = spvRowLight[spvCtxIndex];
    spvLight.shape = (seed && seed.shape) || 'Sphere';
    shipPropertyViewerLightShape(spvLight.shape);
    document.getElementById('spv-light').style.display = 'flex';
};
// Remove Light Volume (light-node context).
window.shipPropertyViewerCtxRemoveLight = function () {
    dauntlessEvent('ship-property-viewer/remove_light:' + spvCtxLightOf);
    spvHideOverlays();
};
// Radius is edited with a mouse-only stepper: the engine has no keyboard->CEF
// forwarding, so a typed <input> can't receive characters. spvRadiusValue holds
// the working value (2 decimal places, clamped > 0); the buttons nudge it.
var spvRadiusValue = 0;

function spvRenderRadiusValue() {
    var el = document.getElementById('spv-radius-value');
    if (el) el.textContent = spvRadiusValue.toFixed(2);
}
window.shipPropertyViewerCtxRadius = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    var start = (spvCtxRadius > 0) ? spvCtxRadius : 0.25;   // fallback if unseeded
    spvRadiusValue = Math.round(start * 100) / 100;
    spvRenderRadiusValue();
    document.getElementById('spv-radius').style.display = 'flex';
};
window.shipPropertyViewerRadiusStep = function (delta) {
    spvRadiusValue = Math.max(0.01, Math.round((spvRadiusValue + delta) * 100) / 100);
    spvRenderRadiusValue();
};
window.shipPropertyViewerRadiusApply = function () {
    if (spvRadiusValue > 0) {
        dauntlessEvent('ship-property-viewer/set_radius:'
                       + JSON.stringify({i: spvCtxIndex, value: spvRadiusValue}));
    }
    spvHideOverlays();
};
window.shipPropertyViewerRadiusCancel = function () { spvHideOverlays(); };

// Light is edited with a mouse-only shape picker + steppers: same reasoning as
// the radius stepper above (no keyboard->CEF forwarding). light_region is
// baked-shaped (radius=[r], extent=[aft,fore], scale=[sx,sy,sz]); spvLight
// holds the flattened working copy while the modal is open.

// Default sizes when a field isn't pre-seeded from light_region.
function spvLightDefaults() {
    return {shape: 'Sphere', radius: 0.25, aft: 0.0, fore: 2.0,
            sx: 0.25, sy: 0.25, sz: 0.25};
}

window.shipPropertyViewerCtxLight = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvLightMode = 'edit';
    document.getElementById('spv-light-title').textContent = 'Edit Light';
    // Select the light node we're about to edit so its wireframe is the
    // selected element — the glow overlay is selection-scoped, so this is
    // what makes the staged edit preview live while the modal is open.
    dauntlessEvent('ship-property-viewer/select_light:' + spvCtxIndex);
    spvLight = spvLightDefaults();
    var seed = spvRowLight[spvCtxIndex];
    if (seed && typeof seed === 'object') {
        // light_region is baked-shaped: radius=[r], extent=[aft,fore], scale=[sx,sy,sz]
        spvLight.shape = seed.shape || 'Sphere';
        if (seed.radius && seed.radius.length) spvLight.radius = seed.radius[0];
        if (seed.extent && seed.extent.length === 2) {
            spvLight.aft = seed.extent[0]; spvLight.fore = seed.extent[1];
        }
        if (seed.scale && seed.scale.length === 3) {
            spvLight.sx = seed.scale[0]; spvLight.sy = seed.scale[1]; spvLight.sz = seed.scale[2];
        }
    }
    shipPropertyViewerLightShape(spvLight.shape);
    document.getElementById('spv-light').style.display = 'flex';
};

function spvStepperHtml(label, field, step) {
    return '<div class="spv-stepper">'
         +   '<span class="spv-stepper__label">' + label + '</span>'
         +   '<button class="spv-step-btn" onclick="shipPropertyViewerLightStep(\'' + field + '\',' + (-step) + ')">&minus;</button>'
         +   '<span class="spv-stepper__val" id="spv-lv-' + field + '">' + spvLight[field].toFixed(2) + '</span>'
         +   '<button class="spv-step-btn" onclick="shipPropertyViewerLightStep(\'' + field + '\',' + step + ')">+</button>'
         + '</div>';
}

window.shipPropertyViewerLightShape = function (shape) {
    spvLight.shape = shape;
    ['Sphere', 'Cylinder', 'Box'].forEach(function (s) {
        var b = document.getElementById('spv-shape-' + s);
        if (b) b.classList.toggle('active', s === shape);
    });
};

window.shipPropertyViewerLightStep = function (field, delta) {
    var floor = (field === 'aft') ? -100.0 : 0.01;   // aft may be <=0; others > 0
    spvLight[field] = Math.round((spvLight[field] + delta) * 100) / 100;
    if (spvLight[field] < floor) spvLight[field] = floor;
    var el = document.getElementById('spv-lv-' + field);
    if (el) el.textContent = spvLight[field].toFixed(2);
};

window.shipPropertyViewerLightApply = function () {
    var action = (spvLightMode === 'add') ? 'add_light:' : 'set_light:';
    dauntlessEvent('ship-property-viewer/' + action
                   + JSON.stringify({i: spvCtxIndex, shape: spvLight.shape}));
    spvHideOverlays();
};

window.shipPropertyViewerLightCancel = function () { spvHideOverlays(); };

// ── Light Emitter modal (Task 10) ───────────────────────────────────────────
// Type picker (Point/Strip/Cone) + a canvas hue/sat colour wheel + an HDR
// intensity slider, all mouse-only pointer-drag (no keyboard->CEF forwarding
// exists — see #spv-radius / #spv-light above for the same constraint).
// Colour/intensity are seeded on ADD directly into the add_emitter dispatch
// (engine/ui/ship_property_viewer_panel.py's add_emitter handler accepts
// optional color/intensity) rather than an echo-then-set round-trip.

function spvEmitterDefaults() {
    return {kind: 'point', hue: 40, sat: 0.3, intensity: 2.0};
}

window.shipPropertyViewerEmitterKind = function (kind) {
    spvEmitter.kind = kind;
    ['point', 'strip', 'cone'].forEach(function (k) {
        var b = document.getElementById('spv-emkind-' + k);
        if (b) b.classList.toggle('active', k === kind);
    });
};

// HSV->RGB with V=1 always: the wheel only picks hue (angle) and saturation
// (radius); brightness is the separate, HDR-range (0..8) intensity slider.
function spvHsToRgb(hue, sat) {
    var h = ((hue % 360) + 360) % 360;
    var s = Math.max(0, Math.min(1, sat));
    var c = s;                       // v(=1) * s
    var x = c * (1 - Math.abs((h / 60) % 2 - 1));
    var m = 1 - c;                   // v - c
    var r, g, b;
    if (h < 60)       { r = c; g = x; b = 0; }
    else if (h < 120) { r = x; g = c; b = 0; }
    else if (h < 180) { r = 0; g = c; b = x; }
    else if (h < 240) { r = 0; g = x; b = c; }
    else if (h < 300) { r = x; g = 0; b = c; }
    else              { r = c; g = 0; b = x; }
    return [r + m, g + m, b + m];
}

// Inverse of spvHsToRgb (V forced to 1), used only to seed the wheel's
// hue/sat marker from a saved emitter's color when Edit opens.
function spvRgbToHs(rgb) {
    var r = rgb[0] || 0, g = rgb[1] || 0, b = rgb[2] || 0;
    var max = Math.max(r, g, b), min = Math.min(r, g, b);
    var d = max - min;
    var h = 0;
    if (d > 1e-6) {
        if (max === r) h = 60 * (((g - b) / d) % 6);
        else if (max === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;
    var sat = (max > 1e-6) ? d / max : 0;
    return {hue: h, sat: Math.max(0, Math.min(1, sat))};
}

// Cached base disc (hue = angle, sat = radius, V = 1) painted once per page
// load; only the selection marker is redrawn on every wheel interaction.
var _spvWheelBase = null;

function spvDrawWheel() {
    var canvas = document.getElementById('spv-emitter-wheel');
    if (!canvas || !spvEmitter) return;
    var ctx = canvas.getContext('2d');
    var w = canvas.width, h = canvas.height;
    var cx = w / 2, cy = h / 2, R = Math.min(cx, cy) - 4;
    if (!_spvWheelBase) {
        var img = ctx.createImageData(w, h);
        for (var y = 0; y < h; y++) {
            for (var x = 0; x < w; x++) {
                var dx = x - cx, dy = y - cy;
                var dist = Math.sqrt(dx * dx + dy * dy);
                var idx = (y * w + x) * 4;
                if (dist > R) { img.data[idx + 3] = 0; continue; }
                var angle = Math.atan2(dy, dx) * 180 / Math.PI;
                if (angle < 0) angle += 360;
                var rgb = spvHsToRgb(angle, Math.min(1, dist / R));
                img.data[idx]     = Math.round(rgb[0] * 255);
                img.data[idx + 1] = Math.round(rgb[1] * 255);
                img.data[idx + 2] = Math.round(rgb[2] * 255);
                img.data[idx + 3] = 255;
            }
        }
        _spvWheelBase = img;
    }
    ctx.putImageData(_spvWheelBase, 0, 0);
    var rad = spvEmitter.hue * Math.PI / 180;
    var r = spvEmitter.sat * R;
    var mx = cx + Math.cos(rad) * r, my = cy + Math.sin(rad) * r;
    ctx.beginPath(); ctx.arc(mx, my, 5, 0, Math.PI * 2);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(mx, my, 3, 0, Math.PI * 2);
    ctx.strokeStyle = '#000'; ctx.lineWidth = 1; ctx.stroke();
}

function _spvSetHueSatFromEvent(canvas, clientX, clientY) {
    var rect = canvas.getBoundingClientRect();
    var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    var R = Math.min(rect.width, rect.height) / 2 - 4;
    var dx = clientX - cx, dy = clientY - cy;
    var angle = Math.atan2(dy, dx) * 180 / Math.PI;
    if (angle < 0) angle += 360;
    spvEmitter.hue = angle;
    spvEmitter.sat = Math.max(0, Math.min(1, Math.sqrt(dx * dx + dy * dy) / R));
    spvDrawWheel();
}
var _spvWheelDragging = false;
function _spvWheelPointerDown(e) {
    var canvas = e.currentTarget;
    canvas.setPointerCapture(e.pointerId);
    _spvWheelDragging = true;
    _spvSetHueSatFromEvent(canvas, e.clientX, e.clientY);
}
function _spvWheelPointerMove(e) {
    if (!_spvWheelDragging) return;
    _spvSetHueSatFromEvent(e.currentTarget, e.clientX, e.clientY);
}
function _spvWheelPointerUp() { _spvWheelDragging = false; }
(function _spvWireEmitterWheel() {
    var canvas = document.getElementById('spv-emitter-wheel');
    if (!canvas) return;
    canvas.addEventListener('pointerdown', _spvWheelPointerDown);
    canvas.addEventListener('pointermove', _spvWheelPointerMove);
    canvas.addEventListener('pointerup', _spvWheelPointerUp);
})();

function spvRenderEmitterIntensity() {
    var el = document.getElementById('spv-em-intensity');
    if (el) el.textContent = spvEmitter.intensity.toFixed(2);
    var fill = document.getElementById('spv-em-intensity-fill');
    if (fill) fill.style.width = Math.max(0, Math.min(100, spvEmitter.intensity / 8 * 100)) + '%';
}
window.shipPropertyViewerEmitterIntensityStep = function (delta) {
    spvEmitter.intensity = Math.max(0, Math.round((spvEmitter.intensity + delta) * 100) / 100);
    spvRenderEmitterIntensity();
};
function _spvApplyIntensityDrag(track, clientX) {
    var rect = track.getBoundingClientRect();
    if (!rect.width) return;
    var raw = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    spvEmitter.intensity = Math.round(raw * 8 * 100) / 100;   // track spans 0..8
    spvRenderEmitterIntensity();
}
var _spvIntensityDragging = false;
function _spvIntensityPointerDown(e) {
    var track = e.currentTarget;
    track.setPointerCapture(e.pointerId);
    _spvIntensityDragging = true;
    _spvApplyIntensityDrag(track, e.clientX);
}
function _spvIntensityPointerMove(e) {
    if (!_spvIntensityDragging) return;
    _spvApplyIntensityDrag(e.currentTarget, e.clientX);
}
function _spvIntensityPointerUp() { _spvIntensityDragging = false; }
(function _spvWireEmitterIntensity() {
    var track = document.getElementById('spv-em-intensity-track');
    if (!track) return;
    track.addEventListener('pointerdown', _spvIntensityPointerDown);
    track.addEventListener('pointermove', _spvIntensityPointerMove);
    track.addEventListener('pointerup', _spvIntensityPointerUp);
})();

// Add Light Emitter (subsystem context) → fresh defaults.
window.shipPropertyViewerCtxAddEmitter = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvEmitterMode = 'add';
    spvEmitterTarget = {i: spvCtxIndex};
    spvEmitter = spvEmitterDefaults();
    document.getElementById('spv-emitter-title').textContent = 'Add Light Emitter';
    shipPropertyViewerEmitterKind(spvEmitter.kind);
    spvRenderEmitterIntensity();
    spvDrawWheel();
    document.getElementById('spv-emitter').style.display = 'flex';
};

// Edit Emitter (emitter-node context) → seed from the row's cached spec.
window.shipPropertyViewerCtxEditEmitter = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    spvEmitterMode = 'edit';
    var i = spvCtxEmitterOf, j = spvCtxEmitterIndex;
    spvEmitterTarget = {i: i, j: j};
    // Select this emitter so its wireframe is the previewed element while
    // the modal is open (mirrors shipPropertyViewerCtxLight's select_light).
    dauntlessEvent('ship-property-viewer/select_emitter:' + JSON.stringify({i: i, j: j}));
    spvEmitter = spvEmitterDefaults();
    var seed = spvRowEmitter[i + '/' + j];
    if (seed && typeof seed === 'object') {
        spvEmitter.kind = seed.kind || 'point';
        var hs = spvRgbToHs(seed.color || [1.0, 0.9, 0.7]);
        spvEmitter.hue = hs.hue; spvEmitter.sat = hs.sat;
        spvEmitter.intensity = (typeof seed.intensity === 'number') ? seed.intensity : 2.0;
    }
    document.getElementById('spv-emitter-title').textContent = 'Edit Emitter';
    shipPropertyViewerEmitterKind(spvEmitter.kind);
    spvRenderEmitterIntensity();
    spvDrawWheel();
    document.getElementById('spv-emitter').style.display = 'flex';
};

// Remove Light Emitter (emitter-node context).
window.shipPropertyViewerCtxRemoveEmitter = function () {
    dauntlessEvent('ship-property-viewer/remove_emitter:'
                   + JSON.stringify({i: spvCtxEmitterOf, j: spvCtxEmitterIndex}));
    spvHideOverlays();
};

window.shipPropertyViewerEmitterApply = function () {
    var rgb = spvHsToRgb(spvEmitter.hue, spvEmitter.sat);
    var payload;
    if (spvEmitterMode === 'add') {
        payload = {i: spvEmitterTarget.i, kind: spvEmitter.kind, color: rgb, intensity: spvEmitter.intensity};
        dauntlessEvent('ship-property-viewer/add_emitter:' + JSON.stringify(payload));
    } else {
        payload = {i: spvEmitterTarget.i, j: spvEmitterTarget.j, kind: spvEmitter.kind,
                   color: rgb, intensity: spvEmitter.intensity};
        dauntlessEvent('ship-property-viewer/set_emitter:' + JSON.stringify(payload));
    }
    spvHideOverlays();
};

window.shipPropertyViewerEmitterCancel = function () { spvHideOverlays(); };

// Emitter node row click: select this emitter (or deselect if already selected).
window.shipPropertyViewerEmitterRow = function (emitterOf, emitterIndex, chosen) {
    dauntlessEvent('ship-property-viewer/' +
                   (chosen ? 'deselect'
                           : ('select_emitter:' + JSON.stringify({i: emitterOf, j: emitterIndex}))));
};

window.shipPropertyViewerSave = function () {
    // List the modified subsystems in the confirm modal, each with a tally of
    // its staged changes in brackets, e.g. "Center Impulse (1)".
    var body = document.getElementById('spv-confirm-body');
    if (body) {
        body.innerHTML = (spvPendingEdits || []).map(function (e) {
            return '<div class="spv-row">'
                 +   '<span class="spv-k">' + escapeHtmlSPV(e.name || '') + '</span>'
                 +   '<span class="spv-v">(' + (e.count || 0) + ')</span>'
                 + '</div>';
        }).join('');
    }
    document.getElementById('spv-confirm').style.display = 'flex';
    dauntlessEvent('ship-property-viewer/overlay:1');
};
window.shipPropertyViewerConfirmSave = function () {
    dauntlessEvent('ship-property-viewer/save'); spvHideOverlays();
};
window.shipPropertyViewerConfirmCancel = function () { spvHideOverlays(); };

// Close button → send 'cancel' to Python via the same console-log bridge
// that every other panel uses (defined in pause_menu.js):
//   dauntlessEvent('ship-property-viewer/cancel')
// C++ OnConsoleMessage strips the 'dauntless-event:' prefix and dispatches
// to PanelRegistry, which routes to ShipPropertyViewerPanel.dispatch_event.
window.shipPropertyViewerClose = function () {
    dauntlessEvent('ship-property-viewer/cancel');
};

// Tool-grid overlay toggles (Glow Regions / Weapon Arcs) → Python flips the
// flag and re-pushes the payload, which round-trips back here as
// data.show_glow / data.show_arcs so the .active button state always mirrors
// the panel's real state.
window.shipPropertyViewerToggle = function (action) {
    dauntlessEvent('ship-property-viewer/' + action);
};

// Transform-tools row (Transform/Rotate/Scale) — mutually exclusive radio;
// mirrors shipPropertyViewerToggle's event channel. Python flips
// active_tool and re-pushes the payload, which round-trips back here as
// data.active_tool so the .active button state always mirrors the panel's
// real state.
window.shipPropertyViewerSetTool = function (name) {
    dauntlessEvent('ship-property-viewer/set_tool:' + name);
};

// Action-tools row (Undo / Pipette / Mirror). Same event channel as the
// toggles above; Python re-pushes the payload so button state mirrors panel
// state (can_undo / pipette_armed / has_selection).
window.shipPropertyViewerUndo = function () {
    dauntlessEvent('ship-property-viewer/undo');
};
window.shipPropertyViewerPipette = function () {
    dauntlessEvent('ship-property-viewer/pipette');
};
window.shipPropertyViewerMirror = function () {
    dauntlessEvent('ship-property-viewer/mirror_element');
};

// Transform coordinate panel: mouse-only XYZ steppers + Copy/Paste/Mirror.
// Same event channel as the toggles/tools above; Python re-pushes
// transform_coords on every apply so the panel always mirrors live state.
window.shipPropertyViewerCoordNudge = function (axis, delta) {
    dauntlessEvent('ship-property-viewer/coord_nudge:' + JSON.stringify({axis: axis, delta: delta}));
};
window.shipPropertyViewerCoordCopy = function () {
    dauntlessEvent('ship-property-viewer/coord_copy');
};
window.shipPropertyViewerCoordPaste = function () {
    dauntlessEvent('ship-property-viewer/coord_paste');
};
window.shipPropertyViewerCoordMirror = function () {
    dauntlessEvent('ship-property-viewer/coord_mirror');
};

// Scale panel: mouse-only shape-aware steppers + Copy/Paste/Uniform. Same
// event channel as the coord handlers above; Python re-pushes scale_values
// on every apply so the panel always mirrors live state.
window.shipPropertyViewerScaleNudge = function (index, delta) {
    dauntlessEvent('ship-property-viewer/scale_nudge:' + JSON.stringify({index: index, delta: delta}));
};
window.shipPropertyViewerScaleCopy = function () {
    dauntlessEvent('ship-property-viewer/scale_copy');
};
window.shipPropertyViewerScalePaste = function () {
    dauntlessEvent('ship-property-viewer/scale_paste');
};
window.shipPropertyViewerScaleUniform = function () {
    dauntlessEvent('ship-property-viewer/scale_uniform');
};

// Rotate panel: mouse-only degree steppers + Copy/Paste/Mirror. Same event
// channel as the coord/scale handlers above; Python re-pushes rotate_values
// on every apply so the panel always mirrors live state.
window.shipPropertyViewerRotateNudge = function (axis, delta) {
    dauntlessEvent('ship-property-viewer/rotate_nudge:' + JSON.stringify({axis: axis, delta: delta}));
};
window.shipPropertyViewerRotateCopy = function () {
    dauntlessEvent('ship-property-viewer/rotate_copy');
};
window.shipPropertyViewerRotatePaste = function () {
    dauntlessEvent('ship-property-viewer/rotate_paste');
};
window.shipPropertyViewerRotateMirror = function () {
    dauntlessEvent('ship-property-viewer/rotate_mirror');
};

// Subsystem-list row click: select that pin; clicking the already-selected
// row deselects (mirrors clicking empty space in the 3D view).
window.shipPropertyViewerRow = function (index, chosen) {
    dauntlessEvent('ship-property-viewer/' +
                   (chosen ? 'deselect' : ('select_pin:' + index)));
};

// Eye glyphs: open = targetable, shut = untargetable. Inline SVG so the
// colour follows the row's currentColor.
var SPV_EYE_OPEN =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none"'
  + ' stroke="currentColor" stroke-width="2" stroke-linejoin="round">'
  + '<path d="M2 12 C 5.5 6.5, 18.5 6.5, 22 12 C 18.5 17.5, 5.5 17.5, 2 12 Z"/>'
  + '<circle cx="12" cy="12" r="3"/></svg>';
var SPV_EYE_SHUT =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none"'
  + ' stroke="currentColor" stroke-width="2" stroke-linecap="round">'
  + '<path d="M2 12 C 5.5 17.5, 18.5 17.5, 22 12"/>'
  + '<path d="M6 15.5l-1.8 2.4M12 17v3M18 15.5l1.8 2.4"/></svg>';

// Accordion caret: expand/collapse a category row's children without
// selecting the category (the caret's onclick stops propagation).
window.shipPropertyViewerGroupToggle = function (index) {
    dauntlessEvent('ship-property-viewer/toggle_group:' + index);
};

function spvSeedRow(row) {
    if (row.kind === 'light') {
        if (row.light_region) spvRowLight[row.light_of] = row.light_region;
        return;
    }
    if (row.kind === 'emitter') {
        if (row.emitter_spec) spvRowEmitter[row.emitter_of + '/' + row.emitter_index] = row.emitter_spec;
        return;
    }
    if (row.radius != null) spvRowRadii[row.index] = row.radius;
    // subsystem row no longer carries light_region; Add uses light_of default
    // captured from its own light child if present (seeded above).
}

// Recursive render: a row, then (if expanded) its children at any depth.
function spvRenderRows(rows, out, selectedIndex, selectedLight, selectedEmitterKey, depth) {
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i] || {};
        spvSeedRow(row);
        out.push(spvRowHtml(row, selectedIndex, selectedLight, selectedEmitterKey, depth));
        if (row.expanded && (row.children || []).length) {
            spvRenderRows(row.children, out, selectedIndex, selectedLight, selectedEmitterKey, depth + 1);
        }
    }
}

// Render the left-column subsystem list: category rows with their child
// pods/banks/tubes/light-volume/emitter nodes nested under them (collapsible,
// like the target list), recursing to any depth.
function renderSPVSubsystemList(rows, selectedIndex, selectedLight, selectedEmitter) {
    var body = document.getElementById('spv-syslist-body');
    if (!body) return;
    var selectedEmitterKey = (Array.isArray(selectedEmitter) && selectedEmitter.length === 2)
        ? (selectedEmitter[0] + '/' + selectedEmitter[1]) : null;
    var out = [];
    spvRenderRows(rows, out, selectedIndex, selectedLight, selectedEmitterKey, 0);
    body.innerHTML = out.join('');
}

function spvRowHtml(row, selectedIndex, selectedLight, selectedEmitterKey, depth) {
    var isLight = (row.kind === 'light');
    var isEmitter = (row.kind === 'emitter');
    var emitterKey = isEmitter ? (row.emitter_of + '/' + row.emitter_index) : null;
    var chosen = isLight ? (selectedLight === row.light_of)
               : isEmitter ? (selectedEmitterKey === emitterKey)
                           : (selectedIndex === row.index);
    var hasChildren = (row.children || []).length > 0;
    var lead;
    if (hasChildren) {
        // Glyph swap (▾/▸), not CSS rotation — see target_list.js on CEF
        // layer promotion hurting text crispness.
        lead = '<span class="spv-sys-caret" onclick="event.stopPropagation();'
             + 'shipPropertyViewerGroupToggle(' + row.index + ')">'
             + (row.expanded ? '&#9662;' : '&#9656;') + '</span>';
    } else {
        lead = '<span class="spv-sys-caret spv-sys-caret--none"></span>';
    }
    var clickJs = isLight
        ? ('shipPropertyViewerLightRow(' + row.light_of + ', ' + chosen + ')')
        : isEmitter
        ? ('shipPropertyViewerEmitterRow(' + row.emitter_of + ', ' + row.emitter_index + ', ' + chosen + ')')
        : ('shipPropertyViewerRow(' + row.index + ', ' + chosen + ')');
    var menuJs = isLight
        ? ('return shipPropertyViewerLightMenu(event, ' + row.light_of + ')')
        : isEmitter
        ? ('return shipPropertyViewerEmitterMenu(event, ' + row.emitter_of + ', ' + row.emitter_index + ')')
        : ('return shipPropertyViewerRowMenu(event, ' + row.index + ', '
           + (row.has_light === true) + ')');
    var extra = isLight ? ' spv-sys-row--light' : isEmitter ? ' spv-sys-row--light' : '';
    var indent = ' style="padding-left:' + (10 + depth * 14) + 'px"';
    var body = '<span class="spv-sys-row__name">' + escapeHtmlSPV(row.name || '') + '</span>';
    if (!isLight && !isEmitter) {
        var eye = row.targetable ? SPV_EYE_OPEN : SPV_EYE_SHUT;
        var eyeCls = row.targetable ? '' : ' spv-sys-row__eye--shut';
        var bar = (typeof row.condition_pct === 'number')
            ? '<span class="spv-sys-row__bar" style="--bar-pct:'
              + Math.max(0, Math.min(100, row.condition_pct)) + '%"></span>' : '';
        body += bar + '<span class="spv-sys-row__eye' + eyeCls + '"'
              +   ' title="' + (row.targetable ? 'Targetable' : 'Not targetable') + '">'
              +   eye + '</span>';
    }
    return '<div class="spv-sys-row' + (depth > 0 ? ' spv-sys-row--child' : '')
         + (chosen ? ' spv-sys-row--chosen' : '')
         + (row.dirty === true ? ' spv-sys-row--dirty' : '') + extra + '"' + indent
         + ' onclick="' + clickJs + '"'
         + ' oncontextmenu="' + menuJs + '">'
         + lead + body + '</div>';
}
