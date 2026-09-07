// The "Select Bridge Commander Install" screen.
//
// Renders whatever engine/ui/first_run_panel.py sends and reports button
// presses back. It holds no logic of its own: CEF is software-rasterized in
// this project, so there is no headless render to test a page against, and
// anything conditional therefore belongs in Python where it can be.
function setFirstRun(payload) {
    var root = document.getElementById('first-run');
    if (!root) { return; }
    if (!payload) { root.hidden = true; return; }

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
        browse.className = 'fr-btn';
        browse.textContent = 'Browse…';
        browse.setAttribute(
            'onclick', "dauntlessEvent('first-run/browse:" + row.kind + "')");

        head.appendChild(label);
        head.appendChild(browse);
        el.appendChild(head);

        var path = document.createElement('div');
        path.className = 'fr-path';
        path.textContent = row.path;
        el.appendChild(path);

        var status = document.createElement('div');
        status.className = 'fr-status ' + (row.ok ? 'ok' : (row.path ? 'bad' : 'unset'));
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
    root.hidden = false;
}
