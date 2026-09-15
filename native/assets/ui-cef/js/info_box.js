// native/assets/ui-cef/js/info_box.js
// Renders SDK info boxes (MissionLib.SetupInfoBoxFromParagraph) into
// #sdk-infobox. Payload: {entries:[{id,title,body[],button}]}. Close clicks
// fire info-box/close:<id> back to InfoBoxPanel.dispatch_event.
// Spec: docs/superpowers/specs/2026-06-17-sdk-info-box-rendering-design.md
function setInfoBoxes(payload) {
    var slot = document.getElementById("sdk-infobox");
    if (!slot) { return; }
    var data = (typeof payload === "string") ? JSON.parse(payload) : payload;
    var entries = (data && data.entries) || [];
    slot.innerHTML = "";

    entries.forEach(function (entry) {
        var modal = document.createElement("div");
        modal.className = "info-box-modal";

        var title = document.createElement("div");
        title.className = "info-box-title";
        title.textContent = entry.title || "";
        modal.appendChild(title);

        var body = document.createElement("div");
        body.className = "info-box-body";
        (entry.body || []).forEach(function (seg) {
            if (seg.kind === "key") {
                var chip = document.createElement("span");
                chip.className = "info-box-key";
                chip.textContent = seg.text;
                if (seg.color) {
                    chip.style.color = "rgba(" +
                        Math.round(seg.color[0] * 255) + "," +
                        Math.round(seg.color[1] * 255) + "," +
                        Math.round(seg.color[2] * 255) + "," +
                        seg.color[3] + ")";
                }
                body.appendChild(chip);
            } else {
                // Preserve newlines from the segment stream.
                (seg.text || "").split("\n").forEach(function (line, i) {
                    if (i > 0) { body.appendChild(document.createElement("br")); }
                    body.appendChild(document.createTextNode(line));
                });
            }
        });

        if (entry.button) {
            // LCARS pill row (08-modal-dialog): red end-caps bookend the
            // hard-cornered button. The caps are decorative; only the
            // <button> is clickable.
            var actions = document.createElement("div");
            actions.className = "info-box-actions";
            var row = document.createElement("div");
            row.className = "info-box-actions__row";
            var capL = document.createElement("div");
            capL.className = "info-box-cap info-box-cap--l";
            var btn = document.createElement("button");
            btn.className = "info-box-close";
            btn.textContent = entry.button.label || "Close";
            btn.onclick = function () {
                dauntlessEvent("info-box/close:" + entry.button.id);
            };
            var capR = document.createElement("div");
            capR.className = "info-box-cap info-box-cap--r";
            row.appendChild(capL);
            row.appendChild(btn);
            row.appendChild(capR);
            actions.appendChild(row);
            body.appendChild(actions);   // inside the U-frame, like the mockup
        }
        modal.appendChild(body);

        slot.appendChild(modal);
    });
    reportInfoBoxBounds();
}

// Tell Python where the modals actually landed, in CEF view px. The host
// loop forwards left-clicks to CEF only inside a known bbox (host_loop.py,
// the _cursor_in_* ladder); every other panel mirrors a CSS constant there,
// but this stack is centred and sized by its text, so the laid-out DOM is
// the only honest source. Union of every modal's rect; nothing is sent
// when the stack is empty -- Python ignores a stale rect once no closeable
// box is up, so an empty report would only be noise.
function reportInfoBoxBounds() {
    var slot = document.getElementById("sdk-infobox");
    if (!slot || typeof dauntlessEvent !== "function") { return; }
    var modals = slot.querySelectorAll(".info-box-modal");
    if (!modals.length) { return; }
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (var i = 0; i < modals.length; i++) {
        var r = modals[i].getBoundingClientRect();
        if (r.left < x0) { x0 = r.left; }
        if (r.top < y0) { y0 = r.top; }
        if (r.right > x1) { x1 = r.right; }
        if (r.bottom > y1) { y1 = r.bottom; }
    }
    dauntlessEvent("info-box/bounds:" +
        Math.floor(x0) + "," + Math.floor(y0) + "," +
        Math.ceil(x1 - x0) + "," + Math.ceil(y1 - y0));
}

// A window resize re-centres the stack (the CEF view tracks the window).
window.addEventListener("resize", reportInfoBoxBounds);
