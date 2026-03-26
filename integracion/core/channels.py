# -*- coding: utf-8 -*-
"""
core/channels.py — Capa de comunicación con el hardware.

Abstrae la fuente de datos (serie, UDP, o lo que venga) detrás de
una interfaz común. El resto del sistema no sabe ni le importa cómo
llegan los bytes: solo recibe líneas de texto a través de un callback.

Para agregar un canal nuevo (TCP, BLE, archivo simulado, etc.):
    1. Crear una clase que herede de DataChannel.
    2. Implementar: open(), close(), is_open, port_name, _read_loop().
    3. Nada más cambia en el resto del sistema.
"""

from __future__ import annotations

import socket
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional

import serial
import serial.tools.list_ports


# ---------------------------------------------------------------------------
# Tipo del callback: recibe una línea de texto cruda del hardware
# ---------------------------------------------------------------------------
RawCallback = Callable[[str], None]


# ===========================================================================
#  CLASE BASE ABSTRACTA
# ===========================================================================
class DataChannel(ABC):
    """
    Interfaz común para cualquier fuente de datos.

    Ciclo de vida esperado:
        channel = SerialChannel()
        ok = channel.open("COM3", baudrate=9600)
        channel.start_reading(mi_callback)
        ...
        channel.pause()
        channel.resume()
        ...
        channel.close()
    """

    def __init__(self) -> None:
        self._callback: Optional[RawCallback] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._lock = threading.Lock()

    # --- Propiedades que las subclases deben exponer ---

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True si el canal está abierto y listo para leer."""

    @property
    @abstractmethod
    def port_name(self) -> str:
        """Descripción legible del puerto/dirección abierta."""

    # --- Métodos que las subclases deben implementar ---

    @abstractmethod
    def open(self, address: str, **kwargs) -> bool:
        """
        Abre la conexión física.
        Retorna True si fue exitoso, False en caso de error.
        No lanza excepciones: los errores se logean internamente.
        """

    @abstractmethod
    def close(self) -> None:
        """Cierra la conexión y detiene el hilo lector."""

    @abstractmethod
    def _read_loop(self) -> None:
        """
        Bucle interno del hilo lector.
        Debe llamar self._dispatch(line) por cada línea recibida.
        Debe respetar self._running y self._paused.
        """

    # --- Implementación común (no sobreescribir salvo necesidad) ---

    def start_reading(self, callback: RawCallback) -> None:
        """
        Inicia la lectura en un hilo de fondo.
        Si ya hay un hilo corriendo, lo detiene limpiamente antes de arrancar
        el nuevo. Garantiza que nunca haya dos hilos compitiendo por los datos.
        """
        with self._lock:
            # Detener hilo previo si existe
            if self._thread and self._thread.is_alive():
                self._running = False
                # Esperar sin bloquear el lock
                thread_ref = self._thread

            else:
                thread_ref = None

        if thread_ref:
            thread_ref.join(timeout=2.0)

        with self._lock:
            self._callback = callback
            self._running = True
            self._paused = False
            self._thread = threading.Thread(
                target=self._read_loop,
                daemon=True,
                name=f"{self.__class__.__name__}-reader"
            )
            self._thread.start()

    def stop_reading(self) -> None:
        """Detiene el hilo lector sin cerrar el canal físico."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def pause(self) -> None:
        """Pausa el procesamiento de datos (el hilo sigue vivo)."""
        self._paused = True

    def resume(self) -> None:
        """Reanuda el procesamiento después de una pausa."""
        self._paused = False

    def flush(self) -> None:
        """Vacía el buffer de entrada. Sobreescribir si el canal lo soporta."""

    def _dispatch(self, line: str) -> None:
        """Envía la línea al callback si no está pausado."""
        if not self._paused and self._callback and line:
            self._callback(line)


# ===========================================================================
#  CANAL SERIE (RS232 / USB)
# ===========================================================================
class SerialChannel(DataChannel):
    """
    Lee datos de un puerto serie.
    Compatible con cualquier dispositivo RS232/USB que envíe líneas de texto.
    """

    def __init__(self) -> None:
        super().__init__()
        self._ser: Optional[serial.Serial] = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    @property
    def port_name(self) -> str:
        return self._ser.port if self._ser else "Sin conectar"

    def open(self, address: str, baudrate: int = 9600, **kwargs) -> bool:
        try:
            self._ser = serial.Serial(address, baudrate, timeout=1)
            return True
        except serial.SerialException as e:
            print(f"[SerialChannel] Error al abrir {address}: {e}")
            self._ser = None
            return False

    def close(self) -> None:
        self.stop_reading()
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def flush(self) -> None:
        if self._ser and self._ser.is_open:
            try:
                self._ser.reset_input_buffer()
            except Exception:
                pass

    def _read_loop(self) -> None:
        while self._running and self._ser and self._ser.is_open:
            try:
                if self._paused:
                    time.sleep(0.05)
                    continue
                line = self._ser.readline().decode("utf-8", errors="ignore").strip()
                self._dispatch(line)
            except serial.SerialException as e:
                print(f"[SerialChannel] Error de lectura: {e}")
                self._running = False
                break
            except Exception as e:
                print(f"[SerialChannel] Error inesperado: {e}")
                self._running = False
                break

    @staticmethod
    def list_ports() -> list[str]:
        """Retorna lista de puertos serie disponibles en el sistema."""
        return [p.device for p in serial.tools.list_ports.comports()]


# ===========================================================================
#  CANAL UDP (WiFi)
# ===========================================================================
class UDPChannel(DataChannel):
    """
    Escucha datagramas UDP en un puerto local.
    Ideal para dispositivos WiFi (ESP32, Arduino WiFi, etc.).
    """

    def __init__(self) -> None:
        super().__init__()
        self._sock: Optional[socket.socket] = None
        self._bound_port: Optional[int] = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    @property
    def port_name(self) -> str:
        return f"UDP:{self._bound_port}" if self._bound_port else "UDP:Sin conectar"

    def open(self, address: str, **kwargs) -> bool:
        """
        address: número de puerto UDP como string o entero.
        Ejemplo: channel.open("4210")
        """
        try:
            port = int(address)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            sock.settimeout(0.5)   # Para que el _read_loop pueda salir limpiamente
            self._sock = sock
            self._bound_port = port
            return True
        except Exception as e:
            print(f"[UDPChannel] Error al abrir puerto {address}: {e}")
            self._sock = None
            return False

    def close(self) -> None:
        self.stop_reading()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._bound_port = None

    def _read_loop(self) -> None:
        while self._running and self._sock:
            try:
                if self._paused:
                    time.sleep(0.05)
                    continue
                data, _ = self._sock.recvfrom(1024)
                line = data.decode("utf-8", errors="ignore").strip()
                self._dispatch(line)
            except socket.timeout:
                continue   # Normal: el timeout permite chequear self._running
            except OSError:
                break      # Socket cerrado externamente
            except Exception as e:
                print(f"[UDPChannel] Error de lectura: {e}")
                break
