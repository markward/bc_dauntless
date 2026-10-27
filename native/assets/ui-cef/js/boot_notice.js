// The boot notice splash: Activision's required notice, before the bridge.
//
// Renders whatever engine/ui/boot_notice_panel.py sends. The panel owns the
// schedule and pushes the opacity every frame; this page only applies it.
// A payload with `ack` is answered with 'boot-notice/shown', which is what
// starts the panel's clock -- pushes are dropped until the page has loaded,
// so the page saying it received one is the only reliable start signal.

function setBootNotice(payload) {
    var root = document.getElementById('boot-notice');
    if (!root) { return; }
    if (!payload) { root.style.display = 'none'; return; }

    if (payload.lines) {
        document.getElementById('bn-notice').textContent = payload.lines[0];
        document.getElementById('bn-credit').textContent = payload.lines[1];
    }
    root.style.display = 'flex';
    document.getElementById('bn-text').style.opacity = String(payload.opacity);
    if (payload.ack) {
        dauntlessEvent('boot-notice/shown');
    }
}
