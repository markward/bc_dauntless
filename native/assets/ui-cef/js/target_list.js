// native/assets/ui-cef/js/target_list.js
//
// Target-list render fn. Driven by Python via cef_execute_javascript:
//   setTargetList({visible, selected, selected_subsystem,
//                  rows: [{name, affiliation, hull, shields,
//                          subsystems: [...], expanded}, ...]});
//
// Event protocol (dauntlessEvent passes through PanelRegistry to
// TargetListView.dispatch_event):
//   target/<ship>                   — set target ship, clear sub-lock
//   target/<ship>/<subsystem>       — set target + subsystem
//   target/<ship>/__toggle__        — toggle accordion expansion
//
// Spec: docs/ui_designs/02-tactical-cluster.md

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
    const selectedSub = state.selected_subsystem || null;

    let html = '';
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const name = String(row.name || '');
        const aff = String(row.affiliation || 'UNKNOWN');
        const chosen = (selected === name) ? ' target-list__row--chosen' : '';
        const expanded = !!row.expanded;
        const expandedCls = expanded ? ' target-list__row--expanded' : '';
        const hull = (typeof row.hull === 'number') ? row.hull : 100;
        const shields = (typeof row.shields === 'number') ? row.shields : 0;
        const nameHtml = escapeHtml(name);
        const toggleAttr = clickAttr('target/' + name + '/__toggle__');
        const targetAttr = clickAttr('target/' + name);

        // Ship row — flat structure: caret with its own onclick
        // (event.stopPropagation prevents the row's onclick from
        // firing too); name + bars sit as direct flex children of
        // the row and inherit the row's set-target onclick.
        //
        // Caret glyph swaps between ▸ (collapsed) and ▾ (expanded)
        // instead of CSS-rotating. CSS rotation promotes the caret
        // to its own GPU layer in CEF, which reduces text crispness
        // of the surrounding row.
        const caretGlyph = expanded ? '&#9662;' : '&#9656;';  // ▾ / ▸
        html += '<div class="target-list__row target-list__row--' + aff + chosen + expandedCls + '"'
              +   ' onclick="' + targetAttr + '">'
              +   '<span class="target-list__caret"'
              +   ' onclick="event.stopPropagation();' + toggleAttr + '">' + caretGlyph + '</span>'
              +   '<span class="target-list__name">' + nameHtml + '</span>'
              +   '<span class="target-list__bars">'
              +     '<span class="target-list__bar target-list__bar--hull"'
              +     ' style="--bar-pct:' + hull + '%"></span>'
              +     '<span class="target-list__bar target-list__bar--shields"'
              +     ' style="--bar-pct:' + shields + '%"></span>'
              +   '</span>'
              + '</div>';

        // Subsystem child rows — only emitted when this row is expanded.
        // Collapsed rows hide their subsystem children entirely.
        // Aggregator subsystems (those with children) get a caret toggle;
        // leaf-only subsystems get a bullet. When a subsystem is itself
        // expanded, its nested leaf rows (banks / tubes / pods / etc.)
        // are emitted directly after it at a deeper indent level.
        if (expanded) {
            const subs = row.subsystems || [];
            for (let j = 0; j < subs.length; j++) {
                const sub = subs[j];
                const subName = String(sub.name || '');
                const subCondition = (typeof sub.condition === 'number') ? sub.condition : 100;
                const subExpanded = !!sub.expanded;
                const subChildren = sub.children || [];
                const hasChildren = subChildren.length > 0;
                const subChosen = (selected === name && selectedSub === subName)
                    ? ' target-list__sub--chosen' : '';
                const subAttr = clickAttr('target/' + name + '/' + subName);
                const subToggleAttr = clickAttr('target/' + name + '/' + subName + '/__toggle__');
                const subCaret = hasChildren
                    ? '<span class="target-list__sub-caret"'
                      + ' onclick="event.stopPropagation();' + subToggleAttr + '">'
                      + (subExpanded ? '&#9662;' : '&#9656;') + '</span>'
                    : '<span class="target-list__sub-bullet">&#8226;</span>';
                html += '<div class="target-list__sub target-list__sub--' + aff + subChosen + '"'
                      +   ' onclick="' + subAttr + '">'
                      +   subCaret
                      +   '<span class="target-list__sub-name">' + escapeHtml(subName) + '</span>'
                      +   '<span class="target-list__sub-bar"'
                      +   ' style="--bar-pct:' + subCondition + '%"></span>'
                      + '</div>';

                // Nested leaf rows (banks / tubes / pods / nacelles / emitters).
                if (subExpanded && hasChildren) {
                    for (let k = 0; k < subChildren.length; k++) {
                        const leaf = subChildren[k];
                        const leafName = String(leaf.name || '');
                        const leafCond = (typeof leaf.condition === 'number') ? leaf.condition : 100;
                        const leafChosen = (selected === name && selectedSub === leafName)
                            ? ' target-list__leaf--chosen' : '';
                        const leafAttr = clickAttr('target/' + name + '/' + leafName);
                        html += '<div class="target-list__leaf target-list__leaf--' + aff + leafChosen + '"'
                              +   ' onclick="' + leafAttr + '">'
                              +   '<span class="target-list__leaf-bullet">&#8226;</span>'
                              +   '<span class="target-list__leaf-name">' + escapeHtml(leafName) + '</span>'
                              +   '<span class="target-list__leaf-bar"'
                              +   ' style="--bar-pct:' + leafCond + '%"></span>'
                              + '</div>';
                    }
                }
            }
        }
    }
    body.innerHTML = html;
}
