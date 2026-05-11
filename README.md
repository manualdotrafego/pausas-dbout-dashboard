# Pausas Bot — DBOUT

Bot Discord que monitora o canal `#financeiro` do servidor DBOUT em tempo real, detectando mensagens de **🚨 Pausar** e **✅ Ativar** de unidades. Persiste em SQLite e publica um dashboard HTML estático via GitHub Pages.

## Estrutura

```
pausas_bot/
├── bot.py              # listener Discord + backfill
├── parser.py           # regex Pausar/Ativar
├── db.py               # SQLite
├── dashboard.py        # gera docs/index.html
├── requirements.txt
├── .gitignore
├── data/pausas.db      # SQLite (gitignored)
└── docs/index.html     # dashboard publicado
```

## Setup local

1. **Dependências**:
   ```bash
   cd pausas_bot
   pip3 install -r requirements.txt
   ```

2. **Token**: garantir que `../.env` (ou `.env` local) tenha:
   ```
   DISCORD_BOT_TOKEN=seu_token_aqui
   DISCORD_CHANNEL_NAME_FINANCEIRO=financeiro   # opcional, default "financeiro"
   ```

3. **Backfill + iniciar listener** (primeira vez):
   ```bash
   python3 bot.py --backfill
   ```
   Vai puxar todo o histórico desde o dia 01 do mês anterior e continuar escutando.

4. **Sem backfill** (uso normal):
   ```bash
   python3 bot.py
   ```

5. **Sem git push** (debug local):
   ```bash
   python3 bot.py --no-git
   ```

## Setup GitHub Pages

1. No GitHub, crie um repositório **público** (ex: `pausas-dbout-dashboard`).
2. Dentro de `pausas_bot/`, inicialize o git e aponte para o repo:
   ```bash
   cd pausas_bot
   git init -b main
   git remote add origin https://github.com/SEU_USUARIO/pausas-dbout-dashboard.git
   git add .
   git commit -m "init"
   git push -u origin main
   ```
3. No GitHub, vá em **Settings → Pages**:
   - Source: **Deploy from a branch**
   - Branch: **main** / pasta **`/docs`**
   - Salvar
4. URL pública sai em `https://SEU_USUARIO.github.io/pausas-dbout-dashboard/`

Cada novo evento → o bot regenera `docs/index.html` e faz `git push` automaticamente. GitHub Pages republica em ~30s.

## Comportamento

- **Detecção**: regex casa "Pausar"/"Pausa"/"pausar" e "Ativar" (case-insensitive, emoji opcional).
- **Status atual**: cada unidade é classificada pelo evento mais recente — `PAUSADA` ou `ATIVA`.
- **Cruzamento**: histórico completo (Pausar↔Ativar) usa `unit_key` normalizado (lowercase, sem acentos).
- **Gestores**: extraídos dos `@mentions` da mensagem (resolve display_name).

## Dashboard inclui

- KPIs: Pausadas / Ativas / Pausas-30d / Ativações-30d
- Bar chart: pausas por gestor (últimos 30 dias)
- Line chart: pausas vs ativações por dia (30d)
- Tabela filtrável: unidade, status, motivo, mentions, autor

## Rodar 24/7 (LaunchAgent)

Para o bot rodar sempre que você estiver logado no Mac, iniciar no login e reiniciar se cair:

```bash
cd "/Users/alexrangelalves/Downloads/Conexão mtds/pausas_bot/launchd"
./install.sh
```

- O bot inicia em background.
- A cada reconexão (login, despertar do sono, reboot, crash) o bot faz **catch-up automático**: importa do Discord qualquer mensagem perdida desde o último evento salvo no DB.
- Logs:
  - `pausas_bot/bot.log` (stdout)
  - `pausas_bot/bot.err.log` (stderr)
- Verificar status: `launchctl list | grep pausasbot`
- Parar/desinstalar: `cd pausas_bot/launchd && ./uninstall.sh`
- Recarregar após mudanças: `./uninstall.sh && ./install.sh`

> Observação: enquanto o Mac estiver **desligado ou em sleep profundo**, o bot não roda — mas quando voltar, o catch-up automático puxa o que ficou faltando.

## Manutenção

- Banco em `data/pausas.db` (não vai pro git). Para reset: `rm data/pausas.db && python3 bot.py --backfill-only`.
- Logs ficam no stdout. Para rodar em background: `nohup python3 bot.py --backfill > bot.log 2>&1 &`
