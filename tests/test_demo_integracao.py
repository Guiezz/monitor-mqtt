"""Cenário demo passando pelo core do CAT, sem broker.

Único lugar do repositório que importa código de dois projetos.
"""

import pytest

from cenarios import temperatura_demo
from core import JanelaTemperaturas, processar_ciclo


def simular(defasagens, duracao=240.0, intervalo=5.0, janela=10.0):
    """Sensores publicam em defasagem + k*intervalo; o CAT roda em 0,5 + k*intervalo."""
    publicacoes = sorted((d + k * intervalo, f"s{i}")
                         for i, d in enumerate(defasagens) for k in range(int(duracao / intervalo)))
    j, anterior, eventos, p = JanelaTemperaturas(janela), None, [], 0
    for k in range(int(duracao / intervalo)):
        agora = 0.5 + k * intervalo
        while p < len(publicacoes) and publicacoes[p][0] <= agora:
            ts, sid = publicacoes[p]
            j.adicionar(sid, temperatura_demo(ts), ts)
            p += 1
        _, novos, anterior = processar_ciclo(j, anterior, agora)
        eventos += [(agora % 120, e["tipo"]) for e in novos]
    return eventos


@pytest.mark.parametrize("defasagens", [(0, 0, 0), (0, 1.7, 3.4)])
def test_demo_dispara_os_dois_alarmes(defasagens):
    eventos = simular(defasagens)
    assert {tipo for _, tipo in eventos} == {"aumento-repentino", "temperatura-alta"}
    assert all(40 <= t <= 55 for t, tipo in eventos if tipo == "aumento-repentino")
    # A primeira ocorrência em ordem cronológica; ao voltar a 170° a média
    # ainda pode ficar acima de 200 por um ciclo, o que também é correto.
    assert 55 <= next(t for t, tipo in eventos if tipo == "temperatura-alta") <= 75
