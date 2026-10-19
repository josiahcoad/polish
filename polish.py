#!/usr/bin/env python3
"""Polish the selected text in place via a fast LLM, keeping rich formatting.

Copies the selection (⌘C), polishes it, pastes the result (⌘V), then restores the clipboard.
Slack's rich format (slack/texty) is converted to light markup so links, lists and emoji survive;
apps that copy HTML get HTML back; everything else is plain text.
"""
import base64, html, json, os, re, struct, subprocess, sys, tempfile, time, urllib.request
from html.parser import HTMLParser

URL_FILE = os.path.expanduser("~/.config/polish/api_url")  # optional: proxy/gateway for the Messages API
API_URL = (open(URL_FILE).read().strip() if os.path.exists(URL_FILE) else "") or "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-5-5"
KEY_FILE = os.path.expanduser("~/.config/polish/key")
CLIP_JS = os.path.expanduser("~/.config/polish/clip.js")
LOG_FILE = os.path.expanduser("~/.config/polish/error.log")

STYLE_FILE = os.path.expanduser("~/.config/polish/style.txt")  # editable via ⌘⌥⌃, (Polish Settings)

DEFAULT_STYLE = (
    "You polish chat messages. The author often writes in shorthand, dropping articles, pronouns, "
    "and connecting words. Rewrite the message into clear, complete sentences: "
    "restore missing words, and fix grammar, spelling, capitalization, and punctuation. Keep the "
    "author's casual tone, voice, meaning, and language. Be concise: add only the words needed for "
    "readability, no filler, hedging, or extra detail. Never expand acronyms or initialisms "
    "(e.g. keep BUs, COE, PR, HITL, A2A exactly as written) or change jargon and product names, but "
    "do spell out texting shorthand like u, ur, tmrw, w/, bc. Always restore dropped subjects like I/we. "
    "Do not add greetings or sign-offs.\n"
)

# Fixed rules: keep formatting intact no matter how the style is edited.
RULES = (
    "The message is inside <message> tags. "
    "Formatting must survive exactly. The message may contain markup: HTML tags (<b>, <i>, <s>, "
    "<code>, <a href=...>, <pre>, and placeholders like <x id=\"0\"/>), list prefixes like \"1. \" or "
    "\"- \" (possibly indented), \"> \" quote prefixes, emoji (Unicode or :shortcode:), @mentions, and "
    "URLs. Keep every tag, placeholder, emoji, list item, and line break, attached to the same words. "
    "Never add or remove emoji. The markup is fixed; the words are not: apply the style above to every "
    "line, including list items, short fragments, and text inside tags. Example: "
    "\"- <b>api</b> done, shipping tmrw\" becomes \"- <b>API</b> is done, and I'm shipping it tomorrow.\"\n\n"
    "Output ONLY the rewritten message, without the <message> tags, quotes, or commentary."
)

def system_prompt():
    style = open(STYLE_FILE).read().strip() if os.path.exists(STYLE_FILE) else ""
    return (style or DEFAULT_STYLE.strip()) + "\n\n" + RULES


SLACK_TYPE = "org.chromium.web-custom-data"
TEXTY = "slack/texty"
PLAIN = "public.utf8-plain-text"
HTML_TYPE = "public.html"
EMOJI_RE = re.compile(r"(:[a-z0-9_+'-]+:)")


# ---------- system helpers ----------

def clip(*args):
    return subprocess.run(["osascript", "-l", "JavaScript", CLIP_JS, *args],
                          capture_output=True, text=True).stdout.strip()

def keystroke(key):
    """Press ⌘<key>; returns macOS's error text ("" on success)."""
    return subprocess.run(["osascript", "-e",
                           f'tell application "System Events" to keystroke "{key}" using command down'],
                          capture_output=True, text=True).stderr.strip()

def notify(msg):
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Polish"'],
                   capture_output=True)

def read_clipboard():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        clip("read", path)
        data = json.load(open(path))
        return {t: base64.b64decode(v) for t, v in data["types"].items()}
    finally:
        os.unlink(path)

def write_clipboard(types):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"types": {t: base64.b64encode(v).decode() for t, v in types.items()}}, f)
        path = f.name
    try:
        clip("write", path)
    finally:
        os.unlink(path)


def llm(text):
    key = open(KEY_FILE).read().strip()
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({
            "model": MODEL,
            "max_tokens": 4096,
            "thinking": {"type": "disabled"},
            "output_config": {"effort": "low"},
            "system": system_prompt(),
            "messages": [{"role": "user", "content": f"<message>\n{text}\n</message>"}],
        }).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    # Skip macOS system proxy lookup (_scproxy), which crashes Python when launched from a Services runner.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=30) as r:
        out = "".join(b["text"] for b in json.load(r)["content"] if b["type"] == "text").strip()
    if not out:
        raise ValueError("empty response")
    return out


