#!/bin/bash
# Installs Polish: ⌘⌥⌃P polishes the selected text, ⌘⌥⌃, opens settings.
set -euo pipefail
cd "$(dirname "$0")"

CONF="$HOME/.config/polish"
mkdir -p "$CONF" "$HOME/Library/Services"
cp polish.py clip.js "$CONF/"
for wf in "Polish.workflow" "Polish Settings.workflow"; do
  rm -rf "$HOME/Library/Services/$wf"
  cp -R "$wf" "$HOME/Library/Services/"
done
/System/Library/CoreServices/pbs -flush 2>/dev/null || true

if [ ! -s "$CONF/key" ]; then
  read -rsp "Anthropic API key (sk-ant-...): " key; echo
  (umask 077; printf '%s' "$key" > "$CONF/key")
fi

cat <<'EOF'

Installed.
  ⌘⌥⌃P  polish the selected text
  ⌘⌥⌃,  settings (prompt, shortcut, API key)

First run: macOS asks to allow the app you're typing in to control your computer
(System Settings → Privacy & Security → Accessibility). Polish needs this to copy and paste.
EOF
