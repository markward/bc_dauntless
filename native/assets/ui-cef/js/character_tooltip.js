// Invoked by the host as setCharacterTooltip(payload). Renders the focused
// officer's status rows as a top-centre .bc-panel (shared crew chrome). Only the
// current-tooltip-owner's box shows; {visible:false} clears it.
function setCharacterTooltip(payload) {
  const host = document.getElementById("character-tooltip-host");
  if (!host) return;
  host.innerHTML = "";
  if (!payload || !payload.visible) return;

  const panel = document.createElement("section");
  panel.className = "bc-panel character-tooltip";

  const header = document.createElement("header");
  header.className = "bc-panel__header";
  const title = document.createElement("span");
  title.className = "bc-panel__title";
  title.textContent = payload.title || "";
  header.appendChild(title);
  panel.appendChild(header);

  const body = document.createElement("div");
  body.className = "bc-panel__body";
  for (const line of payload.rows || []) {
    const row = document.createElement("div");
    row.className = "character-tooltip__row";
    row.textContent = line;
    body.appendChild(row);
  }
  panel.appendChild(body);
  host.appendChild(panel);
}
