// Site-agnostic capture. A site adapter (gmail.js, outlook.js, …) registers
// itself with the selectors below; this file watches for the send and hands
// the message to the background worker. It never reads keystrokes: the text
// is read once, at the moment the user sends it.
//
// Adapter contract:
//   name           "gmail"
//   isSend(event)  true when the event is the user sending (click on a send
//                  button, or Ctrl/Cmd+Enter inside the compose body)
//   read(event)    { text, to_addrs, subject, thread_id, replied_to: { text,
//                  from_addr, from_name, date, external_id } | null } or null
window.Envoy = window.Envoy || {};
(function () {
  const E = window.Envoy;
  E.adapter = null;
  E.register = (adapter) => { E.adapter = adapter; };
  E.text = (el) => (el ? (el.innerText || el.textContent || "") : "").replace(/ /g, " ").trim();
  E.emails = (s) => Array.from(new Set(((s || "").match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) || []).map((a) => a.toLowerCase())));

  async function onSend(ev) {
    const a = E.adapter;
    if (!a || !a.isSend(ev)) return;
    let payload;
    try { payload = a.read(ev); } catch (e) { console.debug("[envoy] read failed", e); return; }
    if (!payload || !payload.text || payload.text.length < 2) return;
    chrome.runtime.sendMessage({ type: "capture", site: a.name, payload }, (r) => {
      if (chrome.runtime.lastError) return;
      if (E.notify) E.notify(r);
    });
  }
  // Capture phase, so the site's own handler (which may remove the compose
  // box) runs after we have read the text.
  document.addEventListener("click", onSend, true);
  document.addEventListener("keydown", onSend, true);
})();
