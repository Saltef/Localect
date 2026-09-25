const $ = (id) => document.getElementById(id);
const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, res));
const STATE = { ready: "Ready to send", check: "Check the warnings", escalate: "Needs your attention" };

async function refresh() {
  const s = await send({ type: "status" });
  $("status").textContent = s && s.ok ? `${s.capture ? "● remembering" : "❚❚ capture paused"} · ${s.counts.messages} messages in memory` : (s && s.error) || "not connected";
}

async function prefill() {
  const { pending } = await chrome.storage.session.get("pending");
  if (pending) { $("message").value = pending; await chrome.storage.session.remove("pending"); }
}

async function compose() {
  const message = $("message").value.trim();
  if (!message) return;
  $("error").hidden = true; $("result").hidden = true; $("busy").hidden = false; $("compose").disabled = true;
  const r = await send({ type: "compose", request: { message } });
  $("busy").hidden = true; $("compose").disabled = false;
  if (!r || r.error) { $("error").textContent = (r && r.error) || "no answer"; $("error").hidden = false; return; }
  const res = r.result;
  $("state").textContent = STATE[res.status] || res.status; $("state").className = `badge ${res.status}`;
  $("locale").textContent = `${res.locale.variety} · ${res.locale.locale}`;
  $("reply").textContent = res.final_text; $("reply").dir = res.locale.rtl ? "rtl" : "ltr";
  $("gloss").textContent = res.reading.gloss;
  $("back").textContent = res.back_translation || "";
  $("flags").innerHTML = "";
  for (const f of res.flags || []) {
    const d = document.createElement("div"); d.className = `flag ${f.severity}`; d.textContent = `${f.segment_id} · ${f.kind.replace(/_/g, " ")}: ${f.reason}`; $("flags").appendChild(d);
  }
  const cited = new Set(); for (const e of res.ledger || []) for (const id of e.source_ids) cited.add(id);
  const kinds = {}; for (const s of res.sources || []) if (cited.has(s.id)) kinds[s.kind] = (kinds[s.kind] || 0) + 1;
  const label = { knowledge: "knowledge base", mail: "your mail", fact: "remembered fact", glossary: "glossary", history: "past reply", thread: "this thread" };
  $("sources").textContent = Object.keys(kinds).length ? "Drew on " + Object.entries(kinds).map(([k, n]) => `${n} from ${label[k] || k}`).join(" · ") : "";
  $("result").hidden = false;
}

async function insert() {
  const text = $("reply").textContent;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, args: [text], func: (t) => {
      const el = document.activeElement && document.activeElement.isContentEditable ? document.activeElement
        : document.querySelector('[data-envoy="body"], div[aria-label="Message Body"], div[aria-label="Message body"][contenteditable="true"], footer div[contenteditable="true"], textarea');
      if (!el) return false;
      if ("value" in el && el.tagName !== "DIV") { el.value = t; el.dispatchEvent(new Event("input", { bubbles: true })); return true; }
      el.focus(); document.execCommand("insertText", false, t); return true;
    } });
  } catch (e) { await navigator.clipboard.writeText(text); }
}

$("compose").addEventListener("click", compose);
$("copy").addEventListener("click", () => navigator.clipboard.writeText($("reply").textContent));
$("insert").addEventListener("click", insert);
$("open-options").addEventListener("click", (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
$("message").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) compose(); });
refresh(); prefill();
