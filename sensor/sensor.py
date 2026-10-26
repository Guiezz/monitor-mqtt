"""Sensor de temperatura simulado: publica uma leitura a cada --interval segundos."""

import argparse
import json
import os
import random
import sys
import time

import paho.mqtt.client as mqtt

from cenarios import TEMPERATURA_BASE, proximo_normal, temperatura_demo

TOPICO_LEITURA = "caldeira/sensores/{id}/temperatura"
RUIDO_DEMO = 0.5


def montar_payload(sensor_id: str, temperatura: float, ts: float) -> str:
    return json.dumps({"sensor_id": sensor_id, "temperatura": round(temperatura, 1), "ts": ts})


def validar_id(valor: str) -> str:
    if not valor or any(c in valor for c in "/+#"):
        raise argparse.ArgumentTypeError("o id não pode ser vazio nem conter '/', '+' ou '#'")
    return valor


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sensor de temperatura simulado da caldeira.")
    parser.add_argument("--id", required=True, type=validar_id, help="identificador do sensor, ex.: s1")
    parser.add_argument("--interval", type=float, default=60.0, help="segundos entre leituras (padrão 60)")
    parser.add_argument("--scenario", choices=["normal", "demo"], default="normal")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    return parser


def conectar_com_retry(client, host: str, port: int, espera: float = 2.0, dormir=time.sleep) -> None:
    while True:
        try:
            client.connect(host, port)
            return
        except OSError:
            print(f"Broker indisponível em {host}:{port}, tentando de novo em {espera:g} s...")
            dormir(espera)


def hora() -> str:
    return time.strftime("%H:%M:%S")


def main(argv=None) -> None:
    args = criar_parser().parse_args(argv)
    topico = TOPICO_LEITURA.format(id=args.id)
    rng = random.Random()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sensor-{args.id}")
    client.on_connect = lambda c, u, f, rc, p: print(f"[{hora()}] conectado ao broker ({rc})")
    client.on_disconnect = lambda c, u, f, rc, p: print(f"[{hora()}] desconectado do broker ({rc})")
    client.reconnect_delay_set(1, 10)
    try:
        conectar_com_retry(client, args.host, args.port)
        client.loop_start()
        print(f"Sensor {args.id}: cenário {args.scenario}, uma leitura a cada {args.interval:g} s em {topico}")
        temperatura = TEMPERATURA_BASE
        proxima = time.monotonic()
        while True:
            agora = time.time()
            if args.scenario == "demo":
                temperatura = temperatura_demo(agora) + rng.uniform(-RUIDO_DEMO, RUIDO_DEMO)
            else:
                temperatura = proximo_normal(temperatura, rng)
            client.publish(topico, montar_payload(args.id, temperatura, agora), qos=1, retain=False)
            print(f"[{hora()}] {args.id} -> {temperatura:.1f} °C")
            proxima += args.interval
            time.sleep(max(0.0, proxima - time.monotonic()))
    except KeyboardInterrupt:
        print(f"\nSensor {args.id} encerrado.")
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    sys.exit(main())
