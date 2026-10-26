# Monitor MQTT — Caldeira

Sensores simulados de temperatura de uma caldeira publicam leituras num broker MQTT (Mosquitto). O serviço **CAT** calcula a média das leituras recentes e publica eventos; o serviço **Alarms** mostra esses eventos numa janela Tkinter e no console.

**Vídeo da demonstração:** _(link a adicionar)_

## Arquitetura

Três projetos independentes, que só conversam pelo broker:

```
sensor(s) -> caldeira/sensores/<id>/temperatura -> [Mosquitto] -> CAT
Alarms <- caldeira/eventos/aumento-repentino <- CAT
       <- caldeira/eventos/temperatura-alta  <- CAT
       <- caldeira/cat/media                 <- CAT
```

| Projeto | Faz |
|---|---|
| `sensor/` | Publica uma leitura a cada `--interval` s. Cada processo é um sensor; abra mais terminais para ter mais sensores. |
| `cat/` | Calcula a média de todas as leituras da janela a cada ciclo e publica a média e os eventos. |
| `alarms/` | Mostra os alarmes numa janela (ou só no console, com `--no-gui`). |

Regras do CAT:
- **Aumento repentino:** a média atual é pelo menos 5 °C maior que a do ciclo anterior. Só conta subida, porque o evento é de *aumento*.
- **Temperatura alta:** a média passa de 200 °C. O evento se repete a cada ciclo enquanto a média ficar acima do limite.

Detalhes de projeto em [docs/design.md](docs/design.md).

## Pré-requisitos

- Python 3.10 ou mais novo (com Tkinter, já incluso no instalador do python.org)
- Mosquitto: `brew install mosquitto` no macOS

## Instalação

```bash
python3 -m venv .venv
.venv/bin/pip install -r sensor/requirements.txt -r cat/requirements.txt -r alarms/requirements.txt -r requirements-dev.txt
```

## Executando a demonstração

Cada comando num terminal separado, nesta ordem:

```bash
/opt/homebrew/sbin/mosquitto -v
```

```bash
.venv/bin/python alarms/alarms.py
```

```bash
.venv/bin/python cat/cat.py --interval 5
```

```bash
.venv/bin/python sensor/sensor.py --id s1 --interval 5 --scenario demo
```

Repita o último comando com `--id s2` e `--id s3`.

O cenário `demo` segue o relógio e se repete a cada 2 minutos, igual para todos os sensores:

| Segundos do ciclo (`hora % 120`) | Temperatura | O que aparece |
|---|---|---|
| 0–40 | 170 °C | médias estáveis |
| 40 | salta para 190 °C | **aumento repentino** (âmbar) |
| 40–73 | sobe 0,6 °C/s até 210 °C | **temperatura alta** (vermelho) a partir de ~60 s |
| 73–120 | 210 °C | temperatura alta a cada ciclo |

Encerre um sensor com Ctrl+C e o número de sensores na média cai em até ~15 s (2 a 3 ciclos), quando as últimas leituras dele saem da janela.

### Por que `--interval 5` e não 60?

O enunciado pede leituras a cada 60 s e janela de 120 s. A janela do CAT é sempre **2 × o intervalo**: com o padrão de 60 s, ela tem os 120 s pedidos. Na demo, `--interval 5` gera janela de 10 s, com a mesma proporção. Com janela fixa de 120 s e leituras a cada 5 s, a média mudaria devagar demais para disparar o aumento repentino. A janela também pode ser definida à mão com `--window`.

### Opções

| Processo | Opções |
|---|---|
| sensor | `--id` (obrigatório), `--interval` (60), `--scenario normal\|demo` (normal) |
| cat | `--interval` (60), `--window` (2 × interval) |
| alarms | `--no-gui` |
| todos | `--host`, `--port`, ou as variáveis `MQTT_HOST` e `MQTT_PORT` (padrão `localhost:1883`) |

Se o broker não estiver no ar, cada processo tenta de novo a cada 2 s. Se ele cair durante a execução, a reconexão é automática.

## Testes

```bash
.venv/bin/pytest
```

Os testes não precisam de broker. O teste de integração em `tests/` passa a curva do cenário demo de três sensores pela lógica do CAT e confirma que os dois alarmes disparam.
