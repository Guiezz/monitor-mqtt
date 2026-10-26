"""Curvas de temperatura simuladas (lógica pura, sem rede)."""

import random

TEMPERATURA_BASE = 170.0
PERIODO_DEMO = 120.0

LIMITE_INFERIOR_NORMAL = 165.0
LIMITE_SUPERIOR_NORMAL = 180.0
PASSO_MAXIMO_NORMAL = 1.5


def temperatura_demo(t: float) -> float:
    """Temperatura do cenário demo no instante t (epoch), sem ruído.

    O ciclo se repete a cada PERIODO_DEMO segundos, então todos os sensores
    ficam sincronizados pelo relógio da máquina.
    """
    t = t % PERIODO_DEMO
    if t < 40:
        return 170.0
    return min(210.0, 190.0 + 0.6 * (t - 40))


def proximo_normal(atual: float, rng: random.Random) -> float:
    """Próxima leitura do cenário normal: passeio aleatório limitado."""
    novo = atual + rng.uniform(-PASSO_MAXIMO_NORMAL, PASSO_MAXIMO_NORMAL)
    return max(LIMITE_INFERIOR_NORMAL, min(LIMITE_SUPERIOR_NORMAL, novo))
