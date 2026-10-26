"""Texto, tipo e cor de cada alarme (lógica pura, sem rede nem Tkinter)."""

import json
import time
from typing import NamedTuple

CORES = {"temperatura-alta": "#c62828", "aumento-repentino": "#f9a825", "outro": "#757575"}
MAX_DETALHE = 200


class Alarme(NamedTuple):
    hora: str
    tipo: str
    detalhe: str
    cor: str
    linha_console: str


def _decodificar(payload: bytes):
    try:
        return json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None


def _hora(dados) -> str:
    ts = dados.get("ts") if isinstance(dados, dict) else None
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        try:
            return time.strftime("%H:%M:%S", time.localtime(ts))
        except (OverflowError, OSError, ValueError):  # NaN, infinito ou fora da faixa
            pass
    return time.strftime("%H:%M:%S")


def _detalhe_conhecido(tipo: str, dados) -> str | None:
    """Detalhe de um evento conhecido, ou None se o payload não tiver o formato esperado."""
    try:
        if tipo == "temperatura-alta":
            return f"média {dados['media_atual']:.1f} °C (limite {dados['limite']:g})"
        if tipo == "aumento-repentino":
            return (f"média {dados['media_atual']:.1f} °C "
                    f"(+{dados['diferenca']:.1f} °C desde {dados['media_anterior']:.1f} °C)")
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return None


def formatar_evento(topico: str, payload: bytes) -> Alarme:
    tipo = topico.rsplit("/", 1)[-1]
    dados = _decodificar(payload)
    hora = _hora(dados)
    detalhe = _detalhe_conhecido(tipo, dados)
    if detalhe is not None:
        tipo_exibido, cor = tipo.replace("-", " ").upper(), CORES[tipo]
    else:
        tipo_exibido, cor = f"OUTRO ({tipo})", CORES["outro"]
        detalhe = payload.decode("utf-8", errors="replace")[:MAX_DETALHE]
    return Alarme(hora, tipo_exibido, detalhe, cor, f"[{hora}] ALARME {tipo_exibido} — {detalhe}")


def formatar_media(payload: bytes) -> str | None:
    dados = _decodificar(payload)
    try:
        n = dados["n_sensores"]
        return f"Média atual: {dados['media']:.1f} °C ({n} {'sensor' if n == 1 else 'sensores'})"
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
