# -*- coding: utf-8 -*-
"""
core/parsers.py — Capa de interpretación de datos.

Transforma la línea de texto cruda que llega del hardware en un diccionario
tipado y consistente. El resto del sistema trabaja solo con ese diccionario;
nunca con strings crudos.

Para agregar un formato nuevo:
    1. Crear una clase que herede de DataParser.
    2. Implementar: parse(), variable_names, y display_config.
    3. Nada más cambia en el sistema.

Contrato de parse():
    - Recibe: string crudo tal como llega del hardware.
    - Retorna: dict con los datos, o None si la línea es inválida/incompleta.
    - NUNCA lanza excepciones. Los errores se tragan silenciosamente.
    - NUNCA modifica estado interno (función pura).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ===========================================================================
#  METADATA DE VISUALIZACIÓN
#  Cada variable sabe cómo quiere mostrarse en la UI.
# ===========================================================================
@dataclass
class VarDisplay:
    """Describe cómo mostrar una variable en la UI."""
    key: str           # Nombre en el dict de datos (ej: "rpm")
    label: str         # Etiqueta para el usuario (ej: "Velocidad")
    unit: str          # Unidad (ej: "RPM", "°C", "")
    color: str         # Color principal para gráficos y displays
    decimals: int = 0  # Decimales a mostrar
    is_alarm_candidate: bool = True   # ¿Puede tener alarma?
    is_boolean: bool = False          # ¿Es un estado ON/OFF?


# ===========================================================================
#  CLASE BASE ABSTRACTA
# ===========================================================================
class DataParser(ABC):
    """
    Interfaz para todos los formatos de datos del hardware.

    Implementación mínima requerida:
        - parse(raw: str) -> Optional[dict]
        - variable_names -> list[str]
        - display_config -> list[VarDisplay]
        - parser_name -> str
    """

    @abstractmethod
    def parse(self, raw: str) -> Optional[dict]:
        """
        Parsea una línea cruda.
        Retorna un dict con claves tipadas, o None si la línea no es válida.
        """

    @property
    @abstractmethod
    def variable_names(self) -> list[str]:
        """Lista de claves que este parser produce en el dict de salida."""

    @property
    @abstractmethod
    def display_config(self) -> list[VarDisplay]:
        """
        Configuración de visualización para cada variable principal.
        La UI usa esto para construir sus widgets automáticamente.
        """

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Nombre legible del parser (para logs y UI)."""

    # --- Utilidades comunes ---

    @staticmethod
    def _safe_float(value: str, default: float = 0.0) -> float:
        """Convierte a float sin lanzar excepciones."""
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_bool(value: str, default: bool = False) -> bool:
        """Convierte '0'/'1' a bool sin lanzar excepciones."""
        try:
            return bool(int(float(value)))
        except (ValueError, TypeError):
            return default


# ===========================================================================
#  PARSER ESTÁNDAR — Máquina 1 (Puerto Serie)
#  Formato: rpm,temp,flujo,rele
# ===========================================================================
class StandardParser(DataParser):
    """
    Parsea el formato estándar de la Máquina 1 (conexión serie).

    Formato esperado:
        "1200,75.3,1,1"
         rpm  temp flujo rele

    Campos:
        rpm   (float) — Velocidad en RPM
        temp  (float) — Temperatura en °C
        flujo (bool)  — 1=flujo OK, 0=sin flujo
        rele  (bool)  — 1=seguro, 0=peligro

    Tolerancia: si faltan campos del final, se usan valores por defecto.
    Si rpm no se puede parsear, retorna None (dato inutilizable).
    """

    @property
    def parser_name(self) -> str:
        return "Estándar (RPM + Temp + Flujo + Relé)"

    @property
    def variable_names(self) -> list[str]:
        return ["rpm", "temp", "flujo", "rele"]

    @property
    def display_config(self) -> list[VarDisplay]:
        return [
            VarDisplay(
                key="rpm", label="Velocidad", unit="RPM",
                color="#00e676", decimals=0, is_alarm_candidate=True
            ),
            VarDisplay(
                key="temp", label="Temperatura", unit="°C",
                color="#ff5252", decimals=1, is_alarm_candidate=True
            ),
            VarDisplay(
                key="flujo", label="Flujo de agua", unit="",
                color="#2979ff", decimals=0,
                is_alarm_candidate=True, is_boolean=True
            ),
            VarDisplay(
                key="rele", label="Relé de seguridad", unit="",
                color="#aa00ff", decimals=0,
                is_alarm_candidate=False, is_boolean=True
            ),
        ]

    def parse(self, raw: str) -> Optional[dict]:
        try:
            parts = [p.strip() for p in raw.split(",")]
            if not parts or not parts[0]:
                return None

            # rpm es el campo obligatorio — si no es un número, la línea es inválida
            try:
                rpm = float(parts[0])
            except ValueError:
                return None

            temp = self._safe_float(parts[1]) if len(parts) > 1 else 0.0
            flujo = self._safe_bool(parts[2]) if len(parts) > 2 else False
            rele = self._safe_bool(parts[3]) if len(parts) > 3 else False

            return {
                "rpm": rpm,
                "temp": temp,
                "flujo": flujo,
                "rele": rele,
            }
        except Exception:
            return None


