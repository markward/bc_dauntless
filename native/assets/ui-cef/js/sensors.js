// native/assets/ui-cef/js/sensors.js
//
// Radar / sensors render fn. Driven by Python via cef_execute_javascript:
//   setRadar({visible, range_gu, contacts: [
//     {name, affiliation, kind, x, y, alt, heading, targeted}, ...
//   ]});
//
// No interaction — the radar is read-only in v1.
// Spec: docs/ui_designs/05-sensors-radar.md

const _SENSORS_HTML_ESCAPES = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
};
function _sensorsEscapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
        return _SENSORS_HTML_ESCAPES[c];
    });
}

// Disc-plane vertical squash, matches .sensors__disc-plane height (75)
// over .sensors__disc height (130) in sensors.css. If those values
// change, update this in lockstep.
const _SENSORS_PLANE_SQUASH = 75.0 / 130.0;
// Max stem length in pixels for |alt| == 1.0. Tuned to match the
// mockup's longest stem (~42 px) without overshooting the disc.
const _SENSORS_MAX_STEM_PX = 28.0;

function _sensorsBuildContact(c) {
    const aff = String(c.affiliation || 'UNKNOWN');
    const kind = String(c.kind || 'ship');
    const targeted = !!c.targeted;
    const altPx = Math.max(-1.0, Math.min(1.0, +c.alt || 0)) * _SENSORS_MAX_STEM_PX;
    // Heading in radians (0 = same as player forward, +ve = clockwise).
    // CSS rotate() uses degrees; +ve degrees = clockwise.
    const headingDeg = (+c.heading || 0) * (180.0 / Math.PI);

    // Glyph: triangle for ships, filled square for torpedoes/projectiles.
    let glyph;
    if (kind === 'torpedo' || kind === 'projectile') {
        glyph = '<div class="sensors__square"></div>';
    } else {
        glyph = '<div class="sensors__triangle"'
              + ' style="--heading-deg:' + headingDeg.toFixed(2) + 'deg"></div>';
    }

    // Glyph y-offset along the stem — triangle/square sits at the stem
    // tip, not the disc anchor. Stem grows upward for positive alt,
    // downward for negative. Pixel sign convention: -y is up on screen.
    const glyphOffsetY = -altPx; // px

    const stemStyle = altPx === 0
        ? 'display:none'
        : '--stem-px:' + Math.abs(altPx).toFixed(2)
          + ';--stem-sign:' + (altPx >= 0 ? '1' : '-1');

    let bracket = '';
    if (targeted) {
        // Bracket sits around the glyph (at stem tip), not at the
        // anchor — that's where the eye reads the contact.
        bracket = '<div class="sensors__bracket"'
                + ' style="transform:translate(-50%,calc(-50% + ' + glyphOffsetY.toFixed(2) + 'px))">'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--tl"></div>'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--tr"></div>'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--bl"></div>'
                +   '<div class="sensors__bracket-corner sensors__bracket-corner--br"></div>'
                + '</div>';
    }

    return ''
        + '<div class="sensors__contact sensors__contact--' + _sensorsEscapeHtml(aff) + '"'
        +   ' data-name="' + _sensorsEscapeHtml(c.name || '') + '"'
        +   ' style="left:0;top:0">'
        +   '<div class="sensors__anchor"></div>'
        +   '<div class="sensors__stem" style="' + stemStyle + '"></div>'
        +   '<div style="transform:translateY(' + glyphOffsetY.toFixed(2) + 'px)">'
        +     glyph
        +   '</div>'
        +   bracket
        + '</div>';
}

function setRadar(state) {
    const panel = document.getElementById('sensors-panel');
    if (!panel) return;
    if (!state || !state.visible) {
        panel.classList.add('sensors--hidden');
        return;
    }
    panel.classList.remove('sensors--hidden');

    // Minimize state — driven by the SDK's IsMinimizable/IsMinimized
    // flags (or the panel's own state when no RadarDisplay is
    // registered). The caret glyph swaps ▾ ↔ ▸ to mirror the
    // target-list caret discipline (no CSS rotate, to keep header text
    // crisp in CEF).
    const minimizable = !!state.minimizable;
    const minimized   = !!state.minimized;
    panel.classList.toggle('sensors--no-minimize', !minimizable);
    panel.classList.toggle('sensors--minimized',    minimized);
    const caret = document.getElementById('sensors-caret');
    if (caret) {
        caret.innerHTML = minimized ? '&#9656;' : '&#9662;';  // ▸ / ▾
    }
    // When minimized the body is hidden, so don't bother rebuilding
    // the contacts overlay — it's not visible and rebuilding would
    // thrash the DOM for nothing.
    if (minimized) return;

    const overlay = document.getElementById('sensors-contacts');
    if (!overlay) return;

    // Disc geometry — re-read on every call so window resize is handled.
    const discRect = overlay.getBoundingClientRect();
    const discW = discRect.width;
    const discH = discRect.height;
    const cx = discW / 2;
    const cy = discH / 2;
    const halfW = discW / 2;
    const halfH = (discH * _SENSORS_PLANE_SQUASH) / 2;

    const contacts = state.contacts || [];
    let html = '';
    for (let i = 0; i < contacts.length; i++) {
        const c = contacts[i];
        // Normalised x,y from Python are already in [-1, +1]; map to px.
        // Invert y: Python's +y = forward = up on screen → CSS pixel -y.
        const px = cx + (+c.x || 0) * halfW;
        const py = cy - (+c.y || 0) * halfH;
        html += '<div style="position:absolute;'
              +   'left:' + px.toFixed(2) + 'px;'
              +   'top:'  + py.toFixed(2) + 'px">'
              +   _sensorsBuildContact(c)
              + '</div>';
    }
    overlay.innerHTML = html;
}
