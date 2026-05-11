"""Gera docs/index.html — dashboard estático de pausas/ativações."""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from html import escape

from db import all_events, latest_event_per_unit
from cpl_lookup import classify, gestor_key_for, cpl_15d

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
.filters{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.filters input,.filters select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:13px}
.filters input{flex:1;min-width:180px}
.chips{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.chip{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;cursor:pointer;transition:all .15s;font-family:inherit}
.chip:hover{border-color:var(--accent);color:var(--accent)}
.chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.chip.consultor.active{background:var(--warn);border-color:var(--warn)}
.chip .n{opacity:.75;margin-left:4px;font-size:11px}
.chip-label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-right:6px;align-self:center}
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
      <h2>Pausas por GESTOR (últimos 30 dias)</h2>
      <canvas id="chartGestores" height="220"></canvas>
    </div>
    <div class="card">
      <h2>Pausas por CONSULTOR (últimos 30 dias)</h2>
      <canvas id="chartConsultores" height="220"></canvas>
    </div>
  </div>

  <div class="card" style="margin-bottom:24px">
    <h2>Pausas vs Ativações por dia (últimos 30 dias)</h2>
    <canvas id="chartTimeline" height="160"></canvas>
  </div>

  <div class="card">
    <h2>Unidades — status atual (com CPL 15d da campanha do gestor)</h2>
    <div class="filters">
      <input id="f-search" placeholder="Buscar unidade, motivo, gestor ou consultor…">
      <select id="f-status">
        <option value="">Todos os status</option>
        <option value="PAUSADA">Pausadas</option>
        <option value="ATIVA">Ativas/Reativadas</option>
      </select>
      <select id="f-date">
        <option value="0">Todo o período</option>
        <option value="7">Últimos 7 dias</option>
        <option value="15">Últimos 15 dias</option>
        <option value="30">Últimos 30 dias</option>
        <option value="60">Últimos 60 dias</option>
      </select>
    </div>
    <div class="chips" id="gestor-chips">
      <span class="chip-label">Gestor:</span>
      {{gestor_chips_html}}
    </div>
    <div class="chips" id="consultor-chips">
      <span class="chip-label">Consultor:</span>
      {{consultor_chips_html}}
    </div>
    <div class="table-wrap">
      <table id="tbl">
        <thead><tr>
          <th>Data</th><th>Unidade</th><th>Status</th>
          <th>Motivo</th><th>Gestor</th><th>Consultor</th>
          <th>CPL 15d</th><th>Spend 15d</th><th>Msgs 15d</th>
          <th>Campanha (Meta)</th>
        </tr></thead>
        <tbody>{{rows_html}}</tbody>
      </table>
    </div>
  </div>

  <div class="foot">Gerado automaticamente pelo Bot Dbout · <a href="https://github.com" style="color:var(--accent)">repo</a></div>
</div>

<script>
const gestoresData = {{gestores_json}};
const consultoresData = {{consultores_json}};
const timelineData = {{timeline_json}};
const barOpts = {responsive:true,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{color:'#8b949e'},grid:{color:'#30363d'}},x:{ticks:{color:'#8b949e'},grid:{display:false}}}};
new Chart(document.getElementById('chartGestores').getContext('2d'),{type:'bar',data:{labels:gestoresData.labels,datasets:[{label:'Pausas',data:gestoresData.values,backgroundColor:'#58a6ffaa',borderColor:'#58a6ff',borderWidth:1}]},options:barOpts});
new Chart(document.getElementById('chartConsultores').getContext('2d'),{type:'bar',data:{labels:consultoresData.labels,datasets:[{label:'Pausas',data:consultoresData.values,backgroundColor:'#d29922aa',borderColor:'#d29922',borderWidth:1}]},options:barOpts});
new Chart(document.getElementById('chartTimeline').getContext('2d'),{type:'line',data:{labels:timelineData.labels,datasets:[{label:'Pausas',data:timelineData.pausas,borderColor:'#f85149',backgroundColor:'#f8514922',tension:.3,fill:true},{label:'Ativações',data:timelineData.ativas,borderColor:'#3fb950',backgroundColor:'#3fb95022',tension:.3,fill:true}]},options:{responsive:true,plugins:{legend:{labels:{color:'#e6edf3'}}},scales:{y:{beginAtZero:true,ticks:{color:'#8b949e'},grid:{color:'#30363d'}},x:{ticks:{color:'#8b949e'},grid:{display:false}}}}});

// table filter
const tbl = document.getElementById('tbl');
const fSearch = document.getElementById('f-search');
const fStatus = document.getElementById('f-status');
const fDate = document.getElementById('f-date');
let activeGestor = '';
let activeConsultor = '';
function applyFilters(){
  const q = fSearch.value.toLowerCase();
  const st = fStatus.value;
  const days = parseInt(fDate.value);
  for (const tr of tbl.tBodies[0].rows){
    const text = tr.textContent.toLowerCase();
    const trStatus = tr.dataset.status || '';
    const trGestores = (tr.dataset.gestores || '').toLowerCase();
    const trConsultores = (tr.dataset.consultores || '').toLowerCase();
    const trDays = parseInt(tr.dataset.daysago || '9999');
    let ok = (!q || text.includes(q));
    ok = ok && (!st || trStatus === st);
    ok = ok && (!activeGestor || trGestores.includes(activeGestor.toLowerCase()));
    ok = ok && (!activeConsultor || trConsultores.includes(activeConsultor.toLowerCase()));
    ok = ok && (days === 0 || trDays <= days);
    tr.style.display = ok ? '' : 'none';
  }
}
fSearch.addEventListener('input', applyFilters);
fStatus.addEventListener('change', applyFilters);
fDate.addEventListener('change', applyFilters);

