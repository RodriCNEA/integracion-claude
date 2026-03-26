# -*- coding: utf-8 -*-
"""
core/maquina_core.py — Motor de la máquina.

Esta clase es el corazón del sistema. No tiene ninguna dependencia de
tkinter ni de Flask. Su única responsabilidad es:

    1. Recibir líneas crudas del canal (hilo de canal)
    2. Parsearlas y actualizar el estado interno
    3. Guardar en la BD si está grabando
    4. Evaluar alarmas
    5. Notificar a los suscriptores (UI, web) mediante callbacks

La UI y el servidor web se "enchufan" a través de on_data(), on_alarm(),
etc. y reciben actualizaciones sin que el core sepa nada de tkinter o HTTP.

Threading:
    - Los callbacks on_data se llaman desde el hilo del canal.
      La UI debe envolverlos con self.after(0, ...) para ir al hilo de Tk.
    - Los escrituras a la BD usan un Lock interno.
    - El watchdog corre en su propio hilo de fondo.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from core.channels import DataChannel
from core.database import MedicionesDB
from core.parsers import DataParser


# ---------------------------------------------------------------------------
# Tipos de callbacks
# ---------------------------------------------------------------------------
DataCallback    = Callable[[dict], None]
AlarmCallback   = Callable[[str, str, Any, Any], None]   # key, name, value, threshold
SimpleCallback  = Callable[[], None]
BoolCallback    = Callable[[bool], None]                  # auto (True = autofin)


# ===========================================================================
#  DEFINICIÓN Y ESTADO DE ALARMAS
# ===========================================================================
@dataclass
class AlarmDef:
    """
    Define una alarma: qué variable chequear, bajo qué condición y con
    qué sensibilidad.

    key:       identificador único ("temp_alta", "rpm_max", etc.)
    name:      nombre legible para la UI ("Temperatura Alta")
    get_value: lambda que extrae el valor a chequear del dict de datos
    condition: lambda(value, threshold) → True si hay falla
    threshold: umbral de disparo
    enabled:   si está activa
    debounce:  número de lecturas consecutivas en falla antes de disparar
    cooldown_min: minutos entre re-envíos de email para la misma alarma activa
    """
    key:          str
    name:         str
    get_value:    Callable[[dict], Any]
    condition:    Callable[[Any, Any], bool]
    threshold:    float  = 0.0
    enabled:      bool   = False
    debounce:     int    = 10
    cooldown_min: int    = 30

    # Estado en runtime (no se serializa)
    active:       bool   = field(default=False, repr=False)
    ack:          bool   = field(default=False, repr=False)
    counter:      int    = field(default=0, repr=False)
    last_fired:   Optional[datetime] = field(default=None, repr=False)


# ===========================================================================
#  ESTADO DE LA GRABACIÓN
# ===========================================================================
@dataclass
class RecordingSession:
    ensayo:    str = ""
    prueba:    str = ""
    started_at: datetime = field(default_factory=datetime.now)
    paused:    bool = False
    zero_rpm_since: Optional[datetime] = None


# ===========================================================================
#  CONFIGURACIÓN POR DEFECTO
# ===========================================================================
DEFAULT_CONFIG = {
    "db_file":       "mediciones.db",
    "watchdog_sec":  5,
    "autofin_min":   30,
    "alarm_debounce": 10,
    "alarm_cooldown": 30,
    "plot_title":    "RPM vs Tiempo",
    "gauge_title":   "Velocímetro",
    "gauge_min":     0.0,
    "gauge_max":     2000.0,
    "plot_ymin":     0.0,
    "plot_ymax":     2000.0,
    "window_seconds": 120,
    "brevo_api_key": "",
    "brevo_email":   "",
    "alarms":        {},   # {key: {enabled, threshold, debounce, cooldown_min}}
}


# ===========================================================================
#  CLASE PRINCIPAL
# ===========================================================================
class MaquinaCore:
    """
    Motor de una máquina. Instanciar uno por máquina.

    Ejemplo de uso:
        channel = SerialChannel()
        parser  = StandardParser()
        db      = MedicionesDB("m1.db", parser)
        core    = MaquinaCore("maquina1", channel, parser, db, "config_m1.json")

        core.on_data(lambda d: root.after(0, actualizar_ui, d))
        core.on_alarm(lambda key, name, val, thr: root.after(0, mostrar_alarma, name))

        core.connect("COM3")
        core.start_recording(ensayo="Test A", prueba="Run 1")
        ...
        core.stop_recording()
        core.disconnect()
    """

    def __init__(
        self,
        machine_id:   str,
        channel:      DataChannel,
        parser:       DataParser,
        db:           MedicionesDB,
        config_path:  str,
    ) -> None:
        self.machine_id = machine_id
        self._channel   = channel
        self._parser    = parser
        self._db        = db
        self._config_path = config_path

        # Config
        self._config: dict = {}
        self._load_config()

        # Estado de datos en tiempo real
        self._latest_data: dict = {}
        self._history_buffer: deque = deque(maxlen=60)   # para web + gráfico
        self._last_data_time: datetime = datetime.now()
        self._db_lock = threading.Lock()

        # Estado de grabación
        self._session: Optional[RecordingSession] = None
        self._watchdog_triggered = False

        # Sistema de alarmas
        self._alarms: dict[str, AlarmDef] = {}
        self._setup_default_alarms()
        self._restore_alarm_config()

        # Callbacks registrados por la UI y el servidor web
        self._data_callbacks:              list[DataCallback]   = []
        self._alarm_callbacks:             list[AlarmCallback]  = []
        self._alarm_resolved_callbacks:    list[AlarmCallback]  = []
        self._connection_lost_callbacks:   list[SimpleCallback] = []
        self._connection_restored_callbacks: list[SimpleCallback] = []
        self._recording_stopped_callbacks: list[BoolCallback]  = []

        # Hilo del watchdog
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name=f"watchdog-{machine_id}"
        )
        self._watchdog_thread.start()

    # =======================================================================
    #  REGISTRO DE CALLBACKS (API pública para UI y web)
    # =======================================================================
    def on_data(self, cb: DataCallback) -> None:
        """
        Suscribe a nuevos datos.
        cb(data_dict) se llama en el hilo del canal.
        La UI debe envolverlo: core.on_data(lambda d: self.after(0, f, d))
        """
        self._data_callbacks.append(cb)

    def on_alarm(self, cb: AlarmCallback) -> None:
        """cb(key, name, value, threshold) cuando una alarma se dispara."""
        self._alarm_callbacks.append(cb)

    def on_alarm_resolved(self, cb: AlarmCallback) -> None:
        """cb(key, name, value, threshold) cuando una alarma se normaliza."""
        self._alarm_resolved_callbacks.append(cb)

    def on_connection_lost(self, cb: SimpleCallback) -> None:
        """cb() cuando el watchdog detecta que no llegan datos."""
        self._connection_lost_callbacks.append(cb)

    def on_connection_restored(self, cb: SimpleCallback) -> None:
        """cb() cuando vuelven los datos después de una pérdida."""
        self._connection_restored_callbacks.append(cb)

    def on_recording_stopped(self, cb: BoolCallback) -> None:
        """cb(auto) cuando finaliza la grabación. auto=True si fue automático."""
        self._recording_stopped_callbacks.append(cb)

    # =======================================================================
    #  CONEXIÓN
    # =======================================================================
    def connect(self, address: str, **kwargs) -> bool:
        """Abre el canal físico. Retorna True si fue exitoso."""
        success = self._channel.open(address, **kwargs)
        if success:
            self._last_data_time = datetime.now()
        return success

    def disconnect(self) -> None:
        """Cierra el canal y detiene la lectura."""
        self._channel.close()

    @property
    def is_connected(self) -> bool:
        return self._channel.is_open

    @property
    def port_name(self) -> str:
        return self._channel.port_name

    # =======================================================================
    #  GRABACIÓN
    # =======================================================================
    def start_recording(self, ensayo: str = "", prueba: str = "") -> bool:
        """
        Inicia la grabación. Si el canal no está leyendo, lo arranca.
        Retorna False si el canal no está conectado.
        """
        if not self._channel.is_open:
            return False

        self._channel.flush()
        self._channel.start_reading(self._on_raw_data)

        self._session = RecordingSession(
            ensayo=ensayo or "Sin Ensayo",
            prueba=prueba or f"Prueba_{datetime.now().strftime('%H:%M')}",
        )
        self._last_data_time = datetime.now()
        self._watchdog_triggered = False
        return True

    def pause_recording(self) -> None:
        """Pausa: deja de guardar datos pero el canal sigue leyendo."""
        if self._session:
            self._channel.pause()
            self._session.paused = True
            # Insertar un NaN en el historial para que el gráfico corte la línea
            self._history_buffer.append({
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "rpm": None,
                "_gap": True,
            })

    def resume_recording(self) -> None:
        """Reanuda la grabación después de una pausa."""
        if self._session:
            self._channel.resume()
            self._session.paused = False
            self._last_data_time = datetime.now()
            self._watchdog_triggered = False

    def stop_recording(self, auto: bool = False) -> None:
        """
        Finaliza la grabación.
        auto=True si fue por autofinalización (RPM=0 por N minutos).
        """
        if self._session:
            self._db.log_alarma(
                evento="FIN DE ENSAYO",
                detalle="Autofinalización" if auto else "Parada manual",
                operador="SISTEMA",
                ensayo=self._session.ensayo,
                prueba=self._session.prueba,
            )

        self._channel.stop_reading()
        self._session = None
        self._session = None

        for cb in self._recording_stopped_callbacks:
            cb(auto)

    @property
    def is_recording(self) -> bool:
        return self._session is not None and not self._session.paused

    @property
    def is_paused(self) -> bool:
        return self._session is not None and self._session.paused

    @property
    def current_session(self) -> Optional[RecordingSession]:
        return self._session

    # =======================================================================
    #  PROCESAMIENTO DE DATOS (corre en hilo del canal)
    # =======================================================================
    def _on_raw_data(self, raw: str) -> None:
        """
        Callback principal: llamado por el canal con cada línea cruda.
        Parsea, actualiza estado, guarda en BD, evalúa alarmas, notifica.
        TODO: corre en el hilo del canal — los callbacks de UI deben usar after(0).
        """
        self._last_data_time = datetime.now()
        self._watchdog_triggered = False

        data = self._parser.parse(raw)
        if data is None:
            return

        # Actualizar estado en tiempo real
        self._latest_data = data

        # Agregar al historial (para web y gráfico)
        entry = {
            "timestamp": self._last_data_time.strftime("%H:%M:%S"),
            **{k: v for k, v in data.items() if isinstance(v, (int, float))},
        }
        self._history_buffer.append(entry)

        # Guardar en BD si está grabando y no está en pausa
        if self._session and not self._session.paused:
            # Verificar auto-finalización por RPM=0
            rpm = data.get("rpm", 1)
            self._check_autofin(rpm)

            # Escritura a la BD (thread-safe por lock)
            threading.Thread(
                target=self._write_to_db,
                args=(data, self._session.ensayo, self._session.prueba, ""),
                daemon=True,
            ).start()

        # Evaluar alarmas siempre (también cuando está en pausa, para no perder fallas)
        self._evaluate_alarms(data)

        # Notificar suscriptores
        for cb in self._data_callbacks:
            try:
                cb(data)
            except Exception as e:
                print(f"[MaquinaCore] Error en data callback: {e}")

    def _write_to_db(self, data: dict, ensayo: str, prueba: str, comentario: str) -> None:
        """Escribe a la BD con lock para evitar condiciones de carrera."""
        try:
            with self._db_lock:
                self._db.save_medicion(data, ensayo, prueba, comentario)
        except Exception as e:
            print(f"[MaquinaCore] Error escribiendo a BD: {e}")

    # =======================================================================
    #  SISTEMA DE ALARMAS
    # =======================================================================
    def _setup_default_alarms(self) -> None:
        """
        Crea las alarmas según las variables que expone el parser.
        Si el parser tiene 'temp', agrega alarma de temperatura.
        Si tiene 'temp_max', alarma para el máximo de todas las temps.
        Si tiene 'flujo', alarma de flujo.
        Siempre agrega alarmas de RPM máx y mín.
        """
        var_names = self._parser.variable_names
        cfg = self._config

        # RPM máxima (disponible en todos los parsers)
        self._alarms["rpm_max"] = AlarmDef(
            key="rpm_max", name="Sobrevelocidad",
            get_value=lambda d: d.get("rpm", 0),
            condition=lambda v, t: v > t,
            threshold=cfg.get("alarms", {}).get("rpm_max", {}).get("threshold", 2000.0),
            enabled=False,
        )

        # RPM mínima (solo cuando la máquina está en marcha)
        self._alarms["rpm_min"] = AlarmDef(
            key="rpm_min", name="Velocidad Baja",
            get_value=lambda d: d.get("rpm", 0),
            condition=lambda v, t: 0 < v < t,
            threshold=cfg.get("alarms", {}).get("rpm_min", {}).get("threshold", 100.0),
            enabled=False,
        )

        # Temperatura alta (para parser estándar: "temp")
        if "temp" in var_names:
            self._alarms["temp_alta"] = AlarmDef(
                key="temp_alta", name="Temperatura Alta",
                get_value=lambda d: d.get("temp", 0),
                condition=lambda v, t: v > t,
                threshold=cfg.get("alarms", {}).get("temp_alta", {}).get("threshold", 100.0),
                enabled=True,
            )

        test_result = self._parser.parse("0,0,0,0,0,0,0,0")
        if test_result and "temp_max" in test_result:
            self._alarms["temp_max_alta"] = AlarmDef(
                key="temp_max_alta", name="Temperatura Máxima Alta",
                get_value=lambda d: d.get("temp_max", 0),
                condition=lambda v, t: v > t,
                threshold=cfg.get("alarms", {}).get("temp_max_alta", {}).get("threshold", 90.0),
                enabled=True,
            )

        # Flujo de agua (para parser estándar)
        test_std = self._parser.parse("0,0,0,0")
        if test_std and "flujo" in test_std:
            self._alarms["flujo"] = AlarmDef(
                key="flujo", name="Falla de Flujo de Agua",
                get_value=lambda d: d.get("flujo", True),
                condition=lambda v, _: v is False,
                threshold=0,
                enabled=True,
            )

    def _restore_alarm_config(self) -> None:
        """Aplica configuración guardada sobre las alarmas por defecto."""
        saved = self._config.get("alarms", {})
        for key, alarm_cfg in saved.items():
            if key in self._alarms:
                alarm = self._alarms[key]
                alarm.enabled      = alarm_cfg.get("enabled", alarm.enabled)
                alarm.threshold    = alarm_cfg.get("threshold", alarm.threshold)
                alarm.debounce     = alarm_cfg.get("debounce", alarm.debounce)
                alarm.cooldown_min = alarm_cfg.get("cooldown_min", alarm.cooldown_min)

    def configure_alarm(
        self,
        key: str,
        enabled: bool,
        threshold: float,
        debounce: Optional[int] = None,
        cooldown_min: Optional[int] = None,
    ) -> None:
        """
        Configura una alarma en tiempo de ejecución (desde la UI).
        Guarda la configuración en el archivo JSON automáticamente.
        """
        if key not in self._alarms:
            return
        alarm = self._alarms[key]
        alarm.enabled   = enabled
        alarm.threshold = threshold
        if debounce is not None:
            alarm.debounce = debounce
        if cooldown_min is not None:
            alarm.cooldown_min = cooldown_min

        # Si se desactiva, limpiar estado
        if not enabled:
            alarm.active  = False
            alarm.ack     = False
            alarm.counter = 0

        self._save_alarm_config()

    def acknowledge_alarm(self, key: str) -> None:
        """El operador reconoció la alarma (silencia los re-envíos de email)."""
        if key in self._alarms:
            self._alarms[key].ack = True

    def acknowledge_all_alarms(self) -> None:
        for alarm in self._alarms.values():
            alarm.ack = True

    def _evaluate_alarms(self, data: dict) -> None:
        """Evalúa todas las alarmas activas contra los datos actuales."""
        debounce_global = self._config.get("alarm_debounce", 10)

        for alarm in self._alarms.values():
            if not alarm.enabled:
                continue

            try:
                value = alarm.get_value(data)
                in_fault = alarm.condition(value, alarm.threshold)
            except Exception:
                continue

            debounce = alarm.debounce if alarm.debounce > 0 else debounce_global

            if in_fault:
                if not alarm.active:
                    alarm.counter += 1
                    if alarm.counter >= debounce:
                        # ¡DISPARO!
                        alarm.active    = True
                        alarm.ack       = False
                        alarm.counter   = 0
                        alarm.last_fired = datetime.now()

                        # Registrar en BD
                        if self._session:
                            threading.Thread(
                                target=self._db.log_alarma,
                                kwargs=dict(
                                    evento=f"ALARMA: {alarm.name}",
                                    detalle=f"Valor: {value} | Umbral: {alarm.threshold}",
                                    ensayo=self._session.ensayo,
                                    prueba=self._session.prueba,
                                ),
                                daemon=True,
                            ).start()

                        # Notificar suscriptores
                        for cb in self._alarm_callbacks:
                            try:
                                cb(alarm.key, alarm.name, value, alarm.threshold)
                            except Exception as e:
                                print(f"[MaquinaCore] Error en alarm callback: {e}")

                        # Email (asíncrono, no bloquea el hilo de datos)
                        threading.Thread(
                            target=self._send_alarm_email,
                            args=(alarm.name, value, alarm.threshold, False),
                            daemon=True,
                        ).start()

                else:
                    # Ya activa: chequear si hay que re-enviar email (cooldown)
                    if not alarm.ack and alarm.last_fired:
                        mins = (datetime.now() - alarm.last_fired).total_seconds() / 60
                        if mins >= alarm.cooldown_min:
                            alarm.last_fired = datetime.now()
                            threading.Thread(
                                target=self._send_alarm_email,
                                args=(alarm.name, value, alarm.threshold, True),
                                daemon=True,
                            ).start()
            else:
                # Condición OK
                if alarm.active:
                    alarm.counter += 1
                    if alarm.counter >= debounce:
                        # Normalización
                        alarm.active  = False
                        alarm.ack     = False
                        alarm.counter = 0

                        for cb in self._alarm_resolved_callbacks:
                            try:
                                cb(alarm.key, alarm.name, value, alarm.threshold)
                            except Exception as e:
                                print(f"[MaquinaCore] Error en alarm_resolved callback: {e}")

                        threading.Thread(
                            target=self._send_alarm_email,
                            args=(alarm.name, value, alarm.threshold, False, True),
                            daemon=True,
                        ).start()
                else:
                    alarm.counter = 0

    @property
    def alarms(self) -> dict[str, AlarmDef]:
        """Diccionario de alarmas (para que la UI lea estado y config)."""
        return self._alarms

    # =======================================================================
    #  WATCHDOG Y AUTO-FINALIZACIÓN
    # =======================================================================
    def _watchdog_loop(self) -> None:
        """Hilo de fondo que monitorea la llegada de datos."""
        while not self._watchdog_stop.is_set():
            time.sleep(1.0)
            if not self._session:
                continue

            elapsed = (datetime.now() - self._last_data_time).total_seconds()
            watchdog_sec = self._config.get("watchdog_sec", 5)

            if elapsed > watchdog_sec:
                if not self._watchdog_triggered:
                    self._watchdog_triggered = True
                    for cb in self._connection_lost_callbacks:
                        try:
                            cb()
                        except Exception:
                            pass
            else:
                if self._watchdog_triggered:
                    self._watchdog_triggered = False
                    for cb in self._connection_restored_callbacks:
                        try:
                            cb()
                        except Exception:
                            pass

    def _check_autofin(self, rpm: float) -> None:
        """Verifica si hay que auto-finalizar por RPM=0 durante mucho tiempo."""
        if not self._session:
            return

        autofin_min = self._config.get("autofin_min", 30)
        if autofin_min <= 0:
            return

        if rpm == 0:
            if self._session.zero_rpm_since is None:
                self._session.zero_rpm_since = datetime.now()
            elif (datetime.now() - self._session.zero_rpm_since).total_seconds() > autofin_min * 60:
                self.stop_recording(auto=True)
        else:
            self._session.zero_rpm_since = None

    def shutdown(self) -> None:
        """Detiene todo limpiamente (llamar al cerrar la app)."""
        self._watchdog_stop.set()
        if self._session:
            self.stop_recording()
        self._channel.close()
        self._db.close()

    # =======================================================================
    #  PROPIEDADES DE ESTADO (acceso de solo lectura para UI y web)
    # =======================================================================
    @property
    def latest_data(self) -> dict:
        """Último dict de datos parseados (puede estar vacío al inicio)."""
        return dict(self._latest_data)

    @property
    def history_buffer(self) -> list[dict]:
        """Copia del historial reciente (para gráfico y web)."""
        return list(self._history_buffer)

    @property
    def alarm_states(self) -> dict[str, dict]:
        """Estado resumido de todas las alarmas (para la web)."""
        return {
            key: {"active": a.active, "ack": a.ack, "name": a.name}
            for key, a in self._alarms.items()
        }

    @property
    def any_alarm_active(self) -> bool:
        return any(a.active for a in self._alarms.values())

    # =======================================================================
    #  EMAIL
    # =======================================================================
    def _send_alarm_email(
        self,
        name: str,
        value: Any,
        threshold: Any,
        is_reminder: bool = False,
        is_resolved: bool = False,
    ) -> None:
        """Envía email de alarma via Brevo API (no bloquea el hilo de datos)."""
        api_key = self._config.get("brevo_api_key", "")
        sender  = self._config.get("brevo_email", "")
        if not api_key or not sender:
            return

        users_file = self._config.get("users_file", "users.json")
        try:
            with open(users_file, "r", encoding="utf-8") as f:
                users = json.load(f)
        except Exception:
            return

        recipients = [
            u["email"] for u in users.values()
            if u.get("alerts") and u.get("email") and "@" in u.get("email", "")
        ]
        if not recipients:
            return

        if is_resolved:
            subject = f"[OK] Normalizado: {name} — {self.machine_id}"
            color   = "green"
            prefix  = "✅ Sistema Normalizado"
            body    = f"La variable <b>{name}</b> volvió a valores seguros. Valor: {value}"
        elif is_reminder:
            subject = f"[Recordatorio] Alarma activa: {name} — {self.machine_id}"
            color   = "orange"
            prefix  = "⏳ Recordatorio de Falla"
            body    = f"La alarma <b>{name}</b> sigue activa. Valor: {value} | Umbral: {threshold}"
        else:
            subject = f"[ALARMA] {name} — {self.machine_id}"
            color   = "red"
            prefix  = "⚠️ Alarma Crítica"
            body    = f"Alarma en <b>{name}</b>. Valor: {value} | Umbral: {threshold}"

        html_content = f"""
        <html><body style="font-family: Arial, sans-serif;">
            <h2 style="color: {color};">{prefix}</h2>
            <p>Máquina: <b>{self.machine_id}</b></p>
            <p>{body}</p>
            <p style="color: gray; font-size: 12px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </body></html>
        """

        payload = {
            "sender": {"name": f"Monitor {self.machine_id}", "email": sender},
            "to": [{"email": e} for e in recipients],
            "subject": subject,
            "htmlContent": html_content,
        }
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }

        try:
            import requests
            r = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if r.status_code != 201:
                print(f"[MaquinaCore] Error Brevo: {r.text}")
        except Exception as e:
            print(f"[MaquinaCore] Error enviando email: {e}")

    # =======================================================================
    #  CONFIGURACIÓN
    # =======================================================================
    def _load_config(self) -> None:
        """Carga config del archivo JSON. Si no existe, usa los defaults."""
        self._config = dict(DEFAULT_CONFIG)
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._config.update(saved)
            except Exception as e:
                print(f"[MaquinaCore] Error leyendo config: {e}")

    def save_config(self) -> None:
        """Guarda la configuración actual en el archivo JSON."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._config_path)), exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[MaquinaCore] Error guardando config: {e}")

    def _save_alarm_config(self) -> None:
        """Persiste la configuración de alarmas dentro del config JSON."""
        alarm_cfg = {}
        for key, alarm in self._alarms.items():
            alarm_cfg[key] = {
                "enabled":      alarm.enabled,
                "threshold":    alarm.threshold,
                "debounce":     alarm.debounce,
                "cooldown_min": alarm.cooldown_min,
            }
        self._config["alarms"] = alarm_cfg
        self.save_config()

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        self._config[key] = value

    @property
    def db(self) -> MedicionesDB:
        return self._db

    @property
    def parser(self) -> DataParser:
        return self._parser
