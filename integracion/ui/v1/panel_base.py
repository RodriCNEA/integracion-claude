# -*- coding: utf-8 -*-
"""
ui/panel_base.py — Panel base compartido por todas las máquinas.

Contiene:
  - Tema visual oscuro (THEME)
  - Widgets reutilizables: GaugeWidget, PlotWidget, StatusLed, ValueCard
  - MaquinaPanel: clase base que construye la estructura de pestañas
    y se engancha al MaquinaCore sin saber el tipo de máquina.

Los paneles específicos (PanelStandard, PanelMultiTemp) heredan de
MaquinaPanel y solo sobreescriben _build_main_sensors() para dibujar
sus propios widgets de sensores.
"""

from __future__ import annotations

import math
import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

matplotlib.use("TkAgg")

if TYPE_CHECKING:
    from core.maquina_core import MaquinaCore

# ===========================================================================
#  TEMA VISUAL — UN SOLO LUGAR PARA CAMBIAR COLORES
# ===========================================================================
THEME = {
    "bg":           "#0f1117",   # fondo principal
    "bg2":          "#1a1d27",   # superficies / cards
    "bg3":          "#10131c",   # fondo de gráficos
    "border":       "#2a2d3a",   # bordes
    "accent":       "#6366f1",   # indigo — color de acento
    "accent2":      "#8b5cf6",   # violeta secundario
    "green":        "#34d399",   # OK / flujo
    "red":          "#f87171",   # error / alarma
    "amber":        "#fbbf24",   # advertencia
    "text_primary": "#e2e8f0",   # texto principal
    "text_muted":   "#64748b",   # texto secundario
    "text_dim":     "#334155",   # texto muy tenue

    # Matplotlib
    "mpl_bg":       "#10131c",
    "mpl_fg":       "#e2e8f0",
    "mpl_grid":     "#1e2235",
    "mpl_line":     "#6366f1",
    "mpl_fill":     "#6366f122",
}

def apply_dark_theme(root: tk.Tk | tk.Widget) -> None:
    """Aplica el tema oscuro a ttk y a la ventana raíz."""
    style = ttk.Style()
    style.theme_use("clam")
    bg, bg2, border = THEME["bg"], THEME["bg2"], THEME["border"]
    txt, muted = THEME["text_primary"], THEME["text_muted"]
    accent = THEME["accent"]

    style.configure(".",
        background=bg, foreground=txt,
        fieldbackground=bg2, troughcolor=bg2,
        bordercolor=border, darkcolor=bg2, lightcolor=bg2,
        relief="flat", font=("Segoe UI", 10),
    )
    style.configure("TFrame",       background=bg)
    style.configure("TLabel",       background=bg,  foreground=txt)
    style.configure("TLabelframe",  background=bg,  foreground=txt,
                    bordercolor=border, relief="flat")
    style.configure("TLabelframe.Label", background=bg, foreground=accent,
                    font=("Segoe UI", 9, "bold"))
    style.configure("TEntry",       fieldbackground=bg2, foreground=txt,
                    bordercolor=border, insertcolor=txt)
    style.configure("TButton",      background=bg2, foreground=txt,
                    bordercolor=border, focuscolor=accent,
                    font=("Segoe UI", 9))
    style.map("TButton",
        background=[("active", accent), ("pressed", "#4f46e5")],
        foreground=[("active", "#fff")],
    )
    style.configure("Accent.TButton", background=accent, foreground="#fff",
                    bordercolor=accent, font=("Segoe UI", 9, "bold"))
    style.map("Accent.TButton",
        background=[("active", "#4f46e5"), ("pressed", "#3730a3")],
    )
    style.configure("TNotebook",    background=bg, bordercolor=border, tabmargins=[0,0,0,0])
    style.configure("TNotebook.Tab",
        background=bg2, foreground=muted,
        padding=[16, 8], bordercolor=border,
        font=("Segoe UI", 9),
    )
    style.map("TNotebook.Tab",
        background=[("selected", bg)],
        foreground=[("selected", txt)],
        expand=[("selected", [0, 0, 0, 2])],
    )
    style.configure("Treeview",
        background=bg2, foreground=txt, fieldbackground=bg2,
        rowheight=26, bordercolor=border, font=("Segoe UI", 9),
    )
    style.configure("Treeview.Heading",
        background=bg, foreground=muted,
        bordercolor=border, font=("Segoe UI", 9, "bold"),
    )
    style.map("Treeview", background=[("selected", accent)], foreground=[("selected","#fff")])
    style.configure("TCombobox",
        fieldbackground=bg2, background=bg2, foreground=txt,
        arrowcolor=muted, bordercolor=border,
    )
    style.configure("TScrollbar", background=bg2, troughcolor=bg, arrowcolor=muted)
    style.configure("TCheckbutton", background=bg, foreground=txt)
    style.map("TCheckbutton", background=[("active", bg)])
    style.configure("TRadiobutton", background=bg, foreground=txt)
    style.configure("TSeparator", background=border)
    style.configure("TPanedwindow", background=border)

    if isinstance(root, tk.Tk):
        root.configure(bg=bg)


