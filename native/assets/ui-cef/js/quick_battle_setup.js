// Quick Battle Setup -- a port of the approved design spike
// (.claude/worktrees/qb-setup-spike/spikes/quickbattle-setup/app.js),
// spec 2026-10-02-quickbattle-setup-screen-design §3.
//
// Python (engine/ui/quick_battle_setup_panel.py) owns every piece of state and
// pushes two payloads:
//   setQuickBattleCatalog(payload)  ships, scale maxima, era/role/species and
//                                   Details tables
//   setQuickBattleSetup(payload)    groups, target, selection, draft, confirm,
//                                   filters, presets, summary, can_start
// This page renders the latest of each and reports every click as
// dauntlessEvent('quick-battle-setup/<verb>'). It owns only the open popover
// menu and which group is being renamed.
//
// Off-screen CEF: no drag-and-drop, no native select dropdowns, no tooltips.
// Text fields follow the keyboard-capture contract (text_capture.js): the
// section carries data-panel, a field commits on its DOM 'change' event, and
// Esc reverts then blurs (no change, so nothing is sent).

var QBS = {
    catalog: null,       // latest setQuickBattleCatalog payload
    setup: null,         // latest setQuickBattleSetup payload (open)
    ships: {},           // lower-cased ship id -> catalog ship
    eras: {},            // era id -> {id, name, tag, start, end}
    renaming: null,      // group id whose name is being edited (page-owned)
    presetAsk: null,     // {kind: 'save'|'load', name} awaiting its toast
    toastTimer: null,
    saveSent: false,     // the open save form has already sent preset-save
    saveCancelled: false, // the open save form was abandoned by a click away
};

// ── helpers ───────────────────────────────────────────────────────────────
// HTML-escape any catalog or scenario string (mod titles are untrusted).
function qbsEsc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

function qbsEnc(s) { return encodeURIComponent(s == null ? '' : s); }

function qbsEl(id) { return document.getElementById(id); }

function qbsShip(id) { return QBS.ships[String(id || '').toLowerCase()] || null; }

function qbsGroup(gid) {
    var gs = (QBS.setup && QBS.setup.groups) || [];
    for (var i = 0; i < gs.length; i++) if (gs[i].id === gid) return gs[i];
    return null;
}

function qbsPlayerShipId() {
    var gs = (QBS.setup && QBS.setup.groups) || [];
    for (var i = 0; i < gs.length; i++) {
        for (var j = 0; j < gs[i].entries.length; j++) {
            if (gs[i].entries[j].player) return gs[i].entries[j].ship;
        }
    }
    return null;
}

function qbsEraIndex(id) {
    var es = (QBS.catalog && QBS.catalog.eras) || [];
    for (var i = 0; i < es.length; i++) if (es[i].id === id) return i;
    return -1;
}

function qbsEraVisible(ship) {
    if (ship.era === 'all') return true;
    if (!ship.era || ship.era.length !== 2) return false;
    var lo = qbsEraIndex(ship.era[0]), hi = qbsEraIndex(ship.era[1]);
    var on = (QBS.setup && QBS.setup.eras) || [];
    for (var i = 0; i < on.length; i++) {
        var k = qbsEraIndex(on[i]);
        if (k >= lo && k <= hi) return true;
    }
    return false;
}

// "(2367–2399)" -- only when more than one era is selected; never for "all".
function qbsBracket(ship) {
    if (!ship || ((QBS.setup && QBS.setup.eras) || []).length < 2 || ship.era === 'all') return '';
    var a = QBS.eras[ship.era[0]], b = QBS.eras[ship.era[1]];
    if (!a || !b) return '';
    return ' (' + a.start + '–' + b.end + ')';
}

function qbsEraLabel(ship) {
    if (ship.era === 'all') return 'All eras';
    var a = QBS.eras[ship.era[0]], b = QBS.eras[ship.era[1]];
    if (!a || !b) return '';
    return a === b ? a.name + ' · ' + a.tag : a.name + ' → ' + b.name;
}

function qbsNoArt(cls) {
    return '<div class="qbs-noart ' + (cls || '') + '">No art</div>';
}

// `src` is a data: URL (ship icons) or a file:// URL (insignias).
function qbsArt(src, cls) {
    if (!src) return qbsNoArt(cls);
    return '<img src="' + qbsEsc(src) + '" alt="" ' +
           'onerror="this.outerHTML=\'<div class=&quot;qbs-noart&quot;>No art</div>\'">';
}

function qbsSpeciesArt(sp) {
    if (sp.insignia) return '<img class="qbs-insignia" src="' + qbsEsc(sp.insignia) + '" alt="">';
    return qbsArt(sp.flagship_icon);
}

