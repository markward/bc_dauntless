// Star map render fn. Driven by Python:
//   setStarMapPanel({visible, selected_system, here_system, course_system,
//                    mission_systems, labels, warp_points, warp_note});
// The 3D map itself is drawn by the NATIVE starmap pass beneath
// #star-map-viewport — this file draws only labels, the warp-point list and
// chrome. Keep #star-map-viewport transparent so the GL shows through.
// Clicking a warp-point row SETS THE COURSE via star-map/set-course:<id> and
// closes the popup; the player then engages the warp from the SDK Helm
// "Warp" button. Cancel/ESC fire star-map/cancel. A drag over the viewport
// orbits (star-map/orbit:<dx>,<dy>); a click without drag picks a star
// (star-map/pick:<x>,<y>); wheel zooms (star-map/zoom:<steps>). Rows with
// available:false are shown greyed and are not clickable.
//
// selected_system (merely clicked) and course_system (what the SDK warp
// button currently targets) are different states and must not share a
// class — sm-label--selected vs sm-label--course.
function escapeHtmlSM(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _smLabelClass(id, state) {
    if (id === state.here_system) return ' sm-label--here';
    if (id === state.course_system) return ' sm-label--course';
    if ((state.mission_systems || []).indexOf(id) !== -1) return ' sm-label--mission';
    if (id === state.selected_system) return ' sm-label--selected';
    return '';
}

function setStarMapPanel(state) {
    const root = document.getElementById('star-map-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const labelEl = document.getElementById('star-map-labels');
    if (labelEl) {
        labelEl.innerHTML = (state.labels || []).filter(function (l) {
            return l.visible;
        }).map(function (l) {
            return '<div class="sm-label' + _smLabelClass(l.id, state) + '"'
                + ' style="left:' + l.x + 'px;top:' + l.y + 'px">'
                + escapeHtmlSM(l.label) + '</div>';
        }).join('');
    }
    const warpEl = document.getElementById('star-map-warps');
    if (warpEl) {
        const note = state.warp_note
            ? '<li class="sc-note">' + escapeHtmlSM(state.warp_note) + '</li>'
            : '';
        warpEl.innerHTML = note + (state.warp_points || []).map(function (w) {
            const ok = (w.available !== false);
            const cls = 'sc-row' + (ok ? '' : ' sc-row--disabled');
            const click = ok
                ? ' onclick="dauntlessEvent(\'star-map/set-course:\' + this.getAttribute(\'data-id\'))"'
                : '';
            return '<li class="' + cls + '" data-id="' + escapeHtmlSM(w.id) + '"'
                + click + '>' + escapeHtmlSM(w.label) + '</li>';
        }).join('');
    }
    root.style.display = 'flex';
}

// Orbit / zoom / pick. A drag orbits; a click without drag picks a star.
(function () {
    let dragging = false, moved = false, lastX = 0, lastY = 0;
    document.addEventListener('DOMContentLoaded', function () {
        const vp = document.getElementById('star-map-viewport');
        if (!vp) return;
        vp.addEventListener('mousedown', function (e) {
            dragging = true; moved = false; lastX = e.clientX; lastY = e.clientY;
        });
        vp.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            const dx = e.clientX - lastX, dy = e.clientY - lastY;
            if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
            lastX = e.clientX; lastY = e.clientY;
            dauntlessEvent('star-map/orbit:' + (dx * 0.008) + ',' + (dy * 0.008));
        });
        vp.addEventListener('mouseup', function (e) {
            if (dragging && !moved) {
                dauntlessEvent('star-map/pick:' + e.clientX + ',' + e.clientY);
            }
            dragging = false;
        });
        vp.addEventListener('mouseleave', function () { dragging = false; });
        vp.addEventListener('wheel', function (e) {
            dauntlessEvent('star-map/zoom:' + (e.deltaY > 0 ? 1 : -1));
            e.preventDefault();
        });
    });
})();