LINE_PREFIX_RE = re.compile(r"^( *)(\d+\.|[-\u2022*]|>)[ \t]+")

def keep_line_prefixes(src, out):
    """The model sometimes drops list numbers/bullets/quote markers. When it kept the same number of
    non-blank lines, put each source line's prefix back (replacing whatever the model put there)."""
    s_lines, o_lines = src.split("\n"), out.split("\n")
    s_idx = [i for i, l in enumerate(s_lines) if l.strip()]
    o_idx = [i for i, l in enumerate(o_lines) if l.strip()]
    if len(s_idx) != len(o_idx):
        return out
    for si, oi in zip(s_idx, o_idx):
        m = LINE_PREFIX_RE.match(s_lines[si])
        if not m:
            continue
        body = LINE_PREFIX_RE.sub("", o_lines[oi])
        o_lines[oi] = m.group(0) + body.lstrip()
    return "\n".join(o_lines)

def polish_markup(text):
    return keep_line_prefixes(text, llm(text))


# ---------- Chromium custom-data pickle ----------

def unpickle(b):
    off = 8
    (n,) = struct.unpack_from("<I", b, 4)
    items = []
    for _ in range(n * 2):
        (l,) = struct.unpack_from("<i", b, off); off += 4
        items.append(b[off:off + 2 * l].decode("utf-16le")); off += 2 * l
        off += (-off) % 4
    return dict(zip(items[::2], items[1::2]))

def pickle(d):
    body = struct.pack("<I", len(d))
    for s in (x for kv in d.items() for x in kv):
        enc = s.encode("utf-16le")
        body += struct.pack("<i", len(enc) // 2) + enc + b"\0" * ((-len(enc)) % 4)
    return struct.pack("<I", len(body)) + body


# ---------- slack/texty (Quill delta) <-> markup ----------

INLINE = [("code", "code"), ("bold", "b"), ("italic", "i"), ("strike", "s")]

def delta_to_markup(ops):
    embeds, lines, cur = [], [], []
    for op in ops:
        ins, attrs = op.get("insert"), op.get("attributes") or {}
        if isinstance(ins, str):
            parts = ins.split("\n")
            for i, part in enumerate(parts):
                if part:
                    s = html.escape(part, quote=False)
                    for a, tag in INLINE:
                        if attrs.get(a):
                            s = f"<{tag}>{s}</{tag}>"
                    if attrs.get("link"):
                        s = f'<a href="{html.escape(attrs["link"])}">{s}</a>'
                    cur.append(s)
                if i < len(parts) - 1:
                    lines.append(("".join(cur), attrs)); cur = []
        elif isinstance(ins, dict) and "slackemoji" in ins:
            cur.append(ins["slackemoji"].get("text", ""))
        else:
            embeds.append(op); cur.append(f'<x id="{len(embeds) - 1}"/>')
    trailing_newline = not cur
    if cur:
        lines.append(("".join(cur), {}))
    out, n = [], 0
    for text, la in lines:
        indent = "  " * int(la.get("indent", 0) or 0)
        if la.get("list") == "ordered":
            n += 1; text = f"{indent}{n}. {text}"
        else:
            n = 0
            if la.get("list"):
                text = f"{indent}- {text}"
            elif la.get("blockquote"):
                text = f"> {text}"
            elif la.get("code-block"):
                text = f"<pre>{text}</pre>"
        out.append(text)
    return "\n".join(out), embeds, trailing_newline


class _Inline(HTMLParser):
    def __init__(self, embeds):
        super().__init__(convert_charrefs=True)
        self.embeds, self.stack, self.ops = embeds, [], []
    def _attrs(self):
        a = {}
        for tag, val in self.stack:
            a.update({"b": {"bold": True}, "i": {"italic": True}, "s": {"strike": True},
                      "code": {"code": True}, "a": {"link": val}}.get(tag, {}))
        return a
    def handle_starttag(self, tag, attrs):
        if tag == "x":
            i = int(dict(attrs).get("id", -1))
            if 0 <= i < len(self.embeds):
                self.ops.append(self.embeds[i])
        else:
            self.stack.append((tag, dict(attrs).get("href")))
    handle_startendtag = handle_starttag
    def handle_endtag(self, tag):
        for j in range(len(self.stack) - 1, -1, -1):
            if self.stack[j][0] == tag:
                del self.stack[j]; break
    def handle_data(self, data):
        for piece in EMOJI_RE.split(data):
            if not piece:
                continue
            if EMOJI_RE.fullmatch(piece):
                self.ops.append({"insert": {"slackemoji": {"text": piece}}})
            else:
                op = {"insert": piece}
                if self._attrs():
                    op["attributes"] = self._attrs()
                self.ops.append(op)

def markup_to_delta(markup, embeds, trailing_newline):
    ops, lines = [], markup.split("\n")
    for idx, line in enumerate(lines):
        la, m = {}, re.match(r"^( *)", line)
        indent = len(m.group(1)) // 2
        body = line.lstrip(" ")
        if (m := re.match(r"^\d+\.\s+", body)):
            la["list"], body = "ordered", body[m.end():]
        elif (m := re.match(r"^[-•*]\s+", body)):
            la["list"], body = "bullet", body[m.end():]
        elif body.startswith("> "):
            la["blockquote"], body = True, body[2:]
        elif (m := re.fullmatch(r"<pre>(.*)</pre>", body)):
            la["code-block"], body = True, m.group(1)
        else:
            body = line
        if indent and "list" in la:
            la["indent"] = indent
        p = _Inline(embeds); p.feed(body); p.close()
        ops += p.ops
        if idx < len(lines) - 1 or trailing_newline or la:
            ops.append({"insert": "\n", **({"attributes": la} if la else {})})
    return ops

def delta_to_plain(ops):
    out = []
    for op in ops:
        ins = op.get("insert")
        if isinstance(ins, str):
            out.append(ins)
        elif isinstance(ins, dict) and "slackemoji" in ins:
            out.append(ins["slackemoji"].get("text", ""))
    return "".join(out)


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []
    def handle_data(self, d): self.out.append(d)
    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "li") and self.out: self.out.append("\n")

