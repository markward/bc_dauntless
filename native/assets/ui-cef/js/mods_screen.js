// The pre-boot Mods screen. Renders engine/ui/mods_screen_panel.py's payload
// and reports clicks/committed text as dauntlessEvent('mods/...'). No logic:
// Python decides every value; the page only remembers which picker is open.
var MS = { p: null, open: null, newSpecies: null };

function msEsc(t) {
    return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
}
function msJs(s) { return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }
// msAttr HTML-escapes a fully-built inline event handler string (the outer
// onclick="..."/onchange="..." layer) -- msJs only escapes the INNER JS
// single-quoted string, so dynamic text containing a literal double quote
// (a player-typed variant-of class, a payload species or mod name) would
// otherwise close the attribute early and corrupt the generated markup.
// Apply this to the complete handler text at the point it is written into
// an attribute; msJs stays as the inner layer underneath it.
function msAttr(js) { return msEsc(js); }
function msSend(verb) { dauntlessEvent('mods/' + verb); }
function msSet(file, field, value) {
    msSend('set:' + file + ':' + field + ':' + encodeURIComponent(value == null ? '' : value));
}

function msEraText(era) {
    if (!era) { return null; }
    if (era === 'all') { return 'All eras'; }
    var ends = era.split('-'), tag = {};
    MS.p.eras.forEach(function (e) { tag[e.id] = e.tag; });
    return ends[0] === ends[1] ? tag[ends[0]] : tag[ends[0]] + ' → ' + tag[ends[1]];
}

function msCell(r, field, text, missing) {
    if (!r.editable) { return '<span class="ms-ro">' + msEsc(text || '—') + '</span>'; }
    var handler = "msPick(event,'" + msJs(r.file) + "','" + field + "')";
    return '<button class="ms-cell' + (missing ? ' ms-cell--missing' : '') +
        '" onclick="' + msAttr(handler) + '">' +
        msEsc(text || 'set…') + '</button>';
}

function msIcon(r) {
    // icon_url is a data:image/png;base64,... URL from engine.ui.ship_icons
    // (same mechanism as ship_display.js's setSilhouette), or '' when the
    // mod ship has no readable icon. An empty src is never put on the page.
    return r.icon_url
        ? '<img class="ms-icon" src="' + msEsc(r.icon_url) + '">'
        : '<span class="ms-icon ms-icon--empty"></span>';
}

function msRow(r) {
    var roleLabel = null;
    MS.p.roles.forEach(function (x) { if (x.id === r.role) { roleLabel = x.label; } });
    var f = msJs(r.file);
    var miss = function (k) { return r.missing.indexOf(k) >= 0; };
    var check = r.editable
        ? '<button class="ms-check' + (r.ticked ? ' ms-check--on' : '') + '" onclick="' +
          msAttr("msSend('tick:" + f + "')") + '">' + (r.ticked ? '✓' : '') + '</button>'
        : '';
    var title = r.editable
        ? '<input class="ms-text' + (miss('title') ? ' ms-text--bad' : '') + '" value="' + msEsc(r.title) +
          '" onchange="' + msAttr("msSet('" + f + "','title',this.value)") + '">'
        : '<span class="ms-ro ms-ro--title">' + msEsc(r.title) + '</span>';
    var variant = r.editable
        ? '<input class="ms-text ms-text--variant" placeholder="— own class —" value="' + msEsc(r.variant_of) +
          '" onfocus="' + msAttr("msVariantMenu(this,'" + f + "')") + '"' +
          ' oninput="' + msAttr("msVariantMenu(this,'" + f + "')") + '"' +
          ' onchange="' + msAttr("msSet('" + f + "','variant_of',this.value)") + '">'
        : '<span class="ms-ro">' + msEsc(r.variant_of || '—') + '</span>';
    var star = !r.variant_of ? '' : r.stock_class ? '<span class="ms-stock">stock default</span>'
        : '<button class="ms-star' + (r.is_default ? ' ms-star--on' : '') + '"' +
          (r.editable && !r.star_locked ? ' onclick="' + msAttr("msSend('star:" + f + "')") + '"' : ' disabled') +
          '>' + (r.is_default ? '★' : '☆') + '</button>';
    var species = MS.newSpecies === r.file
        ? '<input class="ms-text" id="ms-new-species" placeholder="Species" onchange="' +
          msAttr("MS.newSpecies=null;msSet('" + f + "','species',this.value)") + '">'
        : msCell(r, 'species', r.species, miss('species'));
    var playable = r.playable == null ? null : (r.playable ? 'Yes' : 'No');
    return '<tr class="ms-tr' + (r.ticked ? ' ms-tr--ticked' : '') + (r.editable ? '' : ' ms-tr--ro') + '">' +
        '<td class="ms-td-check">' + check + '</td>' +
        '<td class="ms-td-icon">' + msIcon(r) + '</td>' +
        '<td class="ms-td-title">' + title + '<span class="ms-file">' + msEsc(r.file) + '.py</span></td>' +
        '<td class="ms-td-variant">' + variant + '</td>' +
        '<td class="ms-td-star">' + star + '</td>' +
        '<td>' + msCell(r, 'era', msEraText(r.era), miss('era')) + '</td>' +
        '<td>' + msCell(r, 'role', roleLabel, miss('role') || /role/.test(r.conflict)) + '</td>' +
        '<td>' + species + '</td>' +
        '<td>' + msCell(r, 'playable', playable, miss('playable')) + '</td>' +
        '</tr>' + (r.conflict ? '<tr class="ms-conflict"><td></td><td colspan="8">' + msEsc(r.conflict) + '</td></tr>' : '');
}