// Python accepts set-player only when can_be_player(ce, None) holds: the
// class default's playable flag, else the ship's own.
function qbsCanBePlayer(ship) {
    var v0 = ship.variants && ship.variants[0];
    if (v0 && v0.playable != null) return !!v0.playable;
    return !!ship.playable;
}

function qbsAllegianceColour(a) {
    return { friendly: 'var(--qbs-friendly)', enemy: 'var(--qbs-enemy)',
             neutral: 'var(--qbs-neutral)' }[a] || 'var(--qbs-steel)';
}

// BC bios: prose, then "Weapons:/Special:" lines (Python strips the Shield and
// Hull Rating lines), then an optional "Tactics:" paragraph.
function qbsParseBio(raw) {
    var prose = [], stats = [], tactics = [], inTactics = false;
    String(raw || '').split('\n').forEach(function (l) {
        var line = l.trim();
        if (!line) return;
        if (/^Tactics:/.test(line)) { inTactics = true; return; }
        var m = line.match(/^(Weapons|Shield Rating|Hull Rating|Special):\s*(.*)$/);
        if (inTactics) tactics.push(line);
        else if (m) stats.push([m[1], m[2]]);
        else prose.push(line);
    });
    return { prose: prose.join(' ') || 'No description available.', stats: stats,
             tactics: tactics.join(' ') };
}

// ── render: groups column ─────────────────────────────────────────────────
function renderGroups() {
    var s = QBS.setup;
    var h = '<div class="qbs-section">Groups</div>';
    s.groups.forEach(function (g) { h += renderGroup(g); });
    h += '<button class="cp-done-button qbs-newgroup" data-action="group-new">+ New group</button>';
    qbsEl('qbs-groups').innerHTML = h;
    var inp = document.querySelector('#quick-battle-setup .qbs-rename');
    if (inp) {
        inp.addEventListener('change', qbsRenameChange);
        inp.addEventListener('blur', qbsRenameBlur);
        inp.focus();
        inp.select();
    }
}

function renderGroup(g) {
    var s = QBS.setup;
    var isTarget = g.id === s.target;
    var cls = 'qbs-group qbs-group--' + qbsEsc(g.allegiance) + (isTarget ? ' qbs-group--target' : '');
    var h = '<div class="' + cls + '" data-group="' + qbsEsc(g.id) + '">';

    h += '<div class="qbs-group__head">';
    if (QBS.renaming === g.id) {
        h += '<input class="qbs-rename" data-group="' + qbsEsc(g.id) + '" value="' + qbsEsc(g.name) + '">';
    } else {
        h += '<span class="qbs-group__name">' + qbsEsc(g.name) + '</span>';
        if (isTarget) h += '<span class="qbs-group__target-tag">Adding here</span>';
    }
    h += '<button class="qbs-kebab" data-action="group-menu" data-group="' + qbsEsc(g.id) + '">⋮</button></div>';

    h += '<div class="qbs-group__summary">' + qbsEsc(g.summary) + '</div>';

    // Details (⋮ → Details) SWAPS the ship list for the form. Choices edit
    // Python's draft; Update applies it, Cancel drops it.
    var draft = s.draft && s.draft.group === g.id ? s.draft : null;
    if (draft) h += renderDetails(g, draft);
    else {
        h += '<div class="qbs-rows">';
        if (!g.entries.length) {
            h += '<div class="qbs-empty">No ships yet' + (isTarget ? ' — add from the catalog' : '') + '</div>';
        }
        g.entries.forEach(function (e) { h += renderRow(g, e); });
        h += '</div>';
    }
    return h + '</div>';
}

// The player group's escorts form up beside the player, so its Details carry
// only Difficulty.
function renderDetails(g, draft) {
    var c = QBS.catalog || {};
    var h = '<div class="qbs-group__controls">';
    if (!g.player) {
        h += '<div class="qbs-ctl-label">Allegiance</div>' + qbsSeg('allegiance', c.allegiances, draft.allegiance);
        h += '<div class="qbs-ctl-label">Direction</div>' + qbsSeg('direction', c.directions, draft.direction);
        h += '<div class="qbs-ctl-label">Distance</div>' + qbsSeg('distance', c.distances, draft.distance,
            function (d) { return d.label + ' ' + d.km + ' km'; });
    }
    h += '<div class="qbs-ctl-label">Difficulty</div>' + qbsSeg('difficulty', c.difficulties, draft.difficulty);
    h += '<div class="qbs-form-actions">' +
         '<button class="cp-done-button" data-action="draft-cancel">Cancel</button>' +
         '<button class="cp-done-button qbs-add" data-action="draft-update">Update</button></div>';
    return h + '</div>';
}

