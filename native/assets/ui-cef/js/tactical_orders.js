// Renders the tactical Orders / Tactics / Maneuvers command panes.
// Payload: { visible, orders[], tactics[], maneuvers[] }, each row
// { label, id, chosen, enabled }. Mounts into #tactical-orders-host.
function setTacticalOrders(payload) {
  var host = document.getElementById("tactical-orders-host");
  if (!host) return;
  if (!payload || !payload.visible) { host.innerHTML = ""; return; }
  host.innerHTML = "";
  var groups = [["Orders", payload.orders],
                ["Maneuvers", payload.maneuvers],
                ["Tactics", payload.tactics]];
  groups.forEach(function (g) {
    var title = g[0], rows = g[1] || [];
    if (!rows.length) return;
    var section = document.createElement("section");
    section.className = "bc-panel tactical-orders";
    var head = document.createElement("div");
    head.className = "bc-panel__header";
    head.innerHTML = '<span class="bc-panel__title">' + title + "</span>";
    section.appendChild(head);
    var body = document.createElement("div");
    body.className = "bc-panel__body";
    rows.forEach(function (r) {
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