function msRender() {
    var p = MS.p;
    document.getElementById('ms-header').textContent = p.header;
    document.getElementById('ms-intro').textContent = p.intro;
    var err = document.getElementById('ms-error');
    err.textContent = p.error || '';
    err.style.display = p.error ? 'block' : 'none';
    var sel = document.getElementById('ms-selbar');
    sel.style.display = p.ticked ? 'flex' : 'none';
    sel.innerHTML = p.ticked ? p.ticked + ' ticked — any edit to a ticked row applies to all ' + p.ticked +
        ' <button class="ms-link" onclick="msSend(\'clear-ticks\')">Clear</button>' : '';
    var html = '<table class="ms-table"><thead><tr><th></th><th></th><th>Title</th><th>Variant of</th>' +
        '<th>Default</th><th>Era</th><th>Role</th><th>Species</th><th>Playable</th></tr></thead><tbody>';
    p.mods.forEach(function (m) {
        var mine = p.rows.filter(function (r) { return r.mod === m.name; });
        var editable = mine.filter(function (r) { return r.editable; });
        var all = editable.length && editable.every(function (r) { return r.ticked; });
        html += '<tr class="ms-modrow"><td class="ms-td-check">' + (editable.length
            ? '<button class="ms-check' + (all ? ' ms-check--on' : '') + '" onclick="' +
              msAttr("msSend('tick-mod:" + msJs(m.name) + "')") + '">' + (all ? '✓' : '') + '</button>' : '') +
            '</td><td colspan="8"><span class="ms-mod">' + msEsc(m.name) + '</span><span class="ms-count">' +
            m.ships + ' ships · ' + m.classes + (m.classes === 1 ? ' class' : ' classes') + '</span></td></tr>';
        mine.forEach(function (r) { html += msRow(r); });
    });
    document.getElementById('ms-table').innerHTML = html + '</tbody></table>';
    var foot = '<button class="cp-done-button" onclick="msSend(\'quit\')">Quit</button>' +
        '<span class="ms-status' + (p.status_ok ? ' ms-status--ok' : '') + '">' + msEsc(p.status) + '</span>';
    foot += p.mode === 'gate'
        ? '<button class="cp-done-button" onclick="msSend(\'skip\')">Skip for now</button>' +
          '<button class="cp-done-button" onclick="msSend(\'continue\')"' + (p.can_continue ? '' : ' disabled') + '>Continue</button>'
        : '<button class="cp-done-button" onclick="msSend(\'play\')">Play</button>';
    document.getElementById('ms-footer').innerHTML = foot;
    var ns = document.getElementById('ms-new-species');
    if (ns) { ns.focus(); }
}

function msCloseMenu() { document.getElementById('ms-menu').style.display = 'none'; MS.open = null; }

function msShowMenu(anchor, html) {
    var menu = document.getElementById('ms-menu');
    menu.innerHTML = html;
    menu.style.display = 'block';
    var r = anchor.getBoundingClientRect(), h = Math.min(480, menu.scrollHeight);
    menu.style.top = (r.bottom + h + 8 > window.innerHeight ? r.top - h - 4 : r.bottom + 4) + 'px';
    menu.style.left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8) + 'px';
}

function msItem(label, onclick, on) {
    // Central fix point: every picker/quick-pick menu item (role, species,
    // playable, era "All eras", variant-of quick-pick, "New…", "Clear")
    // routes its handler text through here.
    return '<button class="ms-menu__item' + (on ? ' ms-menu__item--on' : '') + '" onclick="' + msAttr(onclick) + '">' + label + '</button>';
}

function msRowOf(file) {
    var hit = null;
    MS.p.rows.forEach(function (r) { if (r.file === file) { hit = r; } });
    return hit;
}

