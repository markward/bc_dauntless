// CrewMenuPanel renderer — officer/tactical menus (F1-F5).
// Payload: {menus:[{id,type,label,enabled,visible,open,expanded,children:[...]}]}
// Invoked by the C++ CEF host as setCrewMenus(payload) (payload is a JS
// object, matching the setSdkMirror convention).
//
// Only the OPEN menu renders, as one .bc-panel mounted in #crew-menu-host
// (first child of #tactical-target-stack). No persistent bar: the host is
// empty until a menu is summoned. Submenus expand inline as indented
// accordion rows; expand-state is Python-owned (crew-menu/expand:<id>).
// Leaf buttons fire crew-menu/click:<id>. The payload carries every menu so
// widget ids stay stable for dispatch.

function setCrewMenus(payload) {
  const host = document.getElementById("crew-menu-host");
  if (!host) return;
  host.innerHTML = "";
  for (const menu of payload.menus) {
    if (!menu.open) continue;
    host.appendChild(renderCrewMenu(menu));
  }
}

function renderCrewMenu(menu) {
  const panel = document.createElement("section");
  panel.className = "bc-panel crew-menu";

  const header = document.createElement("header");
  header.className = "bc-panel__header";
  const title = document.createElement("span");
  title.className = "bc-panel__title";
  title.textContent = menu.label;
  header.appendChild(title);
  panel.appendChild(header);

  const body = document.createElement("div");
  body.className = "bc-panel__body";
  appendCrewRows(body, menu.children || [], 0);
  panel.appendChild(body);
  return panel;
}

// Append rows for `nodes` at `depth`, recursing into expanded submenus.
function appendCrewRows(body, nodes, depth) {
  for (const node of nodes) {
    if (node.visible === false) continue;

    if (node.type === "repair-pane") {
      body.appendChild(renderRepairPane(node));
      continue;
    }

    const hasChildren = node.type === "menu" && node.openable !== false && (node.children || []).length > 0;

    const row = document.createElement("div");
    row.className = "crew-menu__row" + (node.enabled ? "" : " disabled") +
                    (hasChildren ? "" : " crew-menu__row--leaf");
    row.setAttribute("data-depth", String(Math.min(depth, 2)));

    if (hasChildren) {
      const caret = document.createElement("span");
      caret.className = "crew-menu__caret";
      caret.textContent = node.expanded ? "▾" : "▸";   // down / right
      row.appendChild(caret);
    }

    const label = document.createElement("span");
    label.className = "crew-menu__label";
    label.textContent = node.label;
    row.appendChild(label);

    if (node.enabled) {
      if (hasChildren) {
        row.onclick = () => dauntlessEvent("crew-menu/expand:" + node.id);
      } else if (node.type === "button") {
        row.onclick = () => dauntlessEvent("crew-menu/click:" + node.id);
      }
    }
    body.appendChild(row);

    if (hasChildren && node.expanded) {
      appendCrewRows(body, node.children, depth + 1);
    }
  }
}

// EngRepairPane projection — three titled areas (REPAIRING/WAITING/
// DESTROYED). REPAIRING and WAITING rows are clickable and fire
// crew-menu/repair:<id> (Task 7's ET_REPAIR_INCREASE_PRIORITY toggle);
// DESTROYED rows are inert (subsystem isn't in the repair queue at all).
function renderRepairPane(node) {
  const pane = document.createElement("div");
  pane.className = "crew-repair-pane";
  const areas = [
    ["REPAIRING", node.repair, true],
    ["WAITING", node.waiting, true],
    ["DESTROYED", node.destroyed, false],
  ];
  for (const [title, rows, clickable] of areas) {
    if (!rows || !rows.length) continue;
    const h = document.createElement("div");
    h.className = "crew-repair-area-title";
    h.textContent = title;
    pane.appendChild(h);
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "crew-repair-row" + (clickable ? "" : " inert");
      row.textContent = r.label + " — " + r.pct + "%";
      if (clickable) {
        row.onclick = () => dauntlessEvent("crew-menu/repair:" + r.id);
      }
      pane.appendChild(row);
    }
  }
  return pane;
}
