"""Mapeamento Gestor/Consultor e cruzamento de unidade pausada × CPL dos últimos 15 dias.

Lê:
- ../accounts.json    (_gestores → contas Meta Ads)
- ../dashboard_data.json (insights diários por ad)
"""
from __future__ import annotations
import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
DATA_ROOT = HERE.parent  # /Conexão mtds/
ACCOUNTS_FILE = DATA_ROOT / "accounts.json"
DASH_DATA_FILE = DATA_ROOT / "dashboard_data.json"


# ----------------- Classificação Gestor vs Consultor -----------------
# Mapeia o display_name do mention no Discord -> chave do gestor em accounts.json
MENTION_TO_GESTOR = {
    "gustavo": "Bueno",
    "gustavo souza": "Mota",
    "igor": "Igor",
    "victor coutinho": "Victor",
    "victor": "Victor",
    "milena": "Milena",
    "milena sabaini": "Milena",
    "thiago braga": "Thiago Braga",
}

CONSULTORES = {
    "brenda", "brenda torres",
    "dinha", "dinha damasceno",
    "lara", "lara moreira",
    "genilza", "genilza gomes",
}

# Pessoas que NÃO contam como gestor/consultor (financeiro/admin)
ADMIN_OR_FIN = {"samuel", "cesar sabaini", "laura oliveira", "andré"}


def _norm_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def classify(name: str) -> str:
    """Returns 'gestor', 'consultor' ou 'other'."""
    key = _norm_name(name)
    if key in MENTION_TO_GESTOR:
        return "gestor"
    if key in CONSULTORES:
        return "consultor"
    return "other"


def gestor_key_for(mentions: list[str]) -> Optional[str]:
    """Primeiro mention que é classificado como gestor → retorna a chave em _gestores."""
    for m in mentions:
        k = _norm_name(m)
        if k in MENTION_TO_GESTOR:
            return MENTION_TO_GESTOR[k]
    return None


def count_by_role(mentions: list[str]) -> dict[str, list[str]]:
    """Returns {'gestor': [names...], 'consultor': [names...]}."""
    out = {"gestor": [], "consultor": []}
    for m in mentions:
        c = classify(m)
        if c in out:
            out[c].append(m)
    return out


