"""Reduce a message body to what its author wrote.

Mail clients append the whole thread below a reply and a signature after it.
Stored as is, one fact would be indexed once per message in the thread and
the newest statement would drown among its own quotations. Everything from
the first quote marker on is dropped, then the signature."""

from __future__ import annotations

import re
from html.parser import HTMLParser

# "On <date>, <name> wrote:" and its equivalents. Each may wrap onto a second line.
_REPLY_HEADERS = [
    r"^On .{4,200}?wrote:\s*$",                     # en
    r"^Le .{4,200}?a écrit\s*:\s*$",                # fr
    r"^El .{4,200}?escribió:\s*$",                  # es
    r"^Em .{4,200}?escreveu:\s*$",                  # pt
    r"^Am .{4,200}?schrieb .{0,100}?:\s*$",         # de
    r"^\d{4}[/年.\-]\d{1,2}.{1,120}?<[^>]+>\s*[:：]\s*$",  # Gmail, ja and others: date name <addr>:
    r"^في .{4,200}?كتب.{0,40}:\s*$",                # ar
    r"^-{2,}\s*(?:Original Message|Mensaje original|Message d'origine|Mensagem original|"
    r"Ursprüngliche Nachricht|元のメッセージ|الرسالة الأصلية)\s*-{2,}\s*$",
    r"^_{10,}\s*$",                                 # Outlook's divider before From:/Sent:
    r"^(?:From|De|Von|差出人|من):\s.{1,200}$",       # a forwarded header block
]
_REPLY = re.compile("|".join(f"(?:{h})" for h in _REPLY_HEADERS), re.IGNORECASE | re.MULTILINE)
_QUOTE = re.compile(r"^\s*>", re.MULTILINE)
_SIGNATURE = re.compile(r"^-- ?$", re.MULTILINE)
_SENT_FROM = re.compile(
    r"^(?:Sent from my|Enviado desde mi|Envoyé de mon|Von meinem .* gesendet|Enviado do meu|"
    r"iPhone から送信|أرسلت من)\b.*$", re.MULTILINE | re.IGNORECASE)
_MULTI_BLANK = re.compile(r"\n{3,}")


class _Text(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "table"}
    _SKIP = {"style", "script", "head", "title"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._quote = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag == "blockquote":
            self._quote += 1
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "blockquote" and self._quote:
            self._quote -= 1
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and not self._quote:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Visible text, block elements as line breaks, quoted blocks dropped."""
    p = _Text()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _MULTI_BLANK.sub("\n\n", text).strip()


def strip_quotes(text: str) -> str:
    """Everything the author wrote above the first quoted reply."""
    cut = len(text)
    m = _REPLY.search(text)
    if m:
        cut = min(cut, m.start())
    m = _QUOTE.search(text)
    if m:
        cut = min(cut, m.start())
    return text[:cut].rstrip()


def strip_signature(text: str) -> str:
    m = _SIGNATURE.search(text)
    if m:
        text = text[:m.start()]
    m = _SENT_FROM.search(text)
    if m:
        text = text[:m.start()]
    return text.rstrip()


def clean_body(text: str, html: bool = False) -> str:
    if html:
        text = html_to_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = strip_signature(strip_quotes(text))
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return _MULTI_BLANK.sub("\n\n", text).strip()
