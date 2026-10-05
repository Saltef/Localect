# The browser extension

Localect's extension puts Compose next to your mail and chat, and remembers what
you send, with your say-so, into your own Localect on this machine. It talks to
nothing else.

## Install (Chrome or Edge, unpacked)

1. Start Localect (`localect`) and open **Settings → Browser extension**. Copy the
   pairing token.
2. Open `chrome://extensions` (or `edge://extensions`), turn on **Developer
   mode**, click **Load unpacked**, and choose the `extension/` folder of this
   repository.
3. Click the Localect icon → ⚙ (or right-click → Options), paste the token,
   **Save and test**. It should say "Paired with Localect 0.10.0 as you@…".

The token proves to Localect that requests come from your extension and not from
a web page that happens to reach `localhost`. Localect refuses API calls from any
other origin. "New token" in Settings revokes the old one.

## Compose

Click the Localect icon, or select text on any page and choose **Reply with
Localect** from the right-click menu. The side panel runs the whole pipeline
(Reader, Drafter, Rewriter, Critic, Arbiter) on your own Localect and shows the
reply, the gloss, the back-translation, the flags, and where the reply drew
its facts from. **Insert into page** puts the reply into the compose box you
were writing in; **Copy** copies it. You still press send.

## Remembering, like a recorder

On Gmail, Outlook on the web and WhatsApp Web, a small pill sits at the
bottom right:

- **● Localect is remembering this conversation**: when you press send, the
  message you sent and the message it answered are stored in your Localect,
  which strips quoted text and signatures, indexes them, and reads them for
  dated facts. The pill briefly says "Remembered · 2 fact(s)".
- Click the pill to **pause that site**; click again to resume. The
  extension's options page has the same switches.
- **❚❚ capture paused**: memory is paused for everything, from Localect's Memory
  page. Nothing is stored anywhere until you resume.
- Grey: Localect is not running or not paired.

Capture reads the compose box once, at the moment you send. Nothing watches
keystrokes, nothing is captured from drafts, and nothing leaves the machine:
the extension's only network destination is your Localect server on
`127.0.0.1`.

## What is captured, exactly

| field | Gmail | Outlook web | WhatsApp Web |
|---|---|---|---|
| your message | compose body, without the quoted thread | body above the "From:" divider | the text you sent |
| the message it answered | last expanded message in the thread, with sender and date | last message body in the reading pane | last incoming message |
| recipients | To field addresses | To field | the chat name |
| subject and thread | subject box, thread id from the URL | subject | the chat name |

Attachments are never captured. Site selectors are the sites' own DOM as of
September 2026; a redesign degrades to "nothing captured" and never breaks the
page. The generic adapter (`content/generic.js`) documents the contract for any
other site and is what the end-to-end test drives.

## Layout

```
extension/
  manifest.json      Manifest V3, side panel, options, content scripts per site
  background.js      the only code that talks to the server: token, status, badge, capture, compose
  content/core.js    site-agnostic send detection and the capture message
  content/gmail.js, outlook.js, whatsapp.js, generic.js   site adapters
  content/indicator.js   the pill
  panel/             the side panel (Compose)
  options/           server URL, token, per-site switches
```

Everything is plain JavaScript with no build step, so the folder loads as is.
