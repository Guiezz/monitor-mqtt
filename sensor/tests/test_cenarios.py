import random

import pytest

from cenarios import proximo_normal, temperatura_demo


@pytest.mark.parametrize("t, esperado", [
    (0, 170.0), (39.99, 170.0),               # patamar inicial
    (40, 190.0), (50, 196.0),                 # salto e rampa de 0,6 °C/s
    (73.4, 210.0), (119.9, 210.0),            # patamar alto
    (120, 170.0), (120 * 1000 + 45, 193.0),   # repete a cada 120 s
])
def test_curva_demo(t, esperado):
    assert temperatura_demo(t) == pytest.approx(esperado)


def test_normal_fica_nos_limites_com_passos_pequenos():
    rng, atual = random.Random(42), 170.0
    for _ in range(10_000):
        novo = proximo_normal(atual, rng)
        assert 165.0 <= novo <= 180.0
        assert abs(novo - atual) <= 1.5
        atual = novo
