// Star map render fn. Driven by Python:
//   setStarMapPanel({visible, selected_system, here_system, course_system,
//                    mission_systems, labels, disc_labels, warp_points,
//                    warp_note});
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
    // Function scope, not inside the label block: the footer toggle below
    // reads it too, and a block-scoped const there is a ReferenceError that
    // takes setStarMapPanel — and with it the whole panel — down.
    const showAll = state.show_all_labels === true;
    const labelEl = document.getElementById('star-map-labels');
    if (labelEl) {
        // Nebula names FIRST, so the system labels that follow paint over
        // them: nebulae are scenery and must stay subordinate to the stars
        // (.sm-label--disc is smaller and dimmer — see star_map.css). Python
        // omits nameless discs, so there is never a blank label here.
        const discs = (state.disc_labels || []).filter(function (d) {
            return d.visible;
        }).map(function (d) {
            return '<div class="sm-label sm-label--disc"'
                + ' style="left:' + d.x + 'px;top:' + d.y + 'px">'
                + escapeHtmlSM(d.label) + '</div>';
        }).join('');
        // A system this mission offers no course to loses its NAME, not its
        // star: the map then reads as "where this mission will take you" at a
        // glance, while every dot stays pickable. `show_all_labels` restores
        // the rest, dimmed, for a player navigating on their own.
        labelEl.innerHTML = discs + (state.labels || []).filter(function (l) {
            return l.visible && (showAll || l.offered !== false);
        }).map(function (l) {
            // Python already exempts here/course/mission systems from the
            // offer test (star_map.build_scene), so `offered === false` here
            // never collides with a state class — the dot and its name dim
            // together or not at all.
            const cls = _smLabelClass(l.id, state);
            const inert = (l.offered === false) ? ' sm-label--inert' : '';
            return '<div class="sm-label' + cls + inert
                + '" style="left:' + l.x + 'px;top:' + l.y + 'px">'
                + escapeHtmlSM(l.label) + '</div>';
        }).join('');

        // You are here: a hovering arrow over the star, appended INSIDE the
        // label layer so it shares the labels' coordinate space — the payload
        // gives it the same projected position the name uses, so the two can
        // never drift apart. Absent when the player's set maps to no charted
        // system, or when the star is off screen.
        const hm = state.here_marker;
        if (hm && hm.visible) {
            labelEl.innerHTML += '<div class="sm-here-arrow" style="left:'
                + hm.x + 'px;top:' + hm.y + 'px"></div>';
        }
    }
    // Target popup: a centred card over the map, shown only while a system is
    // selected. Its visibility follows `targets_open`, which Python derives
    // from the selection itself — no second flag to fall out of step.
    // Warp: enabled only once a course is set. The label is the Helm menu's
    // own translated string, so the two buttons cannot drift apart.
    // NB: warpBtnEl, not warpEl — `warpEl` below is the warp-POINT list
    // (#star-map-warps). Two `const warpEl` in one function is a SyntaxError
    // that kills the whole file: setStarMapPanel never defines and the
    // DOMContentLoaded handlers never attach, so the panel loads with no
    // chrome and ignores the mouse.
    const warpBtnEl = document.getElementById('star-map-warp');
    if (warpBtnEl) {
        warpBtnEl.disabled = !state.warp_enabled;
        if (state.warp_label) warpBtnEl.textContent = String(state.warp_label);
    }

    // Offered only when something is actually withheld — a switch with
    // nothing on the other side is worse than no switch. It stays offered
    // while show-all is on, so the map can be put back.
    const showAllEl = document.getElementById('star-map-show-all');
    if (showAllEl) {
        showAllEl.style.display = state.has_hidden_labels ? '' : 'none';
        showAllEl.textContent = 'Show all: ' + (showAll ? 'Yes' : 'No');
        showAllEl.classList.toggle('sm-toggle--on', showAll);
    }

    const targetsEl = document.getElementById('star-map-targets');
    if (targetsEl) targetsEl.style.display = state.targets_open ? 'flex' : 'none';
    const titleEl = document.getElementById('star-map-targets-title');
    if (titleEl) titleEl.textContent = String(state.targets_title || '');

    const warpEl = document.getElementById('star-map-warps');
    if (warpEl) {
        const note = state.warp_note
            ? '<li class="sc-note">' + escapeHtmlSM(state.warp_note) + '</li>'
            : '';
        warpEl.innerHTML = note + (state.warp_points || []).map(function (w) {
            const ok = (w.available !== false);
            // `mission` is Python's call, not this file's: it owns the warp
            // button the mission wrote its destination to. Disabled wins,
            // because an unreachable row must not read as somewhere to go.
            const cls = 'sc-row' + (ok
                ? (w.mission ? ' sc-row--mission' : '')
                : ' sc-row--disabled');
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
    // The target popup is modal over the map. Python also drops orbit/zoom/
    // pick while it is open — this is the near side of the same rule, and it
    // stops the drag state machine latching on a press the map will never act
    // on (which would otherwise orbit the moment Back was pressed).
    function mapFrozen() {
        const t = document.getElementById('star-map-targets');
        return !!t && t.style.display !== 'none';
    }
    document.addEventListener('DOMContentLoaded', function () {
        const vp = document.getElementById('star-map-viewport');
        if (!vp) return;
        vp.addEventListener('mousedown', function (e) {
            if (mapFrozen()) return;
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
            if (!mapFrozen()) {
                dauntlessEvent('star-map/zoom:' + (e.deltaY > 0 ? 1 : -1));
            }
            e.preventDefault();
        });
    });
})();
