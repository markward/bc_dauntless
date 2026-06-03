// Mission picker render fn. Driven by Python via cef_execute_javascript:
//   setMissionPicker({tree: [...], visible: true});
//   setMissionPicker({visible: false});
// Tree node shape: {kind, label, children?, module?}.
//   kind === 'family' or 'episode' → collapsible row with .children
//   kind === 'mission' → actionable button with .module
// See docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md.

function escapeHtmlMP(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeJsLiteralMP(s) {
    // Embedded in onclick="dauntlessEvent('...')". Backslash-escape
    // single quotes and backslashes; HTML-escape the result.
    return escapeHtmlMP(String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

function renderMissionTreeMP(nodes, depth) {
    let html = '';
    for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        const indent = 'mp-indent-' + depth;
        if (n.kind === 'mission') {
            const mod = escapeJsLiteralMP(n.module);
            html += '<div class="mp-row mp-mission ' + indent + '"'
                  +   ' onclick="dauntlessEvent(\'mission-picker/pick:'
                  +     mod + '\')">'
                  +     escapeHtmlMP(n.label)
                  + '</div>';
        } else {
            // family or episode: collapsible group. We render it
            // collapsed by default; clicking the row toggles the
            // 'mp-expanded' class on this and its children container.
            const collapsibleId = 'mp-grp-' + depth + '-' + i + '-' + Math.random().toString(36).slice(2, 7);
            html += '<div class="mp-row mp-' + n.kind + ' ' + indent + '"'
                  +   ' onclick="document.getElementById(\'' + collapsibleId
                  +     '\').classList.toggle(\'mp-collapsed\')">'
                  +     '<span class="mp-caret">&#9656;</span>'
                  +     escapeHtmlMP(n.label)
                  + '</div>'
                  + '<div class="mp-children mp-collapsed" id="' + collapsibleId + '">'
                  +     renderMissionTreeMP(n.children || [], depth + 1)
                  + '</div>';
        }
    }
    return html;
}

function setMissionPicker(state) {
    const root = document.getElementById('mission-picker');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const body = document.getElementById('mission-picker-body');
    if (body) {
        body.innerHTML = renderMissionTreeMP(state.tree || [], 0);
    }
    root.style.display = 'flex';
}
