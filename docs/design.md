# Monitor MQTT — Design

Data: 2026-10-26 · Caminho: arquitetural · Status: seções 1 a 5 aprovadas; aguardando revisão do documento escrito.

## Objetivo
Sensores simulados de temperatura de uma caldeira publicam leituras num broker MQTT. O serviço CAT calcula a média dos últimos 120 s e publica eventos. O serviço Alarms exibe esses eventos numa interface gráfica. Meta: nota máxima (3 pts), incluindo interface gráfica (+0,5) e vídeo de demonstração (1 pt).

## Decisões já tomadas
- **Stack:** Python + paho-mqtt 2.x + Mosquitto, em 3 projetos separados (sensor, cat, alarms).
- **Interface do Alarms:** Tkinter (janela desktop, sem dependência extra), com saída no console também.
- **Demonstração:** cada sensor tem `--interval` (padrão 60 s; 5 s na demo) e `--scenario normal|demo`. No cenário demo a temperatura sobe de forma abrupta e depois gradual, passando de 200°, para disparar os dois alarmes de forma repetível.
- **Cálculo no CAT (abordagem A):** janela deslizante global, avaliada por relógio a cada ciclo (igual ao intervalo dos sensores). A média atual é comparada com a do ciclo anterior.
- **Janela proporcional:** a janela padrão é `2 × interval` (120 s com o intervalo padrão de 60 s, como no enunciado). Na demo, `--interval 5` gera janela de 10 s, mantendo a proporção. Com janela fixa de 120 s e leituras a cada 5 s, a média mudaria devagar demais para disparar o aumento repentino.
- **Sem `common/`:** cada projeto repete as poucas constantes de que precisa (tópicos, broker). Os três projetos são de fato independentes.
- **Eventos sem retain:** evita que o Alarms reexiba alarmes antigos ao reiniciar.

## Seção 1 — Arquitetura e estrutura (aprovada)

```
monitor-mqtt/
├── sensor/     sensor.py (rede/CLI), cenarios.py (curvas puras), tests/, requirements.txt
├── cat/        cat.py (rede/CLI), core.py (janela, média, regras), tests/, requirements.txt
├── alarms/     alarms.py (rede/CLI/Tkinter), formatacao.py (texto dos alarmes), tests/, requirements.txt
├── tests/      teste de integração do cenário demo (sem broker)
├── docs/       enunciado, design, plano
└── README.md   como rodar + link do vídeo
```

Fluxo:

```
sensor(s) -> caldeira/sensores/<id>/temperatura -> [Mosquitto] -> CAT
Alarms <- caldeira/eventos/aumento-repentino <- CAT
       <- caldeira/eventos/temperatura-alta  <- CAT
       <- caldeira/cat/media                 <- CAT
```

| Unidade | Faz | Depende de |
|---|---|---|
| sensor | Publica uma leitura simulada a cada `--interval` s. Uma instância = um processo; mais terminais = mais sensores. | Broker |
| cat | Assina `caldeira/sensores/+/temperatura`, guarda leituras e, a cada ciclo, calcula a média da janela. Publica a média e os eventos. | Broker |
| alarms | Assina `caldeira/eventos/#` e `caldeira/cat/media`; mostra cada alarme na janela Tkinter e no console. | Broker |

Isolamento:
- Os três só se comunicam via MQTT, sem importar código uns dos outros. A única exceção é o teste de integração em `tests/`, que importa `sensor/cenarios.py` e `cat/core.py` para validar a demo sem broker.
- Em cada projeto, a lógica pura fica separada do código de rede (paho), para testar sem broker.
- No Alarms, o callback MQTT roda em outra thread e entrega os alarmes à interface por uma `queue` (Tkinter não é thread-safe).
- Broker por argumento (`--host`, `--port`) ou variável de ambiente (`MQTT_HOST`, `MQTT_PORT`), padrão `localhost:1883`.

## Contrato MQTT

