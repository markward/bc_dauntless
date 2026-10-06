// Star map render fn. Driven by Python:
//   setStarMapPanel({visible, selected_system, here_system, course_system,
//                    mission_systems, labels, disc_labels, info, ...});
// The 3D map itself is drawn by the NATIVE starmap pass beneath
// #star-map-viewport — this file draws only labels, the info panel and
// chrome. Keep #star-map-viewport transparent so the GL shows through.
// Cancel/ESC fire star-map/cancel. A drag over the viewport orbits
// (star-map/orbit:<dx>,<dy>); a click without drag picks a star
// (star-map/pick:<x>,<y>), which moves the info panel to it; a double-click
// sets course to that star's outermost region (star-map/pick-course:<x>,<y>);
// wheel zooms (star-map/zoom:<steps>). The magnifier at the map's
// bottom-left opens a search: star-map/search:<query>, results in
// search_results, a pick fires star-map/select-system:<id>.
//
// The info panel lists its system's destinations (warp_points), each with a
// crosshair button that sets the course: star-map/set-course:<id>. The map
// window stays open so the plotted course shows; Warp then engages it.
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
        starMapCloseSearch();
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
    // Warp: enabled only once a course is set. The label is the Helm menu's
    // own translated string, so the two buttons cannot drift apart.
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

    // Wide layout's left panel. Rendered at every width — the stylesheet
    // alone decides whether it is visible. textContent throughout: the
    // description is authored prose and must not inject markup.
    const info = state.info || null;
    const infoText = function (id, text) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = String(text || '');
            el.style.display = text ? '' : 'none';
        }
    };
    infoText('star-map-info-name', info ? info.name : 'Uncharted space');
    infoText('star-map-info-summary', info ? info.summary : '');
    infoText('star-map-info-detail', info ? info.detail : '');
    const hereEl = document.getElementById('star-map-info-here');
    if (hereEl) hereEl.style.display = (info && info.is_here) ? '' : 'none';
    renderStarMapRegions(info ? (state.warp_points || []) : [],
                         info ? state.warp_note : '');
    renderStarMapSearch(state.search_results || []);

    root.style.display = 'flex';
}

// A target crosshair: ring, centre dot and four ticks. currentColor, so the
// row's state classes tint it.
const SM_CROSSHAIR_SVG =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    + '<circle cx="8" cy="8" r="4.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    + '<circle cx="8" cy="8" r="1.2" fill="currentColor"/>'
    + '<path d="M8 0.5v3M8 12.5v3M0.5 8h3M12.5 8h3" stroke="currentColor" stroke-width="1.4"/>'
    + '</svg>';

// The objective marker: a small diamond, drawn as SVG rather than a rotated
// box (a CSS rotate promotes a GPU layer in CEF and blurs nearby text).
const SM_OBJECTIVE_SVG =
    '<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">'
    + '<path d="M5 0.5L9.5 5L5 9.5L0.5 5Z" fill="currentColor"/></svg>';

// The info panel's destination list. Built with DOM calls, not innerHTML,
// for the labels: they are mission-supplied strings. Only the fixed SVG
// above goes in as markup.
function renderStarMapRegions(rows, note) {
    const list = document.getElementById('star-map-info-regions');
    const head = document.getElementById('star-map-info-regions-head');
    const noteEl = document.getElementById('star-map-info-note');
    if (noteEl) {
        noteEl.textContent = String(note || '');
        noteEl.style.display = note ? '' : 'none';
    }
    if (head) head.style.display = rows.length ? '' : 'none';
    if (!list) return;
    list.textContent = '';
    rows.forEach(function (w) {
        const ok = (w.available !== false);
        const li = document.createElement('li');
        // Disabled wins over mission: an unreachable row must not read as
        // somewhere to go.
        li.className = 'sm-region'
            + (ok ? (w.mission ? ' sm-region--mission' : '') : ' sm-region--disabled')
            + (w.course ? ' sm-region--course' : '');
        const label = document.createElement('span');
        label.className = 'sm-region__label';
        label.textContent = String(w.label);
        li.appendChild(label);
        // Mission objective: a marker just left of the crosshair.
        if (w.objective) {
            const mark = document.createElement('span');
            mark.className = 'sm-region__objective';
            mark.innerHTML = SM_OBJECTIVE_SVG;
            li.appendChild(mark);
        }
        if (ok) {
            const btn = document.createElement('button');
            btn.className = 'sm-region__course';
            btn.innerHTML = SM_CROSSHAIR_SVG;
            const id = String(w.id);
            btn.onclick = function () {
                dauntlessEvent('star-map/set-course:' + id);
            };
            li.appendChild(btn);
        }
        list.appendChild(li);
    });
}

