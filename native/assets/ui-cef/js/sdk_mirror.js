// SDK UI mirror — Python pushes a JSON tree via setSdkMirror({entries});
// each entry is routed by entry.type into its semantic slot.
// Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md

function setSdkMirror(payload) {
  const entries = (payload && payload.entries) || [];
  const subtitle = entries.find(e => e.type === "subtitle");
  renderSubtitle(subtitle);
  renderEpisodeTitle(subtitle);
  renderStylizedStack(entries.filter(e => e.type === "stylized"));
}

function renderSubtitle(entry) {
  const el = document.getElementById("sdk-subtitle");
  if (!el) return;
  const lines = (entry && entry.lines) || [];
  const hasSpeech = !!(entry && entry.speech);
  // Same liveness check as renderEpisodeTitle's -- entry is the SAME
  // "subtitle" payload object passed to both, so this always agrees with
  // whether the card is actually showing. Only E2M1 puts both a title and
  // a caption on screen at once; lifting the caption here (rather than
  // permanently raising the card) is what keeps every other mission's
  // caption at its normal height -- see the CSS comment on
  // .sdk-subtitle--title-live.
  if (entry && entry.visible && entry.title_text) {
    el.classList.add("sdk-subtitle--title-live");
  } else {
    el.classList.remove("sdk-subtitle--title-live");
  }
  if (!entry || !entry.visible || (lines.length === 0 && !hasSpeech)) {
    el.hidden = true;
    el.innerHTML = "";
    // Reset so a fading banner never leaves the box dimmed for whatever
    // (caption or banner) shows in it next.
    el.style.opacity = "1";
    return;
  }
  el.hidden = false;
  // Banner lines carry their own fade opacity, computed in Python and
  // rewritten every frame (runs on wall-clock, does NOT freeze under
  // pause -- see sdk_mirror.css); crew captions pop on and off at full
  // opacity.
  const parts = lines.map(line =>
    '<span class="sdk-subtitle__line" style="opacity:' +
    Number(line.opacity).toFixed(3) + '">' + escapeHtml(line.text) + "</span>"
  );
  if (hasSpeech) {
    const speaker = entry.speaker
      ? '<span class="sdk-subtitle__speaker">' +
        escapeHtml(entry.speaker) + "</span>"
      : "";
    parts.push(speaker + escapeHtml(entry.speech));
    // A caption must never be dimmed by a co-resident banner's fade: hold
    // the container at full opacity and let only the (unfaded) line spans
    // control text opacity.
    el.style.opacity = "1";
  } else {
    // No crew line: this is a banner-only render. Mirror the box's opacity
    // onto its own fade so the dark body + salmon rule fade with the text
    // instead of popping in/out at full alpha around faded-out letters.
    // Multiple banner lines can be at different points in their own fade;
    // use the strongest one so the box isn't hidden while any line is
    // still visible.
    const maxLineOpacity = lines.length > 0
      ? Math.max(...lines.map(line => Number(line.opacity)))
      : 1;
    el.style.opacity = maxLineOpacity.toFixed(3);
  }
  el.innerHTML = parts.join("<br>");
}

function renderEpisodeTitle(entry) {
  const el = document.getElementById("sdk-episode-title");
  if (!el) return;
  if (!entry || !entry.visible || !entry.title_text) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.querySelector(".sdk-episode__eyebrow").textContent =
    entry.title_eyebrow || "";
  el.querySelector(".sdk-episode__title").textContent = entry.title_text;
  el.style.opacity = Number(
    entry.title_opacity === undefined ? 1 : entry.title_opacity
  ).toFixed(3);
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
