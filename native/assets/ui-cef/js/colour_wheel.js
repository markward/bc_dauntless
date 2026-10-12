// Shared hue/saturation colour wheel (spec 2026-10-08-bridge-emitters §12.4),
// moved from ship_property_viewer.js. CEF OSR shows no native colour popup,
// so a canvas wheel is the working control. Hue = angle, saturation =
// radius, V = 1 always: brightness lives in a separate control (the SPV's
// intensity, the Bridge Editor's level).

function colourHsToRgb(hue, sat) {
    var h = ((hue % 360) + 360) % 360;
    var s = Math.max(0, Math.min(1, sat));
    var c = s;
    var x = c * (1 - Math.abs((h / 60) % 2 - 1));
    var m = 1 - c;
    var r, g, b;
    if (h < 60)       { r = c; g = x; b = 0; }
    else if (h < 120) { r = x; g = c; b = 0; }
    else if (h < 180) { r = 0; g = c; b = x; }
    else if (h < 240) { r = 0; g = x; b = c; }
    else if (h < 300) { r = x; g = 0; b = c; }
    else              { r = c; g = 0; b = x; }
    return [r + m, g + m, b + m];
}

function colourRgbToHs(rgb) {
    var r = rgb[0] || 0, g = rgb[1] || 0, b = rgb[2] || 0;
    var max = Math.max(r, g, b), min = Math.min(r, g, b);
    var d = max - min;
    var h = 0;
    if (d > 1e-6) {
        if (max === r) h = 60 * (((g - b) / d) % 6);
        else if (max === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;
    var sat = (max > 1e-6) ? d / max : 0;
    return {hue: h, sat: Math.max(0, Math.min(1, sat))};
}

// Base discs cached per canvas size; only the marker redraws per interaction.
var _colourWheelDiscs = {};

function ColourWheel(canvas, hs, onChange) {
    this.canvas = canvas;
    this.hue = hs.hue;
    this.sat = hs.sat;
    this.onChange = onChange || null;
    this.dragging = false;
    var self = this;
    canvas.addEventListener('pointerdown', function (e) {
        canvas.setPointerCapture(e.pointerId);
        self.dragging = true;
        self._fromEvent(e, false);
    });
    canvas.addEventListener('pointermove', function (e) {
        if (self.dragging) self._fromEvent(e, false);
    });
    canvas.addEventListener('pointerup', function (e) {
        if (!self.dragging) return;
        self.dragging = false;
        self._fromEvent(e, true);
    });
    // A drag that loses its pointer (the panel hidden mid-drag, Esc) ends
    // WITHOUT committing; otherwise `dragging` would stick and block every
    // later rebuild of the panel that hosts the wheel (review M1).
    var cancel = function () { self.dragging = false; };
    canvas.addEventListener('lostpointercapture', cancel);
    canvas.addEventListener('pointercancel', cancel);
    this.draw();
}

ColourWheel.prototype._fromEvent = function (e, final) {
    var rect = this.canvas.getBoundingClientRect();
    var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    var R = Math.min(rect.width, rect.height) / 2 - 4;
    var dx = e.clientX - cx, dy = e.clientY - cy;
    var angle = Math.atan2(dy, dx) * 180 / Math.PI;
    if (angle < 0) angle += 360;
    this.hue = angle;
    this.sat = Math.max(0, Math.min(1, Math.sqrt(dx * dx + dy * dy) / R));
    this.draw();
    if (this.onChange) this.onChange({hue: this.hue, sat: this.sat}, final);
};

ColourWheel.prototype.setHs = function (hue, sat) {
    this.hue = hue;
    this.sat = sat;
    this.draw();
};

ColourWheel.prototype.draw = function () {
    var ctx = this.canvas.getContext('2d');
    var w = this.canvas.width, h = this.canvas.height;
    var cx = w / 2, cy = h / 2, R = Math.min(cx, cy) - 4;
    var key = w + 'x' + h;
    if (!_colourWheelDiscs[key]) {
        var img = ctx.createImageData(w, h);
        for (var y = 0; y < h; y++) {
            for (var x = 0; x < w; x++) {
                var dx = x - cx, dy = y - cy;
                var dist = Math.sqrt(dx * dx + dy * dy);
                var idx = (y * w + x) * 4;
                if (dist > R) { img.data[idx + 3] = 0; continue; }
                var angle = Math.atan2(dy, dx) * 180 / Math.PI;
                if (angle < 0) angle += 360;
                var rgb = colourHsToRgb(angle, Math.min(1, dist / R));
                img.data[idx]     = Math.round(rgb[0] * 255);
                img.data[idx + 1] = Math.round(rgb[1] * 255);
                img.data[idx + 2] = Math.round(rgb[2] * 255);
                img.data[idx + 3] = 255;
            }
        }
        _colourWheelDiscs[key] = img;
    }
    ctx.putImageData(_colourWheelDiscs[key], 0, 0);
    var rad = this.hue * Math.PI / 180;
    var r = this.sat * R;
    var mx = cx + Math.cos(rad) * r, my = cy + Math.sin(rad) * r;
    ctx.beginPath(); ctx.arc(mx, my, 5, 0, Math.PI * 2);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(mx, my, 3, 0, Math.PI * 2);
    ctx.strokeStyle = '#000'; ctx.lineWidth = 1; ctx.stroke();
};
