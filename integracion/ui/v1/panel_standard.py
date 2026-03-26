# -*- coding: utf-8 -*-
"""
ui/panel_standard.py — Panel para Máquina 1 (Serie).

Sensores que muestra: RPM (gráfico + gauge), Temperatura, Flujo, Relé.
Solo sobreescribe _build_main_sensors() y _on_data().
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import TYPE_CHECKING

from ui.panel_base import THEME, MaquinaPanel, StatusLed, ValueCard

if TYPE_CHECKING:
    from core.maquina_core import MaquinaCore


class PanelStandard(MaquinaPanel):
    """Panel para máquina con datos: rpm, temp, flujo, rele."""

    def __init__(self, parent, core: "MaquinaCore", **kwargs) -> None:
        # Inicializar atributos ANTES de llamar al super (que llama a _build_ui)
        self._card_temp:  ValueCard | None = None
        self._led_flujo:  StatusLed | None = None
        self._led_rele:   StatusLed | None = None
        self._lbl_avg_rpm: tk.StringVar | None = None
        self._lbl_avg_temp: tk.StringVar | None = None
        super().__init__(parent, core, **kwargs)

    def _build_main_sensors(self, parent: tk.Frame) -> None:
        """
        Construye el panel de sensores de la fila inferior:
        ┌────────────────┬────────────────┬───────────────┐
        │  Temperatura   │  Flujo / Relé  │  Promedios    │
        └────────────────┴────────────────┴───────────────┘
        """
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)

        # --- Temperatura ---
        temp_frame = tk.Frame(parent, bg=THEME["bg3"],
                              highlightbackground=THEME["border"],
                              highlightthickness=1)
        temp_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)

        tk.Label(temp_frame, text="TEMPERATURA",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(10, 0))

        self._card_temp = ValueCard(temp_frame, label="Temperatura",
                                     unit="°C", color="#ff5252")
        self._card_temp.pack(expand=True, fill=tk.BOTH, padx=16, pady=8)

        # Sub-etiqueta de tendencia
        self._temp_trend = tk.Label(temp_frame, text="",
                                     bg=THEME["bg3"], fg=THEME["text_muted"],
                                     font=("Segoe UI", 9))
        self._temp_trend.pack(pady=(0, 8))

        # --- Flujo y Relé ---
        status_frame = tk.Frame(parent, bg=THEME["bg3"],
                                 highlightbackground=THEME["border"],
                                 highlightthickness=1)
        status_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)

        tk.Label(status_frame, text="ESTADO DEL SISTEMA",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(10, 4))

        flujo_row = tk.Frame(status_frame, bg=THEME["bg3"])
        flujo_row.pack(fill=tk.X, padx=10, pady=6)
        tk.Label(flujo_row, text="Flujo de agua:",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._led_flujo = StatusLed(flujo_row, label="—")
        self._led_flujo.configure(bg=THEME["bg3"])
        self._led_flujo.pack(side=tk.RIGHT)

        ttk.Separator(status_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        rele_row = tk.Frame(status_frame, bg=THEME["bg3"])
        rele_row.pack(fill=tk.X, padx=10, pady=6)
        tk.Label(rele_row, text="Relé de seguridad:",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._led_rele = StatusLed(rele_row, label="—")
        self._led_rele.configure(bg=THEME["bg3"])
        self._led_rele.pack(side=tk.RIGHT)

        # Bloque de estado general
        self._lbl_estado = tk.Label(status_frame, text="SISTEMA OK",
                                     bg="#064e3b", fg=THEME["green"],
                                     font=("Segoe UI", 10, "bold"),
                                     pady=6, padx=10)
        self._lbl_estado.pack(fill=tk.X, padx=10, pady=(4, 10))

        # --- Promedios ---
        avg_frame = tk.Frame(parent, bg=THEME["bg3"],
                              highlightbackground=THEME["border"],
                              highlightthickness=1)
        avg_frame.grid(row=0, column=2, sticky="nsew", padx=(4, 0), pady=4)

        tk.Label(avg_frame, text="PROMEDIOS (SESIÓN)",
                 bg=THEME["bg3"], fg=THEME["text_muted"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(10, 6))

        self._lbl_avg_rpm  = tk.StringVar(value="--")
        self._lbl_avg_temp = tk.StringVar(value="--")

        for label, var, unit, color in [
            ("RPM",  self._lbl_avg_rpm,  "RPM", THEME["green"]),
            ("Temp", self._lbl_avg_temp, "°C",  "#ff5252"),
        ]:
            row = tk.Frame(avg_frame, bg=THEME["bg3"])
            row.pack(fill=tk.X, padx=12, pady=4)
            tk.Label(row, text=label, bg=THEME["bg3"],
                     fg=THEME["text_muted"], font=("Segoe UI", 9),
                     width=6, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, textvariable=var, bg=THEME["bg3"],
                     fg=color, font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
            tk.Label(row, text=unit, bg=THEME["bg3"],
                     fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=4)

    def _on_data(self, data: dict) -> None:
        """Actualiza todos los widgets con los nuevos datos."""
        rpm   = data.get("rpm", 0)
        temp  = data.get("temp", 0.0)
        flujo = data.get("flujo", False)
        rele  = data.get("rele", False)

        # Gráfico + gauge (heredado)
        self._gauge.set_value(rpm)
        self._plot.push(datetime.now(), rpm)

        # Temperatura
        if self._card_temp:
            self._card_temp.set_value(temp)
            # Colorear según temperatura (umbral de la alarma si existe)
            thr = self._core.alarms.get("temp_alta")
            if thr and thr.enabled:
                pct = temp / thr.threshold if thr.threshold else 0
                color = "#ff5252" if pct > 0.9 else "#fbbf24" if pct > 0.7 else "#34d399"
                self._card_temp.set_color(color)

        # Flujo
        if self._led_flujo:
            if flujo:
                self._led_flujo.set_ok("Flujo OK")
            else:
                self._led_flujo.set_error("SIN FLUJO")

        # Relé
        if self._led_rele:
            if rele:
                self._led_rele.set_ok("Seguro (ON)")
            else:
                self._led_rele.set_error("Inseguro (OFF)")

        # Estado general
        if hasattr(self, "_lbl_estado"):
            if flujo and rele:
                self._lbl_estado.config(text="SISTEMA OK",
                                         bg="#064e3b", fg=THEME["green"])
            else:
                self._lbl_estado.config(text="ATENCIÓN REQUERIDA",
                                         bg="#450a0a", fg=THEME["red"])

        # Promedios en sesión (del historial del core)
        if self._lbl_avg_rpm and self._lbl_avg_temp:
            hist = self._core.history_buffer
            if hist:
                rpms  = [h.get("rpm",  0) for h in hist if h.get("rpm")  is not None]
                temps = [h.get("temp", 0) for h in hist if h.get("temp") is not None]
                if rpms:
                    self._lbl_avg_rpm.set(f"{sum(rpms)/len(rpms):.0f}")
                if temps:
                    self._lbl_avg_temp.set(f"{sum(temps)/len(temps):.1f}")
