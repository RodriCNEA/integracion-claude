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

    Diseñado para funcionar 24/7 con conexiones inestables:
      - Si el adaptador WiFi se desconecta brevemente, el read_loop detecta
        el OSError y reintenta el bind automáticamente (auto-rebind).
      - close() usa socket.shutdown() antes de close() para liberar el puerto
        inmediatamente, incluso si el hilo lector está bloqueado en recvfrom().
      - SO_REUSEADDR garantiza que el puerto puede reabrirse sin esperar TIME_WAIT.
    """

    def __init__(self) -> None:
        super().__init__()
        self._sock: Optional[socket.socket] = None
        self._bound_port: Optional[int] = None
        # Señal interna para que el read_loop intente un rebind sin salir del loop
        self._request_rebind = False

    @property
    def is_open(self) -> bool:
        """
        True si el socket UDP está abierto y listo para recibir datos.
        No depende del hilo lector: el socket puede estar abierto sin que
        start_reading() haya sido llamado aún (ventana entre connect() e Iniciar).
        """
        return self._sock is not None

    @property
    def port_name(self) -> str:
        return f"UDP:{self._bound_port}" if self._bound_port else "UDP:Sin conectar"

    def open(self, address: str, **kwargs) -> bool:
        """
        address: número de puerto UDP como string o entero.
        Cierra el socket previo si existe antes de abrir uno nuevo.
        """
        # Cerrar socket anterior si quedó colgado
        if self._sock:
            self._force_close_socket()

        try:
            port = int(address)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # En Linux/Mac: SO_REUSEPORT permite múltiples sockets en el mismo puerto
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass
            sock.bind(("0.0.0.0", port))
            sock.settimeout(0.5)
            self._sock = sock
            self._bound_port = port
            return True
        except Exception as e:
            print(f"[UDPChannel] Error al abrir puerto {address}: {e}")
            self._sock = None
            return False

    def close(self) -> None:
        """
        Cierra el canal limpiamente.
        Usa shutdown() antes de close() para desbloquear el recvfrom() del hilo
        lector inmediatamente, sin esperar el timeout de 0.5s.
        El puerto queda libre para que otro bind() pueda usarlo de inmediato.
        """
        self._running = False      # Señal al hilo para que salga
        self._force_close_socket() # Desbloquea recvfrom() y libera el puerto
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        self._bound_port = None

    def _force_close_socket(self) -> None:
        """Cierra el socket con shutdown() para liberar el puerto inmediatamente."""
        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def _rebind(self) -> bool:
        """
        Intenta cerrar y reabrir el socket en el mismo puerto.
        Llamado desde el read_loop cuando se detecta un error de red.
        Retorna True si el rebind fue exitoso.
        """
        port = self._bound_port
        if not port:
            return False

        print(f"[UDPChannel] Intentando re-bind en UDP:{port}...")
        self._force_close_socket()
        time.sleep(1.5)  # Dar tiempo al OS para liberar el puerto

        if not self._running:
            return False  # El canal fue cerrado externamente, no rebindear

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass
            sock.bind(("0.0.0.0", port))
            sock.settimeout(0.5)
            self._sock = sock
            self._bound_port = port
            print(f"[UDPChannel] Re-bind exitoso en UDP:{port}")
            return True
        except Exception as e:
            print(f"[UDPChannel] Re-bind fallido en UDP:{port}: {e}")
            self._sock = None
            return False

    def _read_loop(self) -> None:
        """
        Bucle de lectura con recuperación automática ante errores de red.
        Si el adaptador WiFi se desconecta y reconecta, el socket puede quedar
        inválido. En ese caso, se intenta un re-bind hasta 3 veces antes de
        rendirse y salir del loop.
        """
        consecutive_oserrors = 0
        max_rebind_attempts  = 3

        while self._running:
            try:
                if self._paused:
                    time.sleep(0.05)
                    continue
                if self._sock is None:
                    time.sleep(0.1)
                    continue

                data, _ = self._sock.recvfrom(1024)
                consecutive_oserrors = 0          # Éxito → resetear contador
                line = data.decode("utf-8", errors="ignore").strip()
                self._dispatch(line)

            except socket.timeout:
                # Normal: el timeout de 0.5s permite chequear _running cada medio segundo
                continue

            except OSError as e:
                if not self._running:
                    break  # Cierre intencional via close(), salir limpiamente
                consecutive_oserrors += 1
                print(f"[UDPChannel] OSError #{consecutive_oserrors}: {e}")

                if consecutive_oserrors <= max_rebind_attempts:
                    if self._rebind():
                        consecutive_oserrors = 0
                    else:
                        time.sleep(2.0)
                else:
                    print(f"[UDPChannel] Máximo de re-binds alcanzado. Cerrando loop.")
                    break

            except Exception as e:
                print(f"[UDPChannel] Error inesperado: {e}")
                break

        # Si salimos del loop por error (no por close() intencional),
        # liberar el socket para que is_open=False y el watchdog pueda
        # detectar la situación y disparar _try_reconnect().
        if self._running:
            print(f"[UDPChannel] Hilo lector terminó inesperadamente — liberando socket.")
            self._force_close_socket()
