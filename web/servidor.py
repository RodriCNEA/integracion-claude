# -*- coding: utf-8 -*-
"""
web/servidor.py — Servidor web Flask.

Lee el estado de todos los MaquinaCore registrados y los expone
como una API REST + dashboard HTML. No sabe nada de tkinter.

Uso:
    from web.servidor import WebServer
    server = WebServer()
    server.register(core1)
    server.register(core2)
    server.start()   # arranca en hilo daemon, no bloquea
    ...
    server.stop()
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from functools import wraps
from typing import TYPE_CHECKING

from flask import Flask, Response, jsonify, redirect, render_template_string, request, session, url_for

if TYPE_CHECKING:
    from core.maquina_core import MaquinaCore

# Silenciar logs de werkzeug en consola
logging.getLogger("werkzeug").setLevel(logging.ERROR)

USERS_FILE = "users.json"


# ===========================================================================
#  TEMPLATES HTML
# ===========================================================================

LOGIN_HTML = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Acceso — Monitor de Centrífugas</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0f1117;display:flex;
       justify-content:center;align-items:center;min-height:100vh}
  .card{background:#1a1d27;border:1px solid #2a2d3a;border-radius:16px;
        padding:40px;width:340px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
  h1{color:#e2e8f0;font-size:1.4rem;font-weight:600;margin-bottom:6px;text-align:center}
  .sub{color:#64748b;font-size:.85rem;text-align:center;margin-bottom:30px}
  label{display:block;color:#94a3b8;font-size:.8rem;font-weight:500;
        letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}
  input{width:100%;background:#0f1117;border:1px solid #2a2d3a;border-radius:8px;
        color:#e2e8f0;padding:10px 14px;font-size:.95rem;margin-bottom:18px;
        outline:none;transition:border-color .2s}
  input:focus{border-color:#6366f1}
  button{width:100%;background:#6366f1;color:#fff;border:none;border-radius:8px;
         padding:11px;font-size:1rem;font-weight:600;cursor:pointer;
         transition:background .2s;margin-top:4px}
  button:hover{background:#4f46e5}
  .err{color:#f87171;font-size:.85rem;text-align:center;margin-top:12px}
</style></head><body>
<div class="card">
  <h1>Monitor de Centrífugas</h1>
  <p class="sub">Ingresá tus credenciales para continuar</p>
  <form method="post">
    <label>Usuario</label>
    <input type="text" name="username" placeholder="usuario" required autofocus>
    <label>Contraseña</label>
    <input type="password" name="password" placeholder="••••••••" required>
    <button type="submit">Entrar</button>
  </form>
  {% if error %}<p class="err">{{ error }}</p>{% endif %}
</div></body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor de Centrífugas</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}
  
  /* Header */
  .hdr{display:flex;justify-content:space-between;align-items:center;
       background:#1a1d27;border-bottom:1px solid #2a2d3a;padding:14px 24px}
  .hdr-title{font-size:1.1rem;font-weight:600;color:#e2e8f0}
  .hdr-title span{color:#6366f1}
  .hdr-right{display:flex;align-items:center;gap:12px}
  .tag-user{background:#1e2235;border:1px solid #2a2d3a;border-radius:20px;
            padding:5px 14px;font-size:.82rem;color:#94a3b8}
  .btn{padding:7px 16px;border-radius:8px;border:none;font-size:.85rem;
       font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
  .btn-logout{background:#2d1f1f;color:#f87171;border:1px solid #3d2020}
  .btn-logout:hover{background:#3d2020}

  /* Layout */
  .main{padding:20px 24px;display:flex;flex-direction:column;gap:24px}

  /* Alarma banner */
  .alarm-banner{display:none;background:#2d1515;border:1px solid #7f1d1d;
                border-radius:12px;padding:14px 20px;color:#fca5a5;
                font-weight:600;font-size:.95rem;animation:blink 1.2s infinite}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.6}}

  /* Bloque por máquina */
  .maq-block{background:#1a1d27;border:1px solid #2a2d3a;border-radius:16px;padding:20px}
  .maq-title{font-size:1rem;font-weight:600;color:#e2e8f0;margin-bottom:16px;
             display:flex;align-items:center;gap:10px}
  .maq-title .dot{width:8px;height:8px;border-radius:50%;background:#6366f1}
  .maq-title .badge{background:#1e2235;border:1px solid #2a2d3a;border-radius:6px;
                    padding:2px 10px;font-size:.75rem;color:#64748b;font-weight:400}

  /* Grilla de cards */
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:16px}
  .card{background:#0f1117;border:1px solid #2a2d3a;border-radius:12px;padding:16px;text-align:center}
  .card-label{font-size:.75rem;color:#64748b;text-transform:uppercase;
              letter-spacing:.06em;margin-bottom:8px}
  .card-value{font-size:2rem;font-weight:700;line-height:1}
  .card-unit{font-size:.75rem;color:#64748b;margin-top:4px}
  .card-avg{font-size:.78rem;color:#475569;margin-top:8px;padding-top:8px;
            border-top:1px solid #1e2235}

  /* Estados booleanos */
  .status-ok{color:#34d399}.status-err{color:#f87171}
  .pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.78rem;font-weight:600}
  .pill-ok{background:#064e3b;color:#34d399}
  .pill-err{background:#450a0a;color:#f87171}

  /* Gráficos */
  .charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
  .chart-box{background:#0f1117;border:1px solid #2a2d3a;border-radius:12px;
             padding:14px;height:200px;position:relative}
  .chart-box canvas{position:absolute;inset:12px}

  /* Separador de máquinas */
  .maq-sep{height:1px;background:#2a2d3a;margin:8px 0 20px}

  /* Responsive */
  @media(max-width:600px){
    .hdr{flex-direction:column;gap:10px;text-align:center}
    .cards{grid-template-columns:repeat(2,1fr)}
  }
</style></head><body>

<div class="hdr">
  <div class="hdr-title">Monitor <span>Centrífugas</span></div>
  <div class="hdr-right">
    <span class="tag-user">{{ user }}</span>
    <a href="/logout" class="btn btn-logout">Salir</a>
  </div>
</div>

<div class="main" id="main"></div>

<script>
const MACHINES = {{ machines|tojson }};
const charts = {};

// Inicializar estructura para cada máquina
MACHINES.forEach(maq => {
  const main = document.getElementById('main');

  const block = document.createElement('div');
  block.className = 'maq-block';
  block.id = 'block_' + maq.id;
  block.innerHTML = `
    <div class="maq-title">
      <div class="dot"></div>
      ${maq.label}
      <span class="badge" id="badge_${maq.id}">Sin datos</span>
    </div>
    <div id="alarm_${maq.id}" class="alarm-banner"></div>
    <div class="cards" id="cards_${maq.id}"></div>
    <div class="charts" id="charts_${maq.id}"></div>
  `;
  main.appendChild(block);
  charts[maq.id] = {};
});

function mkChart(canvasId, label, color) {
  const ctx = document.getElementById(canvasId)?.getContext('2d');
  if (!ctx) return null;
  return new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{ label, data: [],
      borderColor: color, backgroundColor: color + '22',
      borderWidth: 2, tension: 0.35, pointRadius: 0, fill: true }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#475569', maxTicksLimit: 6 }, grid: { color: '#1e2235' } },
        y: { ticks: { color: '#475569' }, grid: { color: '#1e2235' } }
      }
    }
  });
}

function pushChart(chart, label, value) {
  if (!chart) return;
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > 60) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update('none');
}

function fmtVal(v, dec) {
  if (v === null || v === undefined) return '--';
  if (typeof v === 'boolean') return v ? '<span class="pill pill-ok">OK</span>' : '<span class="pill pill-err">FALLA</span>';
  return Number(v).toFixed(dec ?? 1);
}

// Construir cards dinámicamente la primera vez que llegan datos de una máquina
const initialized = {};
function initCards(maqId, display_vars) {
  if (initialized[maqId]) return;
  initialized[maqId] = true;
  const cardsEl = document.getElementById('cards_' + maqId);
  const chartsEl = document.getElementById('charts_' + maqId);
  charts[maqId] = {};

  display_vars.forEach(v => {
    // Card
    const card = document.createElement('div');
    card.className = 'card';
    card.style.borderColor = v.color + '55';
    card.innerHTML = `
      <div class="card-label">${v.label}</div>
      <div class="card-value" id="val_${maqId}_${v.key}" style="color:${v.color}">--</div>
      <div class="card-unit">${v.unit}</div>
      <div class="card-avg" id="avg_${maqId}_${v.key}" style="display:none">
        Prom 10m: <b id="avgval_${maqId}_${v.key}">--</b>
      </div>
    `;
    cardsEl.appendChild(card);

    // Gráfico solo para variables numéricas no booleanas
    if (!v.is_boolean) {
      const box = document.createElement('div');
      box.className = 'chart-box';
      const cid = `ch_${maqId}_${v.key}`;
      box.innerHTML = `<canvas id="${cid}"></canvas>`;
      chartsEl.appendChild(box);
      charts[maqId][v.key] = null; // se crea después de insertar el DOM
      setTimeout(() => {
        charts[maqId][v.key] = mkChart(cid, v.label, v.color);
      }, 50);
    }
  });
}

function update() {
  fetch('/api/data').then(r => r.json()).then(data => {
    for (const [maqId, d] of Object.entries(data)) {
      if (!d.display_vars) continue;
      initCards(maqId, d.display_vars);

      // Badge de timestamp
      const badge = document.getElementById('badge_' + maqId);
      if (badge && d.timestamp) badge.textContent = d.timestamp;

      // Alarmas
      const alarmEl = document.getElementById('alarm_' + maqId);
      const alarmMsg = d.alarm_message || '';
      if (alarmEl) {
        alarmEl.textContent = alarmMsg;
        alarmEl.style.display = alarmMsg ? 'block' : 'none';
      }

      // Valores en cards
      d.display_vars.forEach(v => {
        const valEl  = document.getElementById(`val_${maqId}_${v.key}`);
        const avgEl  = document.getElementById(`avg_${maqId}_${v.key}`);
        const avgVal = document.getElementById(`avgval_${maqId}_${v.key}`);
        const raw = d.current[v.key];

        if (valEl) valEl.innerHTML = fmtVal(raw, v.decimals);

        // Promedio en historial (para numéricas)
        if (!v.is_boolean && avgEl && avgVal && d.history?.length) {
          const vals = d.history.map(h => h[v.key]).filter(x => x !== null && x !== undefined);
          if (vals.length) {
            avgEl.style.display = 'block';
            avgVal.textContent = (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(v.decimals ?? 1);
          }
        }
      });

      // Actualizar gráficos con historial
      if (d.history?.length) {
        d.history.forEach(pt => {
          if (pt._gap) return;
          const lbl = pt.timestamp || '';
          d.display_vars.forEach(v => {
            if (!v.is_boolean && charts[maqId][v.key] && pt[v.key] !== undefined) {
              // Solo agregar si el chart no tiene este label ya
            }
          });
        });
        // Actualización simple: reemplazar datos completos del gráfico
        d.display_vars.forEach(v => {
          if (v.is_boolean) return;
          const ch = charts[maqId][v.key];
          if (!ch) return;
          const labels = d.history.filter(h=>!h._gap).map(h=>h.timestamp||'');
          const vals   = d.history.filter(h=>!h._gap).map(h=>h[v.key]??null);
          ch.data.labels = labels;
          ch.data.datasets[0].data = vals;
          ch.update('none');
        });
      }
    }
  }).catch(e => console.warn('Error API:', e));
}

update();
setInterval(update, 2000);
</script></body></html>
"""


