# -*- coding: utf-8 -*-
"""
core/database.py — Capa de almacenamiento SQLite.

Diseño flexible: la estructura de la tabla de mediciones se deriva
automáticamente del parser que se le pase. Un StandardParser genera
columnas (rpm, temp, flujo, rele); un MultiTempParser genera
(rpm, t_tapa_sup, ..., t_amb_inf). El resto del sistema no cambia.

Para una nueva máquina con variables distintas: solo necesitás un
nuevo parser con su display_config y la BD se crea sola.

Tablas que siempre existen (independiente del parser):
    mediciones   — datos en tiempo real + metadatos de ensayo
    alarmas      — registro histórico de eventos de alarma

Thread safety: todas las escrituras pasan por un Lock. Las lecturas
usan conexiones separadas con check_same_thread=False (SQLite WAL).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, time as dt_time
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.parsers import DataParser


# ===========================================================================
#  CLASE PRINCIPAL
# ===========================================================================
class MedicionesDB:
    """
    Base de datos SQLite para una máquina.

    Uso básico:
        db = MedicionesDB("mi_maquina.db", parser)
        db.save_medicion(data_dict, ensayo="Test A", prueba="Run 1", comentario="")
        dias = db.get_days()
        filas = db.get_mediciones_del_dia("2025-01-15")
        db.export_to_excel("salida.xlsx", dias_seleccionados)
        db.close()
    """

    def __init__(self, db_path: str, parser: DataParser) -> None:
        self._db_path = db_path
        self._parser = parser
        self._lock = threading.Lock()

        # Derivamos el esquema del parser de una vez para siempre
        self._data_columns: list[tuple[str, str, str]] = self._build_columns(parser)

        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._create_tables()

    # -----------------------------------------------------------------------
    # Construcción del esquema dinámico
    # -----------------------------------------------------------------------
    @staticmethod
    def _build_columns(parser: DataParser) -> list[tuple[str, str, str]]:
        """
        Retorna lista de (nombre_columna, tipo_sql, label_display).
        Se deriva del display_config del parser.
        Los campos booleanos (flujo, rele) se almacenan como INTEGER.
        """
        cols = []
        for vd in parser.display_config:
            sql_type = "INTEGER" if vd.is_boolean else "REAL"
            cols.append((vd.key, sql_type, vd.label))
        return cols

    def _columns_ddl(self) -> str:
        """Genera el fragmento DDL de las columnas de datos para CREATE TABLE."""
        return ",\n    ".join(
            f"{name} {sql_type}" for name, sql_type, _ in self._data_columns
        )

    # -----------------------------------------------------------------------
    # Conexión y creación de tablas
    # -----------------------------------------------------------------------
    def _connect(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        # WAL mode: permite lecturas concurrentes mientras se escribe
        self._conn.execute("PRAGMA journal_mode=WAL")

    def _create_tables(self) -> None:
        """Crea las tablas si no existen. Migración segura para BDs viejas."""
        with self._lock:
            c = self._conn.cursor()

            # Tabla de mediciones (columnas dinámicas según el parser)
            c.execute(f"""
                CREATE TABLE IF NOT EXISTS mediciones (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    fecha     TEXT    NOT NULL,
                    hora      TEXT    NOT NULL,
                    ensayo    TEXT,
                    prueba    TEXT,
                    comentario TEXT,
                    {self._columns_ddl()}
                )
            """)

            # Índices para consultas rápidas por fecha y ensayo
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_fecha
                ON mediciones (fecha)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_ensayo
                ON mediciones (ensayo, prueba)
            """)

            # Tabla de alarmas (fija, igual para todas las máquinas)
            c.execute("""
                CREATE TABLE IF NOT EXISTS alarmas (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    fecha     TEXT    NOT NULL,
                    hora      TEXT    NOT NULL,
                    evento    TEXT,
                    detalle   TEXT,
                    operador  TEXT,
                    ensayo    TEXT,
                    prueba    TEXT
                )
            """)

            # Migración: agregar columnas que puedan faltar en BDs antiguas
            existing = {row[1] for row in c.execute("PRAGMA table_info(mediciones)")}
            for col_name, col_type, _ in self._data_columns:
                if col_name not in existing:
                    try:
                        c.execute(f"ALTER TABLE mediciones ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError:
                        pass

            self._conn.commit()

    # -----------------------------------------------------------------------
    # Escritura de datos
    # -----------------------------------------------------------------------
    def save_medicion(
        self,
        data: dict,
        ensayo: str = "",
        prueba: str = "",
        comentario: str = "",
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Guarda un punto de medición.
        data: el dict que retorna el parser (las claves deben coincidir
              con las columnas del esquema; las que falten quedan NULL).
        """
        if timestamp is None:
            timestamp = datetime.now()

        col_names = [col for col, _, _ in self._data_columns]
        values = [data.get(col) for col in col_names]

        placeholders = ", ".join(["?"] * len(col_names))
        columns_str = ", ".join(col_names)

        sql = f"""
            INSERT INTO mediciones
                (timestamp, fecha, hora, ensayo, prueba, comentario, {columns_str})
            VALUES
                (?, ?, ?, ?, ?, ?, {placeholders})
        """

        row = (
            timestamp.isoformat(),
            timestamp.strftime("%Y-%m-%d"),
            timestamp.strftime("%H:%M:%S"),
            ensayo,
            prueba,
            comentario,
            *values,
        )

        with self._lock:
            self._conn.execute(sql, row)
            self._conn.commit()

    def log_alarma(
        self,
        evento: str,
        detalle: str,
        operador: str = "SISTEMA",
        ensayo: str = "",
        prueba: str = "",
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Registra un evento de alarma en el historial."""
        if timestamp is None:
            timestamp = datetime.now()

        sql = """
            INSERT INTO alarmas
                (timestamp, fecha, hora, evento, detalle, operador, ensayo, prueba)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        row = (
            timestamp.isoformat(),
            timestamp.strftime("%Y-%m-%d"),
            timestamp.strftime("%H:%M:%S"),
            evento,
            detalle,
            operador,
            ensayo,
            prueba,
        )
        with self._lock:
            self._conn.execute(sql, row)
            self._conn.commit()

    # -----------------------------------------------------------------------
    # Lectura de datos
    # -----------------------------------------------------------------------
    def get_days(self) -> list[str]:
        """Retorna lista de fechas (YYYY-MM-DD) que tienen mediciones."""
        c = self._conn.cursor()
        c.execute("SELECT DISTINCT fecha FROM mediciones ORDER BY fecha")
        return [row[0] for row in c.fetchall()]

    def get_mediciones_del_dia(
        self,
        fecha: str,
        h_inicio: Optional[dt_time] = None,
        h_fin: Optional[dt_time] = None,
        intervalo_seg: int = 1,
    ) -> list[dict]:
        """
        Retorna mediciones de un día como lista de dicts.
        Soporta filtrado horario e interpolación por intervalo.

        fecha: 'YYYY-MM-DD'
        intervalo_seg: 1 = todos los puntos; N = promedia en ventanas de N segundos
        """
        c = self._conn.cursor()
        col_names = [col for col, _, _ in self._data_columns]
        cols_sql = ", ".join(col_names)

        query = f"""
            SELECT timestamp, ensayo, prueba, comentario, {cols_sql}
            FROM mediciones
            WHERE fecha = ?
        """
        params: list = [fecha]

        if h_inicio:
            query += " AND time(timestamp) >= ?"
            params.append(h_inicio.strftime("%H:%M:%S"))
        if h_fin:
            query += " AND time(timestamp) <= ?"
            params.append(h_fin.strftime("%H:%M:%S"))

        query += " ORDER BY timestamp ASC"
        c.execute(query, params)
        rows = c.fetchall()

        if not rows:
            return []

        # Convertir a lista de dicts
        result = []
        for row in rows:
            ts_str, ensayo, prueba, comentario, *data_vals = row
            entry = {
                "timestamp": datetime.fromisoformat(ts_str),
                "ensayo": ensayo,
                "prueba": prueba,
                "comentario": comentario,
            }
            for col_name, val in zip(col_names, data_vals):
                entry[col_name] = val
            result.append(entry)

        if intervalo_seg <= 1:
            return result

        # Reducción por ventana de tiempo
        return self._reduce_by_interval(result, intervalo_seg)

    @staticmethod
    def _reduce_by_interval(rows: list[dict], intervalo_seg: int) -> list[dict]:
        """Agrupa filas en ventanas de tiempo y promedia los valores numéricos."""
        if not rows:
            return []

        groups: list[list[dict]] = []
        current_group: list[dict] = [rows[0]]
        group_start: datetime = rows[0]["timestamp"]

        for row in rows[1:]:
            if (row["timestamp"] - group_start).total_seconds() < intervalo_seg:
                current_group.append(row)
            else:
                groups.append(current_group)
                current_group = [row]
                group_start = row["timestamp"]
        groups.append(current_group)

        result = []
        for group in groups:
            representative = dict(group[0])  # metadatos del primer punto
            representative["timestamp"] = group[len(group) // 2]["timestamp"]

            # Promediar columnas numéricas
            for key in group[0]:
                if isinstance(group[0][key], (int, float)) and group[0][key] is not None:
                    vals = [r[key] for r in group if r[key] is not None]
                    if vals:
                        representative[key] = sum(vals) / len(vals)
            result.append(representative)

        return result

    def get_alarmas(self) -> list[dict]:
        """Retorna todo el registro de alarmas, del más reciente al más viejo."""
        c = self._conn.cursor()
        c.execute("""
            SELECT timestamp, fecha, hora, evento, detalle, operador, ensayo, prueba
            FROM alarmas
            ORDER BY id DESC
        """)
        cols = ["timestamp", "fecha", "hora", "evento", "detalle", "operador", "ensayo", "prueba"]
        return [dict(zip(cols, row)) for row in c.fetchall()]

    def get_runs(self) -> list[dict]:
        """Retorna combinaciones únicas de (ensayo, prueba, fecha) para el visor."""
        c = self._conn.cursor()
        c.execute("""
            SELECT DISTINCT ensayo, prueba, fecha
            FROM mediciones
            ORDER BY fecha DESC, ensayo, prueba
        """)
        return [{"ensayo": r[0], "prueba": r[1], "fecha": r[2]} for r in c.fetchall()]

    # -----------------------------------------------------------------------
    # Exportación a Excel
    # -----------------------------------------------------------------------
    def export_to_excel(
        self,
        filename: str,
        fechas: list[str],
        ensayos_meta: dict,        # {nombre_ensayo: [{atributo, valor}, ...]}
        h_inicio: Optional[dt_time] = None,
        h_fin: Optional[dt_time] = None,
        intervalo_seg: int = 1,
    ) -> str:
        """
        Exporta datos a Excel (.xlsx).

        fechas: lista de 'YYYY-MM-DD' a exportar
        ensayos_meta: dict con atributos de los ensayos (del ensayos.json)

        Retorna la ruta del archivo guardado.
        """
        wb = Workbook()
        ws_data = wb.active
        ws_data.title = "Mediciones"

        # Estilos
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="2E4057")
        subheader_fill = PatternFill("solid", fgColor="4A7C9E")
        date_fill = PatternFill("solid", fgColor="E8F4F8")
        center = Alignment(horizontal="center", vertical="center")

        col_labels = [lbl for _, _, lbl in self._data_columns]
        col_names = [name for name, _, _ in self._data_columns]

        # Columnas fijas + columnas de datos
        all_headers = ["Fecha", "Hora", "Ensayo", "Prueba", "Comentario"] + col_labels

        # Fila de encabezados
        for i, h in enumerate(all_headers, 1):
            cell = ws_data.cell(row=1, column=i, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

        ws_data.freeze_panes = "A2"

        current_row = 2
        fill_alt = PatternFill("solid", fgColor="F5F9FF")

        for fecha in fechas:
            filas = self.get_mediciones_del_dia(fecha, h_inicio, h_fin, intervalo_seg)
            if not filas:
                continue

            # Separador visual por fecha
            cell = ws_data.cell(row=current_row, column=1, value=f"— {fecha} —")
            cell.fill = date_fill
            cell.font = Font(bold=True, color="2E4057")
            ws_data.merge_cells(
                start_row=current_row, start_column=1,
                end_row=current_row, end_column=len(all_headers)
            )
            current_row += 1

            for i, fila in enumerate(filas):
                use_fill = fill_alt if i % 2 == 1 else None
                row_data = [
                    fila["timestamp"].strftime("%Y-%m-%d"),
                    fila["timestamp"].strftime("%H:%M:%S"),
                    fila.get("ensayo", ""),
                    fila.get("prueba", ""),
                    fila.get("comentario", ""),
                ] + [fila.get(col) for col in col_names]

                for j, val in enumerate(row_data, 1):
                    cell = ws_data.cell(row=current_row, column=j, value=val)
                    cell.alignment = center
                    if use_fill:
                        cell.fill = use_fill
                current_row += 1

        # Ajustar anchos de columna
        for i, header in enumerate(all_headers, 1):
            ws_data.column_dimensions[get_column_letter(i)].width = max(12, len(str(header)) + 4)

        # Hoja de alarmas
        ws_alarm = wb.create_sheet(title="Registro de Alarmas")
        alarm_headers = ["Timestamp", "Evento", "Detalle", "Operador", "Ensayo", "Prueba"]
        for i, h in enumerate(alarm_headers, 1):
            cell = ws_alarm.cell(row=1, column=i, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

        for row_i, alarma in enumerate(self.get_alarmas(), 2):
            row_data = [
                alarma["timestamp"],
                alarma["evento"],
                alarma["detalle"],
                alarma["operador"],
                alarma["ensayo"],
                alarma["prueba"],
            ]
            for col_i, val in enumerate(row_data, 1):
                ws_alarm.cell(row=row_i, column=col_i, value=val)

        for i in range(1, len(alarm_headers) + 1):
            ws_alarm.column_dimensions[get_column_letter(i)].width = 20

        # Hoja de atributos de ensayos (si hay metadata)
        if ensayos_meta:
            ws_ens = wb.create_sheet(title="Atributos de Ensayos")
            ws_ens.cell(row=1, column=1, value="Ensayo").font = Font(bold=True)
            ws_ens.cell(row=1, column=2, value="Atributo").font = Font(bold=True)
            ws_ens.cell(row=1, column=3, value="Valor").font = Font(bold=True)
            row_i = 2
            for ensayo_nombre, attrs in ensayos_meta.items():
                for attr in attrs:
                    ws_ens.cell(row=row_i, column=1, value=ensayo_nombre)
                    ws_ens.cell(row=row_i, column=2, value=attr.get("atributo", ""))
                    ws_ens.cell(row=row_i, column=3, value=attr.get("valor", ""))
                    row_i += 1

        wb.save(filename)
        return filename

    # -----------------------------------------------------------------------
    # Mantenimiento
    # -----------------------------------------------------------------------
    def change_db(self, new_path: str) -> None:
        """Cambia la base de datos en caliente. Para uso desde la UI."""
        self.close()
        self._db_path = new_path
        self._connect()
        self._create_tables()

    def close(self) -> None:
        """Cierra la conexión limpiamente."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def column_names(self) -> list[str]:
        """Nombres de las columnas de datos (para la UI)."""
        return [name for name, _, _ in self._data_columns]
