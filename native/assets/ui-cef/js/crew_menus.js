// CrewMenuPanel renderer — dauntless-styled bridge menus.
// Payload: {menus:[{id,type,label,enabled,visible,open,children:[...]}]}
// Invoked directly by the C++ CEF host as setCrewMenus(payload) where
// payload is already a JS object (matching the setSdkMirror convention).
//
// Only the OPEN menu renders. There is no persistent title bar: a menu
// appears when summoned (F1-F5 hotkeys; bridge-character click is a future
// path) and disappears when closed. The payload still carries every menu
// so widget ids stay stable for click/toggle dispatch.

function setCrewMenus(payload) {
  const slot = document.getElementById("crew-menu-bar");
  if (!slot) return;
  slot.innerHTML = "";
  for (const menu of payload.menus) {
    if (!menu.open) continue;
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
  if (menu.enabled) {
    title.onclick = () => dauntlessEvent("crew-menu/toggle:" + menu.id);
  }
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
