import os
import signal
import socket
import subprocess
import sys
import time

from cat import criar_cliente, conectar_com_retry, resolver_janela


def test_janela_padrao_e_o_dobro_do_intervalo():
    assert resolver_janela(60, None) == 120
    assert resolver_janela(5, None) == 10
    assert resolver_janela(5, 30) == 30


class ClienteFalho:
    def __init__(self, falhas):
        self.falhas, self.tentativas = falhas, 0

    def connect(self, host, port):
        self.tentativas += 1
        if self.tentativas <= self.falhas:
            raise ConnectionRefusedError


def test_conectar_tenta_ate_conseguir():
    cliente, esperas = ClienteFalho(2), []
    conectar_com_retry(cliente, "localhost", 1883, dormir=esperas.append)
    assert cliente.tentativas == 3 and esperas == [2.0, 2.0]


def porta_livre():
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def test_ctrl_c_sem_broker_sai_sem_traceback():
    script = os.path.join(os.path.dirname(__file__), "..", "cat.py")
    p = subprocess.Popen([sys.executable, script, "--port", str(porta_livre())],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"},
                         preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    time.sleep(1.0)
    p.send_signal(signal.SIGINT)
    saida, _ = p.communicate(timeout=5)
    assert "Broker indisponível" in saida
    assert "Traceback" not in saida and p.returncode == 0


def test_duas_instancias_tem_client_id_diferente():
    # Com o mesmo client id, o broker derruba uma instância a cada conexão da outra.
    assert criar_cliente()._client_id != criar_cliente()._client_id
