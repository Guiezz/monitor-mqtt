import json
import os
import signal
import socket
import subprocess
import sys
import time

import pytest

from sensor import conectar_com_retry, criar_parser, montar_payload


def test_payload_arredonda_temperatura():
    assert json.loads(montar_payload("s1", 187.46, 1.5)) == {"sensor_id": "s1", "temperatura": 187.5, "ts": 1.5}


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


@pytest.mark.parametrize("ident", ["a/b", "s+", "#", ""])
def test_id_invalido_e_recusado(ident):
    with pytest.raises(SystemExit):
        criar_parser().parse_args(["--id", ident])


def test_padroes(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "broker.local")
    args = criar_parser().parse_args(["--id", "s1"])
    assert (args.interval, args.scenario, args.host, args.port) == (60.0, "normal", "broker.local", 1883)


def porta_livre():
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def test_ctrl_c_sem_broker_sai_sem_traceback():
    script = os.path.join(os.path.dirname(__file__), "..", "sensor.py")
    p = subprocess.Popen([sys.executable, script, "--id", "s1", "--port", str(porta_livre())],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"},
                         preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    time.sleep(1.0)
    p.send_signal(signal.SIGINT)
    saida, _ = p.communicate(timeout=5)
    assert "Broker indisponível" in saida
    assert "Traceback" not in saida and p.returncode == 0
