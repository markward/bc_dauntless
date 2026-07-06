// Engineering Power-Transmission-Grid panel.
// Driven by Python via cef_execute_javascript:
//   setEngineeringPower({visible:true, sliders, power_used, columns, tractor, cloak});
//   setEngineeringPower({visible:false});
// Slider drag events fire dauntlessEvent('engpower:set:<group>:<value>').
// Spec: docs/superpowers/sdd/task-13-brief.md

function _epEscape(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function _epPct(frac) {
    return (frac * 100) + '%';
}

// Key set of the currently-built slider DOM, e.g. "weapons,engines,...".
// Sliders are (re)built only when this changes; per-payload updates touch
// input.value + the % label only, so a mid-drag slider never snaps back
// (the panel pumps every tick — a full innerHTML rebuild would reset the
// thumb continuously while the user drags).
var _epSliderKeys = null;

function _epBuildSliders(sliders) {
    var slBody = document.getElementById('ep-sliders');
    if (!slBody) return;
    var html = '';
    for (var i = 0; i < sliders.length; i++) {
        var sl = sliders[i];
        var key = _epEscape(sl.key);
        html += '<div class="ep-slider-row" data-key="' + key + '">'
              +   '<span class="ep-slider-label">' + _epEscape(sl.label) + '</span>'
              +   '<input type="range" min="0" max="1.25" step="0.05"'
              +          ' value="' + (sl.pct || 0) + '"'
              +          ' class="ep-slider-input"'
              +          ' oninput="this.nextElementSibling.textContent=Math.round(this.value*100)+\'%\';'
              +                    'dauntlessEvent(\'engpower:set:' + key + ':\'+this.value)">'
              +   '<span class="ep-slider-pct">' + Math.round((sl.pct || 0) * 100) + '%</span>'
              + '</div>';
    }
    slBody.innerHTML = html;
}

function _epUpdateSliders(sliders) {
    var slBody = document.getElementById('ep-sliders');
    if (!slBody) return;
    for (var i = 0; i < sliders.length; i++) {
        var sl = sliders[i];
        var row = slBody.querySelector('.ep-slider-row[data-key="' + sl.key + '"]');
        if (!row) continue;
        var input = row.querySelector('.ep-slider-input');
        var pctEl = row.querySelector('.ep-slider-pct');
        // Never write to the input the user is mid-drag on — the payload
        // echo would fight the thumb.
        if (input && input !== document.activeElement) {
            input.value = sl.pct || 0;
            if (pctEl) pctEl.textContent = Math.round((sl.pct || 0) * 100) + '%';
        }
    }
}

function setEngineeringPower(payload) {
    var root = document.getElementById('engpower-root');
    if (!root) return;
    if (!payload || payload.visible !== true) {
        root.style.display = 'none';
        return;
    }
    root.style.display = '';

    // --- Power Used bar: sequential zones (power-system.md §"The Power Used
    // Bar") — blue [0..blue], yellow [blue..blue+yellow], red
    // [blue+yellow..blue+yellow+red]. The fill bar on top is the active reading.
    var pu = payload.power_used || {};
    var bands = pu.bands || {};
    var blue = bands.blue || 0;
    var yellow = bands.yellow || 0;
    var red = bands.red || 0;
    var bBlue = document.getElementById('ep-band-blue');
    var bYellow = document.getElementById('ep-band-yellow');
    var bRed = document.getElementById('ep-band-red');
    var bFill = document.getElementById('ep-power-fill');
    if (bBlue) {
        bBlue.style.left = '0%';
        bBlue.style.width = _epPct(blue);
    }
    if (bYellow) {
        bYellow.style.left = _epPct(blue);
        bYellow.style.width = _epPct(yellow);
    }
    if (bRed) {
        bRed.style.left = _epPct(blue + yellow);
        bRed.style.width = _epPct(red);
    }
    if (bFill) bFill.style.width = _epPct(pu.fraction || 0);

    // --- Sliders: build once per key set; then value-only updates ---
    var sliders = payload.sliders || [];
    var keys = sliders.map(function (s) { return s.key; }).join(',');
    if (keys !== _epSliderKeys) {
        _epBuildSliders(sliders);
        _epSliderKeys = keys;
    } else {
        _epUpdateSliders(sliders);
    }

    // --- Columns ---
    var cols = payload.columns || {};
    var cWarp   = document.getElementById('ep-col-warpcore');
    var cMain   = document.getElementById('ep-col-main');
    var cBackup = document.getElementById('ep-col-backup');
    if (cWarp)   cWarp.textContent   = Math.round((cols.warp_core || 0) * 100) + '%';
    if (cMain)   cMain.textContent   = Math.round((cols.main      || 0) * 100) + '%';
    if (cBackup) cBackup.textContent = Math.round((cols.backup    || 0) * 100) + '%';

    // --- Siphon lines: tractor + cloak ---
    var tractor = payload.tractor || {};
    var cloak   = payload.cloak   || {};
    var tEl = document.getElementById('ep-siphon-tractor');
    var cEl = document.getElementById('ep-siphon-cloak');
    if (tEl) {
        tEl.className = 'ep-siphon' + (tractor.present ? '' : ' ep-siphon--absent')
                                    + (tractor.active  ? ' ep-siphon--active' : '');
        tEl.textContent = 'Tractor: ' + (tractor.active ? 'On' : 'Off');
    }
    if (cEl) {
        cEl.className = 'ep-siphon' + (cloak.present ? '' : ' ep-siphon--absent')
                                    + (cloak.active  ? ' ep-siphon--active' : '');
        cEl.textContent = 'Cloak: ' + (cloak.active ? 'On' : 'Off');
    }
}