# ===========================================================================
#  WIDGET: VELOCÍMETRO (Gauge)
# ===========================================================================
class GaugeWidget(tk.Frame):
    """
    Velocímetro semicircular dibujado con matplotlib.
    Se actualiza con gauge.set_value(valor).
    """

    def __init__(self, parent, min_val=0, max_val=2000,
                 title="Velocímetro", size=(3.0, 2.2), **kwargs):
        super().__init__(parent, bg=THEME["bg"], **kwargs)
        self._min = min_val
        self._max = max_val
        self._title = title
        self._value = min_val

        self._fig, self._ax = plt.subplots(figsize=size)
        self._fig.patch.set_facecolor(THEME["mpl_bg"])
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().configure(bg=THEME["mpl_bg"], highlightthickness=0)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._draw(min_val)

    def set_value(self, value: float) -> None:
        self._value = float(value)
        self._draw(self._value)

    def configure_range(self, min_val: float, max_val: float) -> None:
        self._min = min_val
        self._max = max_val
        self._draw(self._value)

    def _draw(self, value: float) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(THEME["mpl_bg"])

        mn, mx = self._min, self._max
        value = max(mn, min(value, mx))

        # Arco de fondo (gris)
        thetas_bg = np.linspace(np.pi, 0, 180)
        ax.plot(np.cos(thetas_bg), np.sin(thetas_bg),
                lw=18, color="#1e2235", solid_capstyle="butt", zorder=1)

        # Arco de valor (gradiente verde → rojo)
        ratio = (value - mn) / (mx - mn) if mx != mn else 0
        end_theta = np.pi - ratio * np.pi
        thetas_val = np.linspace(np.pi, end_theta, max(2, int(ratio * 180)))
        if len(thetas_val) >= 2:
            for i in range(len(thetas_val) - 1):
                t = i / max(1, len(thetas_val) - 2)
                # Verde → Amarillo → Rojo
                if t < 0.5:
                    r = t * 2
                    g = 1.0
                else:
                    r = 1.0
                    g = 1.0 - (t - 0.5) * 2
                ax.plot(
                    [np.cos(thetas_val[i]), np.cos(thetas_val[i+1])],
                    [np.sin(thetas_val[i]), np.sin(thetas_val[i+1])],
                    lw=18, color=(r, g, 0.15), solid_capstyle="butt", zorder=2,
                )

        # Aguja
        needle_angle = np.pi - ratio * np.pi
        ax.annotate("",
            xy=(0.72 * np.cos(needle_angle), 0.72 * np.sin(needle_angle)),
            xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", color=THEME["text_primary"],
                            lw=2, mutation_scale=14),
            zorder=5,
        )
        ax.add_patch(plt.Circle((0, 0), 0.06, color=THEME["bg2"], zorder=6))
        ax.add_patch(plt.Circle((0, 0), 0.04, color=THEME["accent"], zorder=7))

        # Valor numérico
        ax.text(0, -0.28, f"{value:.0f}",
                ha="center", va="center", fontsize=22, fontweight="bold",
                color=THEME["text_primary"], zorder=8)
        ax.text(0, -0.48, "RPM",
                ha="center", va="center", fontsize=9,
                color=THEME["text_muted"], zorder=8)

        # Límites
        ax.text(-1.1, 0.05, f"{mn:.0f}", ha="center", fontsize=8,
                color=THEME["text_muted"])
        ax.text(1.1, 0.05, f"{mx:.0f}", ha="center", fontsize=8,
                color=THEME["text_muted"])

        # Título
        ax.set_title(self._title, color=THEME["text_muted"],
                     fontsize=9, pad=4)

        ax.set_xlim(-1.3, 1.3)
        ax.set_ylim(-0.65, 1.15)
        ax.set_aspect("equal")
        ax.axis("off")
        self._fig.tight_layout(pad=0.2)
        self._canvas.draw_idle()


