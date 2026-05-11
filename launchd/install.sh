#!/bin/bash
# Instala o LaunchAgent — o bot vai iniciar no login e reiniciar se cair.
set -e

PLIST_NAME="com.alexrangelalves.pausasbot.plist"
SRC="$(cd "$(dirname "$0")" && pwd)/$PLIST_NAME"
DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

if [ ! -f "$SRC" ]; then
    echo "ERRO: $SRC não encontrado"
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# Se já estava carregado, descarrega primeiro
if launchctl list | grep -q "com.alexrangelalves.pausasbot"; then
    echo "→ Descarregando versão anterior…"
    launchctl unload "$DST" 2>/dev/null || true
fi

cp "$SRC" "$DST"
echo "→ Copiado para $DST"

launchctl load -w "$DST"
echo "→ LaunchAgent carregado e habilitado"

sleep 2
if launchctl list | grep -q "com.alexrangelalves.pausasbot"; then
    echo "✅ Bot rodando. Logs em:"
    echo "    /Users/alexrangelalves/Downloads/Conexão mtds/pausas_bot/bot.log"
    echo "    /Users/alexrangelalves/Downloads/Conexão mtds/pausas_bot/bot.err.log"
else
    echo "⚠️  Não consegui confirmar — verifique 'launchctl list | grep pausasbot'"
fi
