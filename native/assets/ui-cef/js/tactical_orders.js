// Renders the tactical Orders / Tactics / Maneuvers command panes.
// Payload: { visible, orders, tactics, maneuvers }, each group an object
// { collapsible, expanded, rows[], current } where rows are
// { label, id, chosen, enabled }.
//
// Orders is never collapsible (collapsible: false, expanded: true always)
// and always renders every row in the existing 2-column grid.
//
// Maneuvers and Tactics are BC's STCharacterMenu popups: collapsed
// (expanded: false, the default) they show only the header + a single row
// for `current` (the chosen selection, or the SDK's own fallback already
// resolved server-side) plus a "▶" affordance; expanded (expanded: true)
// they show the header + every row from `rows` plus a "▼" marker. Clicking
// the header toggles expand state (`tactical-orders/toggle:<group>`, pure
// UI, no SDK call); clicking an option row activates it AND collapses the
// group (unchanged `tactical-orders/click:<id>` path, collapse happens
// server-side).
//
// Mounts into #tactical-orders-host.
function setTacticalOrders(payload) {
  var host = document.getElementById("tactical-orders-host");
  if (!host) return;
  if (!payload || !payload.visible) { host.innerHTML = ""; return; }
  host.innerHTML = "";
  var groups = [["Orders", "orders", payload.orders],
                ["Maneuvers", "maneuvers", payload.maneuvers],
                ["Tactics", "tactics", payload.tactics]];
  groups.forEach(function (g) {
    var title = g[0], group = g[1], entry = g[2];
    if (!entry || !entry.rows || !entry.rows.length) return;

    var section = document.createElement("section");
    section.className = "bc-panel tactical-orders";
    section.setAttribute("data-group", group);
    if (entry.collapsible) {
      section.classList.add(entry.expanded ? "is-expanded" : "is-collapsed");
    }

    var head = document.createElement("div");
    head.className = "bc-panel__header";
    var titleHtml = '<span class="bc-panel__title">' + title + "</span>";
    if (entry.collapsible) {
      titleHtml += '<span class="tactical-orders__marker">'
        + (entry.expanded ? "▼" : "▶") + "</span>";
    }
    head.innerHTML = titleHtml;
    if (entry.collapsible) {
      head.classList.add("tactical-orders__header--clickable");
      head.addEventListener("click", function () {
        dauntlessEvent("tactical-orders/toggle:" + group);
      });
    }
    section.appendChild(head);

    var body = document.createElement("div");
    body.className = "bc-panel__body";
    var displayRows = entry.rows;
    if (entry.collapsible && !entry.expanded) {
      displayRows = entry.current ? [entry.current] : [];
    }
    displayRows.forEach(function (r) {
      var el = document.createElement("div");
      el.className = "tactical-orders__row"
        + (r.chosen ? " is-chosen" : "")
        + (r.enabled ? "" : " is-disabled");
      el.textContent = r.label;
      if (r.enabled) {
        el.addEventListener("click", function () {
          dauntlessEvent("tactical-orders/click:" + r.id);
        });
      }
      body.appendChild(el);
    });
    section.appendChild(body);
    host.appendChild(section);
  });
}
