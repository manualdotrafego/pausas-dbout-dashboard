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
.top-bar{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px;flex-wrap:wrap}
.date-picker{position:relative;display:inline-block}
.date-picker-btn{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:8px}
.date-picker-btn:hover{border-color:var(--accent)}
.date-picker-btn .lbl{color:var(--accent);font-weight:600}
.date-picker-pop{position:absolute;right:0;top:calc(100% + 6px);background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;min-width:340px;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,.4);display:none}
.date-picker-pop.open{display:block}
.date-picker-pop .presets{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.date-picker-pop .presets .chip{font-size:12px;padding:4px 10px}
.date-picker-pop .range-row{display:flex;gap:8px;align-items:center;margin-bottom:8px;font-size:12px;color:var(--muted)}
.date-picker-pop .range-row input{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:13px;font-family:inherit}
.date-picker-pop .actions{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
.date-picker-pop .btn{padding:6px 14px;border-radius:6px;font-size:13px;cursor:pointer;border:1px solid var(--border);background:transparent;color:var(--text);font-family:inherit}
.date-picker-pop .btn-primary{background:var(--accent);border-color:var(--accent);color:#fff}
.tabs{display:flex;gap:2px;margin:8px 0 16px;border-bottom:1px solid var(--border)}
.tab{background:transparent;color:var(--muted);border:none;border-bottom:2px solid transparent;padding:10px 18px;font-size:13px;cursor:pointer;font-family:inherit;font-weight:500;transition:all .15s}
.tab:hover{color:var(--text)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-panel{display:none}
.tab-panel.active{display:block}
.ltv-bar{display:inline-block;background:linear-gradient(90deg,#3fb950 0%, #d29922 50%, #f85149 100%);height:6px;border-radius:3px;vertical-align:middle;margin-right:8px}
</style>
</head>
<body>
<div class="container">
  <h1>📊 Dashboard de Pausas/Ativações</h1>
  <div class="sub">Canal <code>#financeiro</code> · Servidor DBOUT</div>

  <div class="top-bar">
    <div class="update-banner">Última atualização: <strong>{{updated_at}}</strong> · Total de eventos: <strong>{{total_events}}</strong></div>

    <div class="date-picker">
      <button class="date-picker-btn" id="dp-toggle">
        📅 Período: <span class="lbl" id="dp-label">Tudo</span> <span style="color:var(--muted)">▾</span>
      </button>
      <div class="date-picker-pop" id="dp-pop">
        <div style="font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.5px;margin-bottom:6px">Atalhos</div>
        <div class="presets" id="dp-presets">
          <button class="chip" data-preset="all">Tudo</button>
          <button class="chip" data-preset="today">Hoje</button>
          <button class="chip" data-preset="7">Últimos 7 dias</button>
          <button class="chip" data-preset="15">Últimos 15 dias</button>
          <button class="chip" data-preset="30">Últimos 30 dias</button>
          <button class="chip" data-preset="60">Últimos 60 dias</button>
          {{month_presets_html}}
        </div>
        <div style="font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.5px;margin:8px 0 6px">Período customizado</div>
        <div class="range-row">
          <label>De:</label>
          <input type="date" id="dp-start">
          <label>Até:</label>
          <input type="date" id="dp-end">
        </div>
        <div class="actions">
          <button class="btn" id="dp-clear">Limpar</button>
          <button class="btn btn-primary" id="dp-apply">Aplicar</button>
        </div>
      </div>
    </div>
  </div>

  <div class="kpis">
    <div class="kpi danger"><div class="v">{{kpi_pausadas}}</div><div class="l">Atualmente Pausadas</div></div>
    <div class="kpi success"><div class="v">{{kpi_ativas}}</div><div class="l">Reativadas (status atual: ATIVA)</div></div>
    <div class="kpi warn"><div class="v">{{kpi_pausas_30d}}</div><div class="l">Pausas nos últimos 30 dias</div></div>
    <div class="kpi"><div class="v">{{kpi_ativacoes_30d}}</div><div class="l">Ativações nos últimos 30 dias</div></div>
  </div>

  <div class="tabs">
    <button class="tab active" data-tab="overview">📊 Pausas & Atividade</button>
    <button class="tab" data-tab="ltv">⏱️ Tempo de Permanência</button>
  </div>

  <div class="tab-panel active" id="tab-overview">

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
    </div>
    <div class="chips" id="date-chips">
      <span class="chip-label">Período:</span>
      <button class="chip date-chip active" data-days="0">Tudo<span class="n">({{count_total}})</span></button>
      <button class="chip date-chip" data-days="7">Últimos 7 dias<span class="n">({{count_7d}})</span></button>
      <button class="chip date-chip" data-days="15">Últimos 15 dias<span class="n">({{count_15d}})</span></button>
      <button class="chip date-chip" data-days="30">Últimos 30 dias<span class="n">({{count_30d}})</span></button>
      <button class="chip date-chip" data-days="60">Últimos 60 dias<span class="n">({{count_60d}})</span></button>
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

  </div><!-- /tab-overview -->

  <div class="tab-panel" id="tab-ltv">
    <div class="kpis">
      <div class="kpi"><div class="v">{{ltv_count}}</div><div class="l">Pausas com tempo de permanência calculado</div></div>
      <div class="kpi success"><div class="v">{{ltv_avg}}</div><div class="l">Média de dias ativos antes de pausar</div></div>
      <div class="kpi warn"><div class="v">{{ltv_median}}</div><div class="l">Mediana (dias)</div></div>
      <div class="kpi danger"><div class="v">{{ltv_max}}</div><div class="l">Máximo (dias)</div></div>
    </div>

    <div class="card" style="margin-bottom:24px">
      <h2>Distribuição do tempo de permanência (dias antes da pausa)</h2>
      <canvas id="chartLtvHist" height="180"></canvas>
    </div>

    <div class="card">
      <h2>Tempo de Permanência por unidade pausada (LTV em dias)</h2>
      <div class="filters">
        <input id="f-ltv-search" placeholder="Buscar unidade ou gestor…">
      </div>
      <div class="table-wrap">
        <table id="tbl-ltv">
          <thead><tr>
            <th>Unidade</th><th>Ativada em</th><th>Pausada em</th>
            <th>Tempo Ativo</th><th>Gestor</th><th>Consultor</th>
          </tr></thead>
          <tbody>{{ltv_rows_html}}</tbody>
        </table>
      </div>
      <div style="color:var(--muted);font-size:11px;margin-top:8px">
        Unidades em branco: a ativação aconteceu antes do nosso histórico de Discord ou o nome
        difere da mensagem original de <code>✅ Ativar</code> / <code>✅ FRANQUIA E CIDADE</code>.
      </div>
    </div>
  </div><!-- /tab-ltv -->

  <div class="foot">Gerado automaticamente pelo Bot Dbout · <a href="https://github.com/manualdotrafego/pausas-dbout-dashboard" style="color:var(--accent)">repo</a></div>
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
let activeGestor = '';
let activeConsultor = '';
let activeDays = 0;
function inRangeISO(d){
  if (typeof globalStartISO !== 'undefined' && globalStartISO && d < globalStartISO) return false;
  if (typeof globalEndISO !== 'undefined' && globalEndISO && d > globalEndISO) return false;
  return true;
}
function applyFilters(){
  const q = fSearch.value.toLowerCase();
  const st = fStatus.value;
  for (const tr of tbl.tBodies[0].rows){
    const text = tr.textContent.toLowerCase();
    const trStatus = tr.dataset.status || '';
    const trGestores = (tr.dataset.gestores || '').toLowerCase();
    const trConsultores = (tr.dataset.consultores || '').toLowerCase();
    const trDays = parseInt(tr.dataset.daysago || '9999');
    const trTs = (tr.dataset.ts || '').slice(0,10);
    let ok = (!q || text.includes(q));
    ok = ok && (!st || trStatus === st);
    ok = ok && (!activeGestor || trGestores.includes(activeGestor.toLowerCase()));
    ok = ok && (!activeConsultor || trConsultores.includes(activeConsultor.toLowerCase()));
    ok = ok && (activeDays === 0 || trDays <= activeDays);
    ok = ok && inRangeISO(trTs);
    tr.style.display = ok ? '' : 'none';
  }
  // LTV table also respects global date range (filtra pela data da pausa)
  const tblLtvLocal = document.getElementById('tbl-ltv');
  if (tblLtvLocal && tblLtvLocal.tBodies[0]){
    const lq = (fLtvSearch && fLtvSearch.value || '').toLowerCase();
    for (const tr of tblLtvLocal.tBodies[0].rows){
      const trTs = (tr.dataset.ts || '').slice(0,10);
      const txt = tr.textContent.toLowerCase();
      let ok = (!lq || txt.includes(lq));
      ok = ok && inRangeISO(trTs);
      tr.style.display = ok ? '' : 'none';
    }
  }
}
fSearch.addEventListener('input', applyFilters);
fStatus.addEventListener('change', applyFilters);

// chip handlers (toggle-style: clicking active chip deselects)
function setupChips(containerId, varSetter, defaultActive){
  const cont = document.getElementById(containerId);
  for (const chip of cont.querySelectorAll('.chip')){
    chip.addEventListener('click', () => {
      const wasActive = chip.classList.contains('active');
      cont.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      if (!wasActive){
        chip.classList.add('active');
        varSetter(chip.dataset.name !== undefined ? chip.dataset.name : (parseInt(chip.dataset.days) || 0));
      } else if (defaultActive){
        defaultActive.classList.add('active');
        varSetter(defaultActive.dataset.name !== undefined ? defaultActive.dataset.name : (parseInt(defaultActive.dataset.days) || 0));
      } else {
        varSetter(chip.dataset.name !== undefined ? '' : 0);
      }
      applyFilters();
    });
  }
}
setupChips('gestor-chips', v => { activeGestor = v; });
setupChips('consultor-chips', v => { activeConsultor = v; });
const dateAllChip = document.querySelector('#date-chips .chip[data-days="0"]');
setupChips('date-chips', v => { activeDays = v; }, dateAllChip);

// Global date picker
let globalStartISO = '';  // 'YYYY-MM-DD' inclusive
let globalEndISO = '';    // 'YYYY-MM-DD' inclusive
const dpToggle = document.getElementById('dp-toggle');
const dpPop = document.getElementById('dp-pop');
const dpLabel = document.getElementById('dp-label');
const dpStart = document.getElementById('dp-start');
const dpEnd = document.getElementById('dp-end');
dpToggle.addEventListener('click', e => { e.stopPropagation(); dpPop.classList.toggle('open'); });
document.addEventListener('click', e => { if (!dpPop.contains(e.target) && e.target !== dpToggle) dpPop.classList.remove('open'); });

function fmtDateBR(iso){ if(!iso) return ''; const [y,m,d]=iso.split('-'); return `${d}/${m}/${y.slice(2)}`; }

function updateLabel(){
  if (!globalStartISO && !globalEndISO){ dpLabel.textContent = 'Tudo'; return; }
  const s = globalStartISO ? fmtDateBR(globalStartISO) : '…';
  const e = globalEndISO ? fmtDateBR(globalEndISO) : 'hoje';
  dpLabel.textContent = `${s} → ${e}`;
}

function applyGlobalFilter(){
  updateLabel();
  if (typeof applyFilters === 'function') applyFilters();
}

function setPreset(preset){
  const today = new Date();
  const toISO = d => d.toISOString().slice(0,10);
  if (preset === 'all'){ globalStartISO=''; globalEndISO=''; }
  else if (preset === 'today'){ globalStartISO = globalEndISO = toISO(today); }
  else if (!isNaN(parseInt(preset))){
    const days = parseInt(preset);
    const start = new Date(today); start.setDate(start.getDate() - days);
    globalStartISO = toISO(start); globalEndISO = toISO(today);
  } else if (preset.startsWith('m:')){
    const [_, ym] = preset.split(':');
    const [y, m] = ym.split('-').map(Number);
    const start = new Date(y, m-1, 1);
    const end = new Date(y, m, 0);  // last day
    globalStartISO = toISO(start); globalEndISO = toISO(end);
  }
  if (dpStart) dpStart.value = globalStartISO;
  if (dpEnd) dpEnd.value = globalEndISO;
}

document.querySelectorAll('#dp-presets .chip').forEach(b => {
  b.addEventListener('click', () => {
    const preset = b.dataset.preset || b.dataset.month;
    if (b.dataset.month) setPreset('m:' + b.dataset.month);
    else setPreset(preset);
    applyGlobalFilter();
    dpPop.classList.remove('open');
  });
});
document.getElementById('dp-apply').addEventListener('click', () => {
  globalStartISO = dpStart.value || '';
  globalEndISO = dpEnd.value || '';
  applyGlobalFilter();
  dpPop.classList.remove('open');
});
document.getElementById('dp-clear').addEventListener('click', () => {
  setPreset('all');
  applyGlobalFilter();
});

// Tabs
for (const tab of document.querySelectorAll('.tab')){
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
}

// LTV histogram chart
const ltvHistData = {{ltv_hist_json}};
new Chart(document.getElementById('chartLtvHist').getContext('2d'), {
  type: 'bar',
  data: {labels: ltvHistData.labels, datasets: [{label:'Unidades', data: ltvHistData.values, backgroundColor:'#58a6ffaa', borderColor:'#58a6ff', borderWidth: 1}]},
  options: {responsive:true, plugins:{legend:{display:false}}, scales:{y:{beginAtZero:true,ticks:{color:'#8b949e'},grid:{color:'#30363d'}},x:{ticks:{color:'#8b949e'},grid:{display:false}}}}
});

// LTV table filter
const tblLtv = document.getElementById('tbl-ltv');
const fLtvSearch = document.getElementById('f-ltv-search');
if (fLtvSearch && tblLtv){
  fLtvSearch.addEventListener('input', () => {
    const q = fLtvSearch.value.toLowerCase();
    for (const tr of tblLtv.tBodies[0].rows){
      tr.style.display = (!q || tr.textContent.toLowerCase().includes(q)) ? '' : 'none';
    }
  });
}
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
            f'data-daysago="{days_ago}" '
            f'data-ts="{escape(u["timestamp"], quote=True)}">'
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


def _ltv_data(events: list[dict]) -> dict:
    """Coleta dados LTV: lista de pausas com days_active, distribuição, KPIs."""
    pausas_com_ltv = []
    for e in events:
        if e["event_type"] != "pausar":
            continue
        if e.get("days_active") is None:
            continue
        pausas_com_ltv.append(e)
    pausas_sem_ltv = [
        e for e in events
        if e["event_type"] == "pausar" and e.get("days_active") is None
    ]

    days_list = [e["days_active"] for e in pausas_com_ltv]
    count = len(days_list)
    avg_d = round(sum(days_list) / count) if count else 0
    med_d = sorted(days_list)[count // 2] if count else 0
    max_d = max(days_list) if days_list else 0

    # Histograma: buckets de 30 dias
    buckets = [(0, 30, "0-30 dias"), (31, 60, "31-60 dias"), (61, 90, "61-90 dias"),
               (91, 180, "91-180 dias"), (181, 365, "181-365 dias"), (366, 99999, "1 ano+")]
    hist = []
    for lo, hi, label in buckets:
        n = sum(1 for d in days_list if lo <= d <= hi)
        hist.append((label, n))

    return {
        "count": count,
        "avg": avg_d,
        "median": med_d,
        "max": max_d,
        "pausas_com_ltv": pausas_com_ltv,
        "pausas_sem_ltv": pausas_sem_ltv,
        "hist": {"labels": [h[0] for h in hist], "values": [h[1] for h in hist]},
    }


def _ltv_rows_html(ltv_data: dict) -> str:
    rows = []
    # Primeiro as com LTV (ordenadas por dias desc), depois as sem (em branco)
    com_ltv = sorted(ltv_data["pausas_com_ltv"], key=lambda e: -(e["days_active"] or 0))
    for e in com_ltv:
        d = e["days_active"]
        meses = d // 30
        gestores, consultores = _split_mentions(e["mentions"])
        # Cor da barra: verde se > 90, amarelo 30-90, vermelho < 30
        if d >= 90: color = "#3fb950"
        elif d >= 30: color = "#d29922"
        else: color = "#f85149"
        bar_width = min(100, int(d / 365 * 100))  # base 1 ano = 100%
        tempo_html = (
            f'<span class="ltv-bar" style="width:{bar_width}px;background:{color};"></span>'
            f'<strong>{d}</strong> dias'
            + (f' <span style="color:var(--muted)">(~{meses} {"mês" if meses==1 else "meses"})</span>' if meses else '')
        )
        rows.append(
            f'<tr data-ts="{escape(e["timestamp"], quote=True)}">'
            f'<td>{escape(e["unit_name"])}</td>'
            f'<td>{_fmt_ts(e["activated_at"])}</td>'
            f'<td>{_fmt_ts(e["timestamp"])}</td>'
            f'<td>{tempo_html}</td>'
            f'<td class="mentions">{", ".join(escape(m) for m in gestores) or "—"}</td>'
            f'<td class="mentions" style="color:#d29922">{", ".join(escape(m) for m in consultores) or "—"}</td>'
            f'</tr>'
        )
    # Sem LTV — em branco
    sem_ltv = sorted(ltv_data["pausas_sem_ltv"], key=lambda e: e["timestamp"], reverse=True)
    for e in sem_ltv:
        gestores, consultores = _split_mentions(e["mentions"])
        rows.append(
            f'<tr data-ts="{escape(e["timestamp"], quote=True)}" style="opacity:.55">'
            f'<td>{escape(e["unit_name"])}</td>'
            f'<td>—</td>'
            f'<td>{_fmt_ts(e["timestamp"])}</td>'
            f'<td><span style="color:var(--muted)">não encontrado</span></td>'
            f'<td class="mentions">{", ".join(escape(m) for m in gestores) or "—"}</td>'
            f'<td class="mentions" style="color:#d29922">{", ".join(escape(m) for m in consultores) or "—"}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def _month_presets_html(events: list[dict]) -> str:
    """Gera chips de meses presentes nos eventos (max 6 mais recentes)."""
    MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    months = set()
    for e in events:
        try:
            dt = datetime.fromisoformat(e["timestamp"])
            months.add((dt.year, dt.month))
        except Exception:
            continue
    sorted_months = sorted(months, reverse=True)[:6]
    parts = []
    for y, m in sorted_months:
        label = f"{MESES[m-1]}/{str(y)[2:]}"
        parts.append(f'<button class="chip" data-month="{y:04d}-{m:02d}">{escape(label)}</button>')
    return " ".join(parts)


def _date_counts(units: dict[str, dict]) -> dict[str, int]:
    """Conta unidades cujo último evento aconteceu nos últimos N dias.
    Retorna chaves: total, 7d, 15d, 30d, 60d."""
    now = datetime.now(timezone.utc)
    out = {"total": len(units), "7d": 0, "15d": 0, "30d": 0, "60d": 0}
    for u in units.values():
        try:
            dt = datetime.fromisoformat(u["timestamp"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (now - dt).days
        except Exception:
            continue
        if days <= 7: out["7d"] += 1
        if days <= 15: out["15d"] += 1
        if days <= 30: out["30d"] += 1
        if days <= 60: out["60d"] += 1
    return out


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
    dc = _date_counts(units)
    ltv = _ltv_data(events)
    ltv_rows = _ltv_rows_html(ltv)
    month_presets = _month_presets_html(events)
    updated = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    html = (PAGE_TEMPLATE
            .replace("{{updated_at}}", updated)
            .replace("{{total_events}}", str(len(events)))
            .replace("{{ltv_count}}", str(ltv["count"]))
            .replace("{{ltv_avg}}", str(ltv["avg"]))
            .replace("{{ltv_median}}", str(ltv["median"]))
            .replace("{{ltv_max}}", str(ltv["max"]))
            .replace("{{ltv_rows_html}}", ltv_rows)
            .replace("{{ltv_hist_json}}", json.dumps(ltv["hist"]))
            .replace("{{month_presets_html}}", month_presets)
            .replace("{{kpi_pausadas}}", str(kpis["pausadas"]))
            .replace("{{kpi_ativas}}", str(kpis["ativas"]))
            .replace("{{kpi_pausas_30d}}", str(kpis["p30"]))
            .replace("{{kpi_ativacoes_30d}}", str(kpis["a30"]))
            .replace("{{rows_html}}", rows)
            .replace("{{gestor_chips_html}}", gestor_chips)
            .replace("{{consultor_chips_html}}", consultor_chips)
            .replace("{{count_total}}", str(dc["total"]))
            .replace("{{count_7d}}", str(dc["7d"]))
            .replace("{{count_15d}}", str(dc["15d"]))
            .replace("{{count_30d}}", str(dc["30d"]))
            .replace("{{count_60d}}", str(dc["60d"]))
            .replace("{{gestores_json}}", json.dumps(gestores))
            .replace("{{consultores_json}}", json.dumps(consultores))
            .replace("{{timeline_json}}", json.dumps(timeline)))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    return OUT_HTML


if __name__ == "__main__":
    p = generate()
    print(f"Dashboard gerado: {p}")
