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
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="theme-color" content="#0f1117">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Monitor — Centrífugas</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0f1117;--bg2:#1a1d27;--bg3:#10131c;
  --border:#2a2d3a;--accent:#6366f1;
  --green:#34d399;--red:#f87171;--amber:#fbbf24;
  --txt:#e2e8f0;--muted:#64748b;
  --r:12px;--r-sm:8px;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;font-family:'Segoe UI',system-ui,sans-serif;
           background:var(--bg);color:var(--txt);font-size:16px}

/* ── HEADER ── */
.hdr{
  position:sticky;top:0;z-index:50;
  display:flex;align-items:center;justify-content:space-between;
  background:var(--bg2);border-bottom:1px solid var(--border);
  padding:12px 16px;gap:10px;
}
.hdr-logo{font-size:1rem;font-weight:700;white-space:nowrap}
.hdr-logo span{color:var(--accent)}
.hdr-right{display:flex;align-items:center;gap:8px;flex-shrink:0}
.chip{background:var(--bg3);border:1px solid var(--border);border-radius:20px;
      padding:4px 12px;font-size:.8rem;color:var(--muted);white-space:nowrap}
.btn{display:inline-flex;align-items:center;justify-content:center;
     padding:8px 14px;border-radius:var(--r-sm);border:none;
     font-size:.85rem;font-weight:600;cursor:pointer;text-decoration:none;
     min-height:36px;transition:opacity .15s}
