// Generic adapter for any page that opts in with data attributes, and the one
// the end-to-end test drives:
//   <textarea data-envoy="body">, <input data-envoy="to">, <input data-envoy="subject">,
//   <div data-envoy="replied-to" data-from="…" data-name="…">text</div>,
//   <button data-envoy="send">
(function () {
  const E = window.Envoy;
  function isSend(ev) {
    return ev.type === "click" && !!(ev.target.closest && ev.target.closest('[data-envoy="send"]'));
  }
  function read() {
    const body = document.querySelector('[data-envoy="body"]');
    const text = body ? (body.value ?? E.text(body)) : "";
    const to = (document.querySelector('[data-envoy="to"]') || {}).value || "";
    const subject = (document.querySelector('[data-envoy="subject"]') || {}).value || "";
    const rt = document.querySelector('[data-envoy="replied-to"]');
    return { text, to_addrs: E.emails(to), subject, thread_id: (document.querySelector('[data-envoy="thread"]') || {}).value || "",
      replied_to: rt ? { text: E.text(rt), from_addr: rt.dataset.from || "", from_name: rt.dataset.name || "", date: rt.dataset.date || "", external_id: rt.dataset.id || "" } : null };
  }
  E.register({ name: "generic", isSend, read });
})();
