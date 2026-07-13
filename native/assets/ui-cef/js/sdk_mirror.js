// SDK UI mirror — Python pushes a JSON tree via setSdkMirror({entries});
// each entry is routed by entry.type into its semantic slot.
// Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md

function setSdkMirror(payload) {
  const entries = (payload && payload.entries) || [];
  renderSubtitle(entries.find(e => e.type === "subtitle"));
  renderStylizedStack(entries.filter(e => e.type === "stylized"));
}

function renderSubtitle(entry) {
  const el = document.getElementById("sdk-subtitle");
  if (!el) return;
  const lines = (entry && entry.lines) || [];
  const hasSpeech = !!(entry && entry.speech);
  if (!entry || !entry.visible || (lines.length === 0 && !hasSpeech)) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  const parts = lines.map(escapeHtml);
  if (hasSpeech) {
    const speaker = entry.speaker
      ? '<span class="sdk-subtitle__speaker">' +
        escapeHtml(entry.speaker) + ":</span> "
      : "";
    parts.push(speaker + escapeHtml(entry.speech));
  }
  el.innerHTML = parts.join("<br>");
}

function renderStylizedStack(entries) {
  const stack = document.getElementById("sdk-stylized-stack");
  if (!stack) return;

  // Upsert visible entries by id.
  for (const entry of entries) {
    if (!entry.visible) continue;
    const domId = "sdk-stylized-" + entry.id;
    let node = document.getElementById(domId);
    if (!node) {
      node = document.createElement("div");
      node.id = domId;
      node.className = "sdk-stylized-window";
      node.onclick = () => dauntlessEvent("sdk-mirror/click:" + entry.id);
      stack.appendChild(node);
    }
    node.innerHTML =
      '<div class="sdk-stylized-window__header">' +
      escapeHtml(entry.title) +
      '</div>';
  }

  // Prune DOM nodes whose IDs are absent or marked invisible in the payload.
  const visibleIds = new Set(
    entries.filter(e => e.visible).map(e => "sdk-stylized-" + e.id)
  );
  for (const child of Array.from(stack.children)) {
    if (!visibleIds.has(child.id)) stack.removeChild(child);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
