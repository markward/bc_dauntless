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

    // ── Grid (faithful conduit-bandwidth axis; damage on the LEFT) ────────────
    // Python emits true fractions of D (=MaxMain+Backup). Four pieces sum to 1.0:
    //   available.warp_core + available.main + available.reserve + damage = 1.0
    // The damage hatch is the LEFT column (flex-basis = damage). bars-col holds
    // the remaining (1 - damage); its band + used widths re-normalise to barsD
    // so they fill bars-col. The reserve-threshold reading survives because the
    // (1-damage) factor cancels in "used_total vs warp_core+main".
    var grid = p.grid || {};
    var avail = grid.available || {};
    var wcFrac   = avail.warp_core || 0;
    var mnFrac   = avail.main      || 0;
    var rsFrac   = avail.reserve   || 0;
    var dmgFrac  = grid.damage     || 0;

    // Damage column: left flex-basis of the full grid width.
    var dmgEl = document.getElementById('ep-dmg-col');
    if (dmgEl) dmgEl.style.flexBasis = (dmgFrac * 100).toFixed(2) + '%';

    // Re-normalise the band/used widths into bars-col (= 1 - damage of full).
    var barsD = 1 - dmgFrac;
    if (barsD <= 0) barsD = 1;
    var wcN = wcFrac / barsD, mnN = mnFrac / barsD, rsN = rsFrac / barsD;
    var wcPct = (wcN * 100).toFixed(2) + '%';
    var mnPct = (mnN * 100).toFixed(2) + '%';
    var rsPct = (rsN * 100).toFixed(2) + '%';

    var wcEl  = document.getElementById('ep-avail-wc');
    var mnEl  = document.getElementById('ep-avail-mn');
    var rsEl  = document.getElementById('ep-avail-rs');
    if (wcEl)  wcEl.style.width  = wcPct;
    if (mnEl)  mnEl.style.width  = mnPct;
    if (rsEl)  rsEl.style.width  = rsPct;

    // Boundary ticks: positions within bars-col (already normalised).
    var wcBoundaryPct  = (wcN * 100).toFixed(2) + '%';
    var mnBoundaryPct  = ((wcN + mnN) * 100).toFixed(2) + '%';
    var btickWc = document.getElementById('ep-btick-wc');
    var btickMn = document.getElementById('ep-btick-mn');
    if (btickWc) btickWc.style.left = 'calc(' + wcBoundaryPct  + ' - 1px)';
    if (btickMn) btickMn.style.left = 'calc(' + mnBoundaryPct  + ' - 1px)';

    // Label-row span widths — each label centred under its segment (of bars-col).
    var totalWidth = (540 - 28) * barsD; // approx bars-col px after the damage inset
    var lblWc = document.getElementById('ep-lbl-wc');
    var lblMn = document.getElementById('ep-lbl-mn');
    var lblRs = document.getElementById('ep-lbl-rs');
    if (lblWc) {
        lblWc.style.width   = wcPct;
        lblWc.style.opacity = (wcN * totalWidth) < 40 ? '0' : '1';
    }
    if (lblMn) {
        lblMn.style.width   = mnPct;
        lblMn.style.opacity = (mnN * totalWidth) < 40 ? '0' : '1';
    }
    if (lblRs) {
        lblRs.style.width   = rsPct;
        lblRs.style.opacity = (rsN * totalWidth) < 40 ? '0' : '1';
    }

    // Used bar segments — re-normalised into bars-col (same barsD as the bands),
    // so "used bar crosses the main→reserve boundary" reads correctly under damage.
    var usedArr = grid.used || [];
    var usedMap = {};
    for (var j = 0; j < usedArr.length; j++) {
        usedMap[usedArr[j].key] = usedArr[j].frac || 0;
    }
    var usedKeys = ['weapons', 'engines', 'sensors', 'shields'];
    for (var k = 0; k < usedKeys.length; k++) {
        var uk = usedKeys[k];
        var uEl = document.getElementById('ep-used-' + uk);
        if (uEl) uEl.style.width = ((usedMap[uk] || 0) / barsD * 100).toFixed(2) + '%';
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
