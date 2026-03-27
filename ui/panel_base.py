# -*- coding: utf-8 -*-
"""
ui/panel_base.py — Panel base compartido por todas las máquinas.

Incluye:
  - ThemeManager: temas claro/oscuro con cambio en caliente
  - GaugeWidget, PlotWidget, StatusLed, ValueCard, AlarmBanner
  - MaquinaPanel: estructura completa de pestañas
      · Principal  (gráfico + gauge + sensores + tabla ensayo activo)
      · Ensayos    (gestión de ensayos y atributos)
      · Historial  (visor invertido + exportación completa)
      · Análisis   (estadísticas + gráfico acumulado)
      · Web Server (usuarios, permisos, Brevo)
      · Configuración
"""

from __future__ import annotations

import json
import math
import os
import tkinter as tk
from collections import deque
from datetime import datetime
from itertools import cycle
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Optional

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

matplotlib.use("TkAgg")

if TYPE_CHECKING:
    from core.maquina_core import MaquinaCore

USERS_FILE   = "users.json"
ENSAYOS_FILE = "ensayos.json"

# ===========================================================================
#  TEMAS
# ===========================================================================
_DARK = dict(
    bg="#0f1117", bg2="#1a1d27", bg3="#10131c", border="#2a2d3a",
    accent="#6366f1", green="#34d399", red="#f87171", amber="#fbbf24",
    text_primary="#e2e8f0", text_muted="#64748b", text_dim="#334155",
    mpl_bg="#10131c", mpl_grid="#1e2235", mpl_line="#6366f1", name="dark",
)
_LIGHT = dict(
    bg="#f4f6fb", bg2="#ffffff", bg3="#eef1f7", border="#d1d5e0",
    accent="#4f46e5", green="#059669", red="#dc2626", amber="#d97706",
    text_primary="#1e293b", text_muted="#64748b", text_dim="#cbd5e1",
    mpl_bg="#eef1f7", mpl_grid="#d1d5e0", mpl_line="#4f46e5", name="light",
)

THEME: dict = dict(_DARK)   # mutable, se actualiza en caliente


class ThemeManager:
    _callbacks: list = []

    @classmethod
    def toggle(cls) -> None:
        THEME.update(_LIGHT if THEME["name"] == "dark" else _DARK)
        for cb in list(cls._callbacks):
            try:
                cb()
            except Exception:
                pass

    @classmethod
    def register(cls, cb) -> None:
        if cb not in cls._callbacks:
            cls._callbacks.append(cb)

    @classmethod
    def unregister(cls, cb) -> None:
        try:
            cls._callbacks.remove(cb)
        except ValueError:
            pass


def apply_theme_to_style() -> None:
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    bg, bg2, border = THEME["bg"], THEME["bg2"], THEME["border"]
    txt, muted, accent = THEME["text_primary"], THEME["text_muted"], THEME["accent"]

    style.configure(".", background=bg, foreground=txt, fieldbackground=bg2,
                    troughcolor=bg2, bordercolor=border, darkcolor=bg2, lightcolor=bg2,
                    relief="flat", font=("Segoe UI", 10))
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=txt)
    style.configure("TLabelframe", background=bg, foreground=txt,
                    bordercolor=border, relief="flat")
    style.configure("TLabelframe.Label", background=bg, foreground=accent,
                    font=("Segoe UI", 9, "bold"))
    style.configure("TEntry", fieldbackground=bg2, foreground=txt,
                    bordercolor=border, insertcolor=txt)
    style.configure("TButton", background=bg2, foreground=txt,
                    bordercolor=border, font=("Segoe UI", 9))
    style.map("TButton", background=[("active", accent), ("pressed", "#4f46e5")],
              foreground=[("active", "#fff")])
    style.configure("Accent.TButton", background=accent, foreground="#fff",
                    bordercolor=accent, font=("Segoe UI", 9, "bold"))
    style.map("Accent.TButton",
              background=[("active", "#4f46e5"), ("pressed", "#3730a3")])
    style.configure("TNotebook", background=bg, bordercolor=border, tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab", background=bg2, foreground=muted,
                    padding=[14, 7], bordercolor=border, font=("Segoe UI", 9))
    style.map("TNotebook.Tab", background=[("selected", bg)],
              foreground=[("selected", txt)], expand=[("selected", [0, 0, 0, 2])])
    style.configure("Treeview", background=bg2, foreground=txt, fieldbackground=bg2,
                    rowheight=24, bordercolor=border, font=("Segoe UI", 9))
    style.configure("Treeview.Heading", background=bg, foreground=muted,
                    bordercolor=border, font=("Segoe UI", 9, "bold"))
    style.map("Treeview", background=[("selected", accent)],
              foreground=[("selected", "#fff")])
    style.configure("TCombobox", fieldbackground=bg2, background=bg2,
                    foreground=txt, arrowcolor=muted, bordercolor=border)
    style.configure("TScrollbar", background=bg2, troughcolor=bg, arrowcolor=muted)
    style.configure("TCheckbutton", background=bg, foreground=txt)
    style.map("TCheckbutton", background=[("active", bg)])
    style.configure("TRadiobutton", background=bg, foreground=txt)
    style.configure("TSeparator", background=border)


def apply_dark_theme(root: tk.Tk) -> None:
    THEME.update(_DARK)
    apply_theme_to_style()
    root.configure(bg=THEME["bg"])


# ===========================================================================
#  GAUGE
# ===========================================================================
class GaugeWidget(tk.Frame):
    def __init__(self, parent, min_val=0, max_val=2000,
                 title="Velocímetro", size=(3.0, 2.2), **kwargs):
        super().__init__(parent, bg=THEME["bg"], **kwargs)
        self._min, self._max, self._title = min_val, max_val, title
        self._value = float(min_val)
        self._fig, self._ax = plt.subplots(figsize=size)
        self._fig.patch.set_facecolor(THEME["mpl_bg"])
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().configure(bg=THEME["mpl_bg"], highlightthickness=0)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._draw(self._value)
        ThemeManager.register(self._on_theme)

    def _on_theme(self):
        self.configure(bg=THEME["bg"])
        self._fig.patch.set_facecolor(THEME["mpl_bg"])
        self._canvas.get_tk_widget().configure(bg=THEME["mpl_bg"])
        self._draw(self._value)

    def set_value(self, v: float):
        self._value = float(v)
        self._draw(self._value)

    def configure_range(self, mn, mx):
        self._min, self._max = mn, mx
        self._draw(self._value)

    def _draw(self, value: float):
        ax = self._ax
        ax.clear()
        ax.set_facecolor(THEME["mpl_bg"])
        mn, mx = self._min, self._max
        value = max(mn, min(value, mx))
        bg_arc_color = "#1e2235" if THEME["name"] == "dark" else "#d1d5e0"
        thetas_bg = np.linspace(np.pi, 0, 180)
        ax.plot(np.cos(thetas_bg), np.sin(thetas_bg),
                lw=18, color=bg_arc_color, solid_capstyle="butt", zorder=1)
        ratio = (value - mn) / (mx - mn) if mx != mn else 0
        end_theta = np.pi - ratio * np.pi
        thetas_v = np.linspace(np.pi, end_theta, max(2, int(ratio * 180)))
        if len(thetas_v) >= 2:
            for i in range(len(thetas_v) - 1):
                t = i / max(1, len(thetas_v) - 2)
                r = min(1.0, t * 2) if t < 0.5 else 1.0
                g = 1.0 if t < 0.5 else max(0.0, 1.0 - (t - 0.5) * 2)
                ax.plot([np.cos(thetas_v[i]), np.cos(thetas_v[i+1])],
                        [np.sin(thetas_v[i]), np.sin(thetas_v[i+1])],
                        lw=18, color=(r, g, 0.15), solid_capstyle="butt", zorder=2)
        needle = np.pi - ratio * np.pi
        ax.annotate("", xy=(0.72*np.cos(needle), 0.72*np.sin(needle)), xytext=(0, 0),
                    arrowprops=dict(arrowstyle="-|>", color=THEME["text_primary"],
                                    lw=2, mutation_scale=14), zorder=5)
        ax.add_patch(plt.Circle((0,0), 0.06, color=THEME["bg2"], zorder=6))
        ax.add_patch(plt.Circle((0,0), 0.04, color=THEME["accent"], zorder=7))
        ax.text(0, -0.28, f"{value:.0f}", ha="center", va="center",
                fontsize=22, fontweight="bold", color=THEME["text_primary"], zorder=8)
        ax.text(0, -0.48, "RPM", ha="center", va="center",
                fontsize=9, color=THEME["text_muted"], zorder=8)
        ax.text(-1.1, 0.05, f"{mn:.0f}", ha="center", fontsize=8, color=THEME["text_muted"])
        ax.text(1.1,  0.05, f"{mx:.0f}", ha="center", fontsize=8, color=THEME["text_muted"])
        ax.set_title(self._title, color=THEME["text_muted"], fontsize=9, pad=4)
        ax.set_xlim(-1.3, 1.3); ax.set_ylim(-0.65, 1.15)
        ax.set_aspect("equal"); ax.axis("off")
        self._fig.tight_layout(pad=0.2)
        self._canvas.draw_idle()


