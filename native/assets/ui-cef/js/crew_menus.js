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

// BC's two attention verbs, rendered distinctly. Applied to every id-bearing
// row on both render paths below — expandable submenu (caret) rows equally
// with leaf rows and repair-pane rows, since the E1M1 ShowPointerArrow target
// ("Set Course") is itself a submenu row.
//
//   node.attention   <- MissionLib.ShowPointerArrow: BC drew an LCARS arrow
//                       beside the widget; we pulse a ring around the row
//                       instead (identifier-centric — cannot mis-place).
//   node.highlighted <- TGUIObject.SetHighlighted, driven by E1M1's
//                       SetUIObjectHighlighted script action: BC's own lit /
//                       selected widget state. Steady, never pulsing — it is
//                       also plain list selection outside the tutorial.
//
// Both can be set at once; the classes compose.
function applyHighlightClasses(el, node) {
  if (!node) return;
  if (node.attention) {
    el.classList.add("crew-menu__row--attention");
    if (node.attentionColor) {
      el.style.setProperty("--attention-color", node.attentionColor);
    }
  }
  if (node.highlighted) {
    el.classList.add("crew-menu__row--highlighted");
  }
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
    applyHighlightClasses(row, node);

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
  applyHighlightClasses(pane, node);
  // kind drives the styling: the repair-team area reads loudest (active teal
  // marker + rule), damaged is muted-but-clickable, destroyed is inert. BC
  // repairs several systems in parallel (up to the ship's repair-team count),
  // so the whole top group is "currently being worked", not a single row.
  // Header strings are the original BC labels from Bridge Menus.TGL
  // (REPAIR_AREA_LABEL / WAITING_AREA_LABEL / DESTROYED_AREA_LABEL).
  const areas = [
    ["Repair team assignments:", node.repair, true, "repairing"],
    ["Damaged systems:", node.waiting, true, "waiting"],
    ["Destroyed systems:", node.destroyed, false, "destroyed"],
  ];
  const waitingCount = (node.waiting || []).length;
  for (const [title, rows, clickable, kind] of areas) {
    if (!rows || !rows.length) continue;
    const h = document.createElement("div");
    h.className = "crew-repair-area-title crew-repair-area-title--" + kind;
    h.textContent = title;
    pane.appendChild(h);
    // Hint under the repair-team header: explain the click affordance, but
    // only when there are damaged systems to promote.
    if (kind === "repairing" && waitingCount) {
      const hint = document.createElement("div");
      hint.className = "crew-repair-hint";
      hint.textContent = "click a damaged system to prioritize";
      pane.appendChild(hint);
    }
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "crew-repair-row crew-repair-row--" + kind +
                      (clickable ? "" : " inert");
      applyHighlightClasses(row, r);
      // Fixed-width marker slot on every row keeps labels aligned; only
      // actively-repaired rows light it.
      const mark = document.createElement("span");
      mark.className = "crew-repair-mark";
      mark.textContent = kind === "repairing" ? "●" : "";   // ● when active
      row.appendChild(mark);
      const label = document.createElement("span");
      label.className = "crew-repair-label";
      label.textContent = r.label + " — " + r.pct + "%";
      row.appendChild(label);
      if (clickable) {
        row.onclick = () => dauntlessEvent("crew-menu/repair:" + r.id);
      }
      pane.appendChild(row);
    }
  }
  return pane;
}