def html_to_plain(h):
    p = _Strip(); p.feed(h); p.close()
    return re.sub(r"\n{3,}", "\n\n", "".join(p.out)).strip()


# ---------- HTML <-> markup (one line per block; empty blocks become blank lines) ----------

BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "tr"}
KEEP = {"b": "b", "strong": "b", "i": "i", "em": "i", "s": "s", "strike": "s", "del": "s", "code": "code"}

class _ToMarkup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.cur, self.prefix = [], "", ""
        self.blocks, self.lists, self.open = [], [], []  # block had-content flags, [type, n], inline tags
    def _flush(self):
        if self.cur:
            self.lines.append(self.cur); self.cur = ""
    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            self._flush(); self.lists.append([tag, 0])
        elif tag in BLOCKS:
            self._flush()
            if self.blocks: self.blocks[-1] = True  # a child block counts as content
            self.blocks.append(False)
            if tag == "li" and self.lists:
                l = self.lists[-1]; l[1] += 1
                self.prefix = "  " * (len(self.lists) - 1) + (f"{l[1]}. " if l[0] == "ol" else "- ")
            elif tag == "blockquote":
                self.prefix = "> "
        elif tag == "br":
            self.lines.append(self.cur); self.cur = ""
            if self.blocks: self.blocks[-1] = True
        elif tag in KEEP or (tag == "a" and dict(attrs).get("href")):
            t = KEEP.get(tag, "a")
            self._text(f'<a href="{html.escape(dict(attrs)["href"])}">' if t == "a" else f"<{t}>")
            self.open.append((tag, t))
    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            self._flush()
            if self.lists: self.lists.pop()
        elif tag in BLOCKS:
            had = self.blocks.pop() if self.blocks else True
            if not had and not self.cur:
                self.lines.append(self.prefix.rstrip() if self.prefix else ""); self.prefix = ""
            self._flush()
        elif self.open and self.open[-1][0] == tag:
            self._text(f"</{self.open.pop()[1]}>")
    def _text(self, s):
        if not self.cur and self.prefix:
            self.cur, self.prefix = self.prefix, ""
        self.cur += s
        if self.blocks: self.blocks[-1] = True
    def handle_data(self, d):
        d = re.sub(r"\s+", " ", d)
        if d.strip() or self.cur:
            self._text(html.escape(d, quote=False))

def html_to_markup(h):
    p = _ToMarkup(); p.feed(h); p.close(); p._flush()
    lines = [l.rstrip() for l in p.lines]
    while lines and not lines[0]: lines.pop(0)
    while lines and not lines[-1]: lines.pop()
    return "\n".join(lines)

