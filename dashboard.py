"""Gera docs/index.html — dashboard estático de pausas/ativações."""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from html import escape

from db import all_events, latest_event_per_unit

OUT_HTML = Path(__file__).parent / "docs" / "index.html"

# CSS embedded for self-contained file (GitHub Pages friendly)
PAGE_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard Pausas/Ativações — #financeiro</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--danger:#f85149;--success:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);margin:0;padding:0}
.container{max-width:1400px;margin:0 auto;padding:24px}
h1{margin:0 0 4px;font-size:24px}
.sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
.kpi .v{font-size:28px;font-weight:600}
.kpi .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
.kpi.danger .v{color:var(--danger)}
.kpi.success .v{color:var(--success)}
.kpi.warn .v{color:var(--warn)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
.card h2{margin:0 0 12px;font-size:14px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
.filters{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.filters input,.filters select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:13px}
.filters input{flex:1;min-width:180px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:500;text-transform:uppercase;font-size:11px;letter-spacing:.5px;position:sticky;top:0;background:var(--card)}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600}
.badge.pausada{background:rgba(248,81,73,.15);color:var(--danger)}
.badge.ativa{background:rgba(63,185,80,.15);color:var(--success)}
.badge.reativ{background:rgba(210,153,34,.15);color:var(--warn)}
.mentions{color:var(--accent);font-size:12px}
.reason{color:var(--muted);max-width:380px}
.table-wrap{max-height:520px;overflow:auto}
.foot{color:var(--muted);font-size:11px;text-align:center;margin-top:24px}
.update-banner{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:12px;color:var(--muted);margin-bottom:16px;display:inline-block}
</style>
</head>
<body>
<div class="container">
  <h1>📊 Dashboard de Pausas/Ativações</h1>
  <div class="sub">Canal <code>#financeiro</code> · Servidor DBOUT</div>
  <div class="update-banner">Última atualização: <strong>{{updated_at}}</strong> · Total de eventos: <strong>{{total_events}}</strong></div>

  <div class="kpis">
    <div class="kpi danger"><div class="v">{{kpi_pausadas}}</div><div class="l">Atualmente Pausadas</div></div>
    <div class="kpi success"><div class="v">{{kpi_ativas}}</div><div class="l">Reativadas (status atual: ATIVA)</div></div>
    <div class="kpi warn"><div class="v">{{kpi_pausas_30d}}</div><div class="l">Pausas nos últimos 30 dias</div></div>
    <div class="kpi"><div class="v">{{kpi_ativacoes_30d}}</div><div class="l">Ativações nos últimos 30 dias</div></div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Pausas por gestor (mentions, últimos 30 dias)</h2>
      <canvas id="chartGestores" height="220"></canvas>
    </div>
    <div class="card">
      <h2>Pausas por dia (últimos 30 dias)</h2>
      <canvas id="chartTimeline" height="220"></canvas>
    </div>
  </div>

  <div class="card">
    <h2>Unidades — status atual</h2>
    <div class="filters">
      <input id="f-search" placeholder="Buscar unidade, motivo ou gestor…">
      <select id="f-status">
        <option value="">Todos os status</option>
        <option value="PAUSADA">Pausadas</option>
        <option value="ATIVA">Ativas/Reativadas</option>
      </select>
    </div>
    <div class="table-wrap">
      <table id="tbl">
        <thead><tr><th>Data</th><th>Unidade</th><th>Status</th><th>Tipo</th><th>Motivo</th><th>@s</th><th>Autor</th></tr></thead>
        <tbody>{{rows_html}}</tbody>
      </table>
    </div>
  </div>

  <div class="foot">Gerado automaticamente pelo Bot Dbout · <a href="https://github.com" style="color:var(--accent)">repo</a></div>
</div>

<script>
const gestoresData = {{gestores_json}};
const timelineData = {{timeline_json}};
const ctx1 = document.getElementById('chartGestores').getContext('2d');
new Chart(ctx1,{type:'bar',data:{labels:gestoresData.labels,datasets:[{label:'Pausas',data:gestoresData.values,backgroundColor:'#f85149aa',borderColor:'#f85149',borderWidth:1}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{color:'#8b949e'},grid:{color:'#30363d'}},x:{ticks:{color:'#8b949e'},grid:{display:false}}}}});
const ctx2 = document.getElementById('chartTimeline').getContext('2d');
new Chart(ctx2,{type:'line',data:{labels:timelineData.labels,datasets:[{label:'Pausas',data:timelineData.pausas,borderColor:'#f85149',backgroundColor:'#f8514922',tension:.3,fill:true},{label:'Ativações',data:timelineData.ativas,borderColor:'#3fb950',backgroundColor:'#3fb95022',tension:.3,fill:true}]},options:{responsive:true,plugins:{legend:{labels:{color:'#e6edf3'}}},scales:{y:{beginAtZero:true,ticks:{color:'#8b949e'},grid:{color:'#30363d'}},x:{ticks:{color:'#8b949e'},grid:{display:false}}}}});

