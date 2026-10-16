# Polish

Select a message anywhere on your Mac, press **⌘⌥⌃P**, and it's rewritten in place: shorthand becomes full sentences, typos are fixed, and the formatting stays exactly as it was.

![Before and after in Slack, Gmail and iMessage](assets/demo.png)

## Where to use it

Turn rough messages into polished ones in Slack, Gmail and iMessage, especially when you type fast in shorthand with loose grammar and spelling but want to come across polished.

## How it compares

| | Keeps formatting | Works in |
|---|---|---|
| **Polish** | Yes: bold, links, lists, emoji, @mentions, blank lines | Any app where you can select text |
| Wispr Flow commands | No, especially in Slack | Any app |
| Gmail "Polish" | No | Gmail only |

## Speed

About **1 second** for the model and about **1.5 seconds** from keypress to pasted text. Measured with `bench/benchmark.py` on `claude-haiku-5-5` (10 runs per message, see [bench/results.txt](bench/results.txt)):

| Message | Median | p90 |
|---|---|---|
| Slack status (list, bold, emoji) | 0.72s | 0.83s |
| Gmail email | 1.03s | 1.09s |
| iMessage text | 0.97s | 1.05s |

Local overhead (Python start-up plus clipboard reads and writes) adds about 0.46s. Thinking is off and effort is `low`, which keeps it fast.

## Install

```bash
git clone https://github.com/josiahcoad/polish.git && cd polish && ./install.sh
```

The installer asks for an [Anthropic API key](https://console.anthropic.com/settings/keys) and installs two Quick Actions:

- **⌘⌥⌃P** polishes the selected text.
- **⌘⌥⌃,** opens settings: edit the style prompt, change the shortcut, or replace your API key.

The first time you use it, macOS asks to let the app you're typing in control your computer (System Settings → Privacy & Security → Accessibility). Polish needs this to copy your selection and paste the result.

To update later, run `git pull && ./install.sh`.

## How it works

1. Copies your selection with ⌘C and reads the rich version from the clipboard: Slack's own format, HTML, or plain text.
2. Converts it to light markup, one line per paragraph, so the model sees the formatting but can't break it.
3. Sends it to `claude-haiku-5-5` with your style prompt and fixed formatting rules.
4. Rebuilds the original format, pastes it with ⌘V, then restores your clipboard.

Files live in `~/.config/polish/`:

| File | Purpose |
|---|---|
| `key` | Your API key (only you can read it) |
| `style.txt` | Your style prompt, created the first time you choose **Edit style** |
| `api_url` | Optional: send requests through a proxy or gateway instead of `api.anthropic.com` |
