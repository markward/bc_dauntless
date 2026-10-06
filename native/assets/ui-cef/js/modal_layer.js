// Large-modal occlusion. While any .cp-modal-layer root is shown, every
// body-level element that paints BENEATH it gets .ui-occluded (visibility:
// hidden, configuration_panel.css), and loses it again when the last layer
// closes.
//
// Why this exists: z-index puts a window above the HUD, but it cannot stop a
// lower element painting into a TRANSPARENT part of the window. The Set
// Course window's body is exactly that — a hole onto the native GL star map —
// and the Player and Speed panels showed straight through it. Hiding what
// lies beneath is the only fix inside one CEF page, and doing it for every
// layer keeps the rule "a large modal sits above all other UI" uniform.
//
// "Beneath" is decided by computed z-index, not a list of names, so a new HUD
// element is covered without touching this file, and anything ABOVE the
// layer (the pause menu at 100, the system screens at 200+) stays visible.
//
// Each layer's own render function still owns its root's display; this file
// only watches. It observes the layers' style attribute and body's direct
// children — never the whole subtree, which the HUD rewrites every frame.

// Pure core, separately testable: given each body child's
// {isLayer, open, z}, which children are occluded?
function modalLayerOccludedFlags(entries) {
    var topZ = null;
    entries.forEach(function (e) {
        if (e.isLayer && e.open && (topZ === null || e.z > topZ)) topZ = e.z;
    });
    return entries.map(function (e) {
        return topZ !== null && !e.isLayer && e.z < topZ;
    });
}

function _modalLayerZ(el) {
    var z = parseInt(window.getComputedStyle(el).zIndex, 10);
    return isNaN(z) ? 0 : z;   // `auto` paints at the root context's level 0
}

function modalLayerSync() {
    var children = Array.prototype.filter.call(document.body.children,
        function (el) { return el.tagName !== 'SCRIPT'; });
    var entries = children.map(function (el) {
        var isLayer = el.classList.contains('cp-modal-layer');
        return {
            isLayer: isLayer,
            open: isLayer && window.getComputedStyle(el).display !== 'none',
            z: _modalLayerZ(el),
        };
    });
    var flags = modalLayerOccludedFlags(entries);
    children.forEach(function (el, i) {
        el.classList.toggle('ui-occluded', flags[i]);
    });
}

if (typeof document !== 'undefined' && typeof MutationObserver !== 'undefined') {
    (function () {
        var obs = new MutationObserver(modalLayerSync);
        obs.observe(document.body, { childList: true });
        Array.prototype.forEach.call(
            document.querySelectorAll('.cp-modal-layer'), function (layer) {
                obs.observe(layer, { attributes: true, attributeFilter: ['style'] });
            });
        modalLayerSync();
    })();
}
