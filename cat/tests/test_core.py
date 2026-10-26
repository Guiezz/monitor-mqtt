import json

import pytest

from core import (JanelaTemperaturas, ResultadoMedia, avaliar, montar_mensagens,
                  parse_leitura, processar_ciclo)


def test_media_das_leituras_na_janela():
    j = JanelaTemperaturas(10)
    j.adicionar("s1", 170.0, 100.0)
    j.adicionar("s2", 180.0, 104.0)
    assert j.media(105.0) == ResultadoMedia(175.0, 2, 2)


def test_leitura_no_limite_inferior_expira():
    j = JanelaTemperaturas(10)
    j.adicionar("s1", 170.0, 100.0)
    j.adicionar("s1", 190.0, 105.0)
    assert j.media(110.0) == ResultadoMedia(190.0, 1, 1)


def test_janela_vazia():
    assert JanelaTemperaturas(10).media(0.0) is None


def test_conta_sensores_distintos():
    j = JanelaTemperaturas(10)
    for s, ts in [("s1", 1.0), ("s1", 2.0), ("s2", 3.0)]:
        j.adicionar(s, 170.0, ts)
    assert j.media(3.0) == ResultadoMedia(170.0, 3, 2)


def test_parse_leitura_valida():
    assert parse_leitura(b'{"sensor_id": "s1", "temperatura": 187.4, "ts": 1}') == ("s1", 187.4)
    assert parse_leitura(b'{"sensor_id": "s1", "temperatura": 170, "ts": 1}') == ("s1", 170.0)


@pytest.mark.parametrize("payload", [
    b"nao e json", b"\xff", b"[1, 2]", b'{"temperatura": 1}',
    b'{"sensor_id": "s1", "temperatura": "187"}', b'{"sensor_id": "s1", "temperatura": true}',
    b'{"sensor_id": "s1", "temperatura": NaN}', b'{"sensor_id": "s1", "temperatura": Infinity}',
    b'{"sensor_id": "", "temperatura": 170}',
])
def test_parse_leitura_invalida(payload):
    assert parse_leitura(payload) is None


def test_primeira_media_nao_gera_aumento():
    assert avaliar(180.0, None, 0.0) == []
    assert [e["tipo"] for e in avaliar(250.0, None, 0.0)] == ["temperatura-alta"]


def test_diferenca_exatamente_5_dispara():
    assert avaliar(175.0, 170.0, 1.0) == [{
        "tipo": "aumento-repentino", "media_atual": 175.0,
        "media_anterior": 170.0, "diferenca": 5.0, "ts": 1.0}]


def test_abaixo_de_5_ou_queda_nao_dispara():
    assert avaliar(174.96, 170.0, 0.0) == []   # arredonda para 5.0, mas não atinge 5
    assert avaliar(160.0, 170.0, 0.0) == []


def test_limite_200():
    assert avaliar(200.0, 200.0, 0.0) == []
    assert avaliar(200.1, 200.0, 0.0) == [{
        "tipo": "temperatura-alta", "media_atual": 200.1, "limite": 200, "ts": 0.0}]


def test_ciclo_com_janela_vazia_zera_anterior():
    assert processar_ciclo(JanelaTemperaturas(10), 170.0, 50.0) == (None, [], None)


def test_retorno_apos_interrupcao_nao_gera_aumento():
    j = JanelaTemperaturas(10)
    _, _, anterior = processar_ciclo(j, 170.0, 50.0)
    j.adicionar("s1", 190.0, 55.0)
    resultado, eventos, anterior = processar_ciclo(j, anterior, 56.0)
    assert resultado == ResultadoMedia(190.0, 1, 1) and eventos == [] and anterior == 190.0


def test_mensagens_media_retida_e_eventos_nao():
    eventos = avaliar(203.44, 197.0, 9.0)
    msgs = montar_mensagens(ResultadoMedia(203.44, 6, 3), eventos, 9.0)
    assert [(m.topico, m.qos, m.retain) for m in msgs] == [
        ("caldeira/cat/media", 0, True),
        ("caldeira/eventos/aumento-repentino", 1, False),
        ("caldeira/eventos/temperatura-alta", 1, False)]
    assert json.loads(msgs[0].payload) == {"media": 203.4, "n_leituras": 6, "n_sensores": 3, "ts": 9.0}
