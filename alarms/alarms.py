"""Serviço Alarms: mostra os eventos do CAT numa janela Tkinter e no console."""

import argparse
import os
import queue
import signal
import sys
import time
import tkinter as tk
from tkinter import ttk

import paho.mqtt.client as mqtt

from formatacao import CORES, Alarme, formatar_evento, formatar_media

TOPICO_EVENTOS = "caldeira/eventos/#"
TOPICO_MEDIA = "caldeira/cat/media"
COR_TEXTO = {CORES["temperatura-alta"]: "white", CORES["aumento-repentino"]: "black", CORES["outro"]: "white"}
INTERVALO_FILA_MS = 100


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alarms: exibe os alarmes da caldeira.")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument("--no-gui", action="store_true", help="só console, sem janela")
    return parser


def conectar_com_retry(client, host: str, port: int, espera: float = 2.0, dormir=time.sleep) -> None:
    while True:
        try:
            client.connect(host, port)
            return
        except OSError:
            print(f"Broker indisponível em {host}:{port}, tentando de novo em {espera:g} s...")
            dormir(espera)


def hora() -> str:
    return time.strftime("%H:%M:%S")


class JanelaAlarmes:
    """Janela Tkinter. Só a thread principal mexe nos widgets; o paho entrega pela fila."""

    def __init__(self, root: tk.Tk, fila: queue.Queue):
        self.root, self.fila = root, fila
        root.title("Alarms — Caldeira")
        root.geometry("780x480")
        root.minsize(560, 320)
        ttk.Style(root).theme_use("clam")  # o tema padrão do macOS ignora cores de linha

        topo = ttk.Frame(root, padding=(12, 10))
        topo.pack(fill="x")
        self.status = ttk.Label(topo, text="Broker: desconectado", foreground=CORES["temperatura-alta"])
        self.status.pack(side="left")
        self.media = ttk.Label(topo, text="Média atual: —", font=("Helvetica", 13, "bold"))
        self.media.pack(side="right")

        self.faixa = tk.Label(root, text="Nenhum alarme", font=("Helvetica", 16, "bold"),
                              bg="#e0e0e0", fg="#424242", pady=10)
        self.faixa.pack(fill="x", padx=12)

        meio = ttk.Frame(root, padding=(12, 10))
        meio.pack(fill="both", expand=True)
        self.tabela = ttk.Treeview(meio, columns=("hora", "tipo", "detalhe"), show="headings")
        for coluna, titulo, largura, estica in [("hora", "Hora", 80, False), ("tipo", "Tipo", 190, False),
                                                ("detalhe", "Detalhe", 420, True)]:
            self.tabela.heading(coluna, text=titulo, anchor="w")
            self.tabela.column(coluna, width=largura, stretch=estica, anchor="w")
        for cor, texto in COR_TEXTO.items():
            self.tabela.tag_configure(cor, background=cor, foreground=texto)
        rolagem = ttk.Scrollbar(meio, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=rolagem.set)
        self.tabela.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")

        rodape = ttk.Frame(root, padding=(12, 0, 12, 10))
        rodape.pack(fill="x")
        ttk.Button(rodape, text="Limpar", command=self.limpar).pack(side="right")

        root.after(INTERVALO_FILA_MS, self.ler_fila)

    def ler_fila(self) -> None:
        while True:
            try:
                tipo, valor = self.fila.get_nowait()
            except queue.Empty:
                break
            if tipo == "evento":
                self.mostrar_alarme(valor)
            elif tipo == "media":
                self.media.configure(text=valor)
            elif tipo == "conexao":
                self.status.configure(text=f"Broker: {'conectado' if valor else 'desconectado'}",
                                      foreground="#2e7d32" if valor else CORES["temperatura-alta"])
        self.root.after(INTERVALO_FILA_MS, self.ler_fila)

    def mostrar_alarme(self, alarme: Alarme) -> None:
        self.tabela.insert("", 0, values=(alarme.hora, alarme.tipo, alarme.detalhe), tags=(alarme.cor,))
        self.faixa.configure(text=f"{alarme.hora}  {alarme.tipo} — {alarme.detalhe}",
                             bg=alarme.cor, fg=COR_TEXTO[alarme.cor])

    def limpar(self) -> None:
        self.tabela.delete(*self.tabela.get_children())
        self.faixa.configure(text="Nenhum alarme", bg="#e0e0e0", fg="#424242")


def main(argv=None) -> None:
    args = criar_parser().parse_args(argv)
    fila = None if args.no_gui else queue.Queue()

    def entregar(tipo, valor):
        if fila is not None:
            fila.put((tipo, valor))

    def on_connect(client, userdata, flags, rc, properties):
        print(f"[{hora()}] conectado ao broker ({rc})")
        client.subscribe([(TOPICO_EVENTOS, 1), (TOPICO_MEDIA, 0)])
        entregar("conexao", not rc.is_failure)

    def on_disconnect(client, userdata, flags, rc, properties):
        print(f"[{hora()}] desconectado do broker ({rc})")
        entregar("conexao", False)

    def on_message(client, userdata, msg):
        if msg.topic == TOPICO_MEDIA:
            texto = formatar_media(msg.payload)
            if texto is not None:
                entregar("media", texto)
            return
        alarme = formatar_evento(msg.topic, msg.payload)
        print(alarme.linha_console)
        entregar("evento", alarme)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="alarms")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(1, 10)
    try:
        conectar_com_retry(client, args.host, args.port)
        client.loop_start()
        if args.no_gui:
            print("Alarms: só console. Ctrl+C para sair.")
            while True:
                time.sleep(1)
        else:
            root = tk.Tk()
            JanelaAlarmes(root, fila)
            root.protocol("WM_DELETE_WINDOW", root.destroy)
            # Ctrl+C no terminal fecha a janela em vez de virar traceback num callback do Tk.
            signal.signal(signal.SIGINT, lambda s, f: root.destroy())
            root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nAlarms encerrado.")
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    sys.exit(main())