// table filter
const tbl = document.getElementById('tbl');
const fSearch = document.getElementById('f-search');
const fStatus = document.getElementById('f-status');
function applyFilters(){
  const q = fSearch.value.toLowerCase();
  const st = fStatus.value;
  for (const tr of tbl.tBodies[0].rows){
    const text = tr.textContent.toLowerCase();
    const trStatus = tr.dataset.status || '';
    const ok = (!q || text.includes(q)) && (!st || trStatus === st);
    tr.style.display = ok ? '' : 'none';
  }
}
fSearch.addEventListener('input', applyFilters);
fStatus.addEventListener('change', applyFilters);
</script>
</body>
</html>
"""


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ts


def _rows_html(units: dict[str, dict]) -> str:
    out = []
    # Sort by latest timestamp desc
    sorted_units = sorted(units.values(), key=lambda d: d["timestamp"], reverse=True)
    for u in sorted_units:
        status = "ATIVA" if u["event_type"] == "ativar" else "PAUSADA"
        badge_class = "ativa" if status == "ATIVA" else "pausada"
        mentions = ", ".join(escape(m) for m in u["mentions"])
        out.append(
            f'<tr data-status="{status}">'
            f'<td>{_fmt_ts(u["timestamp"])}</td>'
            f'<td>{escape(u["unit_name"])}</td>'
            f'<td><span class="badge {badge_class}">{status}</span></td>'
            f'<td>{escape(u["event_type"])}</td>'
            f'<td class="reason">{escape(u["reason"] or "")}</td>'
            f'<td class="mentions">{mentions}</td>'
            f'<td>{escape(u["author"])}</td>'
            f"</tr>"
        )
    return "\n".join(out)


def _kpis(events: list[dict], units: dict[str, dict]) -> dict:
    now = datetime.now(timezone.utc)
    pausadas = sum(1 for u in units.values() if u["event_type"] == "pausar")
    ativas = sum(1 for u in units.values() if u["event_type"] == "ativar")
    cutoff = now.timestamp() - 30 * 86400
    p30 = a30 = 0
    for e in events:
        try:
            ts = datetime.fromisoformat(e["timestamp"]).timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        if e["event_type"] == "pausar":
            p30 += 1
        else:
            a30 += 1
    return {"pausadas": pausadas, "ativas": ativas, "p30": p30, "a30": a30}


def _gestores_chart(events: list[dict]) -> dict:
    """Counts mentions in Pausar events from last 30 days."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 30 * 86400
    counter: Counter = Counter()
    for e in events:
        if e["event_type"] != "pausar":
            continue
        try:
            ts = datetime.fromisoformat(e["timestamp"]).timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        for m in e["mentions"]:
            counter[m] += 1
    # top 12
    top = counter.most_common(12)
    return {"labels": [k for k, _ in top], "values": [v for _, v in top]}


def _timeline_chart(events: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    days = [(now.date()).fromordinal(now.toordinal() - i) for i in range(29, -1, -1)]
    labels = [d.strftime("%d/%m") for d in days]
    bucket_p = defaultdict(int)
    bucket_a = defaultdict(int)
    for e in events:
        try:
            dt = datetime.fromisoformat(e["timestamp"]).date()
        except Exception:
            continue
        if dt < days[0]:
            continue
        if e["event_type"] == "pausar":
            bucket_p[dt] += 1
        else:
            bucket_a[dt] += 1
    return {
        "labels": labels,
        "pausas": [bucket_p.get(d, 0) for d in days],
        "ativas": [bucket_a.get(d, 0) for d in days],
    }


def generate() -> Path:
    events = all_events()
    units = latest_event_per_unit()
    kpis = _kpis(events, units)
    rows = _rows_html(units)
    gestores = _gestores_chart(events)
    timeline = _timeline_chart(events)
    updated = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    html = (PAGE_TEMPLATE
            .replace("{{updated_at}}", updated)
            .replace("{{total_events}}", str(len(events)))
            .replace("{{kpi_pausadas}}", str(kpis["pausadas"]))
            .replace("{{kpi_ativas}}", str(kpis["ativas"]))
            .replace("{{kpi_pausas_30d}}", str(kpis["p30"]))
            .replace("{{kpi_ativacoes_30d}}", str(kpis["a30"]))
            .replace("{{rows_html}}", rows)
            .replace("{{gestores_json}}", json.dumps(gestores))
            .replace("{{timeline_json}}", json.dumps(timeline)))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    return OUT_HTML


if __name__ == "__main__":
    p = generate()
    print(f"Dashboard gerado: {p}")
