// native/assets/ui-cef/js/target_list.js
//
// Target-list render fn. Driven by Python via cef_execute_javascript:
//   setTargetList({visible, selected, selected_subsystem,
//                  filters: {FRIENDLY, NEUTRAL, ENEMY},
//                  sort: "name" | "distance" | "health",
//                  rows: [{name, label, affiliation, hull, shields,
//                          has_shields, dist_km, marker}, ...]});
//
// Rows arrive already filtered and in display order: the page never sorts
// or filters. `name` is the click/selection key (ship.GetName()) and never
// displayed; `label` is what's drawn (the ship's display name once
// identified, else the "Unknown N" placeholder).
//
// Event protocol (dauntlessEvent passes through PanelRegistry to
// TargetListView.dispatch_event):
//   target/<ship>                   - set target ship, clear sub-lock
//   target/__filter__/<AFF>         - toggle a FRIENDLY / NEUTRAL / ENEMY tab
//   target/__sort__/<mode>          - choose name / distance / health order
//
// Spec: docs/superpowers/specs/2026-11-05-target-list-and-target-panel-redesign-design.md

// ── Escape helpers ───────────────────────────────────────────────────────────
// Ship and subsystem names land here unsanitised — stock BC names are
// safe alphanumerics + space, but mods or localised strings could carry
// any character. We HTML-escape for text content and attribute values,
// and JS-escape for embedded single-quote string literals (the onclick
// attribute holds a JS expression like dauntlessEvent('NAME')).
const _HTML_ESCAPES = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;',
    '"': '&quot;', "'": '&#39;'
};
function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
        return _HTML_ESCAPES[c];
    });
}

// Escape for placement inside a single-quote JS string literal. Order
// matters: replace backslashes first so the subsequent escapes don't
// see their own escape sequences.
function escapeJsString(s) {
    return String(s == null ? '' : s)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'");
}

// Build the `onclick="..."` attribute body. The attribute boundary uses
// double-quotes; inside, the JS expression uses single-quote string
// literals. So the JS string first gets JS-escaped, then the whole
// attribute value gets HTML-escaped for the attribute boundary.
function clickAttr(action) {
    const jsLiteral = "'" + escapeJsString(action) + "'";
    return escapeHtml('dauntlessEvent(' + jsLiteral + ')');
}

function setTargetList(state) {
    const panel = document.getElementById('target-list-panel');
    if (!panel) return;
    if (!state || !state.visible) {
        panel.classList.add('target-list--hidden');
        return;
    }
    panel.classList.remove('target-list--hidden');

    const body = document.getElementById('target-list-body');
    if (!body) return;

    const rows = state.rows || [];
    const selected = state.selected || null;

    let html = '';
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const name = String(row.name || '');
        const label = String(row.label || row.name || '');
        const aff = String(row.affiliation || 'UNKNOWN');
        const chosen = (selected === name) ? ' target-list__row--chosen' : '';
        const clampPct = function (v) { return Math.max(0, Math.min(100, v)); };
        const hull = clampPct((typeof row.hull === 'number') ? row.hull : 100);
        const shields = clampPct((typeof row.shields === 'number') ? row.shields : 0);
        // Inert targets (asteroids) carry no real shields — omit the bar
        // entirely and let the hull bar occupy the far-right slot. Default to
        // showing the bar when the flag is absent (older payloads).
        const hasShields = (row.has_shields !== false);
        const nameHtml = escapeHtml(label);
        const targetAttr = clickAttr('target/' + name);

        // Marker (e.g. "protect"): inline shield in the row's text colour.
        // Only known kinds are emitted, so the class name is never raw input.
        // "target": a crosshair (ring + four ticks), same box and colour.
        const markerHtml = (row.marker === 'protect')
            ? '<span class="target-list__marker target-list__marker--' + row.marker + '">'
              + '<svg viewBox="0 0 10 12" width="1em" height="1.2em" fill="currentColor"'
              + ' aria-hidden="true"><path d="M5 0.5 L9.5 2 V6 C9.5 8.8 7.5 10.8 5 11.5'
              + ' C2.5 10.8 0.5 8.8 0.5 6 V2 Z"/></svg></span>'
            : (row.marker === 'target')
            ? '<span class="target-list__marker target-list__marker--target">'
              + '<svg viewBox="0 0 10 12" width="1em" height="1.2em" fill="none"'
              + ' stroke="currentColor" stroke-width="1" aria-hidden="true">'
              + '<circle cx="5" cy="6" r="3"/>'
              + '<path d="M5 0.5 V3 M5 9 V11.5 M0 6 H2 M8 6 H10"/></svg></span>'
            : '';
        const dist = (typeof row.dist_km === 'number') ? row.dist_km : 0;
        html += '<div class="target-list__row target-list__row--' + aff + chosen + '"'
              +   ' onclick="' + targetAttr + '">'
              +   markerHtml
              +   '<span class="target-list__name">' + nameHtml + '</span>'
              +   '<span class="target-list__dist">' + dist.toFixed(2) + ' km</span>'
              +   '<span class="target-list__bars">'
              +     '<span class="target-list__bar target-list__bar--hull"'
              +     ' style="--bar-pct:' + hull + '%"></span>'
              +     (hasShields
                     ? '<span class="target-list__bar target-list__bar--shields"'
                       + ' style="--bar-pct:' + shields + '%"></span>'
                     : '')
              +   '</span>'
              + '</div>';
    }
    body.innerHTML = html;

    // The strips are static markup: reflect the payload onto them. They are
    // drawn even with zero rows, so an emptied filter can be turned back on.
    const filters = state.filters || {};
    const tabEls = panel.querySelectorAll('.target-list__tab');
    for (let i = 0; i < tabEls.length; i++) {
        const t = tabEls[i];
        t.classList.toggle('target-list__tab--on',
                           filters[t.getAttribute('data-aff')] === true);
    }
    _targetListSort = state.sort || 'name';
    const sortEls = panel.querySelectorAll('.target-list__sort-opt');
    for (let i = 0; i < sortEls.length; i++) {
        const o = sortEls[i];
        const on = (o.getAttribute('data-sort') === _targetListSort);
        o.classList.toggle('target-list__sort-opt--on', on);
        o.setAttribute('aria-checked', on ? 'true' : 'false');
    }
}

// Last sort the payload reported; clicking it again is not an event.
var _targetListSort = 'name';

// Strip clicks, called with a click-like object ({target}); wired below.
function targetListTabClick(ev) {
    const b = ev && ev.target && ev.target.closest
        ? ev.target.closest('[data-aff]') : null;
    if (!b) return;
    dauntlessEvent('target/__filter__/' + b.getAttribute('data-aff'));
}

function targetListSortClick(ev) {
    const b = ev && ev.target && ev.target.closest
        ? ev.target.closest('[data-sort]') : null;
    if (!b) return;
    const mode = b.getAttribute('data-sort');
    if (mode === _targetListSort) return;
    dauntlessEvent('target/__sort__/' + mode);
}

(function wireTargetListStrips() {
    if (typeof document === 'undefined') return;
    const tabs = document.getElementById('target-list-tabs');
    const sort = document.getElementById('target-list-sort');
    if (tabs) tabs.addEventListener('click', targetListTabClick);
    if (sort) sort.addEventListener('click', targetListSortClick);
})();