def markup_to_html(markup):
    out, stack = [], []  # stack of open list tags, one per indent level
    for line in markup.split("\n"):
        indent = (len(line) - len(line.lstrip(" "))) // 2
        body = line.strip()
        m = re.match(r"^(\d+\.|[-•*])\s+", body)
        if m:
            tag = "ol" if m.group(1)[0].isdigit() else "ul"
            while len(stack) > indent + 1: out.append(f"</{stack.pop()}>")
            if len(stack) == indent + 1 and stack[-1] != tag: out.append(f"</{stack.pop()}>")
            while len(stack) < indent + 1: stack.append(tag); out.append(f"<{tag}>")
            out.append(f"<li>{body[m.end():]}</li>")
            continue
        while stack: out.append(f"</{stack.pop()}>")
        if not body:
            out.append("<div><br></div>")
        elif body.startswith("> "):
            out.append(f"<blockquote>{body[2:]}</blockquote>")
        else:
            out.append(f"<div>{body}</div>")
    while stack: out.append(f"</{stack.pop()}>")
    return "".join(out)

def markup_to_plain(markup):
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


# ---------- main ----------

def polish(types):
    """Return new clipboard contents for the copied selection."""
    if SLACK_TYPE in types:
        custom = unpickle(types[SLACK_TYPE])
        if TEXTY in custom:
            ops = json.loads(custom[TEXTY])["ops"]
            markup, embeds, trailing = delta_to_markup(ops)
            new_ops = markup_to_delta(polish_markup(markup), embeds, trailing)
            plain = delta_to_plain(new_ops)
            custom[TEXTY] = json.dumps({"ops": new_ops}, ensure_ascii=False, separators=(",", ":"))
            custom[PLAIN] = plain
            return {PLAIN: plain.encode(), SLACK_TYPE: pickle(custom)}
    if HTML_TYPE in types:
        # Normalize to one line per block so blank lines survive editors (Gmail) that collapse empty <p></p>.
        out = polish_markup(html_to_markup(types[HTML_TYPE].decode("utf-8", "replace")))
        return {HTML_TYPE: markup_to_html(out).encode(), PLAIN: markup_to_plain(out).encode()}
    return {PLAIN: polish_markup(types.get(PLAIN, b"").decode("utf-8", "replace")).encode()}


def main():
    sys.stdin.read()  # Services passes the plain selection; we copy the rich version ourselves.
    for _ in range(40):  # wait for the hotkey's modifiers to be released (max 2s)
        if clip("mods") == "0":
            break
        time.sleep(0.05)
    saved = read_clipboard()
    before = clip("count")
    err = keystroke("c")
    for _ in range(20):
        time.sleep(0.05)
        if clip("count") != before:
            break
    else:
        app = clip("front") or "the app you're in"
        with open(LOG_FILE, "a") as f:
            f.write(f"--- {time.ctime()} copy failed in {app}: {err or 'clipboard unchanged'}\n")
        notify(f"Couldn't copy from {app}. Turn on {app} in Accessibility settings, then try again.")
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
        return
    try:
        write_clipboard(polish(read_clipboard()))
        keystroke("v")
        time.sleep(0.8)
    except Exception as e:
        notify(f"Polish failed - text left unchanged ({type(e).__name__})")
    finally:
        write_clipboard(saved)


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()

def settings():
    choice = osa('choose from list {"Edit prompt", "Change shortcut", "Set API key"} '
                 'with title "Polish" with prompt "Polish settings" default items {"Edit prompt"}')
    if choice == "Edit prompt":
        if not os.path.exists(STYLE_FILE):
            open(STYLE_FILE, "w").write(DEFAULT_STYLE)
        subprocess.run(["open", "-e", STYLE_FILE])
    elif choice == "Change shortcut":
        osa('display dialog "In Keyboard Shortcuts, open Services → Text, then double-click the '
            'shortcut next to Polish and press your new keys." buttons {"Open"} default button 1 with title "Polish"')
        subprocess.run(["open", "x-apple.systempreferences:com.apple.Keyboard-Settings.extension?Shortcuts"])
    elif choice == "Set API key":
        key = osa('text returned of (display dialog "Anthropic API key:" default answer "" '
                  'with hidden answer with title "Polish")')
        if key:
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, key.encode()); os.close(fd)
            notify("API key saved")


if __name__ == "__main__":
    try:
        settings() if "--settings" in sys.argv else main()
    except BaseException as e:  # never surface Automator's opaque error; log it and notify instead
        import traceback
        with open(LOG_FILE, "a") as f:
            f.write(f"--- {time.ctime()} {sys.argv[1:]}\n{traceback.format_exc()}\n")
        notify(f"Polish hit an error ({type(e).__name__}); details in ~/.config/polish/error.log")
    sys.exit(0)