function qbsSeg(field, rows, current, label) {
    var h = '<div class="cp-segmented">';
    (rows || []).forEach(function (r) {
        h += '<button class="cp-toggle' + (r.id === current ? ' cp-toggle--on' : '') + '" data-action="draft" ' +
             'data-arg="' + qbsEsc(field + ':' + r.id) + '">' +
             qbsEsc(label ? label(r) : r.label) + '</button>';
    });
    return h + '</div>';
}

function renderRow(g, e) {
    var ship = qbsShip(e.ship);
    var sub = '';
    if (e.variant) sub = '<div class="qbs-row__sub qbs-row__sub--chosen">' + qbsEsc(e.variant_label) + '</div>';
    else if (e.variant_label) sub = '<div class="qbs-row__sub">' + qbsEsc(e.variant_label) + '</div>';
    // Out-of-era ships are allowed (an "out of time" fight) but flagged.
    var oot = e.out_of_era ? '<span class="qbs-oot">Out of era</span>' : '';
    return '<div class="qbs-row">' + qbsArt(ship && ship.icon) +
        '<div class="qbs-row__text"><div class="qbs-row__title">' + qbsEsc(e.title + qbsBracket(ship)) + oot + '</div>' + sub + '</div>' +
        (e.player ? '<span class="qbs-you">YOU</span>' : '') +
        (e.has_menu ? '<button class="qbs-kebab" data-action="row-menu" data-group="' + qbsEsc(g.id) +
                      '" data-entry="' + qbsEsc(e.id) + '">⋮</button>' : '') +
        '</div>';
}

// ── render: era pills ─────────────────────────────────────────────────────
function renderEras() {
    var on = QBS.setup.eras || [], h = '';
    ((QBS.catalog && QBS.catalog.eras) || []).forEach(function (e) {
        h += '<button class="cp-toggle' + (on.indexOf(e.id) >= 0 ? ' cp-toggle--on' : '') + '" data-action="era" data-arg="' + qbsEsc(e.id) + '">' +
             qbsEsc(e.tag) + '<span class="qbs-era-years">' + qbsEsc(e.start) + '–' + qbsEsc(e.end) + '</span></button>';
    });
    qbsEl('qbs-eras').innerHTML = h;
}

// ── render: species pills (second filter row) ─────────────────────────────
// The count is entries visible under the CURRENT era pills (Python counts).
function renderSpecies() {
    var on = QBS.setup.species || [], counts = QBS.setup.counts || {}, h = '';
    ((QBS.catalog && QBS.catalog.species) || []).forEach(function (sp) {
        var n = counts[sp.name] || 0;
        h += '<button class="cp-toggle qbs-species-pill' + (on.indexOf(sp.name) >= 0 ? ' cp-toggle--on' : '') +
             (n ? '' : ' qbs-species-pill--empty') + '" data-action="species" data-arg="' + qbsEsc(sp.name) + '">' +
             '<span class="qbs-species-pill__art">' + qbsSpeciesArt(sp) + '</span>' + qbsEsc(sp.name) +
             '<span class="qbs-era-years">' + n + '</span></button>';
    });
    qbsEl('qbs-species').innerHTML = h;
}

// ── render: catalog -- role sections ──────────────────────────────────────
function renderCatalog() {
    var body = qbsEl('qbs-catalog'), c = QBS.catalog, s = QBS.setup;
    if (!c) { body.innerHTML = ''; return; }
    var species = s.species || [];
    var shown = c.ships.filter(function (sh) {
        return qbsEraVisible(sh) && species.indexOf(sh.species) >= 0;
    });
    if (!species.length) {
        body.innerHTML = '<div class="qbs-nothing">Choose one or more species above.</div>';
        return;
    }
    if (!shown.length) {
        body.innerHTML = '<div class="qbs-nothing">Nothing matches the selected eras and species.</div>';
        return;
    }
    // Role sections only; within a role, ships keep species order (the pill
    // row's order), then catalog order.
    var rank = {};
    c.species.forEach(function (sp, i) { rank[sp.name] = i; });
    var h = '';
    c.roles.forEach(function (role) {
        var ships = shown.map(function (sh, i) { return [sh, i]; })
            .filter(function (p) { return p[0].role === role.id; })
            .sort(function (a, b) { return (rank[a[0].species] - rank[b[0].species]) || (a[1] - b[1]); })
            .map(function (p) { return p[0]; });
        if (!ships.length) return;
        h += '<div class="qbs-role"><div class="qbs-section">' + qbsEsc(role.label) + '</div><div class="qbs-card-grid">';
        ships.forEach(function (sh) {
            var br = qbsBracket(sh);
            h += '<div class="qbs-card' + (sh.id === s.selected ? ' qbs-card--selected' : '') + '" data-action="select" data-arg="' + qbsEsc(sh.id) + '">' +
                 qbsArt(sh.icon) +
                 '<div class="qbs-card__name">' + qbsEsc(sh.title) + '</div>' +
                 (br ? '<div class="qbs-card__years">' + qbsEsc(br.trim()) + '</div>' : '') + '</div>';
        });
        h += '</div></div>';
    });
    body.innerHTML = h;
}

