"""Re-roda busca de CPL para TODAS as pausas:
- Refresh forçado dos snapshots existentes (dados podem ter sido atualizados)
- Fallback global: se o gestor @ mencionado não encontrar match, tenta TODOS os outros gestores
- Persiste o melhor match no DB
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timedelta

from db import init_db, get_conn
from cpl_lookup import _load, _norm, _match_score, gestor_key_for, classify

init_db()

# Carrega cache
cache = _load()
if not cache.get("enabled"):
    raise SystemExit("accounts.json / dashboard_data.json não encontrados")

ACC_BY_ID = cache["accounts"]
GESTOR_TO_ACC_IDS = cache["gestor_to_acc_ids"]

# Pré-computa: lista de (gestor, account_obj, campaign_obj) para iteração
ALL_CAMPS: list[tuple[str, dict, dict]] = []
for gestor, ids in GESTOR_TO_ACC_IDS.items():
    for acc_id in ids:
        acc = ACC_BY_ID.get(acc_id)
        if not acc:
            continue
        for camp in acc.get("campaigns", []):
            ALL_CAMPS.append((gestor, acc, camp))
print(f"total campanhas indexadas: {len(ALL_CAMPS)} (em {len(GESTOR_TO_ACC_IDS)} gestores)")


def find_best_match(unit_name: str, prefer_gestor: str | None = None) -> tuple[float, str, dict, dict] | None:
    """Retorna (score, gestor, acc, camp) — melhor match em TODAS as campanhas, com preferência ao gestor."""
    unit_key = _norm(unit_name)
    if not unit_key:
        return None
    best = None
    for gestor, acc, camp in ALL_CAMPS:
        score = _match_score(unit_key, _norm(camp.get("name", "")))
        if score == 0:
            continue
        # Boost se for o gestor preferido
        adj = score + (0.5 if prefer_gestor and gestor == prefer_gestor else 0)
        if best is None or adj > best[0]:
            best = (adj, gestor, acc, camp)
    return best


def compute_cpl(camp: dict, days: int = 15) -> dict:
    cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
    spend = 0.0
    msgs = 0
    days_seen = set()
    for ad in camp.get("ads", []):
        for date_str, m in (ad.get("daily") or {}).items():
            if date_str < cutoff:
                continue
            days_seen.add(date_str)
            spend += float(m.get("spend") or 0)
            msgs += int(m.get("msgs") or 0)
    return {
        "spend": round(spend, 2),
        "msgs": msgs,
        "cpl": round(spend / msgs, 2) if msgs else None,
        "days": len(days_seen),
    }


# Re-processa todas as pausas
with get_conn() as con:
    rows = con.execute(
        "SELECT id, unit_name, mentions_json, cpl_snapshot_json FROM events WHERE event_type='pausar' ORDER BY timestamp DESC"
    ).fetchall()

print(f"pausas no DB: {len(rows)}")
updated = 0
new_match = 0
unchanged = 0
no_match = 0
mismatch_gestor = 0
per_gestor = defaultdict(int)

for r in rows:
    mentions = json.loads(r["mentions_json"] or "[]")
    preferred = gestor_key_for(mentions)
    best = find_best_match(r["unit_name"], prefer_gestor=preferred)
    had_snapshot = bool(r["cpl_snapshot_json"])
    if not best:
        if not had_snapshot:
            no_match += 1
        continue
    _, gestor, acc, camp = best
    if preferred and gestor != preferred:
        mismatch_gestor += 1
    metrics = compute_cpl(camp, days=15)
    if metrics["spend"] == 0 and metrics["msgs"] == 0:
        # campanha existe mas sem atividade nos últimos 15d — não é útil
        if not had_snapshot:
            no_match += 1
        continue
    snapshot = {
        "gestor": gestor,
        "spend": metrics["spend"],
        "msgs": metrics["msgs"],
        "cpl": metrics["cpl"],
        "days": metrics["days"],
        "account_name": acc.get("name"),
        "campaign_name": camp.get("name"),
    }
    new_json = json.dumps(snapshot, ensure_ascii=False)
    if had_snapshot and r["cpl_snapshot_json"] == new_json:
        unchanged += 1
        continue
    with get_conn() as con2:
        con2.execute("UPDATE events SET cpl_snapshot_json=? WHERE id=?", (new_json, r["id"]))
    per_gestor[gestor] += 1
    if had_snapshot:
        updated += 1
    else:
        new_match += 1

print(f"\nResultado:")
print(f"  novos matches:     {new_match}")
print(f"  snapshots refresh: {updated}")
print(f"  sem alteração:     {unchanged}")
print(f"  sem match:         {no_match}")
print(f"  match em gestor diferente do @mencionado: {mismatch_gestor}")
print(f"\nPor gestor:")
for g, n in sorted(per_gestor.items(), key=lambda x: -x[1]):
    print(f"  {g:>20s}: {n}")
