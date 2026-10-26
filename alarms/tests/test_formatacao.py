import json
import time

from formatacao import CORES, formatar_evento, formatar_media

TS = 1761490985.0
HORA = time.strftime("%H:%M:%S", time.localtime(TS))


def evento(**campos):
    return json.dumps({**campos, "ts": TS}).encode()


def test_temperatura_alta():
    a = formatar_evento("caldeira/eventos/temperatura-alta",
                        evento(tipo="temperatura-alta", media_atual=203.4, limite=200))
    assert (a.hora, a.tipo, a.detalhe, a.cor) == (
        HORA, "TEMPERATURA ALTA", "média 203.4 °C (limite 200)", CORES["temperatura-alta"])
    assert a.linha_console == f"[{HORA}] ALARME TEMPERATURA ALTA — média 203.4 °C (limite 200)"


def test_aumento_repentino():
    a = formatar_evento("caldeira/eventos/aumento-repentino",
                        evento(tipo="aumento-repentino", media_atual=180.2, media_anterior=170.1, diferenca=10.1))
    assert (a.tipo, a.detalhe, a.cor) == (
        "AUMENTO REPENTINO", "média 180.2 °C (+10.1 °C desde 170.1 °C)", CORES["aumento-repentino"])


def test_tipo_desconhecido_vira_outro():
    a = formatar_evento("caldeira/eventos/fogo", evento(tipo="fogo"))
    assert (a.tipo, a.cor) == ("OUTRO (fogo)", CORES["outro"]) and "fogo" in a.detalhe


def test_payload_malformado_vira_outro():
    a = formatar_evento("caldeira/eventos/temperatura-alta", b"\xffnao json")
    assert a.tipo == "OUTRO (temperatura-alta)" and a.cor == CORES["outro"]


def test_media():
    assert formatar_media(b'{"media": 187.5, "n_leituras": 6, "n_sensores": 3, "ts": 1}') == "Média atual: 187.5 °C (3 sensores)"
    assert formatar_media(b'{"media": 170.0, "n_leituras": 2, "n_sensores": 1, "ts": 1}') == "Média atual: 170.0 °C (1 sensor)"
    assert formatar_media(b"lixo") is None