// ── render: the ship detail sheet ─────────────────────────────────────────
function renderDetail(sh) {
    var s = QBS.setup, bio = qbsParseBio(sh.bio), target = qbsGroup(s.target);
    var isPlayer = String(qbsPlayerShipId() || '').toLowerCase() === String(sh.id).toLowerCase();
    var role = '';
    (QBS.catalog.roles || []).forEach(function (r) { if (r.id === sh.role) role = r.label; });
    var h = '<div class="qbs-detail"><div class="qbs-detail__art">' + qbsArt(sh.icon) + '</div><div class="qbs-detail__body">';
    h += '<div class="qbs-detail__title">' + qbsEsc(sh.title + qbsBracket(sh)) + '</div>';
    h += '<div class="qbs-chips"><span class="qbs-chip">' + qbsEsc(role || sh.role) + '</span>' +
         '<span class="qbs-chip">' + qbsEsc(qbsEraLabel(sh)) + '</span>' +
         '<span class="qbs-chip' + (sh.playable ? '' : ' qbs-chip--muted') + '">' + (sh.playable ? 'Playable' : 'Not playable') + '</span>' +
         (sh.variants.length ? '<span class="qbs-chip">' + sh.variants.length + ' named ships</span>' : '') + '</div>';
    h += '<p class="qbs-bio">' + qbsEsc(bio.prose) + '</p>';
    // BC's text ratings for shields/hull don't match the game's values, so
    // they are replaced by scale bars; Weapons and Special stay as text.
    var textStats = bio.stats.filter(function (kv) { return kv[0] !== 'Shield Rating' && kv[0] !== 'Hull Rating'; });
    if (textStats.length) {
        h += '<dl class="qbs-stats">';
        textStats.forEach(function (kv) { h += '<dt>' + qbsEsc(kv[0]) + '</dt><dd>' + qbsEsc(kv[1]) + '</dd>'; });
        h += '</dl>';
    }
    h += renderDurability(sh);
    if (bio.tactics) h += '<p class="qbs-tactics"><b>Tactics</b> — ' + qbsEsc(bio.tactics) + '</p>';
    h += '<div class="qbs-actions">';
    h += '<button class="cp-done-button qbs-add" data-action="add" data-arg="' + qbsEsc(sh.id) + '"' + (target ? '' : ' disabled') + '>+ Add to ' +
         qbsEsc(target ? target.name : 'a group') + '</button>';
    if (isPlayer) {
        h += '<button class="cp-done-button" disabled>Your ship</button>';
    } else if (qbsCanBePlayer(sh)) {
        h += '<button class="cp-done-button" data-action="set-player" data-arg="' + qbsEsc(sh.id) + '">Set as player ship</button>';
    }
    return h + '</div></div></div>';
}

// 100% is the strongest PLAYABLE ship (Python's maxima). Anything stronger is
// capped at 100%, drawn gold and tagged off scale; a non-zero value never
// draws thinner than 1.5%.
function qbsScaleBar(label, value, max) {
    max = Math.max(1, max || 0);
    var off = value > max;
    var pct = value <= 0 ? 0 : Math.max(1.5, Math.min(100, value / max * 100));
    return '<div class="qbs-bar-row"><span class="qbs-bar-label">' + qbsEsc(label) + '</span>' +
        '<span class="qbs-bar' + (off ? ' qbs-bar--off' : '') + '"><span class="qbs-bar__fill" style="width:' + pct.toFixed(1) + '%"></span></span>' +
        '<span class="qbs-bar-value">' + (value > 0 ? Math.round(value).toLocaleString('en-GB') : 'None') +
        (off ? ' <span class="qbs-bar-off">off scale</span>' : '') + '</span></div>';
}

function renderDurability(sh) {
    if (sh.hull == null) return '<p class="qbs-tactics">No hardpoint data for this entry.</p>';
    return '<div class="qbs-durability">' +
           qbsScaleBar('Hull', sh.hull || 0, QBS.catalog.hull_max) +
           qbsScaleBar('Shields', sh.shields || 0, QBS.catalog.shield_max) + '</div>';
}

