# -*- coding: utf-8 -*-
"""
ui/panel_multitemp.py — Panel para Máquina 2 (WiFi / UDP, 7 temperaturas).

Sobreescribe:
  _build_control_bar()  → campo de puerto UDP + botón Activar/Desactivar
  _build_main_sensors() → grilla de 7 canales + temp máxima
  _on_data()            → actualiza los widgets de temperatura
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ui.panel_base import THEME, MaquinaPanel, ValueCard

if TYPE_CHECKING:
    from core.maquina_core import MaquinaCore


class PanelMultiTemp(MaquinaPanel):
    """Panel para máquina WiFi con 7 canales de temperatura."""

    def __init__(self, parent, core: "MaquinaCore", default_udp_port: int = 4210,
                 **kwargs):
        self._default_udp_port = default_udp_port
        self._temp_cards: dict[str, ValueCard] = {}
        self._card_temp_max: ValueCard | None = None
        self._lbl_avg_rpm: tk.StringVar | None = None
        self._wifi_active = False
        super().__init__(parent, core, **kwargs)

    # -------------------------------------------------------------------
    # Barra de conexión WiFi (reemplaza la versión serie del base)
    # -------------------------------------------------------------------
    def _build_control_bar(self, parent: tk.Frame) -> None:
        inner = tk.Frame(parent, bg=THEME["bg2"])
        inner.pack(fill=tk.X, padx=8, pady=6)

        # --- Sección WiFi ---
        tk.Label(inner, text="Puerto UDP:", bg=THEME["bg2"],
                 fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)

        self._udp_port_var = tk.StringVar(value=str(self._default_udp_port))
        self._udp_entry = ttk.Entry(inner, textvariable=self._udp_port_var,
                                     width=7, justify="center")
        self._udp_entry.pack(side=tk.LEFT, padx=(4, 2))

        self._btn_wifi = ttk.Button(inner, text="Activar WiFi",
                                     style="Accent.TButton",
                                     command=self._toggle_wifi)
        self._btn_wifi.pack(side=tk.LEFT, padx=(4, 10))

        self._led_wifi = tk.Label(inner, text="●  WiFi desactivado",
                                   bg=THEME["bg2"], fg=THEME["text_muted"],
                                   font=("Segoe UI", 9))
        self._led_wifi.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Separator(inner, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, pady=2, padx=6)

        # --- Botones de grabación (heredados del base) ---
        self._build_recording_buttons(inner)

    def _toggle_wifi(self) -> None:
        """Abre o cierra el socket UDP."""
        if not self._wifi_active:
            port = self._udp_port_var.get().strip()
            if not port.isdigit():
                messagebox.showwarning("Puerto inválido",
                                       "Ingresá un número de puerto UDP válido.",
                                       parent=self)
                return
            ok = self._core.connect(port)   # UDPChannel.open() recibe el puerto como string
            if ok:
                self._wifi_active = True
                self._btn_wifi.config(text="Desactivar WiFi")
                self._led_wifi.config(
                    text=f"●  WiFi activo  (UDP:{port})",
                    fg=THEME["green"])
                self._udp_entry.config(state=tk.DISABLED)
                self._btn_start.config(state=tk.NORMAL)
            else:
                messagebox.showerror(
                    "Error WiFi",
                    f"No se pudo abrir el puerto UDP {port}.\n"
                    "Verificá que no esté en uso.",
                    parent=self)
        else:
            # Desactivar
            self._core.disconnect()
            self._wifi_active = False
            self._btn_wifi.config(text="Activar WiFi")
            self._led_wifi.config(text="●  WiFi desactivado",
                                   fg=THEME["text_muted"])
            self._udp_entry.config(state=tk.NORMAL)
            self._btn_start.config(state=tk.DISABLED)

    # Sobreescribimos _connect para que no haga nada
    # (la conexión la maneja _toggle_wifi)
    def _connect(self) -> None:
        pass

    # -------------------------------------------------------------------
    # Sensores de temperatura
    # -------------------------------------------------------------------
    def _build_main_sensors(self, parent: tk.Frame) -> None:
        """
        ┌──────────────────────────────┬──────────────┐
        │  Grilla 7 canales (2 filas)  │  Temp máx +  │
        │                              │  Avg RPM     │
        └──────────────────────────────┴──────────────┘
        """
        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=1)

        # Grilla de 7 temperaturas
        grid_outer = tk.Frame(parent, bg=THEME["bg3"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        grid_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)

        tk.Label(grid_outer, text="TEMPERATURAS — 7 CANALES",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(8, 4))

        grid = tk.Frame(grid_outer, bg=THEME["bg3"])
        grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        temp_channels = [vd for vd in self._core.parser.display_config
                         if vd.key != "rpm"]
        cols_per_row = 4

        for i, vd in enumerate(temp_channels):
            row_i = i // cols_per_row
            col_i = i % cols_per_row
            grid.columnconfigure(col_i, weight=1)
            card = ValueCard(grid, label=vd.label, unit=vd.unit, color=vd.color)
            card.grid(row=row_i, column=col_i, sticky="nsew", padx=3, pady=3)
            self._temp_cards[vd.key] = card

        # Panel derecho: temp máx + promedio RPM
        right = tk.Frame(parent, bg=THEME["bg3"],
                          highlightbackground=THEME["border"],
                          highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=4)

        tk.Label(right, text="TEMPERATURA MÁX",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(10, 0))

        self._card_temp_max = ValueCard(right, label="T. Máxima",
                                         unit="°C", color="#ff5252")
        self._card_temp_max.pack(fill=tk.X, padx=12, pady=6)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=8, pady=2)

        tk.Label(right, text="PROM. RPM (SESIÓN)",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(6, 0))

        self._lbl_avg_rpm = tk.StringVar(value="--")
        avg_row = tk.Frame(right, bg=THEME["bg3"])
        avg_row.pack(pady=4)
        tk.Label(avg_row, textvariable=self._lbl_avg_rpm,
                 bg=THEME["bg3"], fg=THEME["green"],
                 font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        tk.Label(avg_row, text=" RPM", bg=THEME["bg3"],
                 fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, pady=6)

    # -------------------------------------------------------------------
    # Actualización de datos
    # -------------------------------------------------------------------
    def _on_data(self, data: dict) -> None:
        rpm = data.get("rpm", 0)

        # Gráfico + gauge
        self._gauge.set_value(rpm)
        self._plot.push(datetime.now(), rpm)

        # Temperatura máxima
        temp_max = data.get("temp_max", 0.0)
        if self._card_temp_max:
            self._card_temp_max.set_value(temp_max)
            alarm = self._core.alarms.get("temp_max_alta")
            if alarm and alarm.enabled and alarm.threshold:
                pct = temp_max / alarm.threshold
                color = ("#ff5252" if pct > 0.9 else
                         "#fbbf24" if pct > 0.7 else "#34d399")
                self._card_temp_max.set_color(color)

        # Grilla de 7 canales
        temps_list = data.get("temps_list", [])
        t_max_val = max(temps_list) if temps_list else 0

        for key, card in self._temp_cards.items():
            val = data.get(key)
            if val is not None:
                card.set_value(val)
                # Resaltar el canal más caliente en rojo
                if temps_list and abs(val - t_max_val) < 0.1 and t_max_val > 0:
                    card.set_color("#ff5252")
                else:
                    for vd in self._core.parser.display_config:
                        if vd.key == key:
                            card.set_color(vd.color)
                            break

        # Promedio RPM
        if self._lbl_avg_rpm:
            hist = self._core.history_buffer
            rpms = [h.get("rpm", 0) for h in hist
                    if h.get("rpm") is not None]
            if rpms:
                self._lbl_avg_rpm.set(f"{sum(rpms)/len(rpms):.0f}")
