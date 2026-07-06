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
    return Math.round(frac * 100) + '%';
}

function setEngineeringPower(payload) {
    var root = document.getElementById('engpower-root');
    if (!root) return;
    if (!payload || payload.visible !== true) {
        root.style.display = 'none';
        return;
    }
    root.style.display = '';

    // --- Power Used bar ---
    var pu = payload.power_used || {};
    var bands = pu.bands || {};
    var bBlue = document.getElementById('ep-band-blue');
    var bYellow = document.getElementById('ep-band-yellow');
    var bRed = document.getElementById('ep-band-red');
    var bFill = document.getElementById('ep-power-fill');
    if (bBlue)   bBlue.style.width   = _epPct(bands.blue   || 0);
    if (bYellow) bYellow.style.width = _epPct(bands.yellow || 0);
    if (bRed)    bRed.style.width    = _epPct(bands.red    || 0);
    if (bFill)   bFill.style.width   = _epPct(pu.fraction  || 0);

    // --- Sliders ---
    var slBody = document.getElementById('ep-sliders');
    if (slBody) {
        var html = '';
        var sliders = payload.sliders || [];
        for (var i = 0; i < sliders.length; i++) {
            var sl = sliders[i];
            var pctLabel = Math.round((sl.pct || 0) * 100) + '%';
            html += '<div class="ep-slider-row">'
                  +   '<span class="ep-slider-label">' + _epEscape(sl.label) + '</span>'
                  +   '<input type="range" min="0" max="1.25" step="0.05"'
                  +          ' value="' + (sl.pct || 0) + '"'
                  +          ' class="ep-slider-input"'
                  +          ' oninput="this.nextElementSibling.textContent=Math.round(this.value*100)+\'%\';'
                  +                    'dauntlessEvent(\'engpower:set:' + _epEscape(sl.key) + ':\'+this.value)">'
                  +   '<span class="ep-slider-pct">' + pctLabel + '</span>'
                  + '</div>';
        }
        slBody.innerHTML = html;
    }

    // --- Columns ---
    var cols = payload.columns || {};
    var cWarp   = document.getElementById('ep-col-warpcore');
    var cMain   = document.getElementById('ep-col-main');
    var cBackup = document.getElementById('ep-col-backup');
    if (cWarp)   cWarp.textContent   = _epPct(cols.warp_core || 0);
    if (cMain)   cMain.textContent   = _epPct(cols.main      || 0);
    if (cBackup) cBackup.textContent = _epPct(cols.backup    || 0);

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