// chip handlers
function setupChips(containerId, varSetter){
  const cont = document.getElementById(containerId);
  for (const chip of cont.querySelectorAll('.chip')){
    chip.addEventListener('click', () => {
      const wasActive = chip.classList.contains('active');
      cont.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      if (!wasActive){
        chip.classList.add('active');
        varSetter(chip.dataset.name || '');
      } else {
        varSetter('');
      }
      applyFilters();
    });
  }
}
setupChips('gestor-chips', v => { activeGestor = v; });
setupChips('consultor-chips', v => { activeConsultor = v; });
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


def _split_mentions(mentions: list[str]) -> tuple[list[str], list[str]]:
    """Retorna (gestores_mentions, consultores_mentions)."""
    gs, cs = [], []
    for m in mentions:
        c = classify(m)
        if c == "gestor":
            gs.append(m)
        elif c == "consultor":
            cs.append(m)
    return gs, cs


def _fmt_money(v) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _rows_html(units: dict[str, dict]) -> str:
    out = []
    now = datetime.now(timezone.utc)
    sorted_units = sorted(units.values(), key=lambda d: d["timestamp"], reverse=True)
    for u in sorted_units:
        status = "ATIVA" if u["event_type"] == "ativar" else "PAUSADA"
        badge_class = "ativa" if status == "ATIVA" else "pausada"
        gestores, consultores = _split_mentions(u["mentions"])
        gestor_html = ", ".join(escape(m) for m in gestores) or "—"
        consultor_html = ", ".join(escape(m) for m in consultores) or "—"
        # data attrs
        gestores_attr = "|".join(gestores)
        consultores_attr = "|".join(consultores)
        try:
            evt_dt = datetime.fromisoformat(u["timestamp"])
            if evt_dt.tzinfo is None:
                evt_dt = evt_dt.replace(tzinfo=timezone.utc)
            days_ago = max(0, (now - evt_dt).days)
        except Exception:
            days_ago = 9999

        # CPL: prioriza snapshot persistido (capturado no momento do evento), senão tenta lookup live
        cpl_cell = spend_cell = msgs_cell = camp_cell = "—"
        if status == "PAUSADA":
            info = u.get("cpl_snapshot") or cpl_15d(u["unit_name"], u["mentions"])
            if info:
                cpl_cell = _fmt_money(info.get("cpl")) if info.get("cpl") is not None else "—"
                spend_cell = _fmt_money(info.get("spend"))
                msgs_cell = str(info.get("msgs") or 0)
                camp_cell = f'{escape(info.get("account_name") or "")} → {escape(info.get("campaign_name") or "")}'

        out.append(
            f'<tr data-status="{status}" '
            f'data-gestores="{escape(gestores_attr, quote=True)}" '
            f'data-consultores="{escape(consultores_attr, quote=True)}" '
            f'data-daysago="{days_ago}">'
            f'<td>{_fmt_ts(u["timestamp"])}</td>'
            f'<td>{escape(u["unit_name"])}</td>'
            f'<td><span class="badge {badge_class}">{status}</span></td>'
            f'<td class="reason">{escape(u["reason"] or "")}</td>'
            f'<td class="mentions">{gestor_html}</td>'
            f'<td class="mentions" style="color:#d29922">{consultor_html}</td>'
            f'<td>{cpl_cell}</td>'
            f'<td>{spend_cell}</td>'
            f'<td>{msgs_cell}</td>'
            f'<td class="reason" style="font-size:11px">{camp_cell}</td>'
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


def _role_chips(events: list[dict]) -> tuple[str, str]:
    """Conta pausas por gestor/consultor (todo o histórico) e gera os chips HTML clicáveis."""
    g: Counter = Counter()
    c: Counter = Counter()
    for e in events:
        if e["event_type"] != "pausar":
            continue
        for m in e["mentions"]:
            role = classify(m)
            if role == "gestor":
                g[m] += 1
            elif role == "consultor":
                c[m] += 1

    def chips(counter: Counter, css_extra: str = "") -> str:
        if not counter:
            return '<span class="chip-label" style="opacity:.5">nenhum</span>'
        return " ".join(
            f'<button class="chip {css_extra}" data-name="{escape(name, quote=True)}">'
            f'{escape(name)}<span class="n">({n})</span></button>'
            for name, n in counter.most_common()
        )

    return chips(g), chips(c, "consultor")


def _role_charts(events: list[dict]) -> tuple[dict, dict]:
    """Conta mentions em Pausar dos últimos 30 dias, separando gestor vs consultor."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 30 * 86400
    g: Counter = Counter()
    c: Counter = Counter()
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
            role = classify(m)
            if role == "gestor":
                g[m] += 1
            elif role == "consultor":
                c[m] += 1
    return (
        {"labels": [k for k, _ in g.most_common(12)], "values": [v for _, v in g.most_common(12)]},
        {"labels": [k for k, _ in c.most_common(12)], "values": [v for _, v in c.most_common(12)]},
    )


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
    gestores, consultores = _role_charts(events)
    gestor_chips, consultor_chips = _role_chips(events)
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
            .replace("{{gestor_chips_html}}", gestor_chips)
            .replace("{{consultor_chips_html}}", consultor_chips)
            .replace("{{gestores_json}}", json.dumps(gestores))
            .replace("{{consultores_json}}", json.dumps(consultores))
            .replace("{{timeline_json}}", json.dumps(timeline)))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    return OUT_HTML


if __name__ == "__main__":
    p = generate()
    print(f"Dashboard gerado: {p}")