# ===========================================================================
#  PARSER MULTITEMP — Máquina 2 (WiFi / UDP)
#  Formato: rpm,t1,t2,t3,t4,t5,t6,t7
# ===========================================================================

# Etiquetas y colores fijos para los 7 canales de temperatura
_TEMP_CHANNELS: list[tuple[str, str, str]] = [
    # (clave_interna,     etiqueta_display,    color)
    ("t_tapa_sup",  "T. Tapa Sup",   "#FF6B6B"),
    ("t_tapa_inf",  "T. Tapa Inf",   "#FF8E53"),
    ("t_cuna",      "T. Cuña",       "#FFC300"),
    ("t_estator",   "T. Estator",    "#2ECC71"),
    ("t_carcasa",   "T. Carcasa",    "#3498DB"),
    ("t_amb_sup",   "T. Amb. Sup",   "#9B59B6"),
    ("t_amb_inf",   "T. Amb. Inf",   "#1ABC9C"),
]


class MultiTempParser(DataParser):
    """
    Parsea el formato de la Máquina 2 (WiFi, 7 sensores de temperatura).

    Formato esperado:
        "1500,45.2,43.1,41.8,50.3,38.7,25.1,24.9"
         rpm   t1    t2    t3    t4    t5   t6   t7

    El dict de salida incluye:
        rpm        (float) — Velocidad en RPM
        t_tapa_sup (float) — Temperatura tapa superior
        t_tapa_inf (float) — Temperatura tapa inferior
        t_cuna     (float) — Temperatura cuña
        t_estator  (float) — Temperatura estator
        t_carcasa  (float) — Temperatura carcasa
        t_amb_sup  (float) — Temperatura ambiente superior
        t_amb_inf  (float) — Temperatura ambiente inferior
        temps_list (list)  — Lista ordenada de las 7 temperaturas (para gráficos)
        temp_max   (float) — Temperatura máxima (para alarmas)
    """

    CHANNELS = _TEMP_CHANNELS

    @property
    def parser_name(self) -> str:
        return "Multi-Temperatura WiFi (RPM + 7 Temps)"

    @property
    def variable_names(self) -> list[str]:
        return ["rpm"] + [key for key, _, _ in self.CHANNELS]

    @property
    def display_config(self) -> list[VarDisplay]:
        configs = [
            VarDisplay(
                key="rpm", label="Velocidad", unit="RPM",
                color="#00e676", decimals=0, is_alarm_candidate=True
            )
        ]
        for key, label, color in self.CHANNELS:
            configs.append(
                VarDisplay(
                    key=key, label=label, unit="°C",
                    color=color, decimals=1, is_alarm_candidate=True
                )
            )
        return configs

    def parse(self, raw: str) -> Optional[dict]:
        try:
            parts = [p.strip() for p in raw.split(",")]
            if not parts or not parts[0]:
                return None

            # rpm es el campo obligatorio
            try:
                rpm = float(parts[0])
            except ValueError:
                return None

            # Parsear las 7 temperaturas (rellenar con 0.0 si faltan)
            temps: list[float] = []
            for i in range(1, 8):
                val = self._safe_float(parts[i]) if i < len(parts) else 0.0
                temps.append(val)

            # Construir el dict con claves nombradas
            result: dict = {"rpm": rpm}
            for i, (key, _, _) in enumerate(self.CHANNELS):
                result[key] = temps[i]

            # Campos de conveniencia para el sistema de alarmas y gráficos
            result["temps_list"] = temps
            result["temp_max"] = max(temps) if temps else 0.0

            return result
        except Exception:
            return None