// The sheet keeps its last content while it slides closed.
function renderSheet() {
    var sheet = qbsEl('qbs-sheet'), sel = QBS.setup.selected;
    var sh = sel && QBS.catalog ? qbsShip(sel) : null;
    if (sh) {
        sheet.innerHTML = '<button class="qbs-kebab qbs-sheet__close" data-action="select" data-arg="' + qbsEsc(sh.id) +
                          '" aria-label="Close">×</button>' + renderDetail(sh);
        sheet.classList.add('qbs-sheet--open');
    } else {
        sheet.classList.remove('qbs-sheet--open');
    }
}

// ── render: footer ────────────────────────────────────────────────────────
function renderFooter() {
    var s = QBS.setup;
    qbsEl('qbs-preset-btn').textContent = (s.preset ? 'Preset: ' + s.preset : 'Load preset') + ' ▾';
    qbsEl('qbs-summary').textContent = s.summary || '';
    qbsEl('qbs-start').disabled = s.can_start !== true;
}

// ── render: the confirmation overlay (setup.confirm) ──────────────────────
// The body bolds the subject's name, as the spike's "Overwrite preset?" does.
// Python splits the sentence around the name (before/name/after), so the bold
// lands where the sentence names it. Everything is escaped; only the <b> is
// markup.
function renderConfirm() {
    var overlay = qbsEl('qbs-overlay'), c = QBS.setup.confirm;
    if (!c) { overlay.hidden = true; overlay.innerHTML = ''; return; }
    var bodyHtml = qbsEsc(c.before) + '<b>' + qbsEsc(c.name) + '</b>' + qbsEsc(c.after);
    overlay.innerHTML = '<div class="cp-modal qbs-confirm"><div class="cp-header">' + qbsEsc(c.title) + '</div>' +
        '<div class="cp-body"><p class="qbs-bio">' + bodyHtml + '</p></div>' +
        '<div class="cp-footer qbs-confirm__actions"><button class="cp-done-button" data-action="cancel">Cancel</button>' +
        '<button class="cp-done-button qbs-add" data-action="confirm">' + qbsEsc(c.ok) + '</button></div></div>';
    overlay.hidden = false;
}

// ── toast ─────────────────────────────────────────────────────────────────
function toast(text) {
    var t = qbsEl('qbs-toast');
    t.textContent = text;
    t.hidden = false;
    clearTimeout(QBS.toastTimer);
    QBS.toastTimer = setTimeout(function () { t.hidden = true; }, 2200);
}

// A preset save or load (possibly after a confirmation) shows as a change
// between pushes: the current preset becomes the asked-for name, the preset
// list changes, or the setup stops being dirty under that name.
function qbsPresetToast(prev, next) {
    var ask = QBS.presetAsk;
    if (!ask || !prev || next.confirm || next.preset !== ask.name) return;
    var changed = prev.preset !== next.preset ||
        JSON.stringify(prev.presets) !== JSON.stringify(next.presets) ||
        (prev.dirty && !next.dirty);
    if (!changed) return;
    QBS.presetAsk = null;
    toast((ask.kind === 'save' ? 'Saved preset "' : 'Loaded preset "') + ask.name + '"');
}

// ── popover menus (page-local; OSR CEF draws no native popups) ────────────
// `up`: always open above the anchor (footer menus would otherwise drop
// below the modal).
function qbsOpenMenu(anchor, html, up) {
    var menu = qbsEl('qbs-menu');
    menu.innerHTML = html;
    menu.hidden = false;
    var r = anchor.getBoundingClientRect(), m = menu.getBoundingClientRect();
    // Right-align to the anchor, unless the anchor sits in the left half of
    // the screen (the footer preset buttons): then left-align so the popover
    // stays over the modal instead of hanging off its left edge.
    var left = r.left < window.innerWidth / 2 ? r.left : r.right - m.width, top = r.bottom + 2;
    if (up || top + m.height > window.innerHeight - 8) top = r.top - m.height - 2;
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = Math.max(8, top) + 'px';
}

function qbsMenuOpen() { var m = qbsEl('qbs-menu'); return !!m && !m.hidden; }

// A field still focused inside the menu is ABANDONED (reverted, then blurred
// so text_capture releases the keyboard): never remove a focused field.
function qbsCloseMenu() {
    var m = qbsEl('qbs-menu');
    if (!m) return;
    qbsAbandonFocusIn(m);
    m.hidden = true;
    m.innerHTML = '';
}

function qbsAbandonFocusIn(container) {
    var ae = document.activeElement;
    if (!ae || !container.contains(ae) || ae === container) return;
    if (window.__dauntlessTextCancel) window.__dauntlessTextCancel(ae);
    else ae.blur();
}

function qbsItem(label, action, arg, extra) {
    return '<div class="qbs-menu__item' + (extra || '') + '" data-action="' + action + '" data-arg="' +
           qbsEsc(arg) + '">' + label + '</div>';
}