function msPick(ev, file, field) {
    ev.stopPropagation();
    var r = msRowOf(file), f = msJs(file), html = '';
    if (field === 'playable' && r.playable != null) { msSet(file, 'playable', r.playable ? '0' : '1'); return; }
    var many = r.ticked && MS.p.ticked > 1 ? ' <span class="ms-many">(' + MS.p.ticked + ' ticked rows)</span>' : '';
    if (field === 'role') {
        html = '<div class="ms-menu__head">Role' + many + '</div>';
        MS.p.roles.forEach(function (x) { html += msItem(msEsc(x.label), "msSet('" + f + "','role','" + x.id + "');msCloseMenu()", r.role === x.id); });
    } else if (field === 'species') {
        html = '<div class="ms-menu__head">Species' + many + '</div>';
        MS.p.species.forEach(function (s) { html += msItem(msEsc(s), "msSet('" + f + "','species','" + msJs(s) + "');msCloseMenu()", r.species === s); });
        html += msItem('New…', "MS.newSpecies='" + f + "';msCloseMenu();msRender()", false);
    } else if (field === 'playable') {
        html = '<div class="ms-menu__head">Playable' + many + '</div>' +
            msItem('Yes', "msSet('" + f + "','playable','1');msCloseMenu()", false) +
            msItem('No', "msSet('" + f + "','playable','0');msCloseMenu()", false);
    } else if (field === 'era') {
        var ends = r.era && r.era !== 'all' ? r.era.split('-') : [null, null];
        var col = function (which, cur) {
            return MS.p.eras.map(function (e) {
                var handler = "msSet('" + f + "','era-" + which + "','" + e.id + "')";
                return '<button class="ms-era' + (cur === e.id ? ' ms-era--on' : '') + '" onclick="' + msAttr(handler) + '">' +
                    '<b>' + msEsc(e.tag) + '</b><span>' + msEsc(e.name) + '</span></button>';
            }).join('');
        };
        html = '<div class="ms-menu__head">Era' + many + '</div><div class="ms-era-grid"><div><div class="ms-era-col">From</div>' +
            col('from', ends[0]) + '</div><div><div class="ms-era-col">To</div>' + col('to', ends[1]) + '</div></div>' +
            msItem('All eras (timeless)', "msSet('" + f + "','era','all');msCloseMenu()", r.era === 'all');
    }
    MS.open = { file: file, field: field };
    msShowMenu(ev.currentTarget, html);
}

function msVariantMenu(input, file) {
    var typed = input.value.trim().toLowerCase(), counts = {}, f = msJs(file);
    MS.p.rows.forEach(function (r) {
        var v = (r.variant_of || '').trim();
        if (r.file !== file && v) { counts[v] = (counts[v] || 0) + 1; }
    });
    var names = Object.keys(counts).filter(function (v) { return !typed || v.toLowerCase().indexOf(typed) >= 0; });
    names.sort(function (a, b) { return counts[b] - counts[a] || a.localeCompare(b); });
    var html = '<div class="ms-menu__head">Used elsewhere</div>';
    html += names.length ? names.map(function (v) {
        return msItem(msEsc(v) + ' <span class="ms-n">' + counts[v] + (counts[v] === 1 ? ' ship' : ' ships') + '</span>',
            "msSet('" + f + "','variant_of','" + msJs(v) + "');msCloseMenu()", false);
    }).join('') : '<div class="ms-menu__empty">Nothing typed on other rows yet</div>';
    if (typed) {
        var stock = MS.p.stock_classes.filter(function (c) { return c.toLowerCase().indexOf(typed) >= 0; });
        if (stock.length) {
            html += '<div class="ms-menu__head">Stock classes</div>' + stock.map(function (c) {
                return msItem(msEsc(c) + ' <span class="ms-n">stock</span>', "msSet('" + f + "','variant_of','" + msJs(c) + "');msCloseMenu()", false);
            }).join('');
        }
    }
    html += msItem('Clear (own class)', "msSet('" + f + "','variant_of','');msCloseMenu()", false);
    MS.open = { file: file, field: 'variant_of' };
    msShowMenu(input, html);
}

document.addEventListener('click', function (ev) {
    if (!ev.target.closest('#ms-menu') && !(ev.target.classList && ev.target.classList.contains('ms-text--variant'))) { msCloseMenu(); }
});

function setModsScreen(payload) {
    var root = document.getElementById('mods-screen');
    if (!root) { return; }
    if (!payload) { root.style.display = 'none'; msCloseMenu(); return; }
    var reopen = MS.open && MS.open.field === 'era' ? MS.open : null;
    MS.p = payload;
    msRender();
    root.style.display = 'flex';
    if (reopen) {
        var btns = document.querySelectorAll('.ms-cell');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].getAttribute('onclick').indexOf("'" + msJs(reopen.file) + "','era'") >= 0) {
                msPick({ stopPropagation: function () {}, currentTarget: btns[i] }, reopen.file, 'era');
            }
        }
    }
}