| Tópico | Quem publica | QoS | Retain | Payload (JSON) |
|---|---|---|---|---|
| `caldeira/sensores/<id>/temperatura` | sensor | 1 | não | `{"sensor_id": "s1", "temperatura": 187.4, "ts": 1761490000.0}` |
| `caldeira/cat/media` | CAT | 0 | sim | `{"media": 187.5, "n_leituras": 6, "n_sensores": 3, "ts": ...}` |
| `caldeira/eventos/aumento-repentino` | CAT | 1 | não | `{"tipo": "aumento-repentino", "media_atual": 180.2, "media_anterior": 170.1, "diferenca": 10.1, "ts": ...}` |
| `caldeira/eventos/temperatura-alta` | CAT | 1 | não | `{"tipo": "temperatura-alta", "media_atual": 203.4, "limite": 200, "ts": ...}` |

- `temperatura` e as médias são arredondadas para 1 casa decimal no payload; os cálculos usam o valor completo.
- `ts` é epoch em segundos (float).

## Seção 2 — Sensor (aprovada)

**Argumentos:** `--id` (obrigatório), `--interval` (padrão 60), `--scenario normal|demo` (padrão `normal`), `--host`, `--port`.

**Cenário normal:** passeio aleatório em torno de 170°, com passos pequenos (até ±1,5° por leitura), limitado ao intervalo [165°, 180°]. Todos os sensores usam a mesma base, então a entrada ou saída de um sensor mexe pouco na média e não gera aumento repentino falso.

**Cenário demo:** curva definida pelo relógio, `t = time.time() % 120`, igual para todos os sensores. Assim os sensores ficam sincronizados, não importa quando cada um foi iniciado.

| Trecho de `t` | Temperatura | Efeito esperado no CAT |
|---|---|---|
| 0 s ≤ t < 40 s | 170° | médias estáveis |
| t = 40 s | salto para 190° | média sobe ~25° em até 3 ciclos (os sensores não publicam no mesmo instante), então pelo menos um ciclo sobe ≥ 8° → **aumento repentino** |
| 40 s ≤ t < 73,3 s | `190 + 0,6 × (t − 40)` | sobe ~3° por ciclo de 5 s (sem alarme); média passa de 200° por volta de t ≈ 62 s → **temperatura alta** |
| 73,3 s ≤ t < 120 s | 210° | temperatura alta a cada ciclo |
| t volta a 0 | 170° | queda não gera alarme |

Sobre a curva soma-se um ruído uniforme de ±0,5°. A curva é a função pura `temperatura_demo(t)` em `cenarios.py`; o ruído é aplicado fora dela, para a função ser testável de forma determinística.

**Publicação:** a cada `--interval` s, publica no tópico do sensor (contrato acima) e imprime a leitura no console.

## Seção 3 — CAT (aprovada)

**Argumentos:** `--interval` (padrão 60), `--window` (padrão `2 × interval`), `--host`, `--port`.

**Código:**
- `core.py` (puro, sem paho):
  - `JanelaTemperaturas(window)`: `adicionar(sensor_id, temperatura, recebido_em)` e `media(agora)`, que descarta leituras fora de `(agora − window, agora]` e devolve média, número de leituras e número de sensores distintos (ou `None` se a janela estiver vazia). Protegida por lock, pois o callback do paho roda em outra thread.
  - `avaliar(media_atual, media_anterior) -> list[dict]`: aplica as duas regras e devolve os eventos a publicar.
- `cat.py`: argumentos, conexão, assinatura, laço de ciclos e publicação.

**Horário da leitura:** a janela usa o horário em que o CAT recebeu a mensagem, não o `ts` do payload. Isso evita problemas com relógios diferentes entre máquinas.

