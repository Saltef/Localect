// WhatsApp Web adapter. A chat message has no address: the contact is the
// chat title, kept as from_name / the reply's recipient string.
(function () {
  const E = window.Localect;
  const box = () => document.querySelector('footer div[contenteditable="true"][role="textbox"], footer div[contenteditable="true"]');
  function isSend(ev) {
    if (ev.type === "click") return !!(ev.target.closest && ev.target.closest('footer button[aria-label="Send"], footer span[data-icon="send"]'));
    if (ev.type === "keydown" && ev.key === "Enter" && !ev.shiftKey) return !!(ev.target.closest && ev.target.closest("footer"));
    return false;
  }
  function read() {
    const text = E.text(box());
    const title = E.text(document.querySelector("header span[title], header [data-testid='conversation-info-header-chat-title']"));
    const incoming = Array.from(document.querySelectorAll("div.message-in span.selectable-text, div.message-in span.copyable-text"));
    const last = incoming.length ? incoming[incoming.length - 1] : null;
    return {
      text, to_addrs: [], subject: title ? `WhatsApp: ${title}` : "WhatsApp", thread_id: title ? `whatsapp:${title}` : "",
      replied_to: last ? { text: E.text(last), from_addr: "", from_name: title, date: "", external_id: "" } : null,
    };
  }
  E.register({ name: "whatsapp", isSend, read });
})();
