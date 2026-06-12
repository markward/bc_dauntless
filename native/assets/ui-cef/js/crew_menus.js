// CrewMenuPanel renderer — dauntless-styled menu bar for SDK bridge menus.
// Payload: {menus:[{id,type,label,enabled,visible,children:[...]}]}
// Invoked directly by the C++ CEF host as setCrewMenus(payload) where
// payload is already a JS object (matching the setSdkMirror convention).
let crewMenuOpenId = null;

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
  wrap.className = "crew-menu" + (menu.id === crewMenuOpenId ? " open" : "");
  const title = document.createElement("div");
  title.className = "crew-menu-title" + (menu.enabled ? "" : " disabled");
  title.textContent = menu.label;
  title.onclick = () => {
    crewMenuOpenId = crewMenuOpenId === menu.id ? null : menu.id;
    wrap.classList.toggle("open");
  };
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
