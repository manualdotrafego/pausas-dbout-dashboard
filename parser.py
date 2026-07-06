"""Parser para mensagens Pausar/Ativar do canal #financeiro.

Reconhece:
- 🚨 Pausar [unidade], por gentileza
- 🚨 Pausa [unidade]
- 🚨 pausar [unidade] assim que encerrar o saldo
- ✅ Ativar [unidade]
- ✅ Ativar [unidade] (sem por gentileza)

Retorna dict com event_type, unit_name, reason, mentions ou None se não reconhecer.
"""
from __future__ import annotations
import re
import unicodedata
from typing import Optional


PAUSE_HEAD_RE = re.compile(
    r"^\s*"                                  # leading whitespace
    r"(?:🚨\s*)?"                              # optional siren
    r"(?P<verb>pausa[r]?|pausar:)\s+"          # pausar / pausa / pausar:
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)

ACTIVATE_HEAD_RE = re.compile(
    r"^\s*"
    r"(?:✅\s*|🔄\s*)?"
    r"(?P<verb>(?:re)?ativar?)\s+"
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)

# Ativação inicial de uma franquia nova: "✅ FRANQUIA E CIDADE: <nome>"
FRANQUIA_HEAD_RE = re.compile(
    r"^\s*"
    r"(?:✅\s*)?"
    r"FRANQUIA\s+E\s+CIDADE\s*:?\s*"
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)

# strip phrases that come after the unit name on the SAME line
TRAIL_STRIPS = [
    r",?\s*por\s+gentileza.*$",
    r"\s+quando\s+encerrar\s+o\s+saldo.*$",
    r"\s+assim\s+que\s+encerrar\s+o\s+saldo.*$",
    r"\s+ao\s+encerrar\s+o\s+saldo.*$",
    r"\s+a\s+partir\s+de\s+hoje.*$",
    r"\s*\(.*?\)\s*$",
    r"\s*:\s*$",
    r"\s*\.\s*$",
]
TRAIL_RES = [re.compile(p, re.IGNORECASE) for p in TRAIL_STRIPS]

MENTION_RE = re.compile(r"<@!?(\d+)>")


def _clean_unit(raw: str) -> str:
    s = raw.strip()
    # remove emoji prefix if any leaked
    s = re.sub(r"^[\s\W_]+", "", s, count=1) if s and not s[0].isalnum() and not s[0] in "+0123456789" else s
    # strip trailing phrases iteratively
    changed = True
    while changed:
        changed = False
        for r in TRAIL_RES:
            new = r.sub("", s)
            if new != s:
                s = new
                changed = True
    return s.strip(" ,.:;-")


def _extract_reason(lines: list[str]) -> str:
    """The reason is typically the line(s) between the head line and the mentions.
    Common patterns: 'Não continuarão', 'Pagamento em atraso', 'Motivo: X'."""
    if not lines:
        return ""
    body = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # stop when we hit a line that's only mentions
        if re.fullmatch(r"(?:<@!?\d+>\s*)+", s):
            break
        # strip leading "Motivo:" / "[Motivo]"
        s = re.sub(r"^\s*\[?motivo\]?:?\s*", "", s, flags=re.IGNORECASE)
        # strip inline mentions
        s = MENTION_RE.sub("", s).strip()
        if s:
            body.append(s)
    return " ".join(body).strip()


def parse_message(content: str, mention_id_to_name: dict[int, str] | None = None) -> Optional[dict]:
    """Parse a discord message.
    Returns {event_type, unit_name, reason, mentions(list[str])} or None.
    `mention_id_to_name` maps user IDs found in <@...> tokens to display names."""
    if not content:
        return None
    lines = content.splitlines()
    head = lines[0].strip()
    rest = lines[1:]

    event_type = None
    rest_of_head = ""

    m = PAUSE_HEAD_RE.match(head)
    if m:
        event_type = "pausar"
        rest_of_head = m.group("rest")
    else:
        m = ACTIVATE_HEAD_RE.match(head)
        if m:
            event_type = "ativar"
            rest_of_head = m.group("rest")
        else:
            m = FRANQUIA_HEAD_RE.match(head)
            if m:
                event_type = "ativar"  # franquia nova = ativação inicial
                rest_of_head = m.group("rest")

    if not event_type:
        return None

    # unit name is text before "," / "por gentileza" / EOL
    unit_raw = rest_of_head
    cut = re.split(r",|\bpor\s+gentileza\b", unit_raw, maxsplit=1, flags=re.IGNORECASE)[0]
    unit_name = _clean_unit(cut)

    reason = _extract_reason(rest)

    # extract mention IDs from full content
    mention_ids = [int(x) for x in MENTION_RE.findall(content)]
    mentions = []
    if mention_id_to_name:
        for uid in mention_ids:
            name = mention_id_to_name.get(uid)
            if name:
                mentions.append(name)
    else:
        mentions = [f"<@{uid}>" for uid in mention_ids]

    return {
        "event_type": event_type,
        "unit_name": unit_name,
        "unit_key": normalize_unit_key(unit_name),
        "reason": reason,
        "mentions": mentions,
        "mention_ids": mention_ids,
    }


def normalize_unit_key(name: str) -> str:
    """Lowercase, accent-stripped, alnum-only key for cross-referencing pausa/ativa."""
    if not name:
        return ""
    # NFKD normalize and strip combining marks
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    # keep alnum and spaces, collapse spaces
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", no_accents.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


if __name__ == "__main__":
    # quick smoke tests
    samples = [
        "🚨 Pausar Sorrilagos Cabo Frio, por gentileza\nNão continuarão\n<@111> <@222>",
        "🚨 pausar Araguaina por gentileza  assim que encerrar o saldo👇\n\nPassando aqui pra avisar...\n<@333> <@444>",
        "✅ Ativar Ipatinga\nInvestimento: 1200,00 (1365,96 - imposto)\nVenc: 24\n<@555> <@666>",
        "Pausar +Odonto Taguatinga, por gentileza\nPagamento em atraso\n<@111> <@222>",
        "✅ FRANQUIA E CIDADE: Cametá Sorrisos - Cametá/PA\nE-MAIL:\nTELEFONE GESTÃO: 91 8160-2783\nNOME DECISOR: Claudio\n<@111> <@222>",
        "✅ FRANQUIA E CIDADE:  Odonto Company Santo Amaro\nNOME DECISOR: Hercules\n<@333>",
    ]
    for s in samples:
        print("---")
        print(s)
        print("=>", parse_message(s, {111: "Lara", 222: "Victor", 333: "Samuel", 444: "Genilza", 555: "Gustavo", 666: "Genilza"}))
