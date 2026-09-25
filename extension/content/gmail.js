// Gmail adapter. Selectors are Gmail's as of 2026; each is tried in order and
// a miss is logged rather than thrown, so a redesign degrades to "nothing
// captured" and never breaks the page.
(function () {
  const E = window.Envoy;
  const SEND = ['div[role="button"][data-tooltip^="Send"]', 'div[role="button"][aria-label^="Send"]', 'div[role="button"].T-I-atl'];
  const q = (root, sels) => { for (const s of sels) { const el = root.querySelector(s); if (el) return el; } return null; };

  function composeOf(el) {
    return el.closest('div[role="dialog"]') || el.closest("div.nH.Hd") || el.closest("td.Bu") || el.closest("div.AD") || null;
  }
  function isSend(ev) {
    if (ev.type === "click") {
      const b = ev.target.closest && ev.target.closest('div[role="button"]');
      return !!(b && SEND.some((s) => b.matches(s)));
    }
    if (ev.type === "keydown" && ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
      return !!(ev.target.closest && ev.target.closest('div[aria-label="Message Body"], div[g_editable="true"]'));
    }
    return false;
  }
  function read(ev) {
    const compose = composeOf(ev.target);
    if (!compose) return null;
    const body = q(compose, ['div[aria-label="Message Body"]', 'div[g_editable="true"]', 'div[contenteditable="true"]']);
    let text = E.text(body);
    // Drop Gmail's quoted thread from the body: the server strips quotes too,
    // but the quote container is easy to remove here and keeps the payload small.
    const quote = body && body.querySelector("div.gmail_quote, blockquote");
    if (quote) text = text.replace(E.text(quote), "").trim();
    const to = Array.from(compose.querySelectorAll('input[name="to"], span[email], div[data-hovercard-id]'))
      .map((el) => el.getAttribute("email") || el.getAttribute("data-hovercard-id") || el.value || "").join(",");
    const subject = (q(compose, ['input[name="subjectbox"]']) || {}).value || E.text(document.querySelector("h2.hP"));
    // The message being answered: the last expanded message in the open thread.
    const msgs = Array.from(document.querySelectorAll("div.adn.ads, div.gs"));
    const last = msgs.length ? msgs[msgs.length - 1] : null;
    let replied_to = null;
    if (last) {
      const sender = last.querySelector("span.gD, span[email]");
      replied_to = {
        text: E.text(last.querySelector("div.a3s, div.ii.gt")),
        from_addr: sender ? (sender.getAttribute("email") || "") : "",
        from_name: sender ? (sender.getAttribute("name") || E.text(sender)) : "",
        date: (last.querySelector("span.g3") || {}).title || "",
        external_id: (last.querySelector("[data-legacy-message-id]") || {}).getAttribute?.("data-legacy-message-id") || "",
      };
      if (!replied_to.text) replied_to = null;
    }
    const thread = (location.hash.match(/\/([A-Za-z]{10,})$/) || [])[1] || "";
    return { text, to_addrs: E.emails(to), subject, thread_id: thread ? `gmail:${thread}` : "", replied_to };
  }
  E.register({ name: "gmail", isSend, read });
})();
