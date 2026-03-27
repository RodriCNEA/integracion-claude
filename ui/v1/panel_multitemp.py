# -*- coding: utf-8 -*-
"""
ui/panel_multitemp.py — Panel para Máquina 2 (WiFi, 7 temperaturas).

Sensores que muestra: RPM (gráfico + gauge), grilla de 7 temperaturas
con colores individuales, temperatura máxima destacada.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import TYPE_CHECKING

from ui.panel_base import THEME, MaquinaPanel, ValueCard

if TYPE_CHECKING:
    from core.maquina_core import MaquinaCore


class PanelMultiTemp(MaquinaPanel):
    """Panel para máquina WiFi con 7 canales de temperatura."""

    def __init__(self, parent, core: "MaquinaCore", **kwargs) -> None:
        self._temp_cards: dict[str, ValueCard] = {}
        self._card_temp_max: ValueCard | None = None
        self._lbl_avg_rpm: tk.StringVar | None = None
        super().__init__(parent, core, **kwargs)

    def _build_main_sensors(self, parent: tk.Frame) -> None:
        """
        Layout:
        ┌──────────────────────────────────┬──────────────┐
        │  Grilla 7 canales (2 filas x 4)  │  Temp máx +  │
        │                                  │  Avg RPM     │
        └──────────────────────────────────┴──────────────┘
        """
        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=1)

        # --- Grilla de 7 temperaturas ---
        grid_outer = tk.Frame(parent, bg=THEME["bg3"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        grid_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)

        tk.Label(grid_outer, text="TEMPERATURAS (7 CANALES)",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(8, 4))

        grid = tk.Frame(grid_outer, bg=THEME["bg3"])
        grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Obtener metadata del parser para las temperaturas
        temp_channels = [
            vd for vd in self._core.parser.display_config
            if vd.key != "rpm"
        ]

        cols_per_row = 4
        for i, vd in enumerate(temp_channels):
            row_i = i // cols_per_row
            col_i = i % cols_per_row
            grid.columnconfigure(col_i, weight=1)

            card = ValueCard(grid, label=vd.label, unit=vd.unit, color=vd.color)
            card.grid(row=row_i, column=col_i, sticky="nsew", padx=3, pady=3)
            self._temp_cards[vd.key] = card

        # --- Panel derecho: Temp máx + RPM promedio ---
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

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=2)

        tk.Label(right, text="PROM. RPM (SESIÓN)",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(6, 0))

        self._lbl_avg_rpm = tk.StringVar(value="--")
        avg_row = tk.Frame(right, bg=THEME["bg3"])
        avg_row.pack(pady=4)
        tk.Label(avg_row, textvariable=self._lbl_avg_rpm,
                 bg=THEME["bg3"], fg=THEME["green"],
                 font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        tk.Label(avg_row, text=" RPM",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, pady=6)

    def _on_data(self, data: dict) -> None:
        """Actualiza todos los widgets con los nuevos datos."""
        rpm = data.get("rpm", 0)

        # Gráfico + gauge
        self._gauge.set_value(rpm)
        self._plot.push(datetime.now(), rpm)

        # Temperatura máxima
        temp_max = data.get("temp_max", 0.0)
        if self._card_temp_max:
            self._card_temp_max.set_value(temp_max)
            # Colorear según alarma
            alarm = self._core.alarms.get("temp_max_alta")
            if alarm and alarm.enabled and alarm.threshold:
                pct = temp_max / alarm.threshold
                color = "#ff5252" if pct > 0.9 else "#fbbf24" if pct > 0.7 else "#34d399"
                self._card_temp_max.set_color(color)

        # Grilla de 7 canales
        temps_list = data.get("temps_list", [])
        temp_max_val = max(temps_list) if temps_list else 0

        for key, card in self._temp_cards.items():
            val = data.get(key)
            if val is not None:
                card.set_value(val)
                # Resaltar el canal más caliente
                if temps_list and abs(val - temp_max_val) < 0.1:
                    card.set_color("#ff5252")
                else:
                    # Restaurar el color original del parser
                    for vd in self._core.parser.display_config:
                        if vd.key == key:
                            card.set_color(vd.color)
                            break

        # Promedio RPM
        if self._lbl_avg_rpm:
            hist = self._core.history_buffer
            rpms = [h.get("rpm", 0) for h in hist if h.get("rpm") is not None]
            if rpms:
                self._lbl_avg_rpm.set(f"{sum(rpms)/len(rpms):.0f}")
