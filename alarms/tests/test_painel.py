import json

import pytest

from painel import EstadoPainel, duracao, ler_evento, ler_media, tempo_relativo


def alta(media, ts=1.0):
    return json.dumps({"tipo": "temperatura-alta", "media_atual": media, "limite": 200, "ts": ts}).encode()


def aumento(atual, anterior):
    return json.dumps({"tipo": "aumento-repentino", "media_atual": atual, "media_anterior": anterior,
                       "diferenca": round(atual - anterior, 1), "ts": 1.0}).encode()


TOPICO_ALTA = "caldeira/eventos/temperatura-alta"
TOPICO_AUMENTO = "caldeira/eventos/aumento-repentino"


def test_alta_repetida_vira_uma_ocorrencia_com_pico_e_contagem():
    p = EstadoPainel()
    for i, m in enumerate([202.0, 207.5, 205.0]):
        p.registrar_media(m, 3, 100.0 + 5 * i)
        p.registrar_evento(ler_evento(TOPICO_ALTA, alta(m)), 100.0 + 5 * i)
    assert len(p.historico) == 1
    linha = p.historico[0]
    assert (linha.tipo, linha.titulo) == ("alta", "TEMPERATURA ALTA")
    assert p.alta_ativa is not None
    assert (p.alta_ativa.pico, p.alta_ativa.contagem, p.alta_ativa.inicio) == (207.5, 3, 100.0)
    assert p.detalhe(linha, agora=110.0) == "pico 207.5 °C · 10 s · 3 ciclos · em andamento"


def test_media_abaixo_do_limite_encerra_a_ocorrencia():
    p = EstadoPainel()
    p.registrar_media(203.0, 3, 100.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, alta(203.0)), 100.0)
    p.registrar_media(170.0, 3, 105.0)
    assert p.alta_ativa is None
    p.registrar_media(204.0, 3, 110.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, alta(204.0)), 110.0)
    assert len(p.historico) == 2   # nova ocorrência, linha nova no topo
    assert p.detalhe(p.historico[1], agora=200.0) == "pico 203.0 °C · 5 s · 1 ciclo"


def test_aumentos_ficam_em_linhas_proprias_e_marcam_o_grafico():
    p = EstadoPainel()
    p.registrar_evento(ler_evento(TOPICO_AUMENTO, aumento(175.2, 169.8)), 40.0)
    p.registrar_evento(ler_evento(TOPICO_AUMENTO, aumento(183.2, 175.2)), 45.0)
    assert [l.tipo for l in p.historico] == ["aumento", "aumento"]
    assert p.detalhe(p.historico[0], agora=45.0) == "+8.0 °C (175.2 → 183.2 °C)"
    assert (p.n_aumentos, p.ultimo_aumento.recebido_em) == (2, 45.0)
    assert p.marcas_aumento == [40.0, 45.0]


def test_aumento_entre_altas_nao_quebra_a_ocorrencia():
    p = EstadoPainel()
    p.registrar_media(203.0, 3, 100.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, alta(203.0)), 100.0)
    p.registrar_evento(ler_evento(TOPICO_AUMENTO, aumento(203.0, 197.0)), 100.0)
    p.registrar_media(206.0, 3, 105.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, alta(206.0)), 105.0)
    assert [l.tipo for l in p.historico] == ["aumento", "alta"]
    assert p.alta_ativa.contagem == 2


def test_evento_desconhecido_ou_malformado_vira_outro():
    p = EstadoPainel()
    p.registrar_evento(ler_evento("caldeira/eventos/fogo", b'{"tipo": "fogo"}'), 1.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, b'{"media_atual": "x"}'), 2.0)
    assert [(l.tipo, l.titulo) for l in p.historico] == [
        ("outro", "OUTRO (temperatura-alta)"), ("outro", "OUTRO (fogo)")]
    assert p.alta_ativa is None


def test_grafico_guarda_so_os_ultimos_3_minutos():
    p = EstadoPainel()
    for ts in range(0, 400, 5):
        p.registrar_media(170.0, 1, float(ts))
    assert p.pontos[0].ts >= 395 - 180 and p.pontos[-1].ts == 395


def test_dados_parados_depois_de_tres_intervalos_sem_media():
    p = EstadoPainel()
    assert p.sem_dados(agora=0.0)               # nunca recebeu média
    p.registrar_media(170.0, 1, 100.0)
    p.registrar_media(170.0, 1, 105.0)          # intervalo observado: 5 s
    assert not p.sem_dados(agora=119.0)
    assert p.sem_dados(agora=121.0)


def test_limpar_apaga_historico_mas_mantem_ocorrencia_ativa():
    p = EstadoPainel()
    p.registrar_media(203.0, 3, 100.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, alta(203.0)), 100.0)
    p.limpar()
    assert p.historico == [] and p.n_aumentos == 0
    p.registrar_media(205.0, 3, 105.0)
    p.registrar_evento(ler_evento(TOPICO_ALTA, alta(205.0)), 105.0)
    assert len(p.historico) == 1 and p.alta_ativa.contagem == 2


@pytest.mark.parametrize("segundos, esperado", [
    (0, "agora"), (4.9, "agora"), (45, "há 45 s"), (59.9, "há 59 s"), (60, "há 1 min"), (3600 * 2, "há 120 min")])
def test_tempo_relativo(segundos, esperado):
    assert tempo_relativo(segundos) == esperado


@pytest.mark.parametrize("segundos, esperado", [(0, "0 s"), (45, "45 s"), (125, "2 min 05 s")])
def test_duracao(segundos, esperado):
    assert duracao(segundos) == esperado


def test_ler_media():
    assert ler_media(b'{"media": 187.5, "n_leituras": 6, "n_sensores": 3, "ts": 1}') == (187.5, 3)
    for ruim in [b"lixo", b'{"media": NaN, "n_sensores": 1}', b'{"media": 1' + b"0" * 400 + b', "n_sensores": 1}',
                 b'{"media": 170}', b'{"media": 170, "n_sensores": "3"}']:
        assert ler_media(ruim) is None
