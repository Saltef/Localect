const $ = (id) => document.getElementById(id);
const SITES = [["gmail", "Gmail"], ["outlook", "Outlook on the web"], ["whatsapp", "WhatsApp Web"]];
const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, res));

async function load() {
  const c = await send({ type: "config" });
  $("server").value = c.server; $("token").value = c.token;
  $("sites").innerHTML = "";
  for (const [id, name] of SITES) {
    const l = document.createElement("label"); l.style.display = "flex"; l.style.gap = "8px"; l.style.alignItems = "center"; l.style.margin = "6px 0";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = c.sites[id] !== false;
    cb.addEventListener("change", () => send({ type: "setSite", site: id, enabled: cb.checked }));
    l.append(cb, document.createTextNode(name)); $("sites").appendChild(l);
  }
}
$("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ server: $("server").value.trim() || "http://127.0.0.1:8765", token: $("token").value.trim() });
  const s = await send({ type: "status" });
  $("msg").textContent = s && s.ok ? `Paired with Envoy ${s.version}${s.user_email ? " as " + s.user_email : ""}.` : (s && s.error) || "not connected";
});
load();