function qbsRowMenu(anchor, gid, eid) {
    var g = qbsGroup(gid), e = null;
    if (!g) return;
    g.entries.forEach(function (x) { if (x.id === eid) e = x; });
    if (!e) return;
    var sh = qbsShip(e.ship), variants = (sh && sh.variants) || [], h = '';
    if (variants.length) {
        // The player's row offers only names Python lets the player fly.
        var ok = function (v) { return !e.player || v.playable !== false; };
        h += '<div class="qbs-menu__head">Named ship</div>';
        if (ok(variants[0])) {
            h += qbsItem('<span class="qbs-menu__check">' + (e.variant ? '' : '✓') + '</span>Class default — ' + qbsEsc(variants[0].name),
                         'variant', eid + ':', e.variant ? '' : ' qbs-menu__item--on');
        }
        variants.slice(1).forEach(function (v) {
            if (!ok(v)) return;
            var on = e.variant === v.name;
            h += qbsItem('<span class="qbs-menu__check">' + (on ? '✓' : '') + '</span>' + qbsEsc(v.name),
                         'variant', eid + ':' + qbsEnc(v.name), on ? ' qbs-menu__item--on' : '');
        });
    }
    if (!e.player) {
        var others = QBS.setup.groups.filter(function (x) { return x.id !== gid; });
        if (others.length) {
            if (h) h += '<div class="qbs-menu__sep"></div>';
            h += '<div class="qbs-menu__head">Move to</div>';
            others.forEach(function (o) {
                h += qbsItem('<span class="qbs-menu__dot" style="background:' + qbsAllegianceColour(o.allegiance) + '"></span>' + qbsEsc(o.name),
                             'move', eid + ':' + o.id);
            });
        }
        if (h) h += '<div class="qbs-menu__sep"></div>';
        h += qbsItem('Remove', 'remove', eid, ' qbs-menu__item--danger');
    }
    if (h) qbsOpenMenu(anchor, h);
}

function qbsGroupMenu(anchor, gid) {
    var g = qbsGroup(gid);
    if (!g) return;
    var h = qbsItem('Details', 'details', gid) + qbsItem('Rename', 'rename-start', gid);
    if (!g.player) {
        var n = g.entries.length;
        h += '<div class="qbs-menu__sep"></div>' +
             qbsItem('Delete group' + (n ? ' and its ' + n + (n === 1 ? ' ship' : ' ships') : ''),
                     'group-delete', gid, ' qbs-menu__item--danger');
    }
    qbsOpenMenu(anchor, h);
}

function qbsPresetMenu(anchor) {
    var s = QBS.setup, names = s.presets || [];
    var h = '<div class="qbs-menu__head">Load preset</div>';
    if (!names.length) h += '<div class="qbs-menu__empty">No saved presets yet. Use + to save this scenario.</div>';
    names.forEach(function (n) {
        var on = n === s.preset;
        h += '<div class="qbs-menu__item' + (on ? ' qbs-menu__item--on' : '') + '" data-action="preset-load" data-arg="' + qbsEsc(n) + '">' +
             '<span class="qbs-menu__check">' + (on ? '✓' : '') + '</span>' +
             '<span class="qbs-menu__label">' + qbsEsc(n) + '</span>' +
             '<button class="qbs-kebab qbs-menu__del" data-action="preset-delete" data-arg="' + qbsEsc(n) +
             '" aria-label="Delete preset">×</button></div>';
    });
    qbsOpenMenu(anchor, h, true);
}

function qbsSaveMenu(anchor) {
    qbsOpenMenu(anchor,
        '<div class="qbs-menu__head">Save scenario as preset</div>' +
        '<div class="qbs-menu__form"><input class="qbs-preset-name" placeholder="Preset name" value="' + qbsEsc(QBS.setup.preset || '') + '">' +
        '<div class="qbs-form-actions"><button class="cp-done-button" data-action="preset-save-cancel">Cancel</button>' +
        '<button class="cp-done-button qbs-add" data-action="preset-save">Save</button></div></div>', true);
    QBS.saveSent = false;
    QBS.saveCancelled = false;
    var inp = qbsEl('qbs-menu').querySelector('.qbs-preset-name');
    inp.addEventListener('change', function () { qbsSavePreset(inp.value); });
    // Esc (text_capture reverts, then blurs) or a click away ends the form.
    inp.addEventListener('blur', function () { setTimeout(function () {
        if (inp.isConnected && document.activeElement !== inp) qbsCloseMenu();
    }, 0); });
    inp.focus();
    inp.select();
}