# ===========================================================================
#  WIDGET: GRÁFICO DE LÍNEA
# ===========================================================================
class PlotWidget(tk.Frame):
    """
    Gráfico de línea en tiempo real.
    Se actualiza con plot.push(tiempo, valor).
    """

    def __init__(self, parent, title="Dato vs Tiempo",
                 ymin=0, ymax=2000, color=None, size=(6, 2.2), **kwargs):
        super().__init__(parent, bg=THEME["bg"], **kwargs)
        self._title = title
        self._ymin  = ymin
        self._ymax  = ymax
        self._color = color or THEME["mpl_line"]
        self._data: deque = deque(maxlen=3600)

        self._fig, self._ax = plt.subplots(figsize=size)
        self._fig.patch.set_facecolor(THEME["mpl_bg"])
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().configure(bg=THEME["mpl_bg"], highlightthickness=0)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._init_axes()

    def _init_axes(self) -> None:
        ax = self._ax
        ax.set_facecolor(THEME["mpl_bg"])
        ax.tick_params(colors=THEME["text_muted"], labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(THEME["border"])
        ax.grid(True, color=THEME["mpl_grid"], linewidth=0.5, linestyle="--")
        ax.set_title(self._title, color=THEME["text_muted"], fontsize=9, pad=4)
        ax.set_ylim(self._ymin, self._ymax)
        self._fig.tight_layout(pad=0.5)
        self._canvas.draw_idle()

    def push(self, timestamp: datetime, value: float) -> None:
        """Agrega un punto y redibuja."""
        self._data.append((timestamp, value))
        self._redraw()

    def push_gap(self) -> None:
        """Inserta un corte en la línea (para pausas)."""
        self._data.append((datetime.now(), float("nan")))

    def set_range(self, ymin: float, ymax: float) -> None:
        self._ymin = ymin
        self._ymax = ymax
        self._ax.set_ylim(ymin, ymax)
        self._canvas.draw_idle()

    def auto_range(self) -> None:
        """Ajusta el eje Y al rango actual de los datos."""
        vals = [v for _, v in self._data if not math.isnan(v)]
        if not vals:
            return
        mn, mx = min(vals), max(vals)
        pad = (mx - mn) * 0.1 if mx > mn else 1
        self.set_range(mn - pad, mx + pad)

    def _redraw(self) -> None:
        if not self._data:
            return
        ax = self._ax
        ax.clear()
        ax.set_facecolor(THEME["mpl_bg"])
        ax.tick_params(colors=THEME["text_muted"], labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(THEME["border"])
        ax.grid(True, color=THEME["mpl_grid"], linewidth=0.5, linestyle="--")
        ax.set_title(self._title, color=THEME["text_muted"], fontsize=9, pad=4)
        ax.set_ylim(self._ymin, self._ymax)

        times = [t for t, _ in self._data]
        vals  = [v for _, v in self._data]

        ax.plot(times, vals, color=self._color, linewidth=1.5, zorder=3)
        ax.fill_between(times, self._ymin, vals,
                        color=self._color, alpha=0.08, zorder=2)

        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
        self._fig.autofmt_xdate(rotation=0, ha="center")
        self._fig.tight_layout(pad=0.5)
        self._canvas.draw_idle()


# ===========================================================================
#  WIDGET: LED DE ESTADO
# ===========================================================================
class StatusLed(tk.Frame):
    """LED circular + etiqueta. Color cambia según estado."""

    def __init__(self, parent, label="Estado", **kwargs):
        super().__init__(parent, bg=THEME["bg2"], **kwargs)
        self._label_text = label

        self._canvas = tk.Canvas(self, width=14, height=14,
                                  bg=THEME["bg2"], highlightthickness=0)
        self._canvas.pack(side=tk.LEFT, padx=(8, 4))
        self._circle = self._canvas.create_oval(2, 2, 12, 12, fill=THEME["text_dim"], outline="")

        self._lbl = tk.Label(self, text=label, bg=THEME["bg2"],
                              fg=THEME["text_muted"], font=("Segoe UI", 9))
        self._lbl.pack(side=tk.LEFT, padx=(0, 8))

    def set_ok(self, text: str = "") -> None:
        self._canvas.itemconfig(self._circle, fill=THEME["green"])
        self._lbl.config(text=text or self._label_text, fg=THEME["green"])

    def set_error(self, text: str = "") -> None:
        self._canvas.itemconfig(self._circle, fill=THEME["red"])
        self._lbl.config(text=text or self._label_text, fg=THEME["red"])

    def set_warning(self, text: str = "") -> None:
        self._canvas.itemconfig(self._circle, fill=THEME["amber"])
        self._lbl.config(text=text or self._label_text, fg=THEME["amber"])

    def set_idle(self, text: str = "") -> None:
        self._canvas.itemconfig(self._circle, fill=THEME["text_dim"])
        self._lbl.config(text=text or self._label_text, fg=THEME["text_muted"])


# ===========================================================================
#  WIDGET: CARD DE VALOR
# ===========================================================================
class ValueCard(tk.Frame):
    """
    Tarjeta que muestra un valor grande con su unidad y etiqueta.
    Uso: card.set_value(1234.5)
    """

    def __init__(self, parent, label="Valor", unit="", color=None, **kwargs):
        c = color or THEME["accent"]
        super().__init__(parent, bg=THEME["bg2"],
                         highlightbackground=c, highlightthickness=1, **kwargs)
        self._color = c

        tk.Label(self, text=label.upper(), bg=THEME["bg2"],
                 fg=THEME["text_muted"], font=("Segoe UI", 8, "bold")).pack(pady=(10, 0))

        self._var = tk.StringVar(value="---")
        tk.Label(self, textvariable=self._var, bg=THEME["bg2"],
                 fg=c, font=("Segoe UI", 26, "bold")).pack()

        tk.Label(self, text=unit, bg=THEME["bg2"],
                 fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(pady=(0, 8))

    def set_value(self, value) -> None:
        if value is None:
            self._var.set("---")
        elif isinstance(value, bool):
            self._var.set("OK" if value else "FALLA")
        elif isinstance(value, float):
            self._var.set(f"{value:.1f}")
        else:
            self._var.set(str(value))

    def set_color(self, color: str) -> None:
        self._color = color
        self.configure(highlightbackground=color)


# ===========================================================================
#  BARRA DE ALARMA (banner rojo en la parte superior del panel)
# ===========================================================================
class AlarmBanner(tk.Frame):
    """
    Barra roja con mensaje que aparece cuando hay una alarma activa.
    Se muestra/oculta con show() / hide().
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=THEME["red"], **kwargs)
        self._msg = tk.Label(
            self, text="", bg=THEME["red"], fg="#fff",
            font=("Segoe UI", 10, "bold"), pady=6,
        )
        self._msg.pack(side=tk.LEFT, padx=16, expand=True)

        self._btn = tk.Button(
            self, text="RECONOCER", bg="#7f1d1d", fg="#fca5a5",
            font=("Segoe UI", 8, "bold"), relief=tk.FLAT,
            cursor="hand2", padx=10,
        )
        self._btn.pack(side=tk.RIGHT, padx=8, pady=4)
        self._visible = False

    def show(self, message: str, on_ack=None) -> None:
        self._msg.config(text=f"⚠  {message}")
        if on_ack:
            self._btn.config(command=on_ack)
        if not self._visible:
            self.pack(fill=tk.X, side=tk.TOP, before=self.master.winfo_children()[0])
            self._visible = True

    def hide(self) -> None:
        if self._visible:
            self.pack_forget()
            self._visible = False


# ===========================================================================
#  PANEL BASE — Estructura de pestañas + lógica común
# ===========================================================================
class MaquinaPanel(tk.Frame):
    """
    Panel base para una máquina. Hereda tk.Frame para poder meterse
    dentro de un ttk.Notebook del programa maestro.

    Crea la estructura de pestañas:
        Principal  — gráfico + velocímetro + sensores específicos
        Ensayos    — gestión de ensayos y atributos
        Historial  — visor de datos históricos
        Config     — ajustes, alarmas, base de datos

    Los paneles hijos (PanelStandard, PanelMultiTemp) solo
    sobreescriben _build_main_sensors().
    """

    def __init__(self, parent, core: "MaquinaCore", **kwargs) -> None:
        super().__init__(parent, bg=THEME["bg"], **kwargs)
        self._core = core

        # Variables tk para la barra de control
        self._port_var    = tk.StringVar()
        self._baud_var    = tk.StringVar(value="9600")
        self._ensayo_var  = tk.StringVar()
        self._prueba_var  = tk.StringVar()
        self._comment_var = tk.StringVar()

        # Ensayos guardados (nombre → lista de atributos)
        self._ensayos: dict = {}
        self._load_ensayos()

        # Banner de alarma
        self._alarm_banner = AlarmBanner(self)

        # Construir UI
        self._build_ui()

        # Enganchar callbacks del core
        self._core.on_data(lambda d: self.after(0, self._on_data, d))
        self._core.on_alarm(lambda k, n, v, t: self.after(0, self._on_alarm, k, n, v, t))
        self._core.on_alarm_resolved(lambda k, n, v, t: self.after(0, self._on_alarm_resolved, k, n, v, t))
        self._core.on_connection_lost(lambda: self.after(0, self._on_conn_lost))
        self._core.on_connection_restored(lambda: self.after(0, self._on_conn_restored))
        self._core.on_recording_stopped(lambda auto: self.after(0, self._on_recording_stopped, auto))

    # -----------------------------------------------------------------------
    # Construcción de la UI
    # -----------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._alarm_banner.pack_forget()

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Pestaña Principal
        self._tab_main = ttk.Frame(self._nb)
        self._nb.add(self._tab_main, text="  Principal  ")
        self._build_main_tab()

        # Pestaña Ensayos
        self._tab_ensayo = ttk.Frame(self._nb)
        self._nb.add(self._tab_ensayo, text="  Ensayos  ")
        self._build_ensayo_tab()

        # Pestaña Historial
        self._tab_hist = ttk.Frame(self._nb)
        self._nb.add(self._tab_hist, text="  Historial  ")
        self._build_hist_tab()

        # Pestaña Configuración
        self._tab_config = ttk.Frame(self._nb)
        self._nb.add(self._tab_config, text="  Configuración  ")
        self._build_config_tab()

    def _build_main_tab(self) -> None:
        """Construye la pestaña Principal."""
        main = self._tab_main

        # --- Barra de control superior ---
        ctrl = tk.Frame(main, bg=THEME["bg2"],
                        highlightbackground=THEME["border"], highlightthickness=1)
        ctrl.pack(fill=tk.X, padx=6, pady=6)

        inner = tk.Frame(ctrl, bg=THEME["bg2"])
        inner.pack(fill=tk.X, padx=8, pady=6)

        # Puerto
        tk.Label(inner, text="Puerto:", bg=THEME["bg2"],
                 fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._port_combo = ttk.Combobox(inner, textvariable=self._port_var,
                                         width=9, state="readonly")
        self._port_combo.pack(side=tk.LEFT, padx=(4, 2))

        ttk.Button(inner, text="↻", width=2,
                   command=self._refresh_ports).pack(side=tk.LEFT, padx=2)
        self._btn_connect = ttk.Button(inner, text="Conectar",
                                        command=self._connect)
        self._btn_connect.pack(side=tk.LEFT, padx=(2, 12))

        ttk.Separator(inner, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, pady=2, padx=4)

        # Botones de grabación
        self._btn_start = ttk.Button(inner, text="▶  Iniciar",
                                      style="Accent.TButton",
                                      command=self._start_recording, state=tk.DISABLED)
        self._btn_start.pack(side=tk.LEFT, padx=4)

        self._btn_pause = ttk.Button(inner, text="⏸  Pausar",
                                      command=self._pause_recording, state=tk.DISABLED)
        self._btn_pause.pack(side=tk.LEFT, padx=2)

        self._btn_resume = ttk.Button(inner, text="▶  Reanudar",
                                       command=self._resume_recording, state=tk.DISABLED)
        self._btn_resume.pack(side=tk.LEFT, padx=2)

        self._btn_stop = ttk.Button(inner, text="⏹  Finalizar",
                                     command=self._stop_recording, state=tk.DISABLED)
        self._btn_stop.pack(side=tk.LEFT, padx=(2, 12))

        ttk.Separator(inner, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, pady=2, padx=4)

        # Comentario
        tk.Label(inner, text="Comentario:", bg=THEME["bg2"],
                 fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Entry(inner, textvariable=self._comment_var, width=18).pack(side=tk.LEFT, padx=2)

        # LED de estado
        self._led_conn = StatusLed(inner, label="Desconectado")
        self._led_conn.pack(side=tk.RIGHT, padx=8)

        # --- Área de contenido dividida ---
        pane = ttk.PanedWindow(main, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # Fila superior: gráfico + velocímetro
        top_frame = tk.Frame(pane, bg=THEME["bg"])
        pane.add(top_frame, weight=3)

        # Gráfico de RPM
        graph_container = tk.Frame(top_frame, bg=THEME["bg3"],
                                    highlightbackground=THEME["border"],
                                    highlightthickness=1)
        graph_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        graph_ctrl = tk.Frame(graph_container, bg=THEME["bg3"])
        graph_ctrl.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(graph_ctrl, text="Auto Y",
                   command=lambda: self._plot.auto_range()).pack(side=tk.LEFT)

        self._plot = PlotWidget(graph_container,
                                title=self._core.get_config("plot_title", "RPM vs Tiempo"),
                                ymin=self._core.get_config("plot_ymin", 0),
                                ymax=self._core.get_config("plot_ymax", 2000))
        self._plot.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # Velocímetro
        gauge_container = tk.Frame(top_frame, bg=THEME["bg3"],
                                    highlightbackground=THEME["border"],
                                    highlightthickness=1, width=240)
        gauge_container.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))
        gauge_container.pack_propagate(False)

        self._gauge = GaugeWidget(
            gauge_container,
            min_val=self._core.get_config("gauge_min", 0),
            max_val=self._core.get_config("gauge_max", 2000),
            title=self._core.get_config("gauge_title", "Velocímetro"),
        )
        self._gauge.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Fila inferior: widgets de sensores (específicos de cada máquina)
        self._sensors_frame = tk.Frame(pane, bg=THEME["bg"])
        pane.add(self._sensors_frame, weight=2)
        self._build_main_sensors(self._sensors_frame)

    def _build_main_sensors(self, parent: tk.Frame) -> None:
        """
        Sobreescribir en la subclase para mostrar los sensores específicos.
        Por defecto muestra un placeholder.
        """
        tk.Label(parent, text="[ Sin sensores configurados ]",
                 bg=THEME["bg"], fg=THEME["text_muted"],
                 font=("Segoe UI", 10)).pack(expand=True)

    def _build_ensayo_tab(self) -> None:
        """Pestaña de gestión de ensayos."""
        pad = {"padx": 8, "pady": 6}

        # Marco superior: selector y guardado
        top = ttk.LabelFrame(self._tab_ensayo, text="Gestión de Ensayos")
        top.pack(fill=tk.X, padx=10, pady=10)

        r0 = ttk.Frame(top); r0.pack(fill=tk.X, **pad)
        ttk.Label(r0, text="Ensayo:").pack(side=tk.LEFT)
        self._ensayo_combo = ttk.Combobox(r0, textvariable=self._ensayo_var,
                                           state="readonly", width=28)
        self._ensayo_combo.pack(side=tk.LEFT, padx=6)
        self._ensayo_combo.bind("<<ComboboxSelected>>", self._on_ensayo_selected)
        ttk.Button(r0, text="Cargar como activo",
                   command=self._load_ensayo).pack(side=tk.LEFT, padx=4)
        ttk.Button(r0, text="Eliminar",
                   command=self._delete_ensayo).pack(side=tk.LEFT)

        r1 = ttk.Frame(top); r1.pack(fill=tk.X, **pad)
        ttk.Label(r1, text="Nombre prueba:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._prueba_var, width=28).pack(side=tk.LEFT, padx=6)
        ttk.Button(r1, text="Guardar ensayo",
                   command=self._save_ensayo).pack(side=tk.LEFT, padx=4)

        # Marco de atributos
        attr = ttk.LabelFrame(self._tab_ensayo, text="Atributos del Ensayo")
        attr.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        add_row = ttk.Frame(attr); add_row.pack(fill=tk.X, **pad)
        self._attr_key = tk.StringVar()
        self._attr_val = tk.StringVar()
        ttk.Entry(add_row, textvariable=self._attr_key, width=18,
                  ).pack(side=tk.LEFT)
        tk.Label(add_row, text="=", bg=THEME["bg"],
                 fg=THEME["text_muted"]).pack(side=tk.LEFT, padx=4)
        ttk.Entry(add_row, textvariable=self._attr_val, width=30).pack(side=tk.LEFT)
        ttk.Button(add_row, text="Agregar",
                   command=self._add_attr).pack(side=tk.LEFT, padx=6)
        ttk.Button(add_row, text="Limpiar",
                   command=self._clear_attrs).pack(side=tk.LEFT)

        self._attr_tree = ttk.Treeview(attr, columns=("attr", "val"),
                                        show="headings", height=8)
        self._attr_tree.heading("attr", text="Atributo")
        self._attr_tree.heading("val",  text="Valor")
        self._attr_tree.column("attr", width=180)
        self._attr_tree.column("val",  width=380)

        vsb = ttk.Scrollbar(attr, orient=tk.VERTICAL,
                             command=self._attr_tree.yview)
        self._attr_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 6))
        self._attr_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self._attr_tree.bind("<Delete>", lambda e: self._del_attr())

        self._update_ensayos_combo()

    def _build_hist_tab(self) -> None:
        """Pestaña de historial / visor de datos."""
        ctrl = ttk.Frame(self._tab_hist)
        ctrl.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(ctrl, text="Día:").pack(side=tk.LEFT)
        self._hist_day = ttk.Combobox(ctrl, state="readonly", width=14)
        self._hist_day.pack(side=tk.LEFT, padx=6)
        self._hist_day.bind("<<ComboboxSelected>>", lambda e: self._load_hist())

        ttk.Button(ctrl, text="↻ Refrescar días",
                   command=self._refresh_hist_days).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Exportar a Excel",
                   command=self._export_excel).pack(side=tk.RIGHT)
        ttk.Button(ctrl, text="Ver alarmas",
                   command=self._show_alarms).pack(side=tk.RIGHT, padx=4)

        # Tabla de datos
        cols = ["Hora", "Ensayo", "Prueba", "Comentario"] + \
               [vd.label for vd in self._core.parser.display_config]

        frame_tree = ttk.Frame(self._tab_hist)
        frame_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self._hist_tree = ttk.Treeview(frame_tree, columns=cols,
                                        show="headings", height=16)
        for col in cols:
            self._hist_tree.heading(col, text=col)
            self._hist_tree.column(col, width=90 if col != "Comentario" else 140,
                                    anchor=tk.CENTER)
        self._hist_tree.column("Hora", width=70)

        vsb = ttk.Scrollbar(frame_tree, orient=tk.VERTICAL,
                             command=self._hist_tree.yview)
        hsb = ttk.Scrollbar(frame_tree, orient=tk.HORIZONTAL,
                             command=self._hist_tree.xview)
        self._hist_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._hist_tree.pack(fill=tk.BOTH, expand=True)

        self._refresh_hist_days()

    def _build_config_tab(self) -> None:
        """Pestaña de configuración."""
        pad = {"padx": 10, "pady": 6}

        # Sección: Gráfico y velocímetro
        lf_plot = ttk.LabelFrame(self._tab_config, text="Visualización")
        lf_plot.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)

        fields = [
            ("Título gráfico",    "plot_title",  False),
            ("Título velocímetro","gauge_title",  False),
            ("Y Mínimo",          "plot_ymin",    False),
            ("Y Máximo",          "plot_ymax",    False),
            ("Gauge Mínimo",      "gauge_min",    False),
            ("Gauge Máximo",      "gauge_max",    False),
        ]
        self._cfg_vars: dict[str, tk.StringVar] = {}
        for i, (label, key, _) in enumerate(fields):
            ttk.Label(lf_plot, text=label + ":").grid(row=i, column=0, sticky="w",
                                                        padx=8, pady=3)
            var = tk.StringVar(value=str(self._core.get_config(key, "")))
            self._cfg_vars[key] = var
            ttk.Entry(lf_plot, textvariable=var, width=22).grid(row=i, column=1,
                                                                   sticky="w", padx=8)

        # Sección: Watchdog y autofin
        lf_wd = ttk.LabelFrame(self._tab_config, text="Watchdog y Auto-finalización")
        lf_wd.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        for i, (label, key) in enumerate([
            ("Watchdog (seg sin datos)", "watchdog_sec"),
            ("Auto-finalizar si RPM=0 (min)", "autofin_min"),
        ]):
            ttk.Label(lf_wd, text=label + ":").grid(row=i, column=0, sticky="w",
                                                      padx=8, pady=3)
            var = tk.StringVar(value=str(self._core.get_config(key, "")))
            self._cfg_vars[key] = var
            ttk.Entry(lf_wd, textvariable=var, width=10).grid(row=i, column=1,
                                                                sticky="w", padx=8)

        # Sección: Alarmas
        lf_al = ttk.LabelFrame(self._tab_config, text="Alarmas")
        lf_al.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)

        self._alarm_enabled_vars: dict[str, tk.BooleanVar] = {}
        self._alarm_threshold_vars: dict[str, tk.StringVar] = {}

        for row_i, (key, alarm) in enumerate(self._core.alarms.items()):
            en_var = tk.BooleanVar(value=alarm.enabled)
            th_var = tk.StringVar(value=str(alarm.threshold))
            self._alarm_enabled_vars[key]   = en_var
            self._alarm_threshold_vars[key] = th_var

            ttk.Checkbutton(lf_al, text=alarm.name,
                             variable=en_var).grid(row=row_i, column=0,
                                                    sticky="w", padx=8, pady=3)
            ttk.Entry(lf_al, textvariable=th_var, width=10).grid(row=row_i, column=1,
                                                                   sticky="w", padx=4)
            unit = ""
            for vd in self._core.parser.display_config:
                if vd.key in key:
                    unit = vd.unit
                    break
            ttk.Label(lf_al, text=unit).grid(row=row_i, column=2, sticky="w")

        # Sección: Base de datos
        lf_db = ttk.LabelFrame(self._tab_config, text="Base de Datos")
        lf_db.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)

        self._db_var = tk.StringVar(value=self._core.db.db_path)
        ttk.Label(lf_db, textvariable=self._db_var,
                  font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Button(lf_db, text="Cambiar BD...",
                   command=self._change_db).grid(row=0, column=1, padx=8)

        # Sección: Email Brevo
        lf_mail = ttk.LabelFrame(self._tab_config, text="Email (Brevo API)")
        lf_mail.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)

        for i, (label, key) in enumerate([
            ("API Key", "brevo_api_key"),
            ("Email remitente", "brevo_email"),
        ]):
            ttk.Label(lf_mail, text=label + ":").grid(row=i, column=0,
                                                        sticky="w", padx=8, pady=3)
            var = tk.StringVar(value=self._core.get_config(key, ""))
            self._cfg_vars[key] = var
            show = "*" if "key" in key else ""
            ttk.Entry(lf_mail, textvariable=var, width=36, show=show).grid(
                row=i, column=1, sticky="w", padx=8)

        # Botón guardar
        ttk.Button(self._tab_config, text="💾  Guardar configuración",
                   style="Accent.TButton",
                   command=self._save_config).grid(row=5, column=0, columnspan=2,
                                                    pady=16, padx=10, sticky="w")

        self._tab_config.columnconfigure(1, weight=1)

    # -----------------------------------------------------------------------
    # Acciones de control
    # -----------------------------------------------------------------------
    def _refresh_ports(self) -> None:
        from core.channels import SerialChannel
        ports = SerialChannel.list_ports()
        self._port_combo["values"] = ports
        if ports:
            self._port_combo.current(0)

    def _connect(self) -> None:
        port = self._port_var.get()
        if not port:
            messagebox.showwarning("Puerto", "Seleccioná un puerto primero.", parent=self)
            return
        ok = self._core.connect(port, baudrate=int(self._baud_var.get()))
        if ok:
            self._led_conn.set_ok(f"Conectado: {port}")
            self._btn_start.config(state=tk.NORMAL)
        else:
            self._led_conn.set_error("Error de conexión")
            messagebox.showerror("Conexión", f"No se pudo abrir {port}.", parent=self)

    def _start_recording(self) -> None:
        ensayo = self._ensayo_var.get() or "Sin Ensayo"
        prueba = self._prueba_var.get() or f"Prueba {datetime.now().strftime('%H:%M')}"
        ok = self._core.start_recording(ensayo=ensayo, prueba=prueba)
        if ok:
            self._led_conn.set_ok("Grabando...")
            self._btn_start.config(state=tk.DISABLED)
            self._btn_pause.config(state=tk.NORMAL)
            self._btn_stop.config(state=tk.NORMAL)

    def _pause_recording(self) -> None:
        self._core.pause_recording()
        self._plot.push_gap()
        self._btn_pause.config(state=tk.DISABLED)
        self._btn_resume.config(state=tk.NORMAL)
        self._led_conn.set_warning("En pausa")

    def _resume_recording(self) -> None:
        self._core.resume_recording()
        self._btn_pause.config(state=tk.NORMAL)
        self._btn_resume.config(state=tk.DISABLED)
        self._led_conn.set_ok("Grabando...")

    def _stop_recording(self) -> None:
        self._core.stop_recording()

    # -----------------------------------------------------------------------
    # Callbacks del core
    # -----------------------------------------------------------------------
    def _on_data(self, data: dict) -> None:
        """Llamado en el hilo de Tk con cada nuevo dato. Sobreescribir en subclase."""
        rpm = data.get("rpm", 0)
        self._gauge.set_value(rpm)
        self._plot.push(datetime.now(), rpm)

    def _on_alarm(self, key: str, name: str, value, threshold) -> None:
        msg = f"{name}  —  Valor: {value}  |  Umbral: {threshold}"
        self._alarm_banner.show(msg, on_ack=self._ack_alarm)

    def _on_alarm_resolved(self, key: str, name: str, value, threshold) -> None:
        if not self._core.any_alarm_active:
            self._alarm_banner.hide()

    def _on_conn_lost(self) -> None:
        self._led_conn.set_error("Sin señal")

    def _on_conn_restored(self) -> None:
        self._led_conn.set_ok("Grabando...")

    def _on_recording_stopped(self, auto: bool) -> None:
        self._btn_start.config(state=tk.NORMAL)
        self._btn_pause.config(state=tk.DISABLED)
        self._btn_resume.config(state=tk.DISABLED)
        self._btn_stop.config(state=tk.DISABLED)
        self._led_conn.set_idle("Detenido")
        if auto:
            messagebox.showinfo("Auto-finalización",
                                "El ensayo finalizó automáticamente (RPM = 0).",
                                parent=self)

    def _ack_alarm(self) -> None:
        nombre = simpledialog.askstring(
            "Reconocer Alarma",
            "Ingresá tu nombre y apellido:",
            parent=self,
        )
        if nombre:
            self._core.acknowledge_all_alarms()
            session = self._core.current_session
            self._core.db.log_alarma(
                evento="ALARMA RECONOCIDA",
                detalle=f"Atendida por: {nombre}",
                operador=nombre,
                ensayo=session.ensayo if session else "",
                prueba=session.prueba if session else "",
            )
            self._alarm_banner.hide()

    # -----------------------------------------------------------------------
    # Ensayos
    # -----------------------------------------------------------------------
    def _load_ensayos(self) -> None:
        import json, os
        f = "ensayos.json"
        if os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    self._ensayos = json.load(fh)
            except Exception:
                self._ensayos = {}

    def _save_ensayos_file(self) -> None:
        import json
        with open("ensayos.json", "w", encoding="utf-8") as f:
            json.dump(self._ensayos, f, indent=2, ensure_ascii=False)

    def _update_ensayos_combo(self) -> None:
        self._ensayo_combo["values"] = list(self._ensayos.keys())

    def _on_ensayo_selected(self, _=None) -> None:
        nombre = self._ensayo_var.get()
        self._attr_tree.delete(*self._attr_tree.get_children())
        for item in self._ensayos.get(nombre, []):
            self._attr_tree.insert("", tk.END, values=(item["atributo"], item["valor"]))

    def _load_ensayo(self) -> None:
        nombre = self._ensayo_var.get()
        if not nombre:
            messagebox.showwarning("Sin selección",
                                   "Seleccioná un ensayo primero.", parent=self)
            return
        messagebox.showinfo("Ensayo cargado",
                            f"Ensayo '{nombre}' activo para la próxima grabación.",
                            parent=self)

    def _save_ensayo(self) -> None:
        nombre = self._prueba_var.get().strip()
        if not nombre:
            messagebox.showwarning("Nombre vacío",
                                   "Ingresá un nombre para el ensayo.", parent=self)
            return
        items = [
            {"atributo": self._attr_tree.item(c)["values"][0],
             "valor":    self._attr_tree.item(c)["values"][1]}
            for c in self._attr_tree.get_children()
        ]
        self._ensayos[nombre] = items
        self._save_ensayos_file()
        self._update_ensayos_combo()
        messagebox.showinfo("Guardado", f"Ensayo '{nombre}' guardado.", parent=self)

    def _delete_ensayo(self) -> None:
        nombre = self._ensayo_var.get()
        if nombre and messagebox.askyesno("Eliminar", f"¿Eliminar '{nombre}'?",
                                           parent=self):
            self._ensayos.pop(nombre, None)
            self._save_ensayos_file()
            self._update_ensayos_combo()
            self._ensayo_var.set("")

    def _add_attr(self) -> None:
        k, v = self._attr_key.get().strip(), self._attr_val.get().strip()
        if k and v:
            self._attr_tree.insert("", tk.END, values=(k, v))
            self._attr_key.set("")
            self._attr_val.set("")

    def _del_attr(self) -> None:
        for item in self._attr_tree.selection():
            self._attr_tree.delete(item)

    def _clear_attrs(self) -> None:
        if messagebox.askyesno("Limpiar", "¿Limpiar todos los atributos?",
                                parent=self):
            self._attr_tree.delete(*self._attr_tree.get_children())

    # -----------------------------------------------------------------------
    # Historial
    # -----------------------------------------------------------------------
    def _refresh_hist_days(self) -> None:
        days = self._core.db.get_days()
        self._hist_day["values"] = days
        if days:
            self._hist_day.set(days[-1])
            self._load_hist()

    def _load_hist(self) -> None:
        day = self._hist_day.get()
        if not day:
            return
        self._hist_tree.delete(*self._hist_tree.get_children())
        col_names = self._core.db.column_names
        for fila in self._core.db.get_mediciones_del_dia(day):
            row = [
                fila["timestamp"].strftime("%H:%M:%S"),
                fila.get("ensayo", ""),
                fila.get("prueba", ""),
                fila.get("comentario", ""),
            ] + [
                (f"{fila.get(c, ''):.1f}" if isinstance(fila.get(c), float)
                 else str(fila.get(c, "")))
                for c in col_names
            ]
            self._hist_tree.insert("", tk.END, values=row)

    def _show_alarms(self) -> None:
        win = tk.Toplevel(self)
        win.title("Registro de Alarmas")
        win.geometry("850x400")
        win.configure(bg=THEME["bg"])

        cols = ["Timestamp", "Evento", "Detalle", "Operador", "Ensayo", "Prueba"]
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, width=120 if col not in ("Detalle", "Ensayo") else 160,
                        anchor=tk.CENTER)
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        for a in self._core.db.get_alarmas():
            tree.insert("", tk.END, values=(
                a["timestamp"], a["evento"], a["detalle"],
                a["operador"], a["ensayo"], a["prueba"],
            ))

    def _export_excel(self) -> None:
        days = self._core.db.get_days()
        if not days:
            messagebox.showinfo("Sin datos", "No hay datos para exportar.", parent=self)
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            initialfile=f"datos_{datetime.now().strftime('%Y%m%d')}.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if filename:
            self._core.db.export_to_excel(filename, days, self._ensayos)
            messagebox.showinfo("Exportado",
                                f"Archivo guardado en:\n{filename}", parent=self)

    # -----------------------------------------------------------------------
    # Configuración
    # -----------------------------------------------------------------------
    def _save_config(self) -> None:
        try:
            for key, var in self._cfg_vars.items():
                val = var.get()
                try:
                    self._core.set_config(key, float(val))
                except ValueError:
                    self._core.set_config(key, val)

            # Alarmas
            for key, en_var in self._alarm_enabled_vars.items():
                try:
                    thr = float(self._alarm_threshold_vars[key].get())
                except ValueError:
                    thr = 0.0
                self._core.configure_alarm(key, en_var.get(), thr)

            self._core.save_config()

            # Aplicar a widgets
            self._plot._title = self._core.get_config("plot_title", "RPM vs Tiempo")
            self._plot.set_range(
                self._core.get_config("plot_ymin", 0),
                self._core.get_config("plot_ymax", 2000),
            )
            self._gauge.configure_range(
                self._core.get_config("gauge_min", 0),
                self._core.get_config("gauge_max", 2000),
            )

            messagebox.showinfo("Configuración", "Guardada correctamente.", parent=self)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _change_db(self) -> None:
        if self._core.is_recording:
            messagebox.showwarning("Grabando",
                                   "Finalizá el ensayo antes de cambiar la BD.",
                                   parent=self)
            return
        filename = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar base de datos",
            filetypes=[("SQLite", "*.db"), ("Todos", "*.*")],
        )
        if filename:
            self._core.db.change_db(filename)
            self._db_var.set(filename)

    # -----------------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------------
    def on_close(self) -> None:
        """Llamar desde la ventana padre al cerrar."""
        self._core.shutdown()
