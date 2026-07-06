// Engineering Power-Transmission-Grid panel — faithful conduit-bandwidth axis.
// Driven by Python via cef_execute_javascript:
//   setEngineeringPower({visible, sliders, grid, batteries, tractor, cloak});
//   setEngineeringPower({visible:false});
// Slider drag: dauntlessEvent('engpower/set:<key>:<pct>')
// Toggle click: dauntlessEvent('engpower/toggle:tractor'|'engpower/toggle:cloak')
// Spec: docs/superpowers/specs/2026-07-06-power-panel-redesign-design.md
//
// Grid layout (faithful to PowerDisplay.py:734,681-689):
//   D = GetMaxMainConduitCapacity + GetBackupConduitCapacity  (~1400 Galaxy)
//   Four pieces, fractions of D, sum to 1.0, rendered left-to-right:
//     [warp_core][main][reserve][damage-hatch at right]
//   Used bar overlays the full width axis starting at left:0 — segments are
//   already true fractions of D, set directly as widths.
//   reserve_threshold (main_cond/D ≈ 0.8571) marks where used bar enters reserve.
//   No barsD re-normalisation — Python emits true full-width fractions.

var _epDragging = null;       // key of row currently being dragged
var _epRafPending = false;    // animation-frame throttle for drag events
var _epPendingEvent = null;   // event string queued for next rAF

// ── Siphon line ─────────────────────────────────────────────────────────────
// The .cline-on / .cline-off classes only swap solid-vs-dashed geometry; the
// colour must be set inline for BOTH states, or a class swap leaves the new
// state colourless (dashed → currentColor near-black; solid → transparent).
function _epSetLine(lineEl, present, active, colour, offColour) {
    if (!lineEl) return;
    if (!present) { lineEl.style.display = 'none'; return; }
    lineEl.style.display = '';
    if (active) {
        lineEl.className = 'cline-on';
        lineEl.style.background = colour;
        lineEl.style.boxShadow = '0 0 5px ' + colour;
        lineEl.style.borderColor = '';
    } else {
        lineEl.className = 'cline-off';
        lineEl.style.background = 'transparent';
        lineEl.style.boxShadow = 'none';
        lineEl.style.borderColor = offColour;
    }
}

// ── Drag handling ───────────────────────────────────────────────────────────

function _epFireDragEvent() {
    _epRafPending = false;
    if (_epPendingEvent) {
        dauntlessEvent(_epPendingEvent);
        _epPendingEvent = null;
    }
}

function _epOnPointerDown(e) {
    var track = e.currentTarget;
    var row = track.parentElement;
    var key = row ? row.getAttribute('data-key') : null;
    if (!key) return;
    track.setPointerCapture(e.pointerId);
    _epDragging = key;
    _epApplyDrag(track, key, e.clientX);
}

function _epOnPointerMove(e) {
    if (!_epDragging) return;
    var track = e.currentTarget;
    var key = track.parentElement ? track.parentElement.getAttribute('data-key') : null;
    if (key !== _epDragging) return;
    _epApplyDrag(track, key, e.clientX);
}

function _epOnPointerUp(e) {
    _epDragging = null;
}

function _epApplyDrag(track, key, clientX) {
    var rect = track.getBoundingClientRect();
    var w = rect.width;
    if (!w) return;
    // Position from the track's left edge, NOT e.offsetX — offsetX is relative
    // to the child under the pointer (thumb/mark sliver) and would jump to 0.
    var offsetX = clientX - rect.left;
    var raw = offsetX / w;                // 0..1 maps to 0..100% of track
    var pct = raw * 1.25;                 // track spans 0..125%
    pct = Math.max(0, Math.min(1.25, pct));
    pct = Math.round(pct / 0.05) * 0.05; // snap 0.05

    // Local echo: fill + thumb + label
    var fillPct = (pct / 1.25 * 100).toFixed(2) + '%';
    var fill  = document.getElementById('ep-fill-' + key);
    var thumb = document.getElementById('ep-thumb-' + key);
    var pctEl = document.getElementById('ep-pct-' + key);
    if (fill)  fill.style.width  = fillPct;
    if (thumb) thumb.style.left  = fillPct;
    if (pctEl) pctEl.textContent = Math.round(pct * 100) + '%';

    // Throttle to one event per animation frame
    _epPendingEvent = 'engpower/set:' + key + ':' + pct.toFixed(2);
    if (!_epRafPending) {
        _epRafPending = true;
        requestAnimationFrame(_epFireDragEvent);
    }
}

