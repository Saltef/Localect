// Envoy extension: the one place that talks to the local server.
// Content scripts and the side panel send messages here; this worker adds the
// pairing token and the server URL, and keeps the badge in step with capture.

const DEFAULTS = { server: "http://127.0.0.1:8765", token: "", sites: {} };

async function config() {
  const c = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...c };
}

async function call(path, init = {}) {
  const c = await config();
  const r = await fetch(c.server.replace(/\/$/, "") + path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${c.token}`, ...(init.headers || {}) },
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = body.detail || r.statusText;
    throw new Error(r.status === 401 ? "Not paired: paste the token from Envoy's Settings page into the extension options." : String(detail));
  }
  return body;
}

async function status() {
  try {
    const s = await call("/api/extension/status");
    await setBadge(s.capture ? "on" : "paused");
    return { ok: true, ...s };
  } catch (e) {
    await setBadge("off");
    return { ok: false, error: String(e.message || e) };
  }
}

async function setBadge(state) {
  const map = { on: ["●", "#16a34a"], paused: ["❚❚", "#d97706"], off: ["", "#71717a"] };
  const [text, color] = map[state] || map.off;
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
}

// Capture: the message the user just sent, and the one it answered, both
// stored on the local server only. Nothing is captured while capture is
// paused in Envoy, or while the site is off in the extension's options.
async function capture(payload, site) {
  const c = await config();
  if (c.sites[site] === false) return { stored: false, reason: "site is off in the extension" };
  const results = [];
  if (payload.replied_to && payload.replied_to.text) {
    results.push(await call("/api/messages", { method: "POST", body: JSON.stringify({
      text: payload.replied_to.text, from_addr: payload.replied_to.from_addr || "",
      from_name: payload.replied_to.from_name || "", to_addrs: payload.replied_to.to_addrs || [],
      subject: payload.subject || "", thread_id: payload.thread_id || "", date: payload.replied_to.date || "",
      external_id: payload.replied_to.external_id || "", is_mine: false, origin: "capture",
    }) }));
  }
  results.push(await call("/api/messages", { method: "POST", body: JSON.stringify({
    text: payload.text, from_addr: payload.from_addr || "", to_addrs: payload.to_addrs || [],
    subject: payload.subject || "", thread_id: payload.thread_id || "", is_mine: true, origin: "capture",
  }) }));
  const mine = results[results.length - 1];
  await status();
  return { stored: !!mine.stored, reason: mine.reason || "", facts: mine.facts || 0, count: results.length };
}

chrome.runtime.onMessage.addListener((msg, sender, respond) => {
  (async () => {
    try {
      if (msg.type === "status") respond(await status());
      else if (msg.type === "capture") respond(await capture(msg.payload, msg.site));
      else if (msg.type === "compose") respond(await call("/api/compose", { method: "POST", body: JSON.stringify(msg.request) }));
      else if (msg.type === "config") respond(await config());
      else if (msg.type === "setSite") {
        const c = await config();
        c.sites[msg.site] = msg.enabled;
        await chrome.storage.local.set({ sites: c.sites });
        respond({ ok: true, sites: c.sites });
      } else if (msg.type === "openPanel" && sender.tab) {
        await chrome.sidePanel.open({ tabId: sender.tab.id });
        respond({ ok: true });
      } else respond({ error: "unknown message" });
    } catch (e) {
      respond({ error: String(e.message || e) });
    }
  })();
  return true; // async response
});

chrome.runtime.onInstalled.addListener(async () => {
  chrome.contextMenus.create({ id: "envoy-reply", title: "Reply with Envoy", contexts: ["selection"] });
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  await status();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "envoy-reply" && tab) {
    await chrome.storage.session.set({ pending: info.selectionText || "" });
    await chrome.sidePanel.open({ tabId: tab.id });
  }
});

chrome.runtime.onStartup.addListener(status);