.btn:active{opacity:.75}
.btn-cfg{background:var(--bg3);color:var(--txt);border:1px solid var(--border)}
.btn-out{background:#2d1f1f;color:var(--red);border:1px solid #3d2020}

/* ── MAIN ── */
.main{padding:16px;display:flex;flex-direction:column;gap:20px;max-width:1200px;margin:0 auto}

/* ── ALARM BANNER ── */
.alarm-banner{
  display:none;
  background:#450a0a;border:2px solid #7f1d1d;border-radius:var(--r);
  padding:14px 16px;color:#fca5a5;font-weight:700;
  font-size:.95rem;line-height:1.4;
  animation:pulse-border 1.4s ease-in-out infinite;
}
.alarm-banner .alarm-icon{font-size:1.3rem;margin-right:8px;vertical-align:middle}
@keyframes pulse-border{
  0%,100%{border-color:#7f1d1d;box-shadow:0 0 0 0 rgba(127,29,29,.4)}
  50%{border-color:#dc2626;box-shadow:0 0 0 6px rgba(127,29,29,0)}
}

/* ── MACHINE BLOCK ── */
.maq-block{background:var(--bg2);border:1px solid var(--border);
           border-radius:var(--r);padding:16px;display:flex;flex-direction:column;gap:14px}
.maq-header{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.maq-dot{width:9px;height:9px;border-radius:50%;background:var(--accent);flex-shrink:0}
.maq-name{font-size:1rem;font-weight:700}
.maq-badge{background:var(--bg3);border:1px solid var(--border);border-radius:6px;
           padding:2px 10px;font-size:.72rem;color:var(--muted);margin-left:auto}
.maq-rec-badge{background:#064e3b;color:var(--green);
               border:1px solid #065f46;border-radius:6px;
               padding:2px 10px;font-size:.72rem;font-weight:600}

/* ── CARDS GRID ── */
.cards{display:grid;gap:10px;
       grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}
.card{background:var(--bg3);border:1px solid var(--border);
      border-radius:var(--r);padding:14px 10px;text-align:center;
      transition:border-color .3s}
.card-lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;
          letter-spacing:.06em;margin-bottom:6px}
.card-val{font-size:1.9rem;font-weight:800;line-height:1;letter-spacing:-.5px}
.card-unit{font-size:.7rem;color:var(--muted);margin-top:3px}
.card-avg{font-size:.72rem;color:var(--muted);margin-top:8px;
          padding-top:8px;border-top:1px solid var(--border)}
.card-avg b{color:var(--accent)}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;
      font-size:.78rem;font-weight:700}
.pill-ok{background:#064e3b;color:var(--green)}
.pill-err{background:#450a0a;color:var(--red)}

/* ── CHARTS ── */
.charts{display:grid;gap:10px;
        grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.chart-box{background:var(--bg3);border:1px solid var(--border);
           border-radius:var(--r);padding:12px;
           height:180px;position:relative}
.chart-box canvas{position:absolute;inset:10px}

/* ── MODAL ── */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);
         display:none;align-items:center;justify-content:center;
         z-index:200;padding:16px}
.modal{background:var(--bg2);border:1px solid var(--border);
       border-radius:var(--r);padding:24px;width:100%;max-width:360px}
.modal h3{font-size:1.1rem;margin-bottom:16px}
.modal label{display:block;font-size:.82rem;color:var(--muted);margin:12px 0 6px}
.modal input[type=email]{
  width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--r-sm);color:var(--txt);padding:10px 12px;
  font-size:.95rem;outline:none;
}
.modal input[type=email]:focus{border-color:var(--accent)}
.chk-row{display:flex;align-items:center;gap:10px;margin-top:12px;cursor:pointer}
.chk-row input{width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}
.btn-primary{background:var(--accent);color:#fff}
.btn-sec{background:#334155;color:#fff}

/* ── RESPONSIVE ── */
@media(max-width:480px){
  .hdr{padding:10px 12px}
  .hdr-logo{font-size:.9rem}
  .main{padding:10px;gap:14px}
  .cards{grid-template-columns:repeat(2,1fr)}
  .card-val{font-size:1.6rem}
  .charts{grid-template-columns:1fr}
  .chart-box{height:160px}
  .btn{padding:7px 11px;font-size:.8rem}
  .chip{display:none}  /* Ocultar nombre de usuario en mobile muy chico */
}
@media(min-width:768px){
  .main{padding:20px 24px}
  .cards{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
  .chart-box{height:200px}
}
</style></head><body>

<div class="hdr">
  <div class="hdr-logo">Monitor <span>Centrífugas</span></div>
  <div class="hdr-right">
    <span class="chip">{{ user }}</span>
    <button onclick="openModal()" class="btn btn-cfg">⚙ Config</button>
    <a href="/logout" class="btn btn-out">Salir</a>
  </div>
</div>

<div class="main" id="main"></div>

<div class="overlay" id="overlay" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <h3>Configuración de alertas</h3>
    <label>Email para recibir alarmas</label>
    <input type="email" id="userEmail" placeholder="tu@email.com">
    <label class="chk-row">
      <input type="checkbox" id="userAlerts">
      Recibir notificaciones por email
    </label>
    <div class="modal-actions">
      <button class="btn btn-sec" onclick="closeModal()">Cancelar</button>
      <button class="btn btn-primary" onclick="saveSettings()">Guardar</button>
    </div>
  </div>
</div>

<script>
const MACHINES = {{ machines|tojson }};
const charts = {};
const initialized = {};

function openModal(){
  document.getElementById('overlay').style.display='flex';
  fetch('/api/users').then(r=>r.json()).then(d=>{
    document.getElementById('userEmail').value=d.email||'';
    document.getElementById('userAlerts').checked=!!d.alerts;
  });
}
function closeModal(){document.getElementById('overlay').style.display='none'}
function saveSettings(){
  const data={email:document.getElementById('userEmail').value,
              alerts:document.getElementById('userAlerts').checked};
  fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},
                      body:JSON.stringify(data)})
    .then(()=>{closeModal()});
}

MACHINES.forEach(maq=>{
  const main=document.getElementById('main');
  const block=document.createElement('div');
  block.className='maq-block';block.id='block_'+maq.id;
  block.innerHTML=`
    <div class="maq-header">
      <div class="maq-dot"></div>
      <div class="maq-name">${maq.label}</div>
      <span class="maq-badge" id="badge_${maq.id}">Sin datos</span>
    </div>
    <div class="alarm-banner" id="alarm_${maq.id}">
      <span class="alarm-icon">🚨</span>
      <span id="alarm_txt_${maq.id}"></span>
    </div>
    <div class="cards" id="cards_${maq.id}"></div>
    <div class="charts" id="charts_${maq.id}"></div>
  `;
  main.appendChild(block);
  charts[maq.id]={};
});

function mkChart(cid,label,color){
  const ctx=document.getElementById(cid)?.getContext('2d');
  if(!ctx)return null;
  return new Chart(ctx,{
    type:'line',
    data:{labels:[],datasets:[{label,data:[],
      borderColor:color,backgroundColor:color+'18',
      borderWidth:2,tension:.35,pointRadius:0,fill:true}]},
    options:{
      responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},
      scales:{
        x:{ticks:{color:'#475569',maxTicksLimit:5,maxRotation:0},grid:{color:'#1e2235'}},
        y:{ticks:{color:'#475569',maxTicksLimit:5},grid:{color:'#1e2235'}}
      }
    }
  });
}

function fmtVal(v,dec){
  if(v===null||v===undefined)return'--';
  if(typeof v==='boolean')
    return v?'<span class="pill pill-ok">OK</span>'
            :'<span class="pill pill-err">FALLA</span>';
  return Number(v).toFixed(dec??1);
}

function initCards(maqId,dvars){
  if(initialized[maqId])return;
  initialized[maqId]=true;
  const cardsEl=document.getElementById('cards_'+maqId);
  const chartsEl=document.getElementById('charts_'+maqId);
  charts[maqId]={};
  dvars.forEach(v=>{
    const card=document.createElement('div');
    card.className='card';
    card.style.borderColor=v.color+'55';
    card.innerHTML=`
      <div class="card-lbl">${v.label}</div>
      <div class="card-val" id="val_${maqId}_${v.key}" style="color:${v.color}">--</div>
      <div class="card-unit">${v.unit}</div>
      <div class="card-avg" id="avg_${maqId}_${v.key}" style="display:none">
        Prom sesión: <b id="avgv_${maqId}_${v.key}">--</b> ${v.unit}
      </div>`;
    cardsEl.appendChild(card);
    if(!v.is_boolean){
      const box=document.createElement('div');
      box.className='chart-box';
      const cid=`ch_${maqId}_${v.key}`;
      box.innerHTML=`<canvas id="${cid}"></canvas>`;
      chartsEl.appendChild(box);
      charts[maqId][v.key]=null;
      setTimeout(()=>{charts[maqId][v.key]=mkChart(cid,v.label,v.color);},60);
    }
  });
}

function update(){
  fetch('/api/data').then(r=>r.json()).then(data=>{
    for(const[maqId,d]of Object.entries(data)){
      if(!d.display_vars)continue;
      initCards(maqId,d.display_vars);

      const badge=document.getElementById('badge_'+maqId);
      if(badge&&d.timestamp){
        badge.textContent=d.recording?'⏺ '+d.timestamp:d.timestamp;
        badge.className=d.recording?'maq-rec-badge':'maq-badge';
      }

      // Banner de alarma
      const banner=document.getElementById('alarm_'+maqId);
      const txt=document.getElementById('alarm_txt_'+maqId);
      const msg=d.alarm_message||'';
      if(banner){banner.style.display=msg?'block':'none';}
      if(txt)txt.textContent=msg;

      // Cards
      d.display_vars.forEach(v=>{
        const el=document.getElementById('val_'+maqId+'_'+v.key);
        const avgEl=document.getElementById('avg_'+maqId+'_'+v.key);
        const avgV=document.getElementById('avgv_'+maqId+'_'+v.key);
        if(el)el.innerHTML=fmtVal(d.current[v.key],v.decimals);
        if(!v.is_boolean&&avgEl&&avgV&&d.history?.length){
          const vals=d.history.map(h=>h[v.key]).filter(x=>x!=null);
          if(vals.length){
            avgEl.style.display='block';
            avgV.textContent=(vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(v.decimals??1);
          }
        }
      });

      // Gráficos
      if(d.history?.length){
        d.display_vars.forEach(v=>{
          if(v.is_boolean)return;
          const ch=charts[maqId][v.key];
          if(!ch)return;
          const pts=d.history.filter(h=>!h._gap);
          ch.data.labels=pts.map(h=>h.timestamp||'');
          ch.data.datasets[0].data=pts.map(h=>h[v.key]??null);
          ch.update('none');
        });
      }
    }
  }).catch(e=>console.warn('API error:',e));
}

update();
setInterval(update,2000);
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