// ── text commits (keyboard-capture contract: commit on 'change') ──────────
// Reached from the field's 'change' (Enter) or from Save. A click away has
// already abandoned the edit (qbsMouseDown), so it never saves. One send per
// form; the menu closes after the field's blur has finished.
function qbsSavePreset(value) {
    var name = String(value || '').trim();
    if (!name || QBS.saveSent || QBS.saveCancelled) return;
    QBS.saveSent = true;
    QBS.presetAsk = { kind: 'save', name: name };
    dauntlessEvent('quick-battle-setup/preset-save:' + qbsEnc(name));
    setTimeout(qbsCloseMenu, 0);
}

// An empty or unchanged name sends nothing.
function qbsRenameChange(ev) {
    var inp = ev.target, g = qbsGroup(inp.getAttribute('data-group')), name = inp.value.trim();
    if (g && name && name !== g.name) {
        dauntlessEvent('quick-battle-setup/rename:' + g.id + ':' + qbsEnc(name));
    }
}

// Every exit (commit, Esc, click away, forced release) ends the edit.
function qbsRenameBlur() {
    if (QBS.renaming == null) return;
    QBS.renaming = null;
    setTimeout(function () { if (QBS.setup && QBS.renaming == null) renderGroups(); }, 0);
}

// ── clicks ────────────────────────────────────────────────────────────────
function qbsClick(ev) {
    var root = qbsEl('quick-battle-setup'), menu = qbsEl('qbs-menu');
    if (!QBS.setup || !root.contains(ev.target)) return;
    var el = ev.target.closest('[data-action]');
    var action = el ? el.getAttribute('data-action') : null;
    var arg = el ? (el.getAttribute('data-arg') || '') : '';
    if (!menu.contains(ev.target) && !(action && /-menu$/.test(action))) qbsCloseMenu();
    if (ev.target.closest('.qbs-rename')) return;
    if (!el) {
        // A click anywhere else on a group box makes it the add target.
        var box = ev.target.closest('.qbs-group');
        if (box && box.getAttribute('data-group') !== QBS.setup.target) {
            dauntlessEvent('quick-battle-setup/target:' + box.getAttribute('data-group'));
        }
        return;
    }
    if (el.disabled) return;
    var gid = el.getAttribute('data-group'), done = true;
    switch (action) {
    // filters and sheet
    case 'era': dauntlessEvent('quick-battle-setup/era:' + arg); break;
    case 'species': dauntlessEvent('quick-battle-setup/species:' + qbsEnc(arg)); break;
    case 'select': dauntlessEvent('quick-battle-setup/select:' + qbsEnc(arg)); break;
    // adding ships
    case 'add': dauntlessEvent('quick-battle-setup/add:' + qbsEnc(arg)); break;
    case 'set-player': dauntlessEvent('quick-battle-setup/set-player:' + qbsEnc(arg)); break;
    // groups
    case 'group-new': dauntlessEvent('quick-battle-setup/group-new'); break;
    case 'details': dauntlessEvent('quick-battle-setup/details:' + arg); break;
    case 'draft': dauntlessEvent('quick-battle-setup/draft:' + arg); break;
    case 'draft-update': dauntlessEvent('quick-battle-setup/draft-update'); break;
    case 'draft-cancel': dauntlessEvent('quick-battle-setup/draft-cancel'); break;
    case 'group-delete': dauntlessEvent('quick-battle-setup/group-delete:' + arg); break;
    case 'rename-start':
        // Page-owned: no verb until the name is committed.
        QBS.renaming = arg;
        qbsCloseMenu();
        renderGroups();
        break;
    // ship rows ("<eid>:<urlenc or empty>", "<eid>:<gid>", "<eid>")
    case 'variant': dauntlessEvent('quick-battle-setup/variant:' + arg); break;
    case 'move': dauntlessEvent('quick-battle-setup/move:' + arg); break;
    case 'remove': dauntlessEvent('quick-battle-setup/remove:' + arg); break;
    // menus
    case 'group-menu': qbsGroupMenu(el, gid); done = false; break;
    case 'row-menu': qbsRowMenu(el, gid, el.getAttribute('data-entry')); done = false; break;
    case 'preset-menu': qbsPresetMenu(el); done = false; break;
    case 'preset-save-menu': qbsSaveMenu(el); done = false; break;
    // presets
    case 'preset-load':
        QBS.presetAsk = { kind: 'load', name: arg };
        dauntlessEvent('quick-battle-setup/preset-load:' + qbsEnc(arg));
        break;
    case 'preset-delete':
        dauntlessEvent('quick-battle-setup/preset-delete:' + qbsEnc(arg));
        break;
    case 'preset-save': {
        var inp = menu.querySelector('.qbs-preset-name');
        if (!inp || !inp.value.trim()) { if (inp) inp.focus(); done = false; break; }
        qbsSavePreset(inp.value);
        done = false;           // qbsSavePreset closes the menu itself
        break;
    }
    case 'preset-save-cancel': break;
    // dialogs
    case 'confirm': dauntlessEvent('quick-battle-setup/confirm'); break;
    case 'cancel': QBS.presetAsk = null; dauntlessEvent('quick-battle-setup/cancel'); break;
    // footer
    case 'start': dauntlessEvent('quick-battle-setup/start'); break;
    case 'close': dauntlessEvent('quick-battle-setup/close'); break;
    default: done = false;
    }
    if (done) qbsCloseMenu();
}

