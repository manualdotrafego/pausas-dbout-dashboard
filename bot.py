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
from db import init_db, upsert_event, latest_event_timestamp
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
        subprocess.run(["git", "-C", str(repo_dir), "push"], check=True)
        log.info("dashboard publicado no GitHub Pages")
    except subprocess.CalledProcessError as e:
        log.error("git falhou: %s", e)


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
    )
    log.info(
        "%s [%s] %s — %s — %s",
        "NEW" if new else "UPD",
        parsed["event_type"].upper(),
        unit_name,
        parsed["reason"][:60],
        ", ".join(parsed["mentions"]),
    )
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
        # find target channel
        target = None
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
        if not target:
            log.error("canal '%s' não encontrado em nenhum servidor — saindo", TARGET_CHANNEL_NAME)
            await client.close()
            return
        if should_backfill:
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
