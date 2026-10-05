// Generic adapter for any page that opts in with data attributes, and the one
// the end-to-end test drives:
//   <textarea data-localect="body">, <input data-localect="to">, <input data-localect="subject">,
//   <div data-localect="replied-to" data-from="…" data-name="…">text</div>,
//   <button data-localect="send">
(function () {
  const E = window.Localect;
  function isSend(ev) {
    return ev.type === "click" && !!(ev.target.closest && ev.target.closest('[data-localect="send"]'));
  }
  function read() {
    const body = document.querySelector('[data-localect="body"]');
    const text = body ? (body.value ?? E.text(body)) : "";
    const to = (document.querySelector('[data-localect="to"]') || {}).value || "";
    const subject = (document.querySelector('[data-localect="subject"]') || {}).value || "";
    const rt = document.querySelector('[data-localect="replied-to"]');
    return { text, to_addrs: E.emails(to), subject, thread_id: (document.querySelector('[data-localect="thread"]') || {}).value || "",
      replied_to: rt ? { text: E.text(rt), from_addr: rt.dataset.from || "", from_name: rt.dataset.name || "", date: rt.dataset.date || "", external_id: rt.dataset.id || "" } : null };
  }
  E.register({ name: "generic", isSend, read });
})();