# ----------------- CPL lookup -----------------
def _norm(s: str) -> str:
    n = unicodedata.normalize("NFKD", s or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", n)).strip()


_cache: dict = {}


def _load() -> dict:
    if _cache.get("loaded"):
        return _cache
    if not ACCOUNTS_FILE.exists() or not DASH_DATA_FILE.exists():
        _cache["loaded"] = True
        _cache["enabled"] = False
        return _cache
    try:
        with open(ACCOUNTS_FILE) as f:
            accs = json.load(f)
        with open(DASH_DATA_FILE) as f:
            data = json.load(f)
    except Exception:
        _cache["loaded"] = True
        _cache["enabled"] = False
        return _cache

    gestor_to_acc_ids = {}
    for g_name, g_data in accs.get("_gestores", {}).items():
        gestor_to_acc_ids[g_name] = [c["id"] for c in g_data.get("contas", [])]

    acc_by_id = {a["id"]: a for a in data.get("accounts", [])}
    _cache.update(
        loaded=True,
        enabled=True,
        accounts=acc_by_id,
        gestor_to_acc_ids=gestor_to_acc_ids,
        data_until=data.get("until"),
    )
    return _cache


# tokens curtos / genéricos que não devem ser usados sozinhos para match
GENERIC_TOKENS = {
    "op", "ca", "ct", "rs", "rj", "sc", "sp", "pa", "ce", "mg", "ba", "pe",
    "pr", "go", "df", "rn", "pb", "am", "ro", "rr", "se", "ap", "ac", "to", "ms", "mt",
    "para", "por", "sao", "de", "do", "da", "dos", "das", "no", "na",
    # prefixos comuns de rede dental
    "oraldents", "orthodontic", "orthopride", "orthoface", "orthodent",
    "odonto", "odontocia", "odontoclinic", "odontologia",
    "clinica", "consultorio", "consult", "centro", "dental", "implandom",
    "mais", "pop", "sorriso", "coife", "happy", "dent", "star", "lumina",
    "viva", "sorrindo", "volte", "vamos", "bonfante", "dr", "dra", "santo",
    "ieb", "lg", "rp", "novo", "nova", "isoclinicas", "agudos",
}


def _significant_tokens(s_norm: str) -> list[str]:
    return [t for t in s_norm.split() if len(t) >= 4 and t not in GENERIC_TOKENS]


def _match_score(unit_norm: str, campaign_norm: str) -> int:
    """Pontua quantos tokens significativos batem. >0 = candidato."""
    if not unit_norm or not campaign_norm:
        return 0
    u_tokens = _significant_tokens(unit_norm)
    if not u_tokens:
        # Sem token significativo? Usa todos os tokens >=3 chars (raro).
        u_tokens = [t for t in unit_norm.split() if len(t) >= 3 and t not in GENERIC_TOKENS]
    if not u_tokens:
        return 0
    return sum(1 for t in u_tokens if t in campaign_norm)


def cpl_15d(unit_name: str, mentions: list[str], reference_date: datetime | None = None) -> Optional[dict]:
    """Retorna {gestor, spend, msgs, cpl, account_name, campaign_name, days} ou None.

    - msgs = quantidade de mensagens (proxy de leads no Meta Ads p/ campanhas de mensagens)
    - Soma `spend` e `msgs` no daily breakdown dos ads, nos últimos 15 dias.
    """
    cache = _load()
    if not cache.get("enabled"):
        return None
    preferred = gestor_key_for(mentions)
    unit_key = _norm(unit_name)
    if not unit_key:
        return None

    now = reference_date or datetime.now()
    cutoff = (now - timedelta(days=15)).date().isoformat()

    # 1) Busca global: percorre TODAS as contas de TODOS os gestores
    #    Score com bonus se a campanha pertencer ao gestor @mencionado.
    best = None  # (score, gestor, acc, camp)
    for g_name, acc_ids in cache["gestor_to_acc_ids"].items():
        for acc_id in acc_ids:
            acc = cache["accounts"].get(acc_id)
            if not acc:
                continue
            for camp in acc.get("campaigns", []):
                base = _match_score(unit_key, _norm(camp.get("name", "")))
                if base == 0:
                    continue
                score = base + (0.5 if preferred and g_name == preferred else 0)
                if best is None or score > best[0]:
                    best = (score, g_name, acc, camp)
    if best is None:
        return None
    _, matched_gestor, matched_acc_obj, matched_camp_obj = best
    # override gestor com o real (pode diferir do @mencionado)
    gestor = matched_gestor

    # 2) Soma spend + msgs dos ads dela nos últimos 15 dias
    spend_total = 0.0
    msgs_total = 0
    days_seen: set[str] = set()
    for ad in matched_camp_obj.get("ads", []):
        daily = ad.get("daily") or {}
        for date_str, m in daily.items():
            if date_str < cutoff:
                continue
            days_seen.add(date_str)
            spend_total += float(m.get("spend") or 0)
            msgs_total += int(m.get("msgs") or 0)

    matched_acc = matched_acc_obj.get("name")
    matched_camp = matched_camp_obj.get("name")
    cpl = (spend_total / msgs_total) if msgs_total else None
    return {
        "gestor": gestor,
        "spend": round(spend_total, 2),
        "msgs": msgs_total,
        "cpl": round(cpl, 2) if cpl is not None else None,
        "days": len(days_seen),
        "account_name": matched_acc,
        "campaign_name": matched_camp,
    }


if __name__ == "__main__":
    # smoke test com unidades reais da nossa base
    tests = [
        ("Mais Sorriso Paracatu", ["Brenda Torres", "Igor"]),
        ("Sorrilagos Cabo Frio", ["Genilza Gomes", "Victor Coutinho"]),
        ("São José dos Pinhais", ["Thiago Braga", "Dinha Damasceno"]),
        ("Botucatu", ["Samuel", "Gustavo"]),
        ("Ituporanga", ["Brenda Torres", "Igor"]),
    ]
    for unit, mentions in tests:
        print(f"\n{unit} (gestor={gestor_key_for(mentions)})")
        r = cpl_15d(unit, mentions)
        print(" ", r)
