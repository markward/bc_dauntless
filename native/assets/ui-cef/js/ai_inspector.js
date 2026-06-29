// AI Inspector panel render fn. Driven by Python via cef_execute_javascript:
//   setAIInspector({visible:true, ships:[{ship_name, tree|null}, ...]});
//   setAIInspector({visible:false});
// The close affordance + ESC fire dauntlessEvent('ai-inspector/cancel').
// Node expand/collapse is UI-only (toggled in JS); it optionally notifies
// Python via dauntlessEvent('ai-inspector/expand:<id>' | 'collapse:<id>').
// Reuses the cp-* modal CSS (configuration_panel.css) for the chrome and
// adds AI-tree specifics in css/ai_inspector.css.
// Modeled on BC's AIActiveLogView.py socket monitor.

function escapeHtmlAI(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Status -> CSS modifier class for color coding.
function _aiStatusClass(status) {
    switch (status) {
        case 'ACTIVE':  return 'ai-status--active';
        case 'DONE':    return 'ai-status--done';
        case 'DORMANT': return 'ai-status--dormant';
        case 'INVALID': return 'ai-status--invalid';
        default:        return 'ai-status--other';
    }
}

function _aiNodeBadges(node) {
    let html = '';
    html += '<span class="ai-node__type">' + escapeHtmlAI(node.type) + '</span>';
    html += '<span class="ai-node__status ' + _aiStatusClass(node.status) + '">'
          + escapeHtmlAI(node.status) + '</span>';
    if (node.focus) html += '<span class="ai-node__focus">FOCUS</span>';
    if (typeof node.priority === 'number') {
        html += '<span class="ai-node__prio">p' + node.priority + '</span>';
    }
    if (node.active === true) html += '<span class="ai-node__active">&#9656;</span>';
    if (node.current === true) html += '<span class="ai-node__active">&#9656;</span>';
    return html;
}

function _aiLeafDetail(node) {
    let html = '';
    if (typeof node.script_module === 'string') {
        html += '<div class="ai-node__detail">script: '
              + escapeHtmlAI(node.script_module || '(none)');
        if (typeof node.next_update_time === 'number') {
            html += ' &middot; next: ' + node.next_update_time.toFixed(2);
        }
        html += '</div>';
    }
    if (typeof node.preprocessing_method === 'string'
            && node.preprocessing_method.length) {
        html += '<div class="ai-node__detail">preprocess: '
              + escapeHtmlAI(node.preprocessing_method) + '</div>';
    }
    if (Array.isArray(node.conditions)) {
        for (let i = 0; i < node.conditions.length; ++i) {
            const c = node.conditions[i];
            html += '<div class="ai-node__cond">cond: '
                  + escapeHtmlAI(c.name || '(unnamed)')
                  + ' = ' + escapeHtmlAI(String(c.status)) + '</div>';
        }
    }
    return html;
}

function _aiRenderNode(node) {
    if (!node) return '';
    let html = '<li class="ai-node">';
    html += '<div class="ai-node__row">';
    html += '<span class="ai-node__name">' + escapeHtmlAI(node.name || '(unnamed)') + '</span>';
    html += _aiNodeBadges(node);
    html += '</div>';
    html += _aiLeafDetail(node);

    const kids = [];
    if (Array.isArray(node.children)) {
        for (let i = 0; i < node.children.length; ++i) kids.push(node.children[i]);
    }
    if (node.contained) kids.push(node.contained);
    if (kids.length) {
        html += '<ul class="ai-tree">';
        for (let i = 0; i < kids.length; ++i) html += _aiRenderNode(kids[i]);
        html += '</ul>';
    }
    html += '</li>';
    return html;
}

function setAIInspector(state) {
    const root = document.getElementById('ai-inspector-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const body = document.getElementById('ai-inspector-body');
    if (body) {
        const ships = Array.isArray(state.ships) ? state.ships : [];
        if (!ships.length) {
            body.innerHTML = '<div class="ai-empty">No ships</div>';
        } else {
            let html = '';
            for (let i = 0; i < ships.length; ++i) {
                const s = ships[i];
                html += '<div class="ai-ship">';
                html += '<div class="ai-ship__name">'
                      + escapeHtmlAI(s.ship_name || '(unnamed)') + '</div>';
                if (s.tree) {
                    html += '<ul class="ai-tree ai-tree--root">'
                          + _aiRenderNode(s.tree) + '</ul>';
                } else {
                    html += '<div class="ai-ship__noai">(no AI)</div>';
                }
                html += '</div>';
            }
            body.innerHTML = html;
        }
    }
    root.style.display = 'flex';
}