**Ciclo (a cada `--interval` s):**
1. Calcula a média da janela.
2. Janela vazia: imprime "sem leituras na janela", zera a média anterior (para não comparar depois de uma interrupção) e não publica nada.
3. Publica `caldeira/cat/media` e imprime a média no console.
4. **Aumento repentino:** se existe média anterior e `media_atual − media_anterior >= 5`. Só conta subida.
5. **Temperatura alta:** se `media_atual > 200`. É publicada em todo ciclo enquanto a média ficar acima do limite.
6. Guarda a média atual como anterior.

**Payload inválido** (JSON malformado, campo ausente ou temperatura não numérica): imprime um aviso e ignora a mensagem.

## Seção 4 — Alarms (aprovada)

**Argumentos:** `--host`, `--port`, `--no-gui` (só console).

**Assinaturas:** `caldeira/eventos/#` (QoS 1) e `caldeira/cat/media` (QoS 0).

**Janela Tkinter, de cima para baixo:**
1. Barra de status: broker conectado/desconectado e média atual com o número de sensores.
2. Faixa com o último alarme, na cor do tipo.
3. Tabela (`ttk.Treeview`) com as colunas Hora, Tipo e Detalhe, mais recentes no topo.
4. Botão "Limpar" no rodapé.

**Cores:** temperatura alta em vermelho; aumento repentino em âmbar; qualquer outro tópico em `caldeira/eventos/` aparece em cinza como "outro" (deixa espaço para fogo e vazamento, citados no enunciado).

**Threads:** o callback do paho coloca as mensagens numa `queue.Queue`; a interface lê a fila a cada 100 ms com `root.after`.

**Console:** todo alarme também é impresso, por exemplo:
`[14:03:05] ALARME TEMPERATURA ALTA — média 203.4 °C (limite 200)`

**Código:** `formatacao.py` (puro) monta o texto, o tipo exibido e a cor de cada evento; `alarms.py` cuida de rede, fila e Tkinter.

## Seção 5 — Testes, erros e vídeo (aprovada)

**Testes (pytest, sem broker):**
- `cat/tests`: expiração da janela; janela vazia; contagem de sensores distintos; primeira média sem aumento repentino; diferença exatamente 5 dispara; queda não dispara; média exatamente 200 não dispara e 200,1 dispara.
- `sensor/tests`: pontos da curva `temperatura_demo` (patamares, salto em 40 s, rampa, retorno a 170°); limites do cenário normal.
- `alarms/tests`: texto, tipo e cor de cada evento, incluindo tipo desconhecido.
- `tests/` (integração): simula 3 sensores do cenário demo com intervalo 5 s, janela 10 s e horários de publicação defasados entre si (pior caso), passando as leituras pelo `core` do CAT, e confirma que **os dois alarmes disparam** num ciclo de 120 s.
- A interface Tkinter é verificada manualmente.

**Erros e conexão:**
- Broker fora do ar na inicialização: nova tentativa a cada 2 s, com aviso no console.
- Queda durante a execução: reconexão automática do paho (`reconnect_delay_set(1, 10)`); assinaturas refeitas em `on_connect`; o Alarms mostra "desconectado" enquanto isso.
- Ctrl+C encerra cada processo de forma limpa (desconecta e para o loop).
- Usar a API 2.x do paho: `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)`.

**Ambiente:** um venv único na raiz para desenvolver; cada projeto mantém seu `requirements.txt` com `paho-mqtt>=2,<3` (e `pytest` só para desenvolvimento). Broker local com `mosquitto -v`.

**Roteiro do vídeo (~2 min, gravado com Cmd+Shift+5):**
1. Terminais abertos: `mosquitto -v`; Alarms (janela); `cat.py --interval 5`; três sensores com `--interval 5 --scenario demo`.
2. Mostrar as leituras chegando e as médias no console do CAT.
3. Em t ≈ 40 s do ciclo, o aumento repentino aparece em âmbar.
4. Em t ≈ 62 s, a temperatura alta aparece em vermelho.
5. Encerrar um sensor e mostrar `n_sensores` caindo; o CAT continua calculando.
6. Subir o vídeo no repositório do GitHub, com link no README.
