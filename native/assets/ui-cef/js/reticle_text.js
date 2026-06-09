// native/assets/ui-cef/js/reticle_text.js
//
// Target reticle text overlay. Driven by Python via cef_execute_javascript:
//   setReticleText({visible, name, line2, name_xy:[x,y], line2_xy:[x,y]});
// Coordinates are CEF view-space pixels (top-left origin). Non-interactive.
// Spec: docs/superpowers/specs/2026-06-09-reticle-chrome-bars-text-design.md
function setReticleText(state) {
    var nameEl = document.getElementById('reticle-name');
    var distEl = document.getElementById('reticle-dist');
    if (!nameEl || !distEl) return;
    if (!state || !state.visible) {
        nameEl.style.display = 'none';
        distEl.style.display = 'none';
        return;
    }
    nameEl.style.display = 'block';
    distEl.style.display = 'block';
    nameEl.textContent = String(state.name == null ? '' : state.name);
    distEl.textContent = String(state.line2 == null ? '' : state.line2);
    nameEl.style.left = state.name_xy[0].toFixed(1) + 'px';
    nameEl.style.top  = state.name_xy[1].toFixed(1) + 'px';
    distEl.style.left = state.line2_xy[0].toFixed(1) + 'px';
    distEl.style.top  = state.line2_xy[1].toFixed(1) + 'px';
}
