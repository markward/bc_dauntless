// CrewMenuPanel renderer — dauntless-styled menu bar for SDK bridge menus.
// Payload: {menus:[{id,type,label,enabled,visible,children:[...]}]}
// Invoked directly by the C++ CEF host as setCrewMenus(payload) where
// payload is already a JS object (matching the setSdkMirror convention).

function setCrewMenus(payload) {
  const slot = document.getElementById("crew-menu-bar");
  if (!slot) return;
  slot.innerHTML = "";
  for (const menu of payload.menus) {
    slot.appendChild(renderCrewMenu(menu));
  }
}

function renderCrewMenu(menu) {
  const wrap = document.createElement("div");
  wrap.className = "crew-menu" + (menu.open ? " open" : "");
  const title = document.createElement("div");
  title.className = "crew-menu-title" + (menu.enabled ? "" : " disabled");
  title.textContent = menu.label;
  // Open-state lives in CrewMenuPanel (shared with F1-F5 hotkeys);
  // the next setCrewMenus payload re-renders with the new state.
  title.onclick = () => dauntlessEvent("crew-menu/toggle:" + menu.id);
  wrap.appendChild(title);
  const drop = document.createElement("div");
  drop.className = "crew-menu-drop";
  for (const child of menu.children || []) {
    drop.appendChild(renderCrewMenuEntry(child));
  }
  wrap.appendChild(drop);
  return wrap;
}

function renderCrewMenuEntry(node) {
  if (node.visible === false) return document.createDocumentFragment();
  const row = document.createElement("div");
  row.className = "crew-menu-entry " + node.type +
                  (node.enabled ? "" : " disabled");
  row.textContent = node.label;
  if (node.type === "button" && node.enabled) {
    row.onclick = () => dauntlessEvent("crew-menu/click:" + node.id);
  }
  if (node.type === "menu" && (node.children || []).length) {
    const sub = document.createElement("div");
    sub.className = "crew-menu-sub";
    for (const child of node.children) {
      sub.appendChild(renderCrewMenuEntry(child));
    }
    row.appendChild(sub);
  }
  return row;
}
