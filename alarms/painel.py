"""Estado do painel do Alarms (lógica pura, sem rede nem Tkinter).

O CAT publica temperatura alta a cada ciclo enquanto a média passa do limite.
Aqui essas repetições viram uma única ocorrência, com pico, duração e contagem,
para que o histórico não enterre os aumentos repentinos.
"""

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

LIMITE_PADRAO = 200.0
JANELA_GRAFICO = 180.0       # segundos de média mostrados no gráfico
INTERVALO_PADRAO = 60.0      # usado até observar o intervalo real entre médias
CICLOS_SEM_DADOS = 3


class Ponto(NamedTuple):
    ts: float
    media: float


class Evento(NamedTuple):
    tipo: str                 # "alta", "aumento" ou "outro"
    nome: str                 # último segmento do tópico
    media: float | None = None
    anterior: float | None = None
    diferenca: float | None = None
    limite: float | None = None
    texto: str = ""


@dataclass
class Ocorrencia:
    inicio: float
    ultimo: float
    pico: float
    contagem: int = 1
    fim: float | None = None


@dataclass(eq=False)
class Linha:
    tipo: str
    titulo: str
    recebido_em: float
    evento: Evento
    ocorrencia: Ocorrencia | None = None

    @property
    def hora(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.recebido_em))


def _numero(valor) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    try:
        valor = float(valor)
    except OverflowError:
        return None
    return valor if math.isfinite(valor) else None


def ler_evento(topico: str, payload: bytes) -> Evento:
    """Interpreta um evento do CAT; qualquer formato inesperado vira "outro"."""
    nome = topico.rsplit("/", 1)[-1]
    texto = payload.decode("utf-8", errors="replace")[:200]
    try:
        dados = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        dados = None
    if isinstance(dados, dict):
        media = _numero(dados.get("media_atual"))
        if nome == "temperatura-alta" and media is not None:
            return Evento("alta", nome, media=media, limite=_numero(dados.get("limite")))
        anterior, diferenca = _numero(dados.get("media_anterior")), _numero(dados.get("diferenca"))
        if nome == "aumento-repentino" and None not in (media, anterior, diferenca):
            return Evento("aumento", nome, media=media, anterior=anterior, diferenca=diferenca)
    return Evento("outro", nome, texto=texto)


def ler_media(payload: bytes) -> tuple[float, int] | None:
    """(média, número de sensores) da mensagem retida do CAT, ou None se inválida."""
    try:
        dados = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    media, n = _numero(dados.get("media")), dados.get("n_sensores")
    if media is None or isinstance(n, bool) or not isinstance(n, int):
        return None
    return media, n


def tempo_relativo(segundos: float) -> str:
    if segundos < 5:
        return "agora"
    if segundos < 60:
        return f"há {int(segundos)} s"
    return f"há {int(segundos // 60)} min"


def duracao(segundos: float) -> str:
    segundos = int(segundos)
    if segundos < 60:
        return f"{segundos} s"
    return f"{segundos // 60} min {segundos % 60:02d} s"


@dataclass
class EstadoPainel:
    media: float | None = None
    n_sensores: int | None = None
    limite: float = LIMITE_PADRAO
    pontos: deque = field(default_factory=deque)
    historico: list = field(default_factory=list)       # mais recente primeiro
    alta_ativa: Ocorrencia | None = None
    ultimo_aumento: Linha | None = None
    n_aumentos: int = 0
    marcas_aumento: list = field(default_factory=list)
    _ultima_media_em: float | None = None
    _intervalo: float = INTERVALO_PADRAO
    _linha_alta: Linha | None = None

    def registrar_media(self, media: float, n_sensores: int, recebido_em: float) -> None:
        if self._ultima_media_em is not None and recebido_em > self._ultima_media_em:
            self._intervalo = recebido_em - self._ultima_media_em
        self._ultima_media_em = recebido_em
        self.media, self.n_sensores = media, n_sensores
        self.pontos.append(Ponto(recebido_em, media))
        corte = recebido_em - JANELA_GRAFICO
        while self.pontos and self.pontos[0].ts < corte:
            self.pontos.popleft()
        self.marcas_aumento = [ts for ts in self.marcas_aumento if ts >= corte]
        if self.alta_ativa is not None and media <= self.limite:
            self.alta_ativa.fim = recebido_em
            self.alta_ativa = None

    def registrar_evento(self, evento: Evento, recebido_em: float) -> None:
        if evento.tipo == "alta":
            self._registrar_alta(evento, recebido_em)
            return
        if evento.tipo == "aumento":
            linha = Linha("aumento", "AUMENTO REPENTINO", recebido_em, evento)
            self.ultimo_aumento = linha
            self.n_aumentos += 1
            self.marcas_aumento.append(recebido_em)
        else:
            linha = Linha("outro", f"OUTRO ({evento.nome})", recebido_em, evento)
        self.historico.insert(0, linha)

    def _registrar_alta(self, evento: Evento, recebido_em: float) -> None:
        if evento.limite is not None:
            self.limite = evento.limite
        ocorrencia = self.alta_ativa
        if ocorrencia is None:
            ocorrencia = self.alta_ativa = Ocorrencia(recebido_em, recebido_em, evento.media)
            self._linha_alta = None
        else:
            ocorrencia.ultimo = recebido_em
            ocorrencia.pico = max(ocorrencia.pico, evento.media)
            ocorrencia.contagem += 1
        if self._linha_alta is None or self._linha_alta not in self.historico:
            self._linha_alta = Linha("alta", "TEMPERATURA ALTA", recebido_em, evento, ocorrencia)
            self.historico.insert(0, self._linha_alta)

    def detalhe(self, linha: Linha, agora: float) -> str:
        if linha.tipo == "alta":
            o = linha.ocorrencia
            ativa = o is self.alta_ativa
            fim = agora if ativa else (o.fim if o.fim is not None else o.ultimo)
            partes = [f"pico {o.pico:.1f} °C", duracao(fim - o.inicio),
                      f"{o.contagem} {'ciclo' if o.contagem == 1 else 'ciclos'}"]
            if ativa:
                partes.append("em andamento")
            return " · ".join(partes)
        e = linha.evento
        if linha.tipo == "aumento":
            return f"+{e.diferenca:.1f} °C ({e.anterior:.1f} → {e.media:.1f} °C)"
        return e.texto

    def sem_dados(self, agora: float) -> bool:
        if self._ultima_media_em is None:
            return True
        return agora - self._ultima_media_em > CICLOS_SEM_DADOS * self._intervalo

    def limpar(self) -> None:
        self.historico = []
        self.ultimo_aumento = None
        self.n_aumentos = 0
        self.marcas_aumento = []
