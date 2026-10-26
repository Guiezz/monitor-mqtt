"""Lógica pura do CAT: janela deslizante, regras de evento e mensagens MQTT."""

import json
import math
import threading
from typing import NamedTuple

LIMIAR_AUMENTO = 5.0
LIMITE_ALTA = 200.0
TOPICO_MEDIA = "caldeira/cat/media"
PREFIXO_EVENTOS = "caldeira/eventos/"


class ResultadoMedia(NamedTuple):
    media: float
    n_leituras: int
    n_sensores: int


class Mensagem(NamedTuple):
    topico: str
    payload: str
    qos: int
    retain: bool


class JanelaTemperaturas:
    """Leituras recebidas nos últimos `window` segundos, de todos os sensores.

    O callback do paho adiciona leituras em outra thread, por isso o lock.
    """

    def __init__(self, window: float):
        self.window = window
        self._leituras: list[tuple[str, float, float]] = []
        self._lock = threading.Lock()

    def adicionar(self, sensor_id: str, temperatura: float, recebido_em: float) -> None:
        with self._lock:
            self._leituras.append((sensor_id, temperatura, recebido_em))

    def media(self, agora: float) -> ResultadoMedia | None:
        inicio = agora - self.window
        with self._lock:
            self._leituras = [l for l in self._leituras if l[2] > inicio]
            na_janela = [l for l in self._leituras if l[2] <= agora]
        if not na_janela:
            return None
        temperaturas = [t for _, t, _ in na_janela]
        return ResultadoMedia(
            sum(temperaturas) / len(temperaturas),
            len(na_janela),
            len({s for s, _, _ in na_janela}),
        )


def parse_leitura(payload: bytes) -> tuple[str, float] | None:
    """Extrai (sensor_id, temperatura) do payload, ou None se for inválido."""
    try:
        dados = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    sensor_id = dados.get("sensor_id")
    temperatura = dados.get("temperatura")
    if not isinstance(sensor_id, str) or not sensor_id:
        return None
    if isinstance(temperatura, bool) or not isinstance(temperatura, (int, float)):
        return None
    try:
        temperatura = float(temperatura)
    except OverflowError:  # inteiro JSON grande demais para float
        return None
    if not math.isfinite(temperatura):
        return None
    return sensor_id, temperatura


def avaliar(media_atual: float, media_anterior: float | None, agora: float) -> list[dict]:
    """Aplica as regras de aumento repentino e temperatura alta."""
    eventos = []
    if media_anterior is not None and media_atual - media_anterior >= LIMIAR_AUMENTO:
        eventos.append({
            "tipo": "aumento-repentino",
            "media_atual": round(media_atual, 1),
            "media_anterior": round(media_anterior, 1),
            "diferenca": round(media_atual - media_anterior, 1),
            "ts": agora,
        })
    if media_atual > LIMITE_ALTA:
        eventos.append({
            "tipo": "temperatura-alta",
            "media_atual": round(media_atual, 1),
            "limite": int(LIMITE_ALTA),
            "ts": agora,
        })
    return eventos


def processar_ciclo(janela: JanelaTemperaturas, media_anterior: float | None,
                    agora: float) -> tuple[ResultadoMedia | None, list[dict], float | None]:
    """Um ciclo do CAT. Devolve (resultado, eventos, nova média anterior).

    Com a janela vazia a média anterior é zerada, para que a retomada depois
    de uma interrupção não seja comparada com uma média antiga.
    """
    resultado = janela.media(agora)
    if resultado is None:
        return None, [], None
    return resultado, avaliar(resultado.media, media_anterior, agora), resultado.media


def montar_mensagens(resultado: ResultadoMedia, eventos: list[dict], agora: float) -> list[Mensagem]:
    """Mensagens a publicar no ciclo: a média (retida) e depois os eventos."""
    media = {
        "media": round(resultado.media, 1),
        "n_leituras": resultado.n_leituras,
        "n_sensores": resultado.n_sensores,
        "ts": agora,
    }
    mensagens = [Mensagem(TOPICO_MEDIA, json.dumps(media), 0, True)]
    for evento in eventos:
        mensagens.append(Mensagem(PREFIXO_EVENTOS + evento["tipo"], json.dumps(evento), 1, False))
    return mensagens