# ===========================================================================
#  PLOT WIDGET
# ===========================================================================
class PlotWidget(tk.Frame):
    def __init__(self, parent, title="Dato vs Tiempo",
                 ymin=0, ymax=2000, color=None, size=(6, 2.2), **kwargs):
        super().__init__(parent, bg=THEME["bg"], **kwargs)
        self._title = title
        self._ymin, self._ymax = ymin, ymax
        self._color = color or THEME["mpl_line"]
        self._data: deque = deque(maxlen=3600)
        self._fig, self._ax = plt.subplots(figsize=size)
        self._fig.patch.set_facecolor(THEME["mpl_bg"])
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().configure(bg=THEME["mpl_bg"], highlightthickness=0)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._redraw()
        ThemeManager.register(self._on_theme)

    def _on_theme(self):
        self.configure(bg=THEME["bg"])
        self._fig.patch.set_facecolor(THEME["mpl_bg"])
        self._canvas.get_tk_widget().configure(bg=THEME["mpl_bg"])
        self._redraw()

    def push(self, ts: datetime, value: float):
        self._data.append((ts, value))
        self._redraw()

    def push_gap(self):
        self._data.append((datetime.now(), float("nan")))

    def set_range(self, ymin, ymax):
        self._ymin, self._ymax = ymin, ymax
        self._redraw()

    def auto_range(self):
        vals = [v for _, v in self._data if not math.isnan(v)]
        if not vals:
            return
        mn, mx = min(vals), max(vals)
        pad = (mx - mn) * 0.1 if mx > mn else 1
        self.set_range(mn - pad, mx + pad)

    def _redraw(self):
        ax = self._ax
        ax.clear()
        ax.set_facecolor(THEME["mpl_bg"])
        ax.tick_params(colors=THEME["text_muted"], labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(THEME["border"])
        ax.grid(True, color=THEME["mpl_grid"], linewidth=0.5, linestyle="--")
        ax.set_title(self._title, color=THEME["text_muted"], fontsize=9, pad=4)
        ax.set_ylim(self._ymin, self._ymax)
        if self._data:
            times = [t for t, _ in self._data]
            vals  = [v for _, v in self._data]
            ax.plot(times, vals, color=self._color, linewidth=1.5, zorder=3)
            ax.fill_between(times, self._ymin, vals,
                            color=self._color, alpha=0.08, zorder=2)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
            self._fig.autofmt_xdate(rotation=0, ha="center")
        self._fig.tight_layout(pad=0.5)
        self._canvas.draw_idle()


# ===========================================================================
#  STATUS LED
# ===========================================================================
class StatusLed(tk.Frame):
    def __init__(self, parent, label="Estado", bg=None, **kwargs):
        _bg = bg or THEME["bg2"]
        super().__init__(parent, bg=_bg, **kwargs)
        self._bg = _bg
        self._cvs = tk.Canvas(self, width=14, height=14,
                               bg=_bg, highlightthickness=0)
        self._cvs.pack(side=tk.LEFT, padx=(6, 3))
        self._dot = self._cvs.create_oval(2, 2, 12, 12,
                                           fill=THEME["text_dim"], outline="")
        self._lbl = tk.Label(self, text=label, bg=_bg,
                              fg=THEME["text_muted"], font=("Segoe UI", 9))
        self._lbl.pack(side=tk.LEFT, padx=(0, 6))

    def set_ok(self, text=""):
        self._cvs.itemconfig(self._dot, fill=THEME["green"])
        self._lbl.config(text=text, fg=THEME["green"])

    def set_error(self, text=""):
        self._cvs.itemconfig(self._dot, fill=THEME["red"])
        self._lbl.config(text=text, fg=THEME["red"])

    def set_warning(self, text=""):
        self._cvs.itemconfig(self._dot, fill=THEME["amber"])
        self._lbl.config(text=text, fg=THEME["amber"])

    def set_idle(self, text=""):
        self._cvs.itemconfig(self._dot, fill=THEME["text_dim"])
        self._lbl.config(text=text, fg=THEME["text_muted"])


# ===========================================================================
#  VALUE CARD
# ===========================================================================
class ValueCard(tk.Frame):
    def __init__(self, parent, label="Valor", unit="", color=None, **kwargs):
        c = color or THEME["accent"]
        super().__init__(parent, bg=THEME["bg2"],
                         highlightbackground=c, highlightthickness=1, **kwargs)
        self._color = c
        tk.Label(self, text=label.upper(), bg=THEME["bg2"],
                 fg=THEME["text_muted"], font=("Segoe UI", 8, "bold")).pack(pady=(8, 0))
        self._var = tk.StringVar(value="---")
        tk.Label(self, textvariable=self._var, bg=THEME["bg2"],
                 fg=c, font=("Segoe UI", 24, "bold")).pack()
        tk.Label(self, text=unit, bg=THEME["bg2"],
                 fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(pady=(0, 6))

    def set_value(self, value):
        if value is None:
            self._var.set("---")
        elif isinstance(value, bool):
            self._var.set("OK" if value else "FALLA")
        elif isinstance(value, float):
            self._var.set(f"{value:.1f}")
        else:
            self._var.set(str(value))

    def set_color(self, color: str):
        self._color = color
        self.configure(highlightbackground=color)


# ===========================================================================
#  ALARM BANNER
# ===========================================================================
class AlarmBanner(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=THEME["red"], **kwargs)
        self._msg = tk.Label(self, text="", bg=THEME["red"], fg="#fff",
                              font=("Segoe UI", 10, "bold"), pady=5)
        self._msg.pack(side=tk.LEFT, padx=16, expand=True)
        self._btn = tk.Button(self, text="✔ RECONOCER",
                               bg="#7f1d1d", fg="#fca5a5",
                               font=("Segoe UI", 8, "bold"),
                               relief=tk.FLAT, cursor="hand2", padx=8)
        self._btn.pack(side=tk.RIGHT, padx=8, pady=3)
        self._visible = False

    def show(self, message: str, on_ack=None):
        self._msg.config(text=f"⚠  {message}")
        if on_ack:
            self._btn.config(command=on_ack)
        if not self._visible:
            self.pack(fill=tk.X, side=tk.TOP)
            self._visible = True

    def hide(self):
        if self._visible:
            self.pack_forget()
            self._visible = False


# ===========================================================================
#  PANEL BASE
# ===========================================================================
class MaquinaPanel(tk.Frame):
    """
    Panel base para una máquina.

    Subclases sobreescriben:
        _build_control_bar(parent)   — barra de conexión (serial vs UDP)
        _build_main_sensors(parent)  — widgets de sensores específicos
        _on_data(data_dict)          — actualización de sensores
    """

    def __init__(self, parent, core: "MaquinaCore", **kwargs):
        super().__init__(parent, bg=THEME["bg"], **kwargs)
        self._core = core
        self._port_var   = tk.StringVar()
        self._baud_var   = tk.StringVar(value="9600")
        self._ensayo_var = tk.StringVar()
        self._prueba_var = tk.StringVar()
        self._comment_var = tk.StringVar()
        self._ensayos: dict = {}
        self._analisis_colors = cycle([
            "#6366f1", "#f87171", "#34d399", "#fbbf24",
            "#a78bfa", "#38bdf8", "#fb923c",
        ])
        self._load_ensayos()
        self._alarm_banner = AlarmBanner(self)
        self._build_ui()

        # Enganchar callbacks del core
        self._core.on_data(lambda d: self.after(0, self._on_data, d))
        self._core.on_alarm(lambda k, n, v, t: self.after(0, self._on_alarm, k, n, v, t))
        self._core.on_alarm_resolved(
            lambda k, n, v, t: self.after(0, self._on_alarm_resolved))
        self._core.on_connection_lost(lambda: self.after(0, self._on_conn_lost))
        self._core.on_connection_restored(lambda: self.after(0, self._on_conn_restored))
        self._core.on_recording_stopped(
            lambda auto: self.after(0, self._on_recording_stopped, auto))

        ThemeManager.register(self._apply_theme_bg)

    # -------------------------------------------------------------------
    # Construcción de la UI
    # -------------------------------------------------------------------
    def _build_ui(self):
        self._alarm_banner.pack_forget()
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        for label, builder in [
            ("  Principal  ",     self._build_main_tab),
            ("  Ensayos  ",       self._build_ensayo_tab),
            ("  Historial  ",     self._build_hist_tab),
            ("  Análisis  ",      self._build_analisis_tab),
            ("  Web Server  ",    self._build_web_tab),
            ("  Configuración  ", self._build_config_tab),
        ]:
            frame = ttk.Frame(self._nb)
            self._nb.add(frame, text=label)
            builder(frame)
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

    # -------------------------------------------------------------------
    # Pestaña: Principal
    # -------------------------------------------------------------------
    def _build_main_tab(self, tab):
        ctrl_outer = tk.Frame(tab, bg=THEME["bg2"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        ctrl_outer.pack(fill=tk.X, padx=6, pady=6)
        self._build_control_bar(ctrl_outer)

        pane = ttk.PanedWindow(tab, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # --- Fila superior: PanedWindow horizontal (gráfico | gauge) ---
        pane_top = ttk.PanedWindow(pane, orient=tk.HORIZONTAL)
        pane.add(pane_top, weight=3)

        graph_cont = tk.Frame(pane_top, bg=THEME["bg3"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        pane_top.add(graph_cont, weight=4)

        gctr = tk.Frame(graph_cont, bg=THEME["bg3"])
        gctr.pack(fill=tk.X, padx=6, pady=3)
        ttk.Button(gctr, text="Auto Y",
                   command=lambda: self._plot.auto_range()).pack(side=tk.LEFT)

        self._plot = PlotWidget(
            graph_cont,
            title=self._core.get_config("plot_title", "RPM vs Tiempo"),
            ymin=self._core.get_config("plot_ymin", 0),
            ymax=self._core.get_config("plot_ymax", 2000),
        )
        self._plot.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        gauge_cont = tk.Frame(pane_top, bg=THEME["bg3"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        pane_top.add(gauge_cont, weight=1)
        self._gauge = GaugeWidget(
            gauge_cont,
            min_val=self._core.get_config("gauge_min", 0),
            max_val=self._core.get_config("gauge_max", 2000),
            title=self._core.get_config("gauge_title", "Velocímetro"),
        )
        self._gauge.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # --- Fila inferior: PanedWindow horizontal (sensores | ensayo activo) ---
        pane_bot = ttk.PanedWindow(pane, orient=tk.HORIZONTAL)
        pane.add(pane_bot, weight=2)

        self._sensors_frame = tk.Frame(pane_bot, bg=THEME["bg"])
        pane_bot.add(self._sensors_frame, weight=3)
        self._build_main_sensors(self._sensors_frame)

        # Tabla de ensayo activo
        ens_cont = tk.Frame(pane_bot, bg=THEME["bg3"],
                             highlightbackground=THEME["border"],
                             highlightthickness=1)
        pane_bot.add(ens_cont, weight=2)

        tk.Label(ens_cont, text="ENSAYO ACTIVO", bg=THEME["bg3"],
                 fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(8, 2))

        self._ensayo_disp_lbl = tk.Label(
            ens_cont, text="—", bg=THEME["bg3"], fg=THEME["accent"],
            font=("Segoe UI", 10, "bold"), wraplength=220)
        self._ensayo_disp_lbl.pack(padx=8, pady=(0, 4))

        tf = tk.Frame(ens_cont, bg=THEME["bg3"])
        tf.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self._ensayo_disp_tree = ttk.Treeview(tf, columns=("a", "v"),
                                               show="headings", height=6)
        self._ensayo_disp_tree.heading("a", text="Atributo")
        self._ensayo_disp_tree.heading("v", text="Valor")
        self._ensayo_disp_tree.column("a", width=90, anchor=tk.W)
        self._ensayo_disp_tree.column("v", width=120, anchor=tk.W)
        vsb = ttk.Scrollbar(tf, orient=tk.VERTICAL,
                             command=self._ensayo_disp_tree.yview)
        self._ensayo_disp_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._ensayo_disp_tree.pack(fill=tk.BOTH, expand=True)

    def _build_control_bar(self, parent):
        """Barra de conexión serie. PanelMultiTemp sobreescribe esto."""
        inner = tk.Frame(parent, bg=THEME["bg2"])
        inner.pack(fill=tk.X, padx=8, pady=6)

        tk.Label(inner, text="Puerto:", bg=THEME["bg2"],
                 fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._port_combo = ttk.Combobox(inner, textvariable=self._port_var,
                                         width=9, state="readonly")
        self._port_combo.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(inner, text="↻", width=2,
                   command=self._refresh_ports).pack(side=tk.LEFT, padx=2)
        self._btn_connect = ttk.Button(inner, text="Conectar",
                                        command=self._connect)
        self._btn_connect.pack(side=tk.LEFT, padx=(2, 10))

        ttk.Separator(inner, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, pady=2, padx=4)
        self._build_recording_buttons(inner)

    def _build_recording_buttons(self, parent):
        self._btn_start = ttk.Button(parent, text="▶  Iniciar",
                                      style="Accent.TButton",
                                      command=self._start_recording,
                                      state=tk.DISABLED)
        self._btn_start.pack(side=tk.LEFT, padx=4)
        self._btn_pause = ttk.Button(parent, text="⏸  Pausar",
                                      command=self._pause_recording,
                                      state=tk.DISABLED)
        self._btn_pause.pack(side=tk.LEFT, padx=2)
        self._btn_resume = ttk.Button(parent, text="▶  Reanudar",
                                       command=self._resume_recording,
                                       state=tk.DISABLED)
        self._btn_resume.pack(side=tk.LEFT, padx=2)
        self._btn_stop = ttk.Button(parent, text="⏹  Finalizar",
                                     command=self._stop_recording,
                                     state=tk.DISABLED)
        self._btn_stop.pack(side=tk.LEFT, padx=(2, 10))

        ttk.Separator(parent, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, pady=2, padx=4)
        tk.Label(parent, text="Comentario:", bg=THEME["bg2"],
                 fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Entry(parent, textvariable=self._comment_var,
                  width=18).pack(side=tk.LEFT, padx=2)
        self._led_conn = StatusLed(parent, label="Desconectado",
                                    bg=THEME["bg2"])
        self._led_conn.pack(side=tk.RIGHT, padx=8)

    def _build_main_sensors(self, parent):
        tk.Label(parent, text="[ Sin sensores ]",
                 bg=THEME["bg"], fg=THEME["text_muted"]).pack(expand=True)

    # -------------------------------------------------------------------
    # Pestaña: Ensayos
    # -------------------------------------------------------------------
    def _build_ensayo_tab(self, tab):
        pad = {"padx": 8, "pady": 5}
        top = ttk.LabelFrame(tab, text="Gestión de Ensayos")
        top.pack(fill=tk.X, padx=10, pady=10)

        r0 = ttk.Frame(top); r0.pack(fill=tk.X, **pad)
        ttk.Label(r0, text="Ensayo:").pack(side=tk.LEFT)
        self._ensayo_combo = ttk.Combobox(r0, textvariable=self._ensayo_var,
                                           state="readonly", width=26)
        self._ensayo_combo.pack(side=tk.LEFT, padx=6)
        self._ensayo_combo.bind("<<ComboboxSelected>>", self._on_ensayo_selected)
        ttk.Button(r0, text="Cargar como activo",
                   command=self._load_ensayo).pack(side=tk.LEFT, padx=4)
        ttk.Button(r0, text="Eliminar",
                   command=self._delete_ensayo).pack(side=tk.LEFT)

        r1 = ttk.Frame(top); r1.pack(fill=tk.X, **pad)
        ttk.Label(r1, text="Nombre prueba:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._prueba_var, width=26).pack(side=tk.LEFT, padx=6)
        ttk.Button(r1, text="Guardar ensayo",
                   command=self._save_ensayo).pack(side=tk.LEFT, padx=4)

        attr = ttk.LabelFrame(tab, text="Atributos del Ensayo")
        attr.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        add_row = ttk.Frame(attr); add_row.pack(fill=tk.X, **pad)
        self._attr_key = tk.StringVar()
        self._attr_val = tk.StringVar()

        # Atributos predefinidos para ayuda al operador
        self._predefined_attrs = [
            "Prototipo", "Rotor", "Aguja", "Carcasa", "Driver",
            "Tensión (V)", "Nivel de vacío", "Material", "Operador",
            "Temperatura ambiente", "Humedad relativa", "Observaciones",
            "Otro...",
        ]
        self._attr_combo = ttk.Combobox(
            add_row, textvariable=self._attr_key,
            values=self._predefined_attrs, width=20)
        self._attr_combo.pack(side=tk.LEFT)
        self._attr_combo.bind("<<ComboboxSelected>>", self._on_attr_selected)

        tk.Label(add_row, text="=", bg=THEME["bg"],
                 fg=THEME["text_muted"]).pack(side=tk.LEFT, padx=4)
        ttk.Entry(add_row, textvariable=self._attr_val, width=30).pack(side=tk.LEFT)
        ttk.Button(add_row, text="Agregar",
                   command=self._add_attr).pack(side=tk.LEFT, padx=6)
        ttk.Button(add_row, text="Limpiar",
                   command=self._clear_attrs).pack(side=tk.LEFT)

        self._attr_tree = ttk.Treeview(attr, columns=("a", "v"),
                                        show="headings", height=8)
        self._attr_tree.heading("a", text="Atributo")
        self._attr_tree.heading("v", text="Valor")
        self._attr_tree.column("a", width=180)
        self._attr_tree.column("v", width=380)
        vsb = ttk.Scrollbar(attr, orient=tk.VERTICAL,
                             command=self._attr_tree.yview)
        self._attr_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 6))
        self._attr_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self._attr_tree.bind("<Delete>", lambda e: self._del_attr())
        self._update_ensayos_combo()

    # -------------------------------------------------------------------
    # Pestaña: Historial
    # -------------------------------------------------------------------
    def _build_hist_tab(self, tab):
        ctrl = ttk.Frame(tab)
        ctrl.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(ctrl, text="Día:").pack(side=tk.LEFT)
        self._hist_day = ttk.Combobox(ctrl, state="readonly", width=13)
        self._hist_day.pack(side=tk.LEFT, padx=6)
        self._hist_day.bind("<<ComboboxSelected>>", lambda e: self._load_hist())
        ttk.Button(ctrl, text="↻ Refrescar",
                   command=self._refresh_hist_days).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Exportar a Excel…",
                   style="Accent.TButton",
                   command=self._export_dialog).pack(side=tk.RIGHT)
        ttk.Button(ctrl, text="Ver alarmas",
                   command=self._show_alarms_window).pack(side=tk.RIGHT, padx=4)

        col_labels = ["Hora", "Ensayo", "Prueba", "Comentario"] + \
                     [vd.label for vd in self._core.parser.display_config]
        ft = ttk.Frame(tab)
        ft.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        self._hist_tree = ttk.Treeview(ft, columns=col_labels,
                                        show="headings", height=18)
        for col in col_labels:
            self._hist_tree.heading(col, text=col)
            w = 70 if col == "Hora" else 160 if col == "Comentario" else 110
            self._hist_tree.column(col, width=w, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(ft, orient=tk.VERTICAL, command=self._hist_tree.yview)
        hsb = ttk.Scrollbar(ft, orient=tk.HORIZONTAL, command=self._hist_tree.xview)
        self._hist_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._hist_tree.pack(fill=tk.BOTH, expand=True)
        self._refresh_hist_days()

    # -------------------------------------------------------------------
    # Pestaña: Análisis
    # -------------------------------------------------------------------
    def _build_analisis_tab(self, tab):
        pane = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        ctrl = ttk.Frame(pane, width=300)
        pane.add(ctrl, weight=1)

        lf = ttk.LabelFrame(ctrl, text="Selección")
        lf.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(lf, text="Día:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self._an_day = ttk.Combobox(lf, state="readonly", width=13)
        self._an_day.grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(lf, text="Variable:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        numeric_vars = [vd.key for vd in self._core.parser.display_config
                        if not vd.is_boolean]
        self._an_var = ttk.Combobox(lf, state="readonly", width=13,
                                     values=numeric_vars)
        self._an_var.grid(row=1, column=1, sticky="w", padx=6)
        if numeric_vars:
            self._an_var.current(0)

        ttk.Button(lf, text="Analizar y graficar",
                   style="Accent.TButton",
                   command=self._do_analisis).grid(
            row=2, column=0, columnspan=2, pady=8, padx=6, sticky="ew")
        ttk.Button(lf, text="Limpiar",
                   command=self._clear_analisis).grid(
            row=3, column=0, columnspan=2, padx=6, sticky="ew")

        lf2 = ttk.LabelFrame(ctrl, text="Resultados estadísticos")
        lf2.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._an_tree = ttk.Treeview(
            lf2, columns=("desc", "max", "min", "prom", "std"),
            show="headings", height=10)
        for col, lbl, w in [("desc", "Descripción", 150), ("max", "Máx", 70),
                             ("min", "Mín", 70), ("prom", "Prom", 70), ("std", "D.E.", 70)]:
            self._an_tree.heading(col, text=lbl)
            self._an_tree.column(col, width=w, anchor=tk.CENTER)
        self._an_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        plot_f = ttk.Frame(pane)
        pane.add(plot_f, weight=3)
        self._an_fig, self._an_ax = plt.subplots()
        self._an_fig.patch.set_facecolor(THEME["mpl_bg"])
        self._an_ax.set_facecolor(THEME["mpl_bg"])
        self._an_canvas = FigureCanvasTkAgg(self._an_fig, master=plot_f)
        self._an_canvas.get_tk_widget().configure(
            bg=THEME["mpl_bg"], highlightthickness=0)
        self._an_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ThemeManager.register(self._refresh_an_theme)

    def _refresh_an_theme(self):
        self._an_fig.patch.set_facecolor(THEME["mpl_bg"])
        self._an_ax.set_facecolor(THEME["mpl_bg"])
        self._an_canvas.get_tk_widget().configure(bg=THEME["mpl_bg"])
        self._an_canvas.draw_idle()

    def _on_tab_change(self, event):
        try:
            tab_text = self._nb.tab(self._nb.select(), "text").strip()
            if tab_text == "Análisis":
                days = self._core.db.get_days()
                if days:
                    self._an_day["values"] = days
                    self._an_day.set(days[-1])
        except Exception:
            pass

    # -------------------------------------------------------------------
    # Pestaña: Web Server
    # -------------------------------------------------------------------
    def _build_web_tab(self, tab):
        left = ttk.Frame(tab)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                  padx=(10, 4), pady=10)

        ttk.Label(left, text="Usuarios del Web Server",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        self._users_tree = ttk.Treeview(
            left, columns=("user", "email", "alerts"),
            show="headings", height=8)
        for col, lbl, w in [("user", "Usuario", 100),
                              ("email", "Email", 180),
                              ("alerts", "Alertas", 60)]:
            self._users_tree.heading(col, text=lbl)
            self._users_tree.column(col, width=w, anchor=tk.CENTER)
        self._users_tree.pack(fill=tk.BOTH, expand=True)
        self._users_tree.bind("<Button-3>", self._user_ctx_menu)
        self._update_users_list()

        right = ttk.Frame(tab)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 10), pady=10)

        lf_new = ttk.LabelFrame(right, text="Crear usuario")
        lf_new.pack(fill=tk.X, pady=(0, 8))
        self._new_user_var = tk.StringVar()
        self._new_pass_var = tk.StringVar()
        for lbl, var, show in [("Usuario:", self._new_user_var, ""),
                                 ("Contraseña:", self._new_pass_var, "*")]:
            ttk.Label(lf_new, text=lbl).pack(anchor="w", padx=6, pady=(4, 0))
            ttk.Entry(lf_new, textvariable=var, show=show,
                      width=22).pack(padx=6, pady=2)
        ttk.Button(lf_new, text="Crear usuario", style="Accent.TButton",
                   command=self._create_user).pack(fill=tk.X, padx=6, pady=8)

        # Variables visibles en el dashboard
        lf_vars = ttk.LabelFrame(right, text="Variables del Dashboard Web")
        lf_vars.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(lf_vars, text="Seleccioná qué mostrar:",
                  font=("Segoe UI", 8)).pack(anchor="w", padx=6, pady=(4, 2))

        saved_visible = self._core.get_config("web_visible_vars", None)
        self._web_var_checks: dict[str, tk.BooleanVar] = {}
        for vd in self._core.parser.display_config:
            # RPM siempre visible, no se puede desactivar
            default = True if saved_visible is None else (vd.key in saved_visible)
            var = tk.BooleanVar(value=default)
            self._web_var_checks[vd.key] = var
            row = ttk.Frame(lf_vars)
            row.pack(fill=tk.X, padx=6, pady=1)
            chk = ttk.Checkbutton(row, text=f"{vd.label}  ({vd.unit})" if vd.unit else vd.label,
                                   variable=var)
            if vd.key == "rpm":
                var.set(True)
                chk.config(state=tk.DISABLED)
            chk.pack(side=tk.LEFT)

        ttk.Button(lf_vars, text="Guardar selección",
                   command=self._save_web_vars).pack(fill=tk.X, padx=6, pady=6)

        lf_br = ttk.LabelFrame(right, text="Email de alarmas (Brevo)")
        lf_br.pack(fill=tk.X)
        self._brevo_key_var   = tk.StringVar(
            value=self._core.get_config("brevo_api_key", ""))
        self._brevo_email_var = tk.StringVar(
            value=self._core.get_config("brevo_email", ""))
        for lbl, var, show in [("API Key:", self._brevo_key_var, "*"),
                                 ("Email remitente:", self._brevo_email_var, "")]:
            ttk.Label(lf_br, text=lbl).pack(anchor="w", padx=6, pady=(4, 0))
            ttk.Entry(lf_br, textvariable=var, show=show,
                      width=28).pack(padx=6, pady=2)
        ttk.Button(lf_br, text="Guardar config Brevo",
                   command=self._save_brevo).pack(fill=tk.X, padx=6, pady=8)

    # -------------------------------------------------------------------
    # Pestaña: Configuración
    # -------------------------------------------------------------------
    def _build_config_tab(self, tab):
        canvas = tk.Canvas(tab, bg=THEME["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        pad = {"padx": 10, "pady": 5}
        self._cfg_vars: dict[str, tk.StringVar] = {}

        # Visualización
        lf_v = ttk.LabelFrame(inner, text="Visualización")
        lf_v.grid(row=0, column=0, sticky="ew", **pad)
        for i, (lbl, key) in enumerate([
            ("Título gráfico", "plot_title"), ("Título velocímetro", "gauge_title"),
            ("Y Mínimo", "plot_ymin"),       ("Y Máximo", "plot_ymax"),
            ("Gauge Mínimo", "gauge_min"),   ("Gauge Máximo", "gauge_max"),
        ]):
            ttk.Label(lf_v, text=lbl+":").grid(row=i, column=0, sticky="w",
                                                padx=8, pady=3)
            v = tk.StringVar(value=str(self._core.get_config(key, "")))
            self._cfg_vars[key] = v
            ttk.Entry(lf_v, textvariable=v, width=22).grid(
                row=i, column=1, sticky="w", padx=8)

        # Apariencia
        lf_ap = ttk.LabelFrame(inner, text="Apariencia")
        lf_ap.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(lf_ap, text="🌙  Cambiar tema (Claro / Oscuro)",
                   command=self._toggle_theme).pack(padx=8, pady=8, anchor="w")
        self._theme_lbl = tk.Label(
            lf_ap, bg=THEME["bg"],
            text=f"Tema actual: {'Oscuro' if THEME['name'] == 'dark' else 'Claro'}",
            fg=THEME["text_muted"], font=("Segoe UI", 9))
        self._theme_lbl.pack(padx=8, pady=(0, 8), anchor="w")

        # Watchdog
        lf_wd = ttk.LabelFrame(inner, text="Watchdog y Auto-finalización")
        lf_wd.grid(row=2, column=0, sticky="ew", **pad)
        for i, (lbl, key) in enumerate([
            ("Watchdog (seg sin datos)", "watchdog_sec"),
            ("Auto-finalizar si RPM=0 (min)", "autofin_min"),
        ]):
            ttk.Label(lf_wd, text=lbl+":").grid(row=i, column=0, sticky="w",
                                                  padx=8, pady=3)
            v = tk.StringVar(value=str(self._core.get_config(key, "")))
            self._cfg_vars[key] = v
            ttk.Entry(lf_wd, textvariable=v, width=10).grid(
                row=i, column=1, sticky="w", padx=8)

        # Alarmas
        lf_al = ttk.LabelFrame(inner, text="Alarmas")
        lf_al.grid(row=3, column=0, sticky="ew", **pad)
        self._alarm_enabled_vars: dict[str, tk.BooleanVar] = {}
        self._alarm_threshold_vars: dict[str, tk.StringVar] = {}
        for i, (key, alarm) in enumerate(self._core.alarms.items()):
            en = tk.BooleanVar(value=alarm.enabled)
            th = tk.StringVar(value=str(alarm.threshold))
            self._alarm_enabled_vars[key]   = en
            self._alarm_threshold_vars[key] = th
            ttk.Checkbutton(lf_al, text=alarm.name,
                             variable=en).grid(row=i, column=0,
                                               sticky="w", padx=8, pady=3)
            ttk.Entry(lf_al, textvariable=th, width=10).grid(
                row=i, column=1, sticky="w", padx=4)
            unit = next((vd.unit for vd in self._core.parser.display_config
                         if vd.key in key), "")
            ttk.Label(lf_al, text=unit).grid(row=i, column=2, sticky="w")

        # BD
        lf_db = ttk.LabelFrame(inner, text="Base de Datos")
        lf_db.grid(row=4, column=0, sticky="ew", **pad)
        self._db_var = tk.StringVar(value=self._core.db.db_path)
        ttk.Label(lf_db, textvariable=self._db_var,
                  font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w",
                                              padx=8, pady=4)
        ttk.Button(lf_db, text="Cambiar BD…",
                   command=self._change_db).grid(row=0, column=1, padx=8)

        ttk.Button(inner, text="💾  Guardar configuración",
                   style="Accent.TButton",
                   command=self._save_config).grid(row=5, column=0,
                                                    sticky="w", **pad)
        inner.columnconfigure(0, weight=1)

    # -------------------------------------------------------------------
    # Acciones de conexión
    # -------------------------------------------------------------------
    def _refresh_ports(self):
        from core.channels import SerialChannel
        ports = SerialChannel.list_ports()
        self._port_combo["values"] = ports
        if ports:
            self._port_combo.current(0)

    def _connect(self):
        port = self._port_var.get()
        if not port:
            messagebox.showwarning("Puerto", "Seleccioná un puerto.", parent=self)
            return
        if self._core.connect(port, baudrate=int(self._baud_var.get())):
            self._led_conn.set_ok(f"Conectado: {port}")
            self._btn_start.config(state=tk.NORMAL)
        else:
            self._led_conn.set_error("Error de conexión")
            messagebox.showerror("Error", f"No se pudo abrir {port}.", parent=self)

    # -------------------------------------------------------------------
    # Acciones de grabación
    # -------------------------------------------------------------------
    def _start_recording(self):
        ensayo = self._ensayo_var.get() or "Sin Ensayo"
        prueba = self._prueba_var.get() or f"Prueba {datetime.now().strftime('%H:%M')}"
        if self._core.start_recording(ensayo=ensayo, prueba=prueba):
            self._led_conn.set_ok("Grabando...")
            self._btn_start.config(state=tk.DISABLED)
            self._btn_pause.config(state=tk.NORMAL)
            self._btn_stop.config(state=tk.NORMAL)
            self._ensayo_disp_lbl.config(text=f"{ensayo}  |  {prueba}")

    def _pause_recording(self):
        self._core.pause_recording()
        self._plot.push_gap()
        self._btn_pause.config(state=tk.DISABLED)
        self._btn_resume.config(state=tk.NORMAL)
        self._led_conn.set_warning("En pausa")

    def _resume_recording(self):
        self._core.resume_recording()
        self._btn_pause.config(state=tk.NORMAL)
        self._btn_resume.config(state=tk.DISABLED)
        self._led_conn.set_ok("Grabando...")

    def _stop_recording(self):
        self._core.stop_recording()

    # -------------------------------------------------------------------
    # Callbacks del core
    # -------------------------------------------------------------------
    def _on_data(self, data: dict):
        self._gauge.set_value(data.get("rpm", 0))
        self._plot.push(datetime.now(), data.get("rpm", 0))

    def _on_alarm(self, key, name, value, threshold):
        self._alarm_banner.show(
            f"{name}  —  Valor: {value}  |  Umbral: {threshold}",
            on_ack=self._ack_alarm)

    def _on_alarm_resolved(self):
        if not self._core.any_alarm_active:
            self._alarm_banner.hide()

    def _on_conn_lost(self):
        self._led_conn.set_error("Sin señal")

    def _on_conn_restored(self):
        self._led_conn.set_ok("Grabando...")

    def _on_recording_stopped(self, auto: bool):
        self._btn_start.config(state=tk.NORMAL)
        self._btn_pause.config(state=tk.DISABLED)
        self._btn_resume.config(state=tk.DISABLED)
        self._btn_stop.config(state=tk.DISABLED)
        self._led_conn.set_idle("Detenido")
        if auto:
            messagebox.showinfo("Auto-finalización",
                                "Ensayo finalizado (RPM = 0).", parent=self)

    def _ack_alarm(self):
        nombre = simpledialog.askstring(
            "Reconocer Alarma", "Ingresá tu nombre:", parent=self)
        if nombre:
            self._core.acknowledge_all_alarms()
            s = self._core.current_session
            self._core.db.log_alarma(
                "ALARMA RECONOCIDA", f"Atendida por: {nombre}",
                operador=nombre,
                ensayo=s.ensayo if s else "",
                prueba=s.prueba if s else "")
            self._alarm_banner.hide()

    # -------------------------------------------------------------------
    # Ensayos
    # -------------------------------------------------------------------
    def _load_ensayos(self):
        if os.path.exists(ENSAYOS_FILE):
            try:
                with open(ENSAYOS_FILE, "r", encoding="utf-8") as f:
                    self._ensayos = json.load(f)
            except Exception:
                self._ensayos = {}

    def _save_ensayos_file(self):
        with open(ENSAYOS_FILE, "w", encoding="utf-8") as f:
            json.dump(self._ensayos, f, indent=2, ensure_ascii=False)

    def _update_ensayos_combo(self):
        if hasattr(self, "_ensayo_combo"):
            self._ensayo_combo["values"] = list(self._ensayos.keys())

    def _on_ensayo_selected(self, _=None):
        nombre = self._ensayo_var.get()
        self._attr_tree.delete(*self._attr_tree.get_children())
        for item in self._ensayos.get(nombre, []):
            self._attr_tree.insert("", tk.END,
                                   values=(item["atributo"], item["valor"]))

    def _load_ensayo(self):
        nombre = self._ensayo_var.get()
        if not nombre:
            messagebox.showwarning("Sin selección",
                                   "Seleccioná un ensayo.", parent=self)
            return
        self._ensayo_disp_lbl.config(text=nombre)
        self._ensayo_disp_tree.delete(*self._ensayo_disp_tree.get_children())
        for item in self._ensayos.get(nombre, []):
            self._ensayo_disp_tree.insert("", tk.END,
                                          values=(item["atributo"], item["valor"]))
        messagebox.showinfo("Ensayo cargado",
                            f"'{nombre}' activo.", parent=self)

    def _save_ensayo(self):
        nombre = self._prueba_var.get().strip()
        if not nombre:
            messagebox.showwarning("Nombre vacío",
                                   "Ingresá un nombre.", parent=self)
            return
        items = [{"atributo": self._attr_tree.item(c)["values"][0],
                  "valor":    self._attr_tree.item(c)["values"][1]}
                 for c in self._attr_tree.get_children()]
        self._ensayos[nombre] = items
        self._save_ensayos_file()
        self._update_ensayos_combo()
        messagebox.showinfo("Guardado",
                            f"Ensayo '{nombre}' guardado.", parent=self)

    def _delete_ensayo(self):
        nombre = self._ensayo_var.get()
        if nombre and messagebox.askyesno(
                "Eliminar", f"¿Eliminar '{nombre}'?", parent=self):
            self._ensayos.pop(nombre, None)
            self._save_ensayos_file()
            self._update_ensayos_combo()
            self._ensayo_var.set("")

    def _on_attr_selected(self, _=None):
        """Cuando se elige 'Otro...' del combo, limpiar para que el operador escriba."""
        if self._attr_key.get() == "Otro...":
            self._attr_key.set("")
            self._attr_combo.focus_set()

    def _add_attr(self):
        k, v = self._attr_key.get().strip(), self._attr_val.get().strip()
        if k and v:
            self._attr_tree.insert("", tk.END, values=(k, v))
            self._attr_key.set(""); self._attr_val.set("")

    def _del_attr(self):
        for item in self._attr_tree.selection():
            self._attr_tree.delete(item)

    def _clear_attrs(self):
        if messagebox.askyesno("Limpiar",
                                "¿Limpiar todos los atributos?", parent=self):
            self._attr_tree.delete(*self._attr_tree.get_children())

    # -------------------------------------------------------------------
    # Historial
    # -------------------------------------------------------------------
    def _refresh_hist_days(self):
        days = self._core.db.get_days()
        self._hist_day["values"] = days
        if days:
            self._hist_day.set(days[-1])
            self._load_hist()

    def _load_hist(self):
        day = self._hist_day.get()
        if not day:
            return
        self._hist_tree.delete(*self._hist_tree.get_children())
        col_names = self._core.db.column_names
        rows = list(self._core.db.get_mediciones_del_dia(day))
        for fila in reversed(rows):   # más recientes primero
            row = [
                fila["timestamp"].strftime("%H:%M:%S"),
                fila.get("ensayo", ""),
                fila.get("prueba", ""),
                fila.get("comentario", ""),
            ] + [
                (f"{fila[c]:.1f}" if isinstance(fila.get(c), float)
                 else str(fila.get(c, "")))
                for c in col_names
            ]
            self._hist_tree.insert("", tk.END, values=row)

    def _show_alarms_window(self):
        win = tk.Toplevel(self)
        win.title("Registro de Alarmas")
        win.geometry("900x420")
        win.configure(bg=THEME["bg"])
        cols = ["Timestamp", "Evento", "Detalle",
                "Operador", "Ensayo", "Prueba"]
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, width=130, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for a in self._core.db.get_alarmas():
            tree.insert("", tk.END, values=(
                a["timestamp"], a["evento"], a["detalle"],
                a["operador"], a["ensayo"], a["prueba"]))

    # -------------------------------------------------------------------
    # Exportación
    # -------------------------------------------------------------------
    def _export_dialog(self):
        days = self._core.db.get_days()
        if not days:
            messagebox.showinfo("Sin datos",
                                "No hay datos para exportar.", parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Exportar a Excel")
        dlg.geometry("700x520")
        dlg.configure(bg=THEME["bg"])
        dlg.grab_set()

        ttk.Label(dlg, text="Doble click en un día para configurar su rango horario e intervalo:").pack(
            pady=10, padx=12, anchor="w")

        ft = ttk.Frame(dlg)
        ft.pack(fill=tk.BOTH, expand=True, padx=12)
        cols_m = ("dia", "desde", "hasta", "intervalo")
        matrix = ttk.Treeview(ft, columns=cols_m, show="headings", height=12)
        for col, lbl, w in [("dia", "Día", 110), ("desde", "Desde", 90),
                             ("hasta", "Hasta", 90),
                             ("intervalo", "Intervalo (s)", 120)]:
            matrix.heading(col, text=lbl)
            matrix.column(col, width=w, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(ft, orient=tk.VERTICAL, command=matrix.yview)
        matrix.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        matrix.pack(fill=tk.BOTH, expand=True)
        for day in days:
            matrix.insert("", tk.END, iid=day,
                           values=(day, "00:00:00", "23:59:59", "1"))

        def edit_row(_=None):
            sel = matrix.selection()
            if not sel:
                return
            day = sel[0]
            vals = matrix.item(day)["values"]
            sub = tk.Toplevel(dlg)
            sub.title(f"Configurar {vals[0]}")
            sub.geometry("280x190")
            sub.configure(bg=THEME["bg"])
            sub.grab_set()
            dv = tk.StringVar(value=str(vals[1]))
            hv = tk.StringVar(value=str(vals[2]))
            iv = tk.StringVar(value=str(vals[3]))
            for i, (lbl, var) in enumerate([
                ("Desde (HH:MM:SS):", dv),
                ("Hasta (HH:MM:SS):", hv),
                ("Intervalo (seg):", iv),
            ]):
                ttk.Label(sub, text=lbl).grid(row=i, column=0,
                                               padx=10, pady=8, sticky="w")
                ttk.Entry(sub, textvariable=var, width=12).grid(
                    row=i, column=1, padx=8)
            def guardar():
                matrix.item(day, values=(vals[0], dv.get(),
                                          hv.get(), iv.get()))
                sub.destroy()
            ttk.Button(sub, text="Guardar", style="Accent.TButton",
                        command=guardar).grid(row=3, column=0,
                                              columnspan=2, pady=12)

        matrix.bind("<Double-1>", edit_row)

        bf = ttk.Frame(dlg); bf.pack(fill=tk.X, padx=12, pady=8)
        ttk.Button(bf, text="Editar seleccionado",
                   command=edit_row).pack(side=tk.LEFT, padx=4)

        def do_export():
            selected_days = list(matrix.get_children())
            if not selected_days:
                return
            fname = filedialog.asksaveasfilename(
                parent=dlg,
                defaultextension=".xlsx",
                initialfile=f"datos_{datetime.now().strftime('%Y%m%d')}.xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if fname:
                # Usar el intervalo y rango del primer día como referencia global
                try:
                    from datetime import time as dt_time
                    v0 = matrix.item(selected_days[0])["values"]
                    h_ini = dt_time(*[int(x) for x in str(v0[1]).split(":")])
                    h_fin = dt_time(*[int(x) for x in str(v0[2]).split(":")])
                    intervalo = int(v0[3])
                except Exception:
                    h_ini = h_fin = None
                    intervalo = 1
                self._core.db.export_to_excel(
                    fname, selected_days, self._ensayos,
                    h_ini, h_fin, intervalo)
                messagebox.showinfo("Exportado",
                                    f"Guardado en:\n{fname}", parent=dlg)
                dlg.destroy()

        ttk.Button(bf, text="EXPORTAR A EXCEL",
                   style="Accent.TButton",
                   command=do_export).pack(side=tk.RIGHT, padx=4)

    # -------------------------------------------------------------------
    # Análisis
    # -------------------------------------------------------------------
    def _do_analisis(self):
        day = self._an_day.get()
        var_key = self._an_var.get()
        if not day or not var_key:
            messagebox.showwarning("Selección",
                                   "Seleccioná día y variable.", parent=self)
            return
        rows = self._core.db.get_mediciones_del_dia(day)
        if not rows:
            messagebox.showinfo("Sin datos", "No hay datos para ese día.",
                                parent=self)
            return
        vals = [r[var_key] for r in rows if r.get(var_key) is not None]
        if not vals:
            return
        a = np.array(vals)
        label = next((vd.label for vd in self._core.parser.display_config
                      if vd.key == var_key), var_key)
        desc = f"{day} — {label}"
        self._an_tree.insert("", tk.END, values=(
            desc, f"{np.max(a):.2f}", f"{np.min(a):.2f}",
            f"{np.mean(a):.2f}", f"{np.std(a):.2f}"))
        times = [r["timestamp"] for r in rows if r.get(var_key) is not None]
        color = next(self._analisis_colors)
        self._an_ax.plot(times, vals, color=color, linewidth=1.5, label=desc)
        self._an_ax.legend(fontsize=8)
        self._an_ax.set_facecolor(THEME["mpl_bg"])
        self._an_ax.tick_params(colors=THEME["text_muted"], labelsize=8)
        for s in self._an_ax.spines.values():
            s.set_edgecolor(THEME["border"])
        self._an_ax.grid(True, color=THEME["mpl_grid"],
                          linewidth=0.5, linestyle="--")
        self._an_fig.autofmt_xdate()
        self._an_fig.tight_layout()
        self._an_canvas.draw()

    def _clear_analisis(self):
        self._an_tree.delete(*self._an_tree.get_children())
        self._an_ax.clear()
        self._an_ax.set_facecolor(THEME["mpl_bg"])
        self._an_canvas.draw()
        self._analisis_colors = cycle([
            "#6366f1", "#f87171", "#34d399", "#fbbf24",
            "#a78bfa", "#38bdf8", "#fb923c"])

    # -------------------------------------------------------------------
    # Web Server — usuarios
    # -------------------------------------------------------------------
    def _load_users(self) -> dict:
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_users(self, users: dict):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)

    def _update_users_list(self):
        if not hasattr(self, "_users_tree"):
            return
        self._users_tree.delete(*self._users_tree.get_children())
        for user, data in self._load_users().items():
            self._users_tree.insert("", tk.END, values=(
                user,
                data.get("email", ""),
                "✔" if data.get("alerts") else "—",
            ))

    def _create_user(self):
        u = self._new_user_var.get().strip()
        p = self._new_pass_var.get().strip()
        if not u or not p:
            messagebox.showwarning("Campos vacíos",
                                   "Completá usuario y contraseña.",
                                   parent=self)
            return
        users = self._load_users()
        if u in users:
            messagebox.showwarning("Existente",
                                   f"'{u}' ya existe.", parent=self)
            return
        users[u] = {"password": p, "email": "", "alerts": False,
                    "perms": {"rpm": True, "temp": True, "status": True}}
        self._save_users(users)
        self._new_user_var.set(""); self._new_pass_var.set("")
        self._update_users_list()

    def _user_ctx_menu(self, event):
        row = self._users_tree.identify_row(event.y)
        if not row:
            return
        self._users_tree.selection_set(row)
        username = self._users_tree.item(row)["values"][0]
        menu = tk.Menu(self, tearoff=0,
                        bg=THEME["bg2"], fg=THEME["text_primary"])
        menu.add_command(label="Editar propiedades",
                         command=lambda: self._edit_user(username))
        menu.add_separator()
        menu.add_command(label="Eliminar usuario",
                         command=lambda: self._delete_user(username))
        menu.post(event.x_root, event.y_root)

    def _edit_user(self, username: str):
        users = self._load_users()
        if username not in users:
            return
        u = users[username]
        win = tk.Toplevel(self)
        win.title(f"Propiedades: {username}")
        win.geometry("320x280")
        win.configure(bg=THEME["bg"])
        win.grab_set()

        email_v  = tk.StringVar(value=u.get("email", ""))
        alerts_v = tk.BooleanVar(value=u.get("alerts", False))
        p_rpm    = tk.BooleanVar(value=u.get("perms", {}).get("rpm",    True))
        p_temp   = tk.BooleanVar(value=u.get("perms", {}).get("temp",   True))
        p_st     = tk.BooleanVar(value=u.get("perms", {}).get("status", True))

        ttk.Label(win, text="Email:").grid(row=0, column=0,
                                            sticky="w", padx=10, pady=8)
        ttk.Entry(win, textvariable=email_v, width=26).grid(
            row=0, column=1, padx=8)
        ttk.Checkbutton(win, text="Recibir alertas por email",
                         variable=alerts_v).grid(row=1, column=0,
                                                  columnspan=2,
                                                  sticky="w", padx=10, pady=4)

        lf_p = ttk.LabelFrame(win, text="Permisos en el dashboard web")
        lf_p.grid(row=2, column=0, columnspan=2,
                   sticky="ew", padx=10, pady=6)
        for i, (lbl, var) in enumerate([("RPM", p_rpm),
                                         ("Temperatura", p_temp),
                                         ("Estado", p_st)]):
            ttk.Checkbutton(lf_p, text=lbl, variable=var).grid(
                row=0, column=i, padx=8, pady=4)

        def guardar():
            users[username]["email"]  = email_v.get()
            users[username]["alerts"] = alerts_v.get()
            users[username]["perms"]  = {
                "rpm": p_rpm.get(), "temp": p_temp.get(),
                "status": p_st.get()}
            self._save_users(users)
            self._update_users_list()
            win.destroy()

        ttk.Button(win, text="Guardar", style="Accent.TButton",
                   command=guardar).grid(row=3, column=0, columnspan=2,
                                         pady=12, padx=10, sticky="ew")

    def _delete_user(self, username: str):
        if username == "admin":
            messagebox.showerror("Error",
                                  "No se puede eliminar al admin.",
                                  parent=self)
            return
        if messagebox.askyesno("Eliminar",
                                f"¿Eliminar '{username}'?", parent=self):
            users = self._load_users()
            users.pop(username, None)
            self._save_users(users)
            self._update_users_list()

    def _save_web_vars(self):
        """Guarda la selección de variables visibles en el dashboard web."""
        visible = [key for key, var in self._web_var_checks.items() if var.get()]
        if "rpm" not in visible:
            visible.insert(0, "rpm")   # rpm siempre incluido
        self._core.set_config("web_visible_vars", visible)
        self._core.save_config()
        messagebox.showinfo("Web Dashboard",
                            f"Variables seleccionadas: {', '.join(visible)}",
                            parent=self)

    def _save_brevo(self):
        self._core.set_config("brevo_api_key", self._brevo_key_var.get())
        self._core.set_config("brevo_email",   self._brevo_email_var.get())
        self._core.save_config()
        messagebox.showinfo("Guardado",
                            "Configuración Brevo guardada.", parent=self)

    # -------------------------------------------------------------------
    # Configuración
    # -------------------------------------------------------------------
    def _save_config(self):
        try:
            for key, var in self._cfg_vars.items():
                val = var.get()
                try:
                    self._core.set_config(key, float(val))
                except ValueError:
                    self._core.set_config(key, val)
            for key, en_var in self._alarm_enabled_vars.items():
                try:
                    thr = float(self._alarm_threshold_vars[key].get())
                except ValueError:
                    thr = 0.0
                self._core.configure_alarm(key, en_var.get(), thr)
            self._core.save_config()
            self._plot._title = self._core.get_config("plot_title", "RPM")
            self._plot.set_range(self._core.get_config("plot_ymin", 0),
                                  self._core.get_config("plot_ymax", 2000))
            self._gauge.configure_range(
                self._core.get_config("gauge_min", 0),
                self._core.get_config("gauge_max", 2000))
            messagebox.showinfo("Configuración",
                                "Guardada correctamente.", parent=self)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _change_db(self):
        if self._core.is_recording:
            messagebox.showwarning("Grabando",
                                   "Finalizá el ensayo antes de cambiar la BD.",
                                   parent=self)
            return
        fname = filedialog.askopenfilename(
            parent=self, title="Seleccionar base de datos",
            filetypes=[("SQLite", "*.db"), ("Todos", "*.*")])
        if fname:
            self._core.db.change_db(fname)
            self._db_var.set(fname)

    def _toggle_theme(self):
        # Capturar colores del tema ANTERIOR antes de cambiar
        old = dict(THEME)
        ThemeManager.toggle()       # Actualiza THEME
        apply_theme_to_style()      # Actualiza estilos ttk

        # Mapa de reemplazo: color_viejo → color_nuevo
        # Solo colores que cambian entre temas (excluye text_muted que es igual en ambos)
        color_map = {old[k]: THEME[k] for k in THEME
                     if k != "name" and old.get(k) != THEME[k]
                     and isinstance(old.get(k), str) and old[k].startswith("#")}

        def update_widget(w):
            """Recorre recursivamente todos los widgets tk y actualiza colores."""
            for prop in ("bg", "fg"):
                try:
                    val = str(w.cget(prop))
                    if val in color_map:
                        w.configure(**{prop: color_map[val]})
                except Exception:
                    pass
            try:
                for child in w.winfo_children():
                    update_widget(child)
            except Exception:
                pass

        root = self.winfo_toplevel()
        root.configure(bg=THEME["bg"])
        update_widget(root)

        if hasattr(self, "_theme_lbl"):
            self._theme_lbl.config(
                bg=THEME["bg"],
                text=f"Tema actual: "
                     f"{'Oscuro' if THEME['name'] == 'dark' else 'Claro'}",
                fg=THEME["text_muted"])

    def _apply_theme_bg(self):
        self.configure(bg=THEME["bg"])

    # -------------------------------------------------------------------
    # Ciclo de vida
    # -------------------------------------------------------------------
    def on_close(self):
        ThemeManager.unregister(self._apply_theme_bg)
        self._core.shutdown()
