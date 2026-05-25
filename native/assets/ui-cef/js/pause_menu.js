// Pause-menu render fn. Driven by Python via cef_execute_javascript:
//   setPauseMenu({items:[{label, action}, ...], focused: 0});
// Rebuilds the row list inside #pause-menu-list from the payload.
// See docs/ui_designs/10-pause-menu.md for the spec.

// JS→Python event channel. Each call emits a console message with a
// known prefix; C++ side OnConsoleMessage parses it, calls the
// registered Python callback, and suppresses the default log.
function dauntlessEvent(name) {
    console.info('dauntless-event:' + name);
}

function setPauseMenu(state) {
    const list = document.getElementById('pause-menu-list');
    if (!list) return;
    const items = (state && state.items) || [];
    // -1 (or missing) means "no row keyboard-focused" — rows still
    // light up on :hover but the initial paint shows nothing selected.
    const focused = (state && typeof state.focused === 'number') ? state.focused : -1;

    // Re-emit from scratch each call — cheap (handful of rows) and
    // keeps the DOM faithful to the Python model without diff logic.
    let html = '';
    for (let i = 0; i < items.length; i++) {
        const it = items[i];
        const focusedCls = (i === focused) ? ' pause-row--focused' : '';
        const action = String(it.action || '').replace(/"/g, '&quot;');
        const label = String(it.label || '');
        html += '<div class="pause-row' + focusedCls + '"'
              +   ' data-action="' + action + '"'
              +   ' onclick="dauntlessEvent(\'' + action + '\')">'
              +   '<span class="pause-row__caret">&#9656;</span>' + label
              + '</div>';
    }
    list.innerHTML = html;
}
