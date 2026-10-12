// Bridge Editor dev page (spec 2026-10-08-bridge-emitters §8, §13.3).
// Python pushes setBridgeEmitters(state); actions go back through
// dauntlessEvent('bridge-emitters/<action>'). The top-left bar is always
// shown while the editor is open (its presence IS editing mode); the dock
// shows only with a selection, as Object / Material tabs of collapsible
// stack entries. No <select> anywhere: CEF OSR draws no native popup.

function _beEsc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
}

// A value placed inside a single-quoted JS string in an onclick attribute:
// JS-escape first, then HTML-escape (the attribute decodes &#39; back to ').
function _beJs(s) {
    return _beEsc(String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

function _beChip(label, action, active, disabled) {
    return '<button class="be-chip' + (active ? ' active' : '') + '"'
        + ' onclick="dauntlessEvent(\'bridge-emitters/' + action + '\')"'
        + (disabled ? ' disabled' : '') + '>' + _beEsc(label) + '</button>';
}

function _beNumberRow(label, action, value, step) {
    return '<div class="be-row">'
        + '<label>' + _beEsc(label) + '</label>'
        + '<input type="number" step="' + (step || 0.01) + '" value="' + _beEsc(Number(value)) + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/' + action + ':\' + this.value)">'
        + '</div>';
}

const _BE_STATES = [['offline', '⬛'], ['green', '🟩'], ['yellow', '🟨'], ['red', '🟥'],
                    ['special', '🟦']];

function _beBar(state) {
    let html = '<span class="be-title">BRIDGE EDITOR</span><span class="be-sep">|</span>';
    _BE_STATES.forEach(function (p) {
        html += '<button class="be-state ' + p[0] + (state.state === p[0] ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/state:' + p[0] + '\')">' + p[1] + '</button>';
    });
    html += '<span class="be-sep">|</span>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/preview-toggle\')">'
        + (state.playing ? '⏸' : '▶') + '</button><span class="be-sep">|</span>'
        + '<button' + (state.can_undo ? '' : ' disabled')
        + ' onclick="dauntlessEvent(\'bridge-emitters/undo\')">Undo</button>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/revert\')">Revert</button>'
        + '<button' + (state.can_save ? '' : ' disabled')
        + ' onclick="dauntlessEvent(\'bridge-emitters/save\')">Save' + (state.dirty ? '*' : '')
        + '</button><span class="be-sep">|</span>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/close\')">✕</button>';
    return html;
}

// One stack entry: a header row (expand toggle, title, optional scope
// squares, optional ×) and, when expanded, its fields.
function _beEntry(id, title, expanded, scope, removeAction, fields) {
    let html = '<div class="be-entry"><div class="be-entry-head">'
        + '<button class="be-caret" onclick="dauntlessEvent(\'bridge-emitters/expand:' + id + '\')">'
        + (expanded ? '▾' : '▸') + '</button><span class="be-entry-title">' + _beEsc(title) + '</span>';
    if (scope) {
        _BE_STATES.forEach(function (p) {
            html += '<button class="be-scope ' + p[0] + (scope.list.indexOf(p[0]) >= 0 ? ' on' : '') + '"'
                + ' onclick="dauntlessEvent(\'bridge-emitters/' + scope.action + p[0] + '\')">'
                + p[1] + '</button>';
        });
    }
    if (removeAction)
        html += '<button onclick="dauntlessEvent(\'bridge-emitters/' + removeAction + '\')">×</button>';
    html += '</div>';
    if (expanded) html += '<div class="be-entry-body">' + fields + '</div>';
    return html + '</div>';
}

function _beUsers(n) {
    return 'used by ' + n + (n === 1 ? ' object' : ' objects');
}

// Each TGA is a material (Mark 2026-10-11): with no link an object uses its
// texture's material, so "unlink" is the chip naming that material.
function _beLibrary(s) {
    const unlinked = s.texture_material ? 'texture · ' + s.texture_material : 'none';
    let html = '<div class="be-list">' + _beChip(unlinked, 'material-link:', !s.linked, false);
    (s.library || []).forEach(function (m) {
        if (m.texture) return;              // the texture's own material: the first chip
        html += '<button class="be-chip' + (s.linked && m.name === s.material ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/material-link:' + _beJs(m.name) + '\')">'
            + _beEsc(m.name + ' — ' + _beUsers(m.used_by))
            + '</button>';
    });
    html += '</div><div class="be-row">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/material-new\')">New</button>';
    if (s.material || s.texture_material)
        html += '<button onclick="dauntlessEvent(\'bridge-emitters/material-duplicate\')">Duplicate</button>';
    return html + '</div>';
}

// Add Light (spec §16.4): one menu, like Add Modifier. A spot is placed
// where you clicked; a strip or panel is cut from the object's front.
let _beAddLightOpen = false;

const _BE_LIGHTS = [
    ['spot', 'Spot', 'A cone from a point: placed where you clicked'],
    ['strip', 'Strip', 'A line of light along one edge of the object'],
    ['panel', 'Panel', 'The object\'s front, or part of it, as a soft light']];

function _beToggleAddLight() {
    _beAddLightOpen = !_beAddLightOpen;
    if (_beLast) setBridgeEmitters(_beLast);
}

function _beAddLight() {
    let html = '<div class="be-add"><button class="be-add-button" onclick="_beToggleAddLight()">'
        + 'Add Light ' + (_beAddLightOpen ? '▴' : '▾') + '</button>';
    if (_beAddLightOpen) {
        html += '<div class="be-menu">';
        _BE_LIGHTS.forEach(function (m) {
            html += '<button class="be-menu-item" onclick="_beAddLightOpen = false; '
                + 'dauntlessEvent(\'bridge-emitters/light-add:' + m[0] + '\')">'
                + '<span class="be-menu-name">' + m[1] + '</span>'
                + '<span class="be-menu-help">' + m[2] + '</span></button>';
        });
        html += '</div>';
    }
    return html + '</div>';
}

const _BE_EDGES = [['top', 'Top'], ['bottom', 'Bottom'], ['left', 'Left'], ['right', 'Right']];

function _beLightFields(l, i) {
    const a = 'light:' + i + ':';
    const shape = l.shape || 'spot';
    const tail = _beNumberRow('range', a + 'range', l.range, 0.1)
        + _beNumberRow('intensity', a + 'intensity', l.intensity, shape === 'spot' ? 1 : 0.1);
    if (shape === 'strip') {
        let edges = '<div class="be-row"><label>edge</label><div class="be-list">';
        _BE_EDGES.forEach(function (e) {
            edges += _beChip(e[1], a + 'edge:' + e[0], (l.edge || 'top') === e[0], false);
        });
        return edges + '</div></div>'
            + _beSlider('start', a + 'start', l.start === undefined ? 0 : l.start, 1, 1)
            + _beSlider('end', a + 'end', l.end === undefined ? 1 : l.end, 1, 1)
            + _beNumberRow('offset', a + 'offset', l.offset || 0, 0.1) + tail;
    }
    if (shape === 'panel') {
        const x = l.x || [0, 1], y = l.y || [0, 1];
        return _beSlider('x from', a + 'x0', x[0], 1, 1) + _beSlider('x to', a + 'x1', x[1], 1, 1)
            + _beSlider('y from', a + 'y0', y[0], 1, 1) + _beSlider('y to', a + 'y1', y[1], 1, 1)
            + _beNumberRow('offset', a + 'offset', l.offset || 0, 0.1) + tail;
    }
    return '<div class="be-row">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/light-place:' + i + '\')">Place here</button>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/light-aim:' + i + '\')">Aim where I\'m looking</button>'
        + '</div>'
        // HALF-angles from the axis; CEF OSR shows no tooltips, so say so.
        + _beNumberRow('inner half-angle°', a + 'inner_deg', l.inner_deg, 0.1)
        + _beNumberRow('outer half-angle°', a + 'outer_deg', l.outer_deg, 0.1) + tail;
}

function _beObjectTab(s) {
    const open = function (id) { return (s.expanded || []).indexOf(id) >= 0; };
    const title = s.linked ? s.material
        : (s.texture_material ? s.texture_material + ' (texture)' : 'none');
    // The library is long (one material per TGA): collapsed until its caret opens it.
    let html = _beEntry('material', 'Material: ' + title, open('material'), null, null,
                        _beLibrary(s));
    if (!s.material && s.has_emission_map) {
        const stem = String((s.textures || [''])[0]).replace(/\.[^.]*$/, '');
        html += '<div class="be-help">Emission map · ' + _beEsc(stem) + '_emissive · steady</div>';
    }
    (s.lights || []).forEach(function (l, i) {
        const shape = l.shape || 'spot';
        const title = 'Light ' + (i + 1)
            + (shape === 'spot' ? '' : ' · ' + shape.charAt(0).toUpperCase() + shape.slice(1));
        html += _beEntry('light:' + i, title, open('light:' + i), null,
                         'light-remove:' + i, _beLightFields(l, i));
    });
    html += _beAddLight();
    return html;
}

// Slider rows show the slider and its value; the pencil swaps in a typed
// number box (Mark 2026-10-12), remembered per action across refreshes.
let _beTyping = {};
let _beLast = null;

function _beToggleType(action) {
    if (_beTyping[action]) delete _beTyping[action];
    else _beTyping[action] = true;
    if (_beLast) setBridgeEmitters(_beLast);
}

// One slider row. `top` is the slider's end (typing may go past it, to
// what Python clamps); `max` caps the typed box when set; `extra` follows
// (source label, ×); a disabled row (a map wins) has no pencil.
function _beSlider(label, action, value, top, max, extra, disabled) {
    const v = Number(value);
    const commit = ' onchange="dauntlessEvent(\'bridge-emitters/' + action + ':\' + this.value)"';
    let html = '<div class="be-row"><label>' + _beEsc(label) + '</label>';
    if (_beTyping[action] && !disabled) {
        html += '<input type="number" min="0"' + (max !== null ? ' max="' + max + '"' : '')
            + ' step="0.01" value="' + v.toFixed(2) + '" class="be-typed"' + commit + '>';
    } else {
        html += '<input type="range" min="0" max="' + top + '" step="0.01" value="'
            + Math.min(v, top).toFixed(2) + '"' + (disabled ? ' disabled' : '') + commit + '>'
            + '<span class="be-value">' + v.toFixed(2) + '</span>';
    }
    if (!disabled)
        html += '<button class="be-pencil" onclick="_beToggleType(\'' + action + '\')">✎</button>';
    return html + (extra || '') + '</div>';
}

// Emission's slider runs 0-4 (typing goes higher) and stays editable over a
// map: the map says what glows, the level how much (spec §14).
function _beFinishRow(ch, f) {
    const emission = ch === 'emission';
    // Source and × share one fixed-width tail, × tight against the word.
    const extra = '<span class="be-tail"><span class="be-source">' + _beEsc(f.source) + '</span>'
        + (f.source === 'material'
            ? '<button class="be-clear" onclick="dauntlessEvent(\'bridge-emitters/finish-clear:'
              + ch + '\')">×</button>'
            : '') + '</span>';
    return _beSlider(ch, 'finish:' + ch, f.value, emission ? 4 : 1, emission ? null : 1, extra,
                     f.source === 'map' && !emission);
}

const _BE_SOURCES = [['texture', 'own texture'], ['flat', 'flat colour']];

function _beModifier(m, i, expanded) {
    let fields = '';
    if (m.type === 'state') {
        const lv = Number(m.level);
        fields = '<div class="be-row"><canvas id="be-wheel-' + i + '" width="120" height="120"></canvas>'
            + '<div id="be-swatch-' + i + '" class="be-swatch"></div></div>'
            + _beSlider('level', 'mod:' + i + ':level', lv, 4, null, '', false);
    } else if (m.type === 'transition') {
        fields = _beNumberRow('seconds', 'mod:' + i + ':seconds', m.seconds, 0.05);
    } else {
        fields = '<div class="be-row"><label>shape</label>'
            + _beChip('sine', 'mod:' + i + ':shape:sine', m.shape === 'sine', false)
            + _beChip('square', 'mod:' + i + ':shape:square', m.shape === 'square', false) + '</div>'
            + _beNumberRow('period s', 'mod:' + i + ':period_s', m.period_s, 0.05)
            + _beNumberRow('min', 'mod:' + i + ':min', m.min || 0, 0.05)
            + _beNumberRow('phase', 'mod:' + i + ':phase', m.phase || 0, 0.05);
        if (m.shape === 'square') {
            fields += _beNumberRow('duty', 'mod:' + i + ':duty', m.duty === undefined ? 0.5 : m.duty, 0.05)
                + _beNumberRow('soft', 'mod:' + i + ':soft', m.soft || 0, 0.05);
        }
    }
    const title = m.type === 'state' ? 'State'
        : m.type === 'transition' ? 'Transition (' + Number(m.seconds) + ' s)'
        : 'Animation (' + m.shape + ')';
    return _beEntry('mod:' + i, title, expanded,
                    {list: m.scope || [], action: 'mod:' + i + ':scope:'},
                    'mod-remove:' + i, fields);
}

// Blender-style "Add Modifier" menu (Mark 2026-10-12), drawn in the page:
// CEF OSR draws no popup for a <select>. Open/closed is page-side state.
let _beAddOpen = false;

const _BE_MODIFIERS = [
    ['state', 'State', 'Replaces the emission in the ticked states'],
    ['animation', 'Animation', 'Pulses the glow (sine or square)'],
    ['transition', 'Transition', 'Blend time into the ticked states']];

function _beToggleAdd() {
    _beAddOpen = !_beAddOpen;
    if (_beLast) setBridgeEmitters(_beLast);
}

function _beAddModifier() {
    let html = '<div class="be-add"><button class="be-add-button" onclick="_beToggleAdd()">'
        + 'Add Modifier ' + (_beAddOpen ? '▴' : '▾') + '</button>';
    if (_beAddOpen) {
        html += '<div class="be-menu">';
        _BE_MODIFIERS.forEach(function (m) {
            html += '<button class="be-menu-item" onclick="_beAddOpen = false; '
                + 'dauntlessEvent(\'bridge-emitters/mod-add:' + m[0] + '\')">'
                + '<span class="be-menu-name">' + m[1] + '</span>'
                + '<span class="be-menu-help">' + m[2] + '</span></button>';
        });
        html += '</div>';
    }
    return html + '</div>';
}

function _beMaterialTab(s) {
    const m = s.material_data;
    if (!m) {
        return '<div class="be-help">No material. New makes one for this object; adding a '
            + 'modifier makes one too.</div><div class="be-row">'
            + '<button onclick="dauntlessEvent(\'bridge-emitters/material-new\')">New</button></div>'
            + _beAddModifier();
    }
    const open = function (id) { return (s.expanded || []).indexOf(id) >= 0; };
    // Commits on `change` (Enter blurs via text_capture) and on the button.
    let html = '<div class="be-row"><input type="text" id="be-rename" value="' + _beEsc(m.name) + '"'
        + ' style="width:150px" onchange="dauntlessEvent(\'bridge-emitters/material-rename:\' + this.value)">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/material-rename:\' + '
        + 'document.getElementById(\'be-rename\').value)">Rename</button>'
        + '<span class="be-source">' + _beEsc((m.kind === 'texture' ? 'texture material · ' : '')
                                            + _beUsers(m.used_by || 0)) + '</span></div>';
    // Finish is fixed and open by default: toggling its header collapses it
    // (modifiers and lights start collapsed). Emission is a Finish row (Mark
    // 2026-10-12); the texture decides what glows -- its `_emissive` map when
    // it has one (shown, not chosen), else own texture or a flat colour.
    const stem = String((s.textures || [''])[0]).replace(/\.[^.]*$/, '');
    let fin = _beFinishRow('roughness', m.finish.roughness)
        + _beFinishRow('metalness', m.finish.metalness)
        + _beFinishRow('emission', m.finish.emission);
    if (s.has_emission_map) {
        fin += '<div class="be-help">source: emission map · ' + _beEsc(stem) + '_emissive</div>';
    } else {
        fin += '<div class="be-row"><label>glows</label>';
        _BE_SOURCES.forEach(function (p) {
            fin += _beChip(p[1], 'emission-source:' + p[0], m.emission_source === p[0], false);
        });
        fin += '</div>';
    }
    html += _beEntry('finish', 'Finish', !open('finish'), null, null, fin);
    (m.modifiers || []).forEach(function (mod, i) {
        html += _beModifier(mod, i, open('mod:' + i));
    });
    return html + _beAddModifier();
}

function _beDockHtml(state) {
    const s = state.selected;
    let html = '<div class="be-row"><label>Object</label><span>'
        + _beEsc(s.display_name || s.name) + '</span></div>'
        + '<div class="be-row"><label>Block</label><span>' + _beEsc(s.block) + '</span></div>'
        + '<div class="be-row"><label>Textures</label><span>'
        + _beEsc((s.textures || []).join(', ') || '—') + '</span></div>'
        + '<div class="be-chain">' + _beEsc((s.node_chain || []).join(' › ')) + '</div>'
        + '<div class="be-tabs">'
        + _beChip('Object', 'tab:object', s.tab === 'object', false)
        + _beChip('Material', 'tab:material', s.tab === 'material', false) + '</div>';
    return html + (s.tab === 'material' ? _beMaterialTab(s) : _beObjectTab(s));
}

// One wheel per expanded State modifier. A drag commits once, on release (one undo
// step); the swatch follows live. A dragging wheel blocks rebuilds.
var _beWheels = [];
function _beMountWheels(state) {
    _beWheels = [];
    const s = state.selected;
    if (!s || !s.material_data || typeof ColourWheel === 'undefined') return;
    (s.material_data.modifiers || []).forEach(function (m, i) {
        const canvas = document.getElementById('be-wheel-' + i);
        if (!canvas || !canvas.getContext || m.type !== 'state') return;
        const swatch = document.getElementById('be-swatch-' + i);
        const paint = function (rgb) {
            if (swatch) swatch.style.background = 'rgb(' + rgb.map(function (c) {
                return Math.round(Math.max(0, Math.min(1, c)) * 255);
            }).join(',') + ')';
        };
        paint(m.tint);
        _beWheels.push(new ColourWheel(canvas, colourRgbToHs(m.tint), function (hs, final) {
            const rgb = colourHsToRgb(hs.hue, hs.sat);
            paint(rgb);
            if (final) dauntlessEvent('bridge-emitters/mod:' + i + ':tint:'
                + rgb.map(function (c) { return c.toFixed(4); }).join(','));
        }));
    });
}

// The dock is rebuilt from the payload -- but never while the user is typing
// in a field inside it (every hover change sends a payload, and a rebuild
// destroys the focused field mid-edit), nor while a colour wheel is dragging.
function _beEditingInDock(root) {
    if (_beWheels.some(function (w) { return w.dragging; })) return true;
    const a = document.activeElement;
    if (!a || !root.contains || !root.contains(a)) return false;
    if (a.tagName === 'TEXTAREA' || a.isContentEditable) return true;
    return a.tagName === 'INPUT' && a.type !== 'range' && a.type !== 'checkbox'
        && a.type !== 'button';
}

// Bridge Settings (Mark 2026-10-12): a cog at the bottom right opens the
// bridge-level settings -- the room light per state. Python owns open/closed
// (it needs the click region); rows reuse the slider + pencil rows.
const _BE_STATE_NAMES = {offline: 'Power offline', green: 'Green', yellow: 'Yellow',
                         red: 'Red', special: 'Special'};

function _beSettingsHtml(st) {
    st = st || {};
    let html = '';
    if (st.open) {
        html += '<div class="be-settings-panel"><div class="be-entry-title">Bridge Settings</div>'
            + '<div class="be-entry"><div class="be-entry-head"><span class="be-entry-title">'
            + 'Room light</span></div><div class="be-help">'
            + (st.has_lights
                ? 'This bridge has its own lights, so the room light defaults to 0.'
                : 'No lights of its own: the engine default per state.')
            + '</div>';
        (st.room_light || []).forEach(function (r) {
            const tail = '<span class="be-tail"><span class="be-source">' + _beEsc(r.source) + '</span>'
                + (r.source === 'bridge'
                    ? '<button class="be-clear" onclick="dauntlessEvent(\'bridge-emitters/room-clear:'
                      + r.state + '\')">×</button>'
                    : '') + '</span>';
            html += _beSlider(_BE_STATE_NAMES[r.state] || r.state, 'room:' + r.state, r.value,
                              2, 4, tail, false);
        });
        html += '</div></div>';
    }
    return html + '<button class="be-cog' + (st.open ? ' active' : '') + '"'
        + ' onclick="dauntlessEvent(\'bridge-emitters/settings-toggle\')">⚙</button>';
}

function setBridgeEmitters(state) {
    const root = document.getElementById('bridge-emitters-root');
    if (!root) return;
    _beLast = state;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        _beWheels = [];          // a hidden panel holds no drag
        return;
    }
    const bar = document.getElementById('be-bar');
    if (bar) bar.innerHTML = _beBar(state);
    const hint = document.getElementById('be-hint');
    if (hint) hint.textContent = state.in_bridge === false
        ? 'Close this, press Space to go to the bridge, then reopen Bridge Editor.'
        : (state.hint || '');
    const hover = document.getElementById('be-hover');
    if (hover) hover.textContent = state.hover || '';
    const status = document.getElementById('be-status');
    if (status) status.textContent = state.status || '';
    const dock = document.getElementById('be-dock');
    if (dock) dock.style.display = state.selected ? 'flex' : 'none';
    root.className = state.selected ? 'dev-only be-has-dock' : 'dev-only';
    const settings = document.getElementById('be-settings');
    if (settings && !_beEditingInDock(root)) settings.innerHTML = _beSettingsHtml(state.settings);
    const body = document.getElementById('bridge-emitters-body');
    if (body && state.selected && !_beEditingInDock(root)) {
        body.innerHTML = _beDockHtml(state);
        _beMountWheels(state);
    }
    root.style.display = 'block';
}