// ── Wire up drag listeners once the DOM is ready ────────────────────────────
(function _epWireDrag() {
    var keys = ['weapons', 'engines', 'sensors', 'shields'];
    for (var i = 0; i < keys.length; i++) {
        (function(key) {
            var track = document.getElementById('ep-track-' + key);
            if (!track) return;
            track.addEventListener('pointerdown', _epOnPointerDown);
            track.addEventListener('pointermove', _epOnPointerMove);
            track.addEventListener('pointerup',   _epOnPointerUp);
        })(keys[i]);
    }
})();

// ── Main update function ────────────────────────────────────────────────────

function setEngineeringPower(p) {
    var root = document.getElementById('engpower-root');
    if (!root) return;
    if (!p || p.visible !== true) {
        root.style.display = 'none';
        return;
    }
    root.style.display = '';

    // ── Sliders ──────────────────────────────────────────────────────────────
    var sliders = p.sliders || [];
    for (var i = 0; i < sliders.length; i++) {
        var sl  = sliders[i];
        var key = sl.key;
        // Skip the row being dragged (payload echo would fight the thumb)
        if (key === _epDragging) continue;
        var pct = sl.pct || 0;
        var row = document.getElementById('ep-row-' + key);
        if (row) {
            row.style.display = sl.present === false ? 'none' : '';
        }
        var fillPct = (pct / 1.25 * 100).toFixed(2) + '%';
        var fill  = document.getElementById('ep-fill-' + key);
        var thumb = document.getElementById('ep-thumb-' + key);
        var pctEl = document.getElementById('ep-pct-' + key);
        if (fill)  fill.style.width  = fillPct;
        if (thumb) thumb.style.left  = fillPct;
        if (pctEl) pctEl.textContent = Math.round(pct * 100) + '%';
    }

    // ── Grid (faithful conduit-bandwidth axis) ────────────────────────────────
    // Python emits true fractions of D (=MaxMain+Backup). Four pieces sum to 1.0:
    //   available.warp_core + available.main + available.reserve + damage = 1.0
    // Layout: [warp_core][main][reserve][damage-hatch] left-to-right.
    // Used bar starts at left:0; segment widths are already fractions of D.
    // No barsD re-normalisation needed.
    var grid = p.grid || {};
    var avail = grid.available || {};
    var wcFrac   = avail.warp_core || 0;
    var mnFrac   = avail.main      || 0;
    var rsFrac   = avail.reserve   || 0;
    var dmgFrac  = grid.damage     || 0;
    var rsThr    = grid.reserve_threshold || (wcFrac + mnFrac);  // fallback

    // Available bar: segments are fractions of full axis width (D), set directly.
    // Running offsets: warp_core starts at 0; main after warp_core; reserve after main.
    var wcPct = (wcFrac * 100).toFixed(2) + '%';
    var mnPct = (mnFrac * 100).toFixed(2) + '%';
    var rsPct = (rsFrac * 100).toFixed(2) + '%';
    var dmgPct = (dmgFrac * 100).toFixed(2) + '%';

    var wcEl  = document.getElementById('ep-avail-wc');
    var mnEl  = document.getElementById('ep-avail-mn');
    var rsEl  = document.getElementById('ep-avail-rs');
    var dmgEl = document.getElementById('ep-dmg-col');
    if (wcEl)  wcEl.style.width  = wcPct;
    if (mnEl)  mnEl.style.width  = mnPct;
    if (rsEl)  rsEl.style.width  = rsPct;
    // Damage hatch at the right: width = dmgFrac of full bar
    if (dmgEl) dmgEl.style.width = dmgPct;

    // Boundary ticks: warp/main boundary at wcFrac, main/reserve boundary at wcFrac+mnFrac.
    // These are positions on the full axis (0..1 → 0%..100% of the bars-col).
    var wcBoundaryPct  = (wcFrac * 100).toFixed(2) + '%';
    var mnBoundaryPct  = ((wcFrac + mnFrac) * 100).toFixed(2) + '%';
    var btickWc = document.getElementById('ep-btick-wc');
    var btickMn = document.getElementById('ep-btick-mn');
    if (btickWc) btickWc.style.left = 'calc(' + wcBoundaryPct  + ' - 1px)';
    if (btickMn) btickMn.style.left = 'calc(' + mnBoundaryPct  + ' - 1px)';

    // Label-row span widths — each label centred under its segment.
    // Widths are fractions of the full axis; fade label below 40 px.
    var totalWidth = 540 - 28; // approx bars-col px (panel 540px; approx padding)
    var lblWc = document.getElementById('ep-lbl-wc');
    var lblMn = document.getElementById('ep-lbl-mn');
    var lblRs = document.getElementById('ep-lbl-rs');
    if (lblWc) {
        var wcPx = wcFrac * totalWidth;
        lblWc.style.width   = wcPct;
        lblWc.style.opacity = wcPx < 40 ? '0' : '1';
    }
    if (lblMn) {
        var mnPx = mnFrac * totalWidth;
        lblMn.style.width   = mnPct;
        lblMn.style.opacity = mnPx < 40 ? '0' : '1';
    }
    if (lblRs) {
        var rsPx = rsFrac * totalWidth;
        lblRs.style.width   = rsPct;
        lblRs.style.opacity = rsPx < 40 ? '0' : '1';
    }

    // Used bar segments — fractions of D already; set widths directly (no barsD division).
    // Used bar starts at left:0 (full axis), so segments run left-to-right with no inset.
    var usedArr = grid.used || [];
    var usedMap = {};
    for (var j = 0; j < usedArr.length; j++) {
        usedMap[usedArr[j].key] = usedArr[j].frac || 0;
    }
    var usedKeys = ['weapons', 'engines', 'sensors', 'shields'];
    for (var k = 0; k < usedKeys.length; k++) {
        var uk = usedKeys[k];
        var uEl = document.getElementById('ep-used-' + uk);
        // Segment width = frac * 100% of full bar axis
        if (uEl) uEl.style.width = ((usedMap[uk] || 0) * 100).toFixed(2) + '%';
    }

    // Overload tint
    var usedBar = document.getElementById('ep-used-bar');
    if (usedBar) {
        if (grid.overload) {
            usedBar.classList.add('overload');
        } else {
            usedBar.classList.remove('overload');
        }
    }

    // ── Batteries ────────────────────────────────────────────────────────────
    var batts = p.batteries || {};
    _epUpdateBattery('main',    batts.main    || {});
    _epUpdateBattery('reserve', batts.reserve || {});

    // ── Tractor ──────────────────────────────────────────────────────────────
    var tractor = p.tractor || {};
    var tractorToggle = document.getElementById('ep-toggle-tractor');
    var tractorLine   = document.getElementById('ep-tractor-line');
    var tractorState  = document.getElementById('ep-tractor-state');
    if (tractorToggle) {
        tractorToggle.style.display = tractor.present ? '' : 'none';
    }
    _epSetLine(tractorLine, tractor.present, tractor.active,
               'rgb(180,157,64)', 'rgba(180,157,64,0.55)');
    if (tractorState) {
        if (tractor.active) {
            tractorState.textContent = 'On';
            tractorState.style.color = 'rgb(180,157,64)';
        } else {
            tractorState.textContent = 'Off';
            tractorState.style.color = '#666';
        }
    }

    // ── Cloak ────────────────────────────────────────────────────────────────
    var cloak = p.cloak || {};
    var cloakToggle = document.getElementById('ep-toggle-cloak');
    var cloakLine   = document.getElementById('ep-cloak-line');
    var cloakState  = document.getElementById('ep-cloak-state');
    if (cloakToggle) {
        cloakToggle.style.display = cloak.present ? '' : 'none';
    }
    _epSetLine(cloakLine, cloak.present, cloak.active,
               'rgb(208,87,42)', 'rgba(208,87,42,0.55)');
    if (cloakState) {
        if (cloak.active) {
            cloakState.textContent = 'On';
            cloakState.style.color = 'rgb(208,87,42)';
        } else {
            cloakState.textContent = 'Off';
            cloakState.style.color = '#666';
        }
    }
}

function _epUpdateBattery(name, batt) {
    var chargePct = Math.round((batt.charge || 0) * 100);
    var fillEl  = document.getElementById('ep-pfill-'  + name);
    var drainEl = document.getElementById('ep-pdrain-' + name);
    var pctEl   = document.getElementById('ep-ppct-'   + name);
    if (fillEl)  fillEl.style.height  = chargePct + '%';
    if (pctEl)   pctEl.textContent    = chargePct + '%';
    if (drainEl) {
        drainEl.style.display = batt.draining ? '' : 'none';
        // Sit just inside the fill's top surface (fill rises from the bottom,
        // so its top edge is at (100 - charge)% from the top of the column).
        drainEl.style.top = 'calc(' + (100 - chargePct) + '% + 2px)';
    }
}