// ── Search (bottom-left of the map) ────────────────────────────────────
const SM_SEARCH_SVG =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    + '<circle cx="6.5" cy="6.5" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    + '<path d="M10 10l4.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    + '</svg>';

function starMapSearchOpen() {
    const box = document.getElementById('star-map-search');
    return !!box && box.classList.contains('sm-search--open');
}

function starMapCloseSearch() {
    const box = document.getElementById('star-map-search');
    const input = document.getElementById('star-map-search-input');
    if (!box || !starMapSearchOpen()) return;
    box.classList.remove('sm-search--open');
    if (input) {
        input.value = '';
        input.blur();
    }
    dauntlessEvent('star-map/search:');
}

function starMapToggleSearch() {
    const box = document.getElementById('star-map-search');
    const input = document.getElementById('star-map-search-input');
    if (!box) return;
    if (starMapSearchOpen()) {
        starMapCloseSearch();
        return;
    }
    box.classList.add('sm-search--open');
    if (input) input.focus();
}

function starMapPickSearchResult(systemId) {
    dauntlessEvent('star-map/select-system:' + systemId);
    starMapCloseSearch();
}

// Results sit ABOVE the field (the box is anchored to the map's bottom
// edge). DOM calls, not innerHTML: names come from data files and mods.
function renderStarMapSearch(results) {
    const list = document.getElementById('star-map-search-results');
    if (!list) return;
    list.textContent = '';
    if (!starMapSearchOpen()) return;
    results.forEach(function (r) {
        const li = document.createElement('li');
        li.className = 'sm-search__result';
        const name = document.createElement('span');
        name.className = 'sm-search__name';
        name.textContent = String(r.name);
        li.appendChild(name);
        if (r.via) {
            const via = document.createElement('span');
            via.className = 'sm-search__via';
            via.textContent = String(r.via);
            li.appendChild(via);
        }
        const id = String(r.system);
        li.onclick = function () { starMapPickSearchResult(id); };
        list.appendChild(li);
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const toggle = document.getElementById('star-map-search-toggle');
    if (toggle) toggle.innerHTML = SM_SEARCH_SVG;
    const input = document.getElementById('star-map-search-input');
    if (!input) return;
    input.addEventListener('input', function () {
        dauntlessEvent('star-map/search:' + encodeURIComponent(input.value));
    });
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            const first = document.querySelector('#star-map-search-results li');
            if (first) first.click();
            e.preventDefault();
        } else if (e.key === 'Escape') {
            starMapCloseSearch();
            e.preventDefault();
        }
    });
});

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
        // Double-click a star: set course to its outermost region. The two
        // single clicks before it have already picked (selected) the star.
        vp.addEventListener('dblclick', function (e) {
            if (moved) return;
            dauntlessEvent('star-map/pick-course:' + e.clientX + ',' + e.clientY);
        });
        vp.addEventListener('wheel', function (e) {
            dauntlessEvent('star-map/zoom:' + (e.deltaY > 0 ? 1 : -1));
            e.preventDefault();
        });
    });
})();
