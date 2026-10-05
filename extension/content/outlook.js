// Outlook on the web adapter (outlook.live.com, outlook.office.com).
(function () {
  const E = window.Localect;
  function isSend(ev) {
    if (ev.type === "click") {
      const b = ev.target.closest && ev.target.closest('button[aria-label="Send"], button[name="Send"], button[title="Send"]');
      return !!b;
    }
    if (ev.type === "keydown" && ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
      return !!(ev.target.closest && ev.target.closest('div[aria-label="Message body"], div[role="textbox"]'));
    }
    return false;
  }
  function read(ev) {
    const body = document.querySelector('div[aria-label="Message body"][contenteditable="true"], div[role="textbox"][contenteditable="true"]');
    let text = E.text(body);
    const divider = body && Array.from(body.querySelectorAll("div, hr")).find((el) => /^From:|^-{3,}\s*Original/i.test(E.text(el)));
    if (divider) text = text.split(E.text(divider))[0].trim();
    const to = Array.from(document.querySelectorAll('div[aria-label^="To"] [title*="@"], div[aria-label^="To"] span'))
      .map((el) => el.getAttribute("title") || E.text(el)).join(",");
    const subject = (document.querySelector('input[aria-label="Add a subject"], input[aria-label="Subject"]') || {}).value
      || E.text(document.querySelector('div[role="main"] h1, div[role="heading"][aria-level="1"]'));
    const items = Array.from(document.querySelectorAll('div[aria-label="Message body"]:not([contenteditable="true"]), div[role="document"]'));
    const last = items.length ? items[items.length - 1] : null;
    const replied_to = last ? { text: E.text(last), from_addr: E.emails(E.text(last.closest("div[role='listitem'], div[data-convid]") || last))[0] || "", from_name: "", date: "", external_id: "" } : null;
    return { text, to_addrs: E.emails(to), subject, thread_id: "", replied_to: replied_to && replied_to.text ? replied_to : null };
  }
  E.register({ name: "outlook", isSend, read });
})();
