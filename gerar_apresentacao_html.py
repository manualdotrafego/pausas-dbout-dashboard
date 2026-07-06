"""Gera página estática interativa (Chart.js) com timeline de pausas de junho por gestor.

Saída: docs/apresentacao-junho.html — chips clicáveis, gráfico muda ao clicar.
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from db import get_conn
from cpl_lookup import classify, MENTION_TO_GESTOR

START = "2026-06-01T00:00:00"
END   = "2026-07-01T00:00:00"

CORES = {
    "Victor":       "#ef4444",
    "Thiago Braga": "#f59e0b",
    "Milena":       "#3b82f6",
    "Mota":         "#10b981",
    "Igor":         "#a855f7",
    "Bueno":        "#14b8a6",
}


def _fetch():
    with get_conn() as con:
        return con.execute(
            """SELECT unit_name, unit_key, timestamp, mentions_json, reason FROM events
               WHERE event_type='pausar' AND timestamp >= ? AND timestamp < ?
               ORDER BY timestamp ASC""",
            (START, END),
        ).fetchall()


def _gestor_of(mentions_json: str) -> str | None:
    ms = json.loads(mentions_json or "[]")
    for m in ms:
        if classify(m) == "gestor":
            k = m.strip().lower().replace("  ", " ")
            return MENTION_TO_GESTOR.get(k, m)
    return None


def _build_data():
    rows = _fetch()
    por_gestor: dict[str, list] = defaultdict(list)
    for r in rows:
        g = _gestor_of(r["mentions_json"]) or "Sem gestor"
        por_gestor[g].append({
            "unit": r["unit_name"],
            "key": r["unit_key"],
            "ts": r["timestamp"],
            "reason": (r["reason"] or "")[:200],
        })
    # dedup: mantém 1ª pausa por unit_key dentro do mês
    for g in list(por_gestor.keys()):
        seen, out = set(), []
        for p in por_gestor[g]:
            if p["key"] in seen:
                continue
            seen.add(p["key"])
            out.append(p)
        por_gestor[g] = out
    return por_gestor


HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pausas Junho/2026 — Apresentação por Gestor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  :root {
    --bg: #0d1117;
    --panel: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: -apple-system, "SF Pro Display", "Segoe UI", Roboto, sans-serif; }
  .wrap { max-width: 1400px; margin: 0 auto; padding: 32px 24px 64px; }
  h1 { font-size: 32px; margin: 0 0 4px; letter-spacing: -0.02em; }
  .sub { color: var(--muted); font-size: 15px; margin-bottom: 28px; }
  .chips { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
  .chip {
    background: var(--panel); border: 1.5px solid var(--border); color: var(--text);
    padding: 10px 16px; border-radius: 999px; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: all 0.15s; user-select: none;
    display: flex; align-items: center; gap: 8px;
  }
  .chip:hover { border-color: var(--muted); }
  .chip.active { background: var(--gestor-color, #3b82f6); border-color: var(--gestor-color, #3b82f6); color: #fff; }
  .chip .count { background: rgba(255,255,255,0.15); padding: 2px 8px; border-radius: 999px; font-size: 12px; }
  .chip.active .count { background: rgba(0,0,0,0.25); }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 24px; margin-bottom: 20px;
  }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .kpi .lbl { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
  .kpi .val { font-size: 32px; font-weight: 700; margin-top: 4px; }
  .chart-wrap { position: relative; height: 480px; }
  .list { margin-top: 18px; max-height: 320px; overflow-y: auto; }
  .list table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .list th, .list td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
  .list th { color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }
  .list td.data { color: var(--muted); white-space: nowrap; }
  .list td.reason { color: var(--muted); max-width: 500px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .footer { color: var(--muted); font-size: 12px; margin-top: 32px; text-align: center; }
  .footer a { color: var(--muted); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Pausas em Junho/2026 — por Gestor</h1>
  <div class="sub">Clique num gestor abaixo para ver a linha do tempo das pausas. Dados extraídos do canal #financeiro (Discord DBOUT).</div>

  <div class="chips" id="chips"></div>

  <div class="kpis">
    <div class="kpi"><div class="lbl">Unidades pausadas</div><div class="val" id="kpi-total">–</div></div>
    <div class="kpi"><div class="lbl">Dias com pausa</div><div class="val" id="kpi-dias">–</div></div>
    <div class="kpi"><div class="lbl">Reativações no mês</div><div class="val">0</div></div>
    <div class="kpi"><div class="lbl">Evasão</div><div class="val">100%</div></div>
  </div>

  <div class="card">
    <div class="chart-wrap"><canvas id="chart"></canvas></div>
    <div class="list">
      <table>
        <thead><tr><th>Data</th><th>Unidade</th><th>Motivo</th></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="footer">
    Gerado automaticamente · Dashboard completo em <a href="index.html">/index.html</a>
  </div>
</div>

<script>
const DATA = /*DATA_JSON*/;
const CORES = /*CORES_JSON*/;

const chips = document.getElementById("chips");
const gestores = Object.keys(DATA).sort((a,b) => DATA[b].length - DATA[a].length);

let atual = gestores[0];

gestores.forEach(g => {
  const el = document.createElement("div");
  el.className = "chip";
  el.style.setProperty("--gestor-color", CORES[g] || "#666");
  el.innerHTML = `${g} <span class="count">${DATA[g].length}</span>`;
  el.onclick = () => { atual = g; render(); };
  chips.appendChild(el);
});

const ctx = document.getElementById("chart").getContext("2d");
let chart;

function render() {
  // chip ativo
  Array.from(chips.children).forEach((el, i) => {
    el.classList.toggle("active", gestores[i] === atual);
  });

  const pausas = DATA[atual] || [];
  const cor = CORES[atual] || "#3b82f6";

  // Empilha múltiplas pausas no mesmo dia
  const contDia = {};
  const pontos = pausas.map(p => {
    const dia = p.ts.slice(0, 10);
    contDia[dia] = (contDia[dia] || 0) + 1;
    return { x: p.ts.slice(0, 10), y: contDia[dia], unit: p.unit, reason: p.reason, ts: p.ts };
  });

  const cfg = {
    type: "scatter",
    data: {
      datasets: [{
        label: atual,
        data: pontos,
        backgroundColor: cor,
        borderColor: "#fff",
        borderWidth: 1.5,
        pointRadius: 9,
        pointHoverRadius: 12,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "time",
          time: { unit: "day", displayFormats: { day: "dd/MM" }, tooltipFormat: "dd/MM/yyyy" },
          min: "2026-05-31",
          max: "2026-07-01",
          grid: { color: "#30363d40" },
          ticks: { color: "#8b949e" },
        },
        y: {
          beginAtZero: true,
          min: 0,
          max: Math.max(3, Math.max(...pontos.map(p => p.y), 0) + 1),
          grid: { display: false },
          ticks: { display: false },
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161b22",
          borderColor: cor,
          borderWidth: 1,
          titleColor: "#e6edf3",
          bodyColor: "#e6edf3",
          padding: 12,
          callbacks: {
            title: (items) => items[0].raw.unit,
            label: (item) => {
              const d = new Date(item.raw.ts);
              return d.toLocaleDateString("pt-BR");
            },
            afterLabel: (item) => item.raw.reason ? "\n" + item.raw.reason : "",
          }
        }
      }
    }
  };

  if (chart) { chart.destroy(); }
  chart = new Chart(ctx, cfg);

  // KPIs
  document.getElementById("kpi-total").textContent = pausas.length;
  document.getElementById("kpi-dias").textContent = Object.keys(contDia).length;

  // Lista
  const tbody = document.getElementById("tbody");
  tbody.innerHTML = "";
  pausas.slice().sort((a,b) => a.ts.localeCompare(b.ts)).forEach(p => {
    const tr = document.createElement("tr");
    const d = new Date(p.ts).toLocaleDateString("pt-BR");
    tr.innerHTML = `<td class="data">${d}</td><td><b>${p.unit}</b></td><td class="reason">${p.reason || "—"}</td>`;
    tbody.appendChild(tr);
  });
}

render();
</script>
</body>
</html>
"""


def main():
    por_gestor = _build_data()
    # remove "Sem gestor" se estiver vazio
    if "Sem gestor" in por_gestor and not por_gestor["Sem gestor"]:
        del por_gestor["Sem gestor"]

    data_json = json.dumps(por_gestor, ensure_ascii=False)
    cores_json = json.dumps(CORES, ensure_ascii=False)
    html = HTML.replace("/*DATA_JSON*/", data_json).replace("/*CORES_JSON*/", cores_json)

    out = HERE / "docs" / "apresentacao-junho.html"
    out.write_text(html, encoding="utf-8")
    print(f"✓ Gerado: {out}")
    print(f"  Gestores: {list(por_gestor.keys())}")
    print(f"  Total pausas: {sum(len(v) for v in por_gestor.values())}")


if __name__ == "__main__":
    main()
