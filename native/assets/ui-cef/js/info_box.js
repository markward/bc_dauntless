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
                seg.text.split("\n").forEach(function (line, i) {
                    if (i > 0) { body.appendChild(document.createElement("br")); }
                    body.appendChild(document.createTextNode(line));
                });
            }
        });
        modal.appendChild(body);

        if (entry.button) {
            var btn = document.createElement("button");
            btn.className = "info-box-close";
            btn.textContent = entry.button.label || "Close";
            btn.onclick = function () {
                dauntlessEvent("info-box/close:" + entry.button.id);
            };
            modal.appendChild(btn);
        }

        slot.appendChild(modal);
    });
}
