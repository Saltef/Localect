// The recording-style pill: visible whenever memory is on for this site, one
// click to pause the site, one to open the side panel. Nothing is captured
// while it says paused or is absent.
(function () {
  const E = window.Envoy;
  const site = () => (E.adapter && E.adapter.name) || "site";
  let pill, dot, label, state = { ok: false, capture: false, siteOn: true };

  function render() {
    if (!pill) return;
    const on = state.ok && state.capture && state.siteOn;
    dot.style.background = on ? "#16a34a" : state.ok ? "#d97706" : "#71717a";
    label.textContent = !state.ok ? "Envoy: not connected" : !state.capture ? "Envoy: capture paused" : !state.siteOn ? `Envoy: off on ${site()}` : "Envoy is remembering this conversation";
    pill.title = on ? "Click to pause on this site" : "Click to resume on this site";
  }
  function mount() {
    if (pill) return;
    pill = document.createElement("div");
    pill.setAttribute("data-envoy-indicator", "");
    Object.assign(pill.style, { position: "fixed", right: "16px", bottom: "16px", zIndex: 2147483646, display: "flex", alignItems: "center", gap: "8px",
      padding: "6px 12px", borderRadius: "999px", background: "rgba(24,24,27,.92)", color: "#fafafa", font: "12px/1.2 system-ui, sans-serif",
      boxShadow: "0 4px 16px rgba(0,0,0,.25)", cursor: "pointer", userSelect: "none" });
    dot = document.createElement("span");
    Object.assign(dot.style, { width: "8px", height: "8px", borderRadius: "50%", display: "inline-block" });
    label = document.createElement("span");
    const open = document.createElement("span");
    open.textContent = "↗";
    open.title = "Open Envoy";
    open.style.opacity = ".7";
    pill.append(dot, label, open);
    pill.addEventListener("click", (ev) => {
      if (ev.target === open) { chrome.runtime.sendMessage({ type: "openPanel" }); return; }
      state.siteOn = !state.siteOn;
      chrome.runtime.sendMessage({ type: "setSite", site: site(), enabled: state.siteOn }, () => render());
    });
    document.documentElement.appendChild(pill);
    render();
  }
  function refresh() {
    chrome.runtime.sendMessage({ type: "status" }, (s) => {
      if (chrome.runtime.lastError || !s) return;
      state.ok = !!s.ok; state.capture = !!s.capture;
      chrome.runtime.sendMessage({ type: "config" }, (c) => {
        state.siteOn = !(c && c.sites && c.sites[site()] === false);
        mount(); render();
      });
    });
  }
  E.notify = (r) => {
    if (!pill || !r) return;
    const was = label.textContent;
    label.textContent = r.error ? `Envoy: ${r.error}` : r.stored ? `Remembered${r.facts ? ` · ${r.facts} fact(s)` : ""}` : `Not remembered: ${r.reason || "paused"}`;
    pill.setAttribute("data-envoy-last", r.error ? "error" : r.stored ? "stored" : "skipped");
    setTimeout(() => { label.textContent = was; }, 4000);
  };
  refresh();
  setInterval(refresh, 60000);
})();
