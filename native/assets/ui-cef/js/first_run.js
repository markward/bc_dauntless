// The "Select Bridge Commander Install" screen.
//
// Renders whatever engine/ui/first_run_panel.py sends and reports button
// presses back. It holds no logic of its own: CEF is software-rasterized in
// this project, so there is no headless render to test a page against, and
// anything conditional therefore belongs in Python where it can be.

function escapeJsLiteralFR(s) {
    // Embedded in onclick="dauntlessEvent('...')". Backslash-escape single
    // quotes and backslashes so a value can never break out of the string
    // literal. row.kind currently only ever comes from Python's closed
    // _ROWS set, but this matches js/mission_picker.js's defensive idiom
    // for exactly this pattern rather than trusting that invariant here too.
    return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function setFirstRun(payload) {
    var root = document.getElementById('first-run');
    if (!root) { return; }
    // An inline style wins the cascade over the user-agent [hidden] rule
    // once #first-run has its own `display` declaration (see
    // css/first_run.css); toggle the same property both ways, matching how
    // js/mission_picker.js drives #mission-picker.
    if (!payload) { root.style.display = 'none'; return; }

    document.getElementById('fr-title').textContent = payload.title;

    var rows = document.getElementById('fr-rows');
    rows.innerHTML = '';
    payload.rows.forEach(function (row) {
        var el = document.createElement('div');
        el.className = 'fr-row';

        var head = document.createElement('div');
        head.className = 'fr-row-head';

        var label = document.createElement('span');
        label.className = 'fr-label';
        label.textContent = row.label;

        var browse = document.createElement('button');
        browse.type = 'button';
        browse.className = 'cp-done-button';
        browse.textContent = 'Browse…';
        browse.setAttribute(
            'onclick',
            "dauntlessEvent('first-run/browse:" + escapeJsLiteralFR(row.kind) + "')");

        head.appendChild(label);
        head.appendChild(browse);
        el.appendChild(head);

        var path = document.createElement('div');
        path.className = 'fr-path';
        path.textContent = row.path;
        el.appendChild(path);

        // row.state is the authority on ok/bad/unset -- Python already
        // knows the three-way distinction; row.path alone cannot carry it
        // (a rejected root and an untouched one are both "").
        var status = document.createElement('div');
        status.className = 'fr-status ' + row.state;
        status.textContent = row.status;
        el.appendChild(status);

        if (row.hint) {
            var hint = document.createElement('div');
            hint.className = 'fr-hint';
            hint.textContent = row.hint;
            el.appendChild(hint);
        }

        rows.appendChild(el);
    });

    document.getElementById('fr-continue').disabled = !payload.can_continue;
    root.style.display = 'flex';
}
