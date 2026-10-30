"""Serviço Alarms: mostra os eventos do CAT numa janela Tkinter e no console."""

import argparse
import math
import os
import queue
import signal
import sys
import time
import uuid
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import paho.mqtt.client as mqtt

from formatacao import formatar_evento
from painel import JANELA_GRAFICO, EstadoPainel, ler_evento, ler_media, tempo_relativo

TOPICO_EVENTOS = "caldeira/eventos/#"
TOPICO_MEDIA = "caldeira/cat/media"
INTERVALO_FILA_MS = 100
INTERVALO_RELOGIO_MS = 1000
AUMENTO_RECENTE = 30.0  # segundos em que o cartão de aumento fica aceso


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


def criar_cliente() -> mqtt.Client:
    # Id único por processo: com ids iguais o broker derruba uma instância a cada conexão da outra.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"alarms-{uuid.uuid4().hex[:8]}")
    client.reconnect_delay_set(1, 10)
    return client


def hora() -> str:
    return time.strftime("%H:%M:%S")


# Paleta escura de sala de controle: o vermelho e o âmbar só aparecem quando há alarme.
FUNDO = "#0f1215"
SUPERFICIE = "#171b20"
SUPERFICIE_ALTA = "#1e232a"
LINHA_GRADE = "#262d35"
TEXTO = "#e9edf1"
TEXTO_SECUNDARIO = "#9aa5b1"
VERMELHO = "#ff5a5f"
VERMELHO_FUNDO = "#3a1618"
VERMELHO_ZONA = "#1d1517"
AMBAR = "#ffb020"
AMBAR_FUNDO = "#3a2a0c"
VERDE = "#3ccf91"
COR_LINHA = {"alta": VERMELHO, "aumento": AMBAR, "outro": TEXTO_SECUNDARIO}


def escolher_fonte(root: tk.Tk, *candidatas: str) -> str:
    disponiveis = set(tkfont.families(root))
    return next((f for f in candidatas if f in disponiveis), "TkDefaultFont")


