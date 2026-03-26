# -*- coding: utf-8 -*-
"""
main.py — Punto de entrada del sistema.

Instancia los cores, paneles y el servidor web, los conecta
y abre la ventana principal con un Notebook de dos pestañas.

Para agregar una tercera máquina en el futuro:
    1. Definir su canal y parser
    2. Crear un MaquinaCore con su config
    3. Crear su Panel (PanelStandard, PanelMultiTemp, o uno nuevo)
    4. Añadir al notebook y registrar en el servidor web
    Solo eso. Sin tocar nada más.
"""

import tkinter as tk
from tkinter import ttk

from core.channels import SerialChannel, UDPChannel
from core.database import MedicionesDB
from core.maquina_core import MaquinaCore
from core.parsers import MultiTempParser, StandardParser
from ui.panel_base import THEME, apply_dark_theme
from ui.panel_multitemp import PanelMultiTemp
from ui.panel_standard import PanelStandard
from web.servidor import WebServer


def main() -> None:
    # -----------------------------------------------------------------------
    # 1. Ventana principal
    # -----------------------------------------------------------------------
    root = tk.Tk()
    root.title("Sistema de Control de Centrífugas — V9")
    root.geometry("1400x820")
    root.minsize(1100, 680)
    apply_dark_theme(root)

    # -----------------------------------------------------------------------
    # 2. Máquina 1 — Serie / Estándar
    # -----------------------------------------------------------------------
    parser1  = StandardParser()
    channel1 = SerialChannel()
    db1      = MedicionesDB("mediciones_m1.db", parser1)
    core1    = MaquinaCore(
        machine_id  = "maquina1",
        channel     = channel1,
        parser      = parser1,
        db          = db1,
        config_path = "config/maquina1.json",
    )

    # -----------------------------------------------------------------------
    # 3. Máquina 2 — WiFi / MultiTemp
    # -----------------------------------------------------------------------
    parser2  = MultiTempParser()
    channel2 = UDPChannel()
    db2      = MedicionesDB("mediciones_m2.db", parser2)
    core2    = MaquinaCore(
        machine_id  = "maquina2",
        channel     = channel2,
        parser      = parser2,
        db          = db2,
        config_path = "config/maquina2.json",
    )

    # -----------------------------------------------------------------------
    # 4. Servidor web Flask
    # -----------------------------------------------------------------------
    server = WebServer(port=5000)
    server.register(core1)
    server.register(core2)
    server.start()

    # -----------------------------------------------------------------------
    # 5. Notebook principal
    # -----------------------------------------------------------------------
    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    panel1 = PanelStandard(nb, core=core1)
    nb.add(panel1, text="  ► MÁQUINA 1  (Serie)  ")

    panel2 = PanelMultiTemp(nb, core=core2)
    nb.add(panel2, text="  ► MÁQUINA 2  (WiFi — 7 Temps)  ")

    # -----------------------------------------------------------------------
    # 6. Barra de estado inferior
    # -----------------------------------------------------------------------
    status_bar = tk.Frame(root, bg=THEME["bg2"],
                           highlightbackground=THEME["border"],
                           highlightthickness=1)
    status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    tk.Label(
        status_bar,
        text="  Sistema de Control de Centrífugas — V9  |  "
             "Web Dashboard → http://localhost:5000",
        bg=THEME["bg2"], fg=THEME["text_muted"],
        font=("Segoe UI", 8), pady=4,
    ).pack(side=tk.LEFT)

    tk.Label(
        status_bar,
        text="Máquina 1: Serie  |  Máquina 2: WiFi UDP  ",
        bg=THEME["bg2"], fg=THEME["text_dim"],
        font=("Segoe UI", 8), pady=4,
    ).pack(side=tk.RIGHT)

    # -----------------------------------------------------------------------
    # 7. Cierre limpio
    # -----------------------------------------------------------------------
    def on_close() -> None:
        panel1.on_close()
        panel2.on_close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # -----------------------------------------------------------------------
    # 8. Inicializar lista de puertos al arrancar
    # -----------------------------------------------------------------------
    root.after(200, panel1._refresh_ports)

    root.mainloop()


if __name__ == "__main__":
    main()