# ===========================================================================
#  SERVIDOR WEB
# ===========================================================================
class WebServer:
    """
    Servidor Flask que expone el estado de todos los cores registrados.

    No bloquea: corre en un hilo daemon.
    """

    def __init__(self, port: int = 5000) -> None:
        self._port  = port
        self._cores: dict[str, "MaquinaCore"] = {}
        self._thread: threading.Thread | None = None
        self._app = Flask(__name__)
        self._app.secret_key = secrets.token_hex(16)
        self._register_routes()
        self._ensure_users_file()

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------
    def register(self, core: "MaquinaCore") -> None:
        """Registra un MaquinaCore para que sea servido por el dashboard."""
        self._cores[core.machine_id] = core

    def start(self) -> None:
        """Arranca el servidor en un hilo daemon. No bloquea."""
        self._thread = threading.Thread(
            target=lambda: self._app.run(
                host="0.0.0.0", port=self._port,
                debug=False, use_reloader=False
            ),
            daemon=True,
            name="flask-server",
        )
        self._thread.start()

    # -----------------------------------------------------------------------
    # Rutas Flask
    # -----------------------------------------------------------------------
    def _login_required(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper

    def _register_routes(self) -> None:
        app = self._app

        @app.route("/login", methods=["GET", "POST"])
        def login():
            error = None
            if request.method == "POST":
                u = request.form.get("username", "")
                p = request.form.get("password", "")
                users = self._load_users()
                if u in users and users[u].get("password") == p:
                    session["user"] = u
                    return redirect(url_for("dashboard"))
                error = "Credenciales incorrectas."
            return render_template_string(LOGIN_HTML, error=error)

        @app.route("/logout")
        def logout():
            session.pop("user", None)
            return redirect(url_for("login"))

        @app.route("/")
        @self._login_required
        def dashboard():
            machines = [
                {"id": mid, "label": f"MÁQUINA {i+1} ({mid})"}
                for i, mid in enumerate(self._cores)
            ]
            return render_template_string(
                DASHBOARD_HTML,
                user=session["user"],
                machines=machines,
            )

        @app.route("/api/data")
        @self._login_required
        def api_data():
            result = {}
            for mid, core in self._cores.items():
                latest = core.latest_data
                history = core.history_buffer

                # Mensaje de alarma activa (para el banner)
                alarm_msg = ""
                for key, state in core.alarm_states.items():
                    if state["active"]:
                        ack = " (En revisión)" if state.get("ack") else ""
                        alarm_msg += f"⚠ {state['name']}{ack}  "

                # Metadata de visualización: filtrar por selección del usuario
                visible_keys = core.get_config("web_visible_vars", None)
                display_vars = []
                for vd in core.parser.display_config:
                    if visible_keys is None or vd.key in visible_keys:
                        display_vars.append({
                            "key":        vd.key,
                            "label":      vd.label,
                            "unit":       vd.unit,
                            "color":      vd.color,
                            "decimals":   vd.decimals,
                            "is_boolean": vd.is_boolean,
                        })

                result[mid] = {
                    "current":      latest,
                    "history":      history[-60:],
                    "alarm_message": alarm_msg.strip(),
                    "timestamp":    latest.get("timestamp", ""),
                    "display_vars": display_vars,
                    "recording":    core.is_recording,
                    "paused":       core.is_paused,
                }
            return jsonify(result)

        @app.route("/api/users", methods=["GET"])
        @self._login_required
        def api_users_get():
            users = self._load_users()
            u = session["user"]
            data = users.get(u, {})
            return jsonify({"email": data.get("email", ""), "alerts": data.get("alerts", False)})

        @app.route("/api/users", methods=["POST"])
        @self._login_required
        def api_users_post():
            users = self._load_users()
            u = session["user"]
            body = request.get_json() or {}
            if u in users:
                users[u]["email"]  = body.get("email", "")
                users[u]["alerts"] = body.get("alerts", False)
                self._save_users(users)
            return jsonify({"status": "ok"})

    # -----------------------------------------------------------------------
    # Gestión de usuarios
    # -----------------------------------------------------------------------
    def _ensure_users_file(self) -> None:
        if not os.path.exists(USERS_FILE):
            self._save_users({
                "admin": {
                    "password": "centrifuga2024",
                    "email":    "",
                    "alerts":   True,
                    "perms":    {"rpm": True, "temp": True, "status": True},
                }
            })

    @staticmethod
    def _load_users() -> dict:
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _save_users(data: dict) -> None:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