class JanelaAlarmes:
    """Painel Tkinter. Só a thread principal mexe nos widgets; o paho entrega pela fila."""

    def __init__(self, root: tk.Tk, fila: queue.Queue):
        self.root, self.fila = root, fila
        self.estado = EstadoPainel()
        self.conectado = False
        self.linhas_tabela: dict[int, str] = {}

        numeros = escolher_fonte(root, "DIN Alternate", "Bahnschrift", "Helvetica Neue", "Helvetica")
        texto = escolher_fonte(root, "Avenir Next", "Segoe UI", "Helvetica Neue", "Helvetica", "DejaVu Sans")
        self.f_titulo = (texto, 18, "bold")
        self.f_texto = (texto, 13)
        self.f_texto_forte = (texto, 13, "bold")
        self.f_pequeno = (texto, 11)
        self.f_media = (numeros, 76, "bold")
        self.f_unidade = (numeros, 26, "bold")
        self.f_estado = (numeros, 26, "bold")
        self.f_eixo = (numeros, 11)

        root.title("Alarms — Caldeira")
        root.geometry("1000x720")
        root.minsize(780, 640)
        root.configure(bg=FUNDO)
        self._configurar_estilos()

        corpo = tk.Frame(root, bg=FUNDO, padx=24, pady=20)
        corpo.pack(fill="both", expand=True)
        corpo.columnconfigure(0, weight=0)
        corpo.columnconfigure(1, weight=1)
        corpo.rowconfigure(1, weight=5, minsize=170)
        corpo.rowconfigure(4, weight=3, minsize=150)

        self._montar_topo(corpo)
        self._montar_media(corpo)
        self._montar_grafico(corpo)
        self._montar_cartoes(corpo)
        self._montar_historico(corpo)

        self.atualizar()
        root.after(INTERVALO_FILA_MS, self.ler_fila)
        root.after(INTERVALO_RELOGIO_MS, self.tique)

    # --- montagem -----------------------------------------------------------

    def _configurar_estilos(self) -> None:
        estilo = ttk.Style(self.root)
        estilo.theme_use("clam")  # o tema padrão do macOS ignora cores de linha e de fundo
        estilo.configure("Treeview", background=SUPERFICIE, fieldbackground=SUPERFICIE, foreground=TEXTO,
                         rowheight=32, borderwidth=0, font=self.f_texto)
        estilo.map("Treeview", background=[("selected", SUPERFICIE_ALTA)], foreground=[("selected", TEXTO)])
        estilo.configure("Treeview.Heading", background=SUPERFICIE, foreground=TEXTO_SECUNDARIO,
                         borderwidth=0, relief="flat", font=self.f_pequeno, padding=(8, 6))
        estilo.map("Treeview.Heading", background=[("active", SUPERFICIE)])
        estilo.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        estilo.configure("Vertical.TScrollbar", background=SUPERFICIE_ALTA, troughcolor=SUPERFICIE,
                         bordercolor=SUPERFICIE, arrowcolor=TEXTO_SECUNDARIO, relief="flat")
        estilo.map("Vertical.TScrollbar", background=[("active", LINHA_GRADE)])
        estilo.configure("Limpar.TButton", background=SUPERFICIE_ALTA, foreground=TEXTO, borderwidth=0,
                         focusthickness=1, focuscolor=TEXTO_SECUNDARIO, padding=(14, 6), font=self.f_pequeno)
        estilo.map("Limpar.TButton", background=[("active", LINHA_GRADE), ("pressed", LINHA_GRADE)])

    def _montar_topo(self, corpo: tk.Frame) -> None:
        topo = tk.Frame(corpo, bg=FUNDO)
        topo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        tk.Label(topo, text="Caldeira", font=self.f_titulo, bg=FUNDO, fg=TEXTO).pack(side="left")
        tk.Label(topo, text="Monitor de alarmes", font=self.f_texto, bg=FUNDO,
                 fg=TEXTO_SECUNDARIO).pack(side="left", padx=(12, 0), pady=(5, 0))
        self.lbl_atualizacao = tk.Label(topo, font=self.f_pequeno, bg=FUNDO, fg=TEXTO_SECUNDARIO)
        self.lbl_atualizacao.pack(side="right", pady=(5, 0))
        self.lbl_conexao = tk.Label(topo, font=self.f_texto_forte, bg=FUNDO)
        self.lbl_conexao.pack(side="right", padx=(0, 18), pady=(3, 0))
        self.ponto_conexao = tk.Canvas(topo, width=10, height=10, bg=FUNDO, highlightthickness=0)
        self.ponto_conexao.pack(side="right", padx=(0, 7), pady=(5, 0))

    def _montar_media(self, corpo: tk.Frame) -> None:
        bloco = tk.Frame(corpo, bg=FUNDO)
        bloco.grid(row=1, column=0, sticky="nw", padx=(0, 28))
        linha = tk.Frame(bloco, bg=FUNDO)
        linha.pack(anchor="w")
        self.lbl_media = tk.Label(linha, font=self.f_media, bg=FUNDO, fg=TEXTO)
        self.lbl_media.pack(side="left")
        self.lbl_unidade = tk.Label(linha, text="°C", font=self.f_unidade, bg=FUNDO, fg=TEXTO_SECUNDARIO)
        self.lbl_unidade.pack(side="left", anchor="n", padx=(4, 0), pady=(16, 0))
        self.lbl_media_info = tk.Label(bloco, font=self.f_texto, bg=FUNDO, fg=TEXTO_SECUNDARIO, justify="left")
        self.lbl_media_info.pack(anchor="w")

    def _montar_grafico(self, corpo: tk.Frame) -> None:
        self.grafico = tk.Canvas(corpo, bg=SUPERFICIE, highlightthickness=0, height=220)
        self.grafico.grid(row=1, column=1, sticky="nsew")
        self.grafico.bind("<Configure>", lambda _e: self.desenhar_grafico())

    def _montar_cartoes(self, corpo: tk.Frame) -> None:
        linha = tk.Frame(corpo, bg=FUNDO)
        linha.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        linha.columnconfigure(0, weight=1, uniform="cartao")
        linha.columnconfigure(1, weight=1, uniform="cartao")
        self.cartao_alta = self._cartao(linha, "Temperatura alta", 0, (0, 9))
        self.cartao_aumento = self._cartao(linha, "Aumento repentino", 1, (9, 0))

    def _cartao(self, pai: tk.Frame, titulo: str, coluna: int, padx) -> dict:
        quadro = tk.Frame(pai, bg=SUPERFICIE, padx=18, pady=14)
        quadro.grid(row=0, column=coluna, sticky="nsew", padx=padx)
        rotulo = tk.Label(quadro, text=titulo, font=self.f_texto_forte, bg=SUPERFICIE, fg=TEXTO)
        rotulo.pack(anchor="w")
        estado = tk.Label(quadro, font=self.f_estado, bg=SUPERFICIE, anchor="w")
        estado.pack(anchor="w", pady=(6, 0))
        detalhe = tk.Label(quadro, font=self.f_texto, bg=SUPERFICIE, fg=TEXTO_SECUNDARIO, anchor="w",
                           justify="left")
        detalhe.pack(anchor="w", fill="x")
        # quebra o detalhe na largura do cartão em vez de empurrar a janela
        quadro.bind("<Configure>", lambda ev: detalhe.configure(wraplength=max(ev.width - 36, 120)))
        return {"quadro": quadro, "rotulo": rotulo, "estado": estado, "detalhe": detalhe}

    def _montar_historico(self, corpo: tk.Frame) -> None:
        cabecalho = tk.Frame(corpo, bg=FUNDO)
        cabecalho.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(22, 8))
        tk.Label(cabecalho, text="Histórico", font=self.f_texto_forte, bg=FUNDO, fg=TEXTO).pack(side="left")
        self.lbl_contagem = tk.Label(cabecalho, font=self.f_pequeno, bg=FUNDO, fg=TEXTO_SECUNDARIO)
        self.lbl_contagem.pack(side="left", padx=(10, 0), pady=(2, 0))
        ttk.Button(cabecalho, text="Limpar histórico", style="Limpar.TButton",
                   command=self.limpar).pack(side="right")

        quadro = tk.Frame(corpo, bg=SUPERFICIE)
        quadro.grid(row=4, column=0, columnspan=2, sticky="nsew")
        self.tabela = ttk.Treeview(quadro, columns=("hora", "tipo", "detalhe"), show="headings",
                                   selectmode="browse")
        for coluna, titulo, largura, estica in [("hora", "Hora", 96, False), ("tipo", "Alarme", 210, False),
                                                ("detalhe", "Detalhe", 480, True)]:
            self.tabela.heading(coluna, text=titulo, anchor="w")
            self.tabela.column(coluna, width=largura, stretch=estica, anchor="w")
        for tipo, cor in COR_LINHA.items():
            self.tabela.tag_configure(tipo, foreground=cor)
        self.tabela.tag_configure("ativa", foreground=VERMELHO, font=self.f_texto_forte)
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=rolagem.set)
        self.tabela.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(4, 6))
        rolagem.pack(side="right", fill="y")
        self.lbl_vazio = tk.Label(quadro, text="Nenhum alarme registrado nesta sessão.",
                                  font=self.f_texto, bg=SUPERFICIE, fg=TEXTO_SECUNDARIO)

    # --- dados --------------------------------------------------------------

    def ler_fila(self) -> None:
        mudou = False
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "evento":
                    self.estado.registrar_evento(*valor)
                elif tipo == "media":
                    self.estado.registrar_media(*valor)
                elif tipo == "conexao":
                    self.conectado = valor
                mudou = True
        except queue.Empty:
            pass
        finally:
            if mudou:
                self.atualizar()
            self.root.after(INTERVALO_FILA_MS, self.ler_fila)

    def tique(self) -> None:
        self.atualizar()
        self.root.after(INTERVALO_RELOGIO_MS, self.tique)

    def limpar(self) -> None:
        self.estado.limpar()
        self.tabela.delete(*self.tabela.get_children())
        self.linhas_tabela.clear()
        self.atualizar()

    # --- renderização -------------------------------------------------------

    def atualizar(self) -> None:
        agora = time.time()
        self._atualizar_topo(agora)
        self._atualizar_media(agora)
        self._atualizar_cartoes(agora)
        self._sincronizar_tabela(agora)
        self.desenhar_grafico(agora)

    def _atualizar_topo(self, agora: float) -> None:
        cor = VERDE if self.conectado else VERMELHO
        self.ponto_conexao.delete("all")
        self.ponto_conexao.create_oval(1, 1, 9, 9, fill=cor, outline="")
        self.lbl_conexao.configure(text="Conectado ao broker" if self.conectado else "Sem conexão com o broker",
                                   fg=cor)
        e = self.estado
        if e._ultima_media_em is None:
            texto = "Aguardando a primeira média do CAT"
        else:
            sensores = f"{e.n_sensores} {'sensor' if e.n_sensores == 1 else 'sensores'}"
            texto = f"{sensores} · média recebida {tempo_relativo(agora - e._ultima_media_em)}"
        self.lbl_atualizacao.configure(text=texto)

    def _atualizar_media(self, agora: float) -> None:
        e = self.estado
        parado = e.sem_dados(agora)
        if e.media is None:
            self.lbl_media.configure(text="—", fg=TEXTO_SECUNDARIO)
        else:
            acima = e.media > e.limite
            self.lbl_media.configure(text=f"{e.media:.1f}",
                                     fg=TEXTO_SECUNDARIO if parado else (VERMELHO if acima else TEXTO))
        if parado and e.media is not None:
            info = "Média parada: o CAT não publica\nhá mais de três ciclos"
        else:
            info = f"Média da janela do CAT\nLimite de alarme: {e.limite:.0f} °C"
        self.lbl_media_info.configure(text=info, fg=VERMELHO if parado and e.media is not None else TEXTO_SECUNDARIO)

    def _pintar_cartao(self, cartao: dict, fundo: str, cor_estado: str, estado: str, detalhe: str) -> None:
        for chave in ("quadro", "rotulo", "estado", "detalhe"):
            cartao[chave].configure(bg=fundo)
        cartao["estado"].configure(text=estado, fg=cor_estado)
        cartao["detalhe"].configure(text=detalhe, fg=TEXTO if fundo != SUPERFICIE else TEXTO_SECUNDARIO)

    def _atualizar_cartoes(self, agora: float) -> None:
        e = self.estado
        o = e.alta_ativa
        if o is not None:
            ciclos = f"{o.contagem} {'ciclo' if o.contagem == 1 else 'ciclos'}"
            self._pintar_cartao(self.cartao_alta, VERMELHO_FUNDO, VERMELHO,
                                f"Ativa há {int(agora - o.inicio)} s",
                                f"Pico de {o.pico:.1f} °C · {ciclos} acima de {e.limite:.0f} °C")
        else:
            ultima = next((l for l in e.historico if l.tipo == "alta"), None)
            if ultima is None or ultima.ocorrencia.fim is None:
                detalhe = "Nenhuma ocorrência nesta sessão"
            else:
                detalhe = (f"Última terminou {tempo_relativo(agora - ultima.ocorrencia.fim)}, "
                           f"pico de {ultima.ocorrencia.pico:.1f} °C")
            self._pintar_cartao(self.cartao_alta, SUPERFICIE, VERDE, "Normal", detalhe)

        u = e.ultimo_aumento
        sessao = f"{e.n_aumentos} {'aumento' if e.n_aumentos == 1 else 'aumentos'} nesta sessão"
        if u is not None and agora - u.recebido_em <= AUMENTO_RECENTE:
            self._pintar_cartao(self.cartao_aumento, AMBAR_FUNDO, AMBAR, f"+{u.evento.diferenca:.1f} °C",
                                f"{tempo_relativo(agora - u.recebido_em).capitalize()} · "
                                f"{u.evento.anterior:.1f} → {u.evento.media:.1f} °C · {sessao}")
        elif u is not None:
            self._pintar_cartao(self.cartao_aumento, SUPERFICIE, TEXTO, "Estável",
                                f"Último {tempo_relativo(agora - u.recebido_em)} "
                                f"(+{u.evento.diferenca:.1f} °C) · {sessao}")
        else:
            self._pintar_cartao(self.cartao_aumento, SUPERFICIE, VERDE, "Estável",
                                "Nenhum aumento nesta sessão")

    def _sincronizar_tabela(self, agora: float) -> None:
        historico = self.estado.historico
        novas = []
        for linha in historico:
            if id(linha) in self.linhas_tabela:
                break
            novas.append(linha)
        for linha in reversed(novas):
            self.linhas_tabela[id(linha)] = self.tabela.insert("", 0, values=())
        for linha in historico:
            iid = self.linhas_tabela[id(linha)]
            if linha.tipo == "alta" or linha in novas:
                ativa = linha.tipo == "alta" and linha.ocorrencia is self.estado.alta_ativa
                self.tabela.item(iid, values=(linha.hora, linha.titulo, self.estado.detalhe(linha, agora)),
                                 tags=("ativa",) if ativa else (linha.tipo,))
        n = len(historico)
        self.lbl_contagem.configure(text="" if n == 0 else f"{n} {'registro' if n == 1 else 'registros'}")
        if n == 0:
            self.lbl_vazio.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.lbl_vazio.place_forget()

    def desenhar_grafico(self, agora: float | None = None) -> None:
        agora = time.time() if agora is None else agora
        c = self.grafico
        c.delete("all")
        largura, altura = c.winfo_width(), c.winfo_height()
        if largura < 50 or altura < 50:
            return
        esq, dir_, topo, base = 52, 16, 16, 30
        x0, x1, y0, y1 = esq, largura - dir_, topo, altura - base
        e = self.estado
        pontos = [p for p in e.pontos if p.ts >= agora - JANELA_GRAFICO]
        valores = [p.media for p in pontos] + [e.limite + 12, e.limite - 45]
        minimo = math.floor(min(valores) / 10) * 10
        maximo = math.ceil(max(valores) / 10) * 10

        def x(ts):
            return x0 + (ts - (agora - JANELA_GRAFICO)) / JANELA_GRAFICO * (x1 - x0)

        def y(valor):
            return y1 - (valor - minimo) / (maximo - minimo) * (y1 - y0)

        # zona acima do limite, grade e eixos
        c.create_rectangle(x0, y0, x1, y(e.limite), fill=VERMELHO_ZONA, outline="")
        passo = 10 if maximo - minimo <= 80 else 20
        for valor in range(int(minimo), int(maximo) + 1, passo):
            c.create_line(x0, y(valor), x1, y(valor), fill=LINHA_GRADE)
            c.create_text(x0 - 10, y(valor), text=f"{valor}", fill=TEXTO_SECUNDARIO, font=self.f_eixo, anchor="e")
        for minutos, rotulo in [(3, "−3 min"), (2, "−2 min"), (1, "−1 min"), (0, "agora")]:
            c.create_text(x(agora - 60 * minutos), y1 + 15, text=rotulo, fill=TEXTO_SECUNDARIO, font=self.f_eixo,
                          anchor="w" if minutos == 3 else ("e" if minutos == 0 else "center"))
        c.create_line(x0, y(e.limite), x1, y(e.limite), fill=VERMELHO, dash=(6, 4))
        c.create_text(x1 - 6, y(e.limite) - 9, text=f"limite {e.limite:.0f} °C", fill=VERMELHO,
                      font=self.f_eixo, anchor="e")

        # marcas dos aumentos repentinos
        for ts in e.marcas_aumento:
            if ts >= agora - JANELA_GRAFICO:
                xm = x(ts)
                c.create_line(xm, y0 + 10, xm, y1, fill=AMBAR, dash=(2, 4))
                c.create_polygon(xm - 6, y0, xm + 6, y0, xm, y0 + 9, fill=AMBAR, outline="")

        if not pontos:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Aguardando médias do CAT",
                          fill=TEXTO_SECUNDARIO, font=self.f_texto)
            return
        # linha da média, quebrada onde faltaram ciclos e vermelha acima do limite
        intervalo = max(e._intervalo, 1.0)
        for a, b in zip(pontos, pontos[1:]):
            if b.ts - a.ts > 3 * intervalo:
                continue
            cor = VERMELHO if max(a.media, b.media) > e.limite else TEXTO
            c.create_line(x(a.ts), y(a.media), x(b.ts), y(b.media), fill=cor, width=2.5, capstyle="round")
        ultimo = pontos[-1]
        cor = VERMELHO if ultimo.media > e.limite else TEXTO
        c.create_oval(x(ultimo.ts) - 4, y(ultimo.media) - 4, x(ultimo.ts) + 4, y(ultimo.media) + 4,
                      fill=cor, outline=SUPERFICIE, width=2)


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
        # Uma exceção aqui mataria o thread do paho; vira só um aviso.
        try:
            agora = time.time()
            if msg.topic == TOPICO_MEDIA:
                media = ler_media(msg.payload)
                if media is not None:
                    entregar("media", (*media, agora))
                return
            print(formatar_evento(msg.topic, msg.payload).linha_console)
            entregar("evento", (ler_evento(msg.topic, msg.payload), agora))
        except Exception as erro:
            print(f"[{hora()}] Erro ao tratar mensagem de {msg.topic}: {erro!r}")

    client = criar_cliente()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
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
