"""Bot principal — escuta #financeiro, parseia Pausar/Ativar, atualiza dashboard.

Flags CLI:
  --backfill           : faz backfill desde 01 do mês anterior antes de iniciar listener
  --backfill-only      : só backfill, não inicia listener
  --no-git             : não faz git add/commit/push após cada evento
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

# local modules
sys.path.insert(0, str(Path(__file__).parent))
from parser import parse_message
from db import init_db, upsert_event, latest_event_timestamp, first_activation_before, update_ltv
from cpl_lookup import cpl_15d
import dashboard

# load .env from parent (Conexão mtds/) and local
HERE = Path(__file__).parent
load_dotenv(HERE.parent / ".env")
load_dotenv(HERE / ".env")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_NAME = os.getenv("DISCORD_CHANNEL_NAME_FINANCEIRO", "financeiro")
TARGET_GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("pausas-bot")


def _first_of_last_month(now: datetime) -> datetime:
    """Returns first day of the previous month at 00:00 UTC."""
    year = now.year
    month = now.month - 1
    if month == 0:
        month = 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _git_commit_push(repo_dir: Path, html_path: Path) -> None:
    """git add + commit + push (idempotent if no changes)."""
    rel = html_path.relative_to(repo_dir)
    try:
        subprocess.run(["git", "-C", str(repo_dir), "add", str(rel)], check=True)
        # check if there's anything staged
        diff = subprocess.run(
            ["git", "-C", str(repo_dir), "diff", "--cached", "--quiet"],
            check=False,
        )
        if diff.returncode == 0:
            log.info("nada novo para commitar")
            return
        msg = f"dash: update {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-m", msg],
            check=True,
        )
        # rebase contra remoto pra evitar race quando alguém comita manualmente
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--rebase", "--autostash"],
            check=False,
        )
        subprocess.run(["git", "-C", str(repo_dir), "push"], check=True)
        log.info("dashboard publicado no GitHub Pages")
    except subprocess.CalledProcessError as e:
        log.error("git falhou: %s", e)


async def _find_activation_in_discord(
    channel: discord.TextChannel,
    unit_key: str,
    before: datetime,
    *,
    deep_until: datetime | None = None,
) -> datetime | None:
    """Varre o histórico do canal procurando a primeira ativação de uma unidade
    (qualquer ativar OU FRANQUIA E CIDADE com mesmo unit_key) ANTES de `before`.
    Para no `deep_until` (default: 1 ano antes de `before`)."""
    from parser import parse_message, normalize_unit_key  # local import
    if deep_until is None:
        from datetime import timedelta as _td
        deep_until = before - _td(days=365)
    earliest_ts: datetime | None = None
    try:
        async for msg in channel.history(limit=None, before=before, after=deep_until, oldest_first=True):
            if not msg.content:
                continue
            parsed = parse_message(msg.content)
            if not parsed or parsed["event_type"] != "ativar":
                continue
            if parsed["unit_key"] != unit_key:
                continue
            ts = msg.created_at.astimezone(timezone.utc)
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts
                break  # oldest_first=True, then this is the first
    except Exception as exc:
        log.warning("erro no scan de ativação: %s", exc)
    return earliest_ts


def _build_mention_map(message: discord.Message) -> dict[int, str]:
    """Map of mentioned-user-id -> display name."""
    m: dict[int, str] = {}
    for u in message.mentions:
        m[u.id] = u.display_name or u.name
    # also include role mentions if any (rare for our case)
    for r in message.role_mentions:
        m[r.id] = f"@{r.name}"
    return m


async def _process_message(message: discord.Message, *, do_git: bool = True) -> bool:
    """Returns True if message was a Pausar/Ativar event and was saved."""
    if not message.content:
        return False
    mention_map = _build_mention_map(message)
    parsed = parse_message(message.content, mention_map)
    if not parsed:
        return False
    unit_name = parsed["unit_name"]
    if not unit_name:
        return False
    # Captura CPL 15d no momento do evento (apenas para Pausar — para Ativar não faz sentido)
    cpl_snap = None
    if parsed["event_type"] == "pausar":
        try:
            cpl_snap = cpl_15d(unit_name, parsed["mentions"])
        except Exception as exc:
            log.warning("cpl_lookup falhou para %s: %s", unit_name, exc)
    new = upsert_event(
        message_id=str(message.id),
        event_type=parsed["event_type"],
        timestamp=message.created_at.astimezone(timezone.utc),
        author=message.author.display_name or message.author.name,
        author_id=str(message.author.id),
        unit_name=unit_name,
        unit_key=parsed["unit_key"],
        reason=parsed["reason"],
        mentions=parsed["mentions"],
        raw_content=message.content,
        channel_id=str(message.channel.id),
        channel_name=getattr(message.channel, "name", None),
        cpl_snapshot=cpl_snap,
    )
    log.info(
        "%s [%s] %s — %s — %s",
        "NEW" if new else "UPD",
        parsed["event_type"].upper(),
        unit_name,
        parsed["reason"][:60],
        ", ".join(parsed["mentions"]),
    )

    # Para pausas: calcula LTV (tempo de permanência)
    if parsed["event_type"] == "pausar":
        pause_ts = message.created_at.astimezone(timezone.utc)
        activated_at = first_activation_before(parsed["unit_key"], pause_ts)
        if activated_at is None:
            # Fallback: varre histórico do Discord (slow path) — só pra novas pausas em real-time
            # Para backfill, o script de enrichment faz isso de forma controlada
            channel = message.channel
            if hasattr(channel, "history"):
                activated_at = await _find_activation_in_discord(channel, parsed["unit_key"], pause_ts)
        if activated_at is not None:
            days_active = max(0, (pause_ts - activated_at).days)
            update_ltv(str(message.id), activated_at, days_active)
            log.info("  LTV: %s → %s = %d dias", activated_at.date(), pause_ts.date(), days_active)
    return True


async def _refresh_dashboard(do_git: bool) -> None:
    """Regenera HTML e (opcionalmente) faz git push."""
    out = dashboard.generate()
    log.info("dashboard regenerado: %s", out)
    if do_git:
        _git_commit_push(HERE, out)


async def backfill(client: discord.Client, channel: discord.TextChannel, since: datetime, *, do_git: bool) -> int:
    log.info("backfill iniciando em #%s desde %s", channel.name, since.isoformat())
    count = 0
    async for msg in channel.history(limit=None, after=since, oldest_first=True):
        ok = await _process_message(msg, do_git=False)
        if ok:
            count += 1
    log.info("backfill concluído: %d eventos importados", count)
    await _refresh_dashboard(do_git)
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help="puxa histórico desde o dia 01 do mês anterior antes de iniciar listener")
    parser.add_argument("--backfill-only", action="store_true",
                        help="só faz backfill, não inicia listener")
    parser.add_argument("--backfill-since", type=str, default=None,
                        help="data inicial customizada para backfill (YYYY-MM-DD)")
    parser.add_argument("--no-git", action="store_true",
                        help="não faz git push após eventos")
    args = parser.parse_args()

    if not TOKEN or TOKEN.startswith("COLE_AQUI"):
        print("ERRO: DISCORD_BOT_TOKEN não definido em .env", file=sys.stderr)
        sys.exit(1)

    init_db()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.messages = True
    client = discord.Client(intents=intents)

    do_git = not args.no_git
    should_backfill = args.backfill or args.backfill_only
    backfill_only = args.backfill_only

    @client.event
    async def on_ready() -> None:
        log.info("logado como %s (id=%s)", client.user, client.user.id)
        # find target channel — retry até 6x se guilds ainda não populadas (race no reconnect)
        target = None
        for attempt in range(6):
            for guild in client.guilds:
                if TARGET_GUILD_ID and str(guild.id) != TARGET_GUILD_ID:
                    continue
                for ch in guild.text_channels:
                    if ch.name == TARGET_CHANNEL_NAME or TARGET_CHANNEL_NAME in ch.name:
                        target = ch
                        log.info("canal alvo: #%s (id=%s) no servidor %s", ch.name, ch.id, guild.name)
                        break
                if target:
                    break
            if target:
                break
            log.warning("canal '%s' não achado (tentativa %d/6, %d guilds carregadas) — aguardando...",
                        TARGET_CHANNEL_NAME, attempt+1, len(client.guilds))
            await asyncio.sleep(5)
        if not target:
            log.error("canal '%s' não encontrado em nenhum servidor após retries — saindo (LaunchAgent vai reiniciar)", TARGET_CHANNEL_NAME)
            await client.close()
            return
        if should_backfill:
            if args.backfill_since:
                since = datetime.fromisoformat(args.backfill_since).replace(tzinfo=timezone.utc)
            else:
                since = _first_of_last_month(datetime.now(timezone.utc))
            await backfill(client, target, since, do_git=do_git)
        else:
            # catch-up automático: importa mensagens desde o último evento salvo
            last_ts = latest_event_timestamp()
            if last_ts is not None:
                # subtrai 1s pra garantir sobreposição segura (upsert é idempotente)
                from datetime import timedelta
                since = last_ts - timedelta(seconds=1)
                log.info("catch-up: importando mensagens desde %s", since.isoformat())
                await backfill(client, target, since, do_git=do_git)
            else:
                log.info("DB vazio — execute com --backfill para popular histórico")
        if backfill_only:
            await client.close()
            return

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        ch_name = getattr(message.channel, "name", "")
        if ch_name != TARGET_CHANNEL_NAME and TARGET_CHANNEL_NAME not in ch_name:
            return
        if await _process_message(message, do_git=do_git):
            await _refresh_dashboard(do_git)

    @client.event
    async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
        if after.author.bot:
            return
        ch_name = getattr(after.channel, "name", "")
        if ch_name != TARGET_CHANNEL_NAME and TARGET_CHANNEL_NAME not in ch_name:
            return
        if await _process_message(after, do_git=do_git):
            await _refresh_dashboard(do_git)

    try:
        client.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
