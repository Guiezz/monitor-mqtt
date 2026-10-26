"""Serviço CAT: média das temperaturas da janela e eventos de alarme."""

import argparse
import os
import sys
import time
import uuid

import paho.mqtt.client as mqtt

from core import JanelaTemperaturas, montar_mensagens, parse_leitura, processar_ciclo

TOPICO_LEITURAS = "caldeira/sensores/+/temperatura"


def resolver_janela(interval: float, window: float | None) -> float:
    return 2 * interval if window is None else window


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CAT: calcula a média das temperaturas e publica eventos.")
    parser.add_argument("--interval", type=float, default=60.0, help="segundos entre ciclos (padrão 60)")
    parser.add_argument("--window", type=float, default=None, help="janela em segundos (padrão 2 × interval)")
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


def criar_cliente() -> mqtt.Client:
    # Id único por processo: com ids iguais o broker derruba uma instância a cada conexão da outra.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"cat-{uuid.uuid4().hex[:8]}")
    client.reconnect_delay_set(1, 10)
    return client


def hora() -> str:
    return time.strftime("%H:%M:%S")


def main(argv=None) -> None:
    args = criar_parser().parse_args(argv)
    janela = JanelaTemperaturas(resolver_janela(args.interval, args.window))

    def on_connect(client, userdata, flags, rc, properties):
        print(f"[{hora()}] conectado ao broker ({rc})")
        client.subscribe(TOPICO_LEITURAS, qos=1)

    def on_message(client, userdata, msg):
        # Uma exceção aqui mataria o thread do paho; vira só um aviso.
        try:
            leitura = parse_leitura(msg.payload)
            if leitura is None:
                print(f"[{hora()}] Leitura inválida em {msg.topic}: {msg.payload!r}")
                return
            janela.adicionar(*leitura, time.time())
        except Exception as erro:
            print(f"[{hora()}] Erro ao tratar mensagem de {msg.topic}: {erro!r}")

    client = criar_cliente()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = lambda c, u, f, rc, p: print(f"[{hora()}] desconectado do broker ({rc})")
    try:
        conectar_com_retry(client, args.host, args.port)
        client.loop_start()
        print(f"CAT: ciclo a cada {args.interval:g} s, janela de {janela.window:g} s")
        media_anterior = None
        proximo = time.monotonic() + args.interval
        while True:
            time.sleep(max(0.0, proximo - time.monotonic()))
            proximo += args.interval
            agora = time.time()
            resultado, eventos, media_anterior = processar_ciclo(janela, media_anterior, agora)
            if resultado is None:
                print(f"[{hora()}] sem leituras na janela")
                continue
            for m in montar_mensagens(resultado, eventos, agora):
                client.publish(m.topico, m.payload, qos=m.qos, retain=m.retain)
            print(f"[{hora()}] média {resultado.media:.1f} °C "
                  f"({resultado.n_leituras} leituras, {resultado.n_sensores} sensores)")
            for e in eventos:
                print(f"[{hora()}] EVENTO {e['tipo']}: média {e['media_atual']:.1f} °C")
    except KeyboardInterrupt:
        print("\nCAT encerrado.")
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    sys.exit(main())
