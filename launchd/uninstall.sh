#!/bin/bash
# Desinstala o LaunchAgent (para o bot e desabilita o auto-start)
set -e

DST="$HOME/Library/LaunchAgents/com.alexrangelalves.pausasbot.plist"

if [ -f "$DST" ]; then
    launchctl unload "$DST" 2>/dev/null || true
    rm "$DST"
    echo "✅ LaunchAgent removido"
else
    echo "Nada para remover (já estava desinstalado)"
fi