// Runs (capture phase) before focus moves, which is the only point where a
// click away can be told from Enter without a key listener:
//  - inside the popover, anything but the field keeps the focus on the field
//    (Save/Cancel buttons and dead space; keyboard-capture spec §5.1);
//  - outside it, while the preset-name field is focused, the edit is
//    abandoned through text_capture's cancel path (revert, then blur, so no
//    'change' fires) and flagged, so a click away never saves -- as in the
//    spike, where only Enter or Save saved.
function qbsMouseDown(ev) {
    var menu = qbsEl('qbs-menu');
    if (!menu || menu.hidden) return;
    if (menu.contains(ev.target)) {
        if (!ev.target.closest('.qbs-preset-name')) ev.preventDefault();
        return;
    }
    var ae = document.activeElement;
    if (ae && ae.classList && ae.classList.contains('qbs-preset-name') && menu.contains(ae)) {
        QBS.saveCancelled = true;
        if (window.__dauntlessTextCancel) window.__dauntlessTextCancel(ae);
        else ae.blur();
    }
}

// ── entry points ──────────────────────────────────────────────────────────
function setQuickBattleCatalog(payload) {
    QBS.catalog = payload || null;
    QBS.ships = {};
    QBS.eras = {};
    if (!QBS.catalog) return;
    (QBS.catalog.ships || []).forEach(function (s) { QBS.ships[String(s.id).toLowerCase()] = s; });
    (QBS.catalog.eras || []).forEach(function (e) { QBS.eras[e.id] = e; });
    if (QBS.setup) qbsRender();
}

function setQuickBattleSetup(payload) {
    var root = qbsEl('quick-battle-setup');
    if (!root) return;
    if (!payload || payload.open !== true) {
        // Closing abandons any edit in progress (keyboard contract §4.4).
        qbsAbandonFocusIn(root);
        qbsCloseMenu();
        QBS.setup = null;
        QBS.renaming = null;
        QBS.presetAsk = null;
        root.style.display = 'none';
        return;
    }
    var prev = QBS.setup;
    QBS.setup = payload;
    // A popover closes on re-render -- unless the player is typing in it.
    var menu = qbsEl('qbs-menu');
    if (!(menu && menu.contains(document.activeElement))) qbsCloseMenu();
    if (QBS.renaming != null && !qbsGroup(QBS.renaming)) QBS.renaming = null;
    qbsRender();
    qbsPresetToast(prev, payload);
    // A confirmation that went away without the preset change it guarded
    // (Esc, Cancel, or refused) ends that request: no toast may fire later.
    if (prev && prev.confirm && !payload.confirm) QBS.presetAsk = null;
    root.style.display = 'flex';
}

function qbsRender() {
    // A rename in progress keeps its field: re-rendering the column would
    // destroy it (and abandon the edit) under the player's cursor.
    var editing = QBS.renaming != null && document.activeElement &&
                  document.activeElement.classList.contains('qbs-rename');
    if (!editing) renderGroups();
    renderEras();
    renderSpecies();
    renderCatalog();
    renderFooter();
    renderSheet();
    renderConfirm();
}

// Esc with no text field focused (spec §3.6): close a popover first, else let
// Python close the innermost layer.
function qbEscape() {
    if (qbsMenuOpen()) { qbsCloseMenu(); return; }
    dauntlessEvent('quick-battle-setup/esc');
}

(function () {
    var root = document.getElementById('quick-battle-setup');
    if (!root) return;
    document.addEventListener('click', qbsClick);
    root.addEventListener('mousedown', qbsMouseDown, true);
    // A plain mouse wheel only scrolls vertically; turn it sideways over the
    // single-line filter strips so they scroll without Shift or a trackpad.
    ['qbs-eras', 'qbs-species'].forEach(function (id) {
        document.getElementById(id).addEventListener('wheel', function (ev) {
            var strip = ev.currentTarget;
            if (strip.scrollWidth <= strip.clientWidth || Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) return;
            strip.scrollLeft += ev.deltaY;
            ev.preventDefault();
        }, { passive: false });
    });
    window.addEventListener('resize', qbsCloseMenu);
    document.getElementById('qbs-catalog').addEventListener('scroll', qbsCloseMenu);
    document.getElementById('qbs-groups').addEventListener('scroll', qbsCloseMenu);
})();
