# Monitor MQTT — Plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development ou superpowers:executing-plans para executar este plano tarefa por tarefa. Os passos usam checkbox (`- [ ]`) para acompanhamento.

**Objetivo:** sensores simulados, serviço CAT e serviço Alarms (Tkinter) comunicando por MQTT, prontos para gravar o vídeo de entrega.

**Arquitetura:** três projetos Python independentes (`sensor/`, `cat/`, `alarms/`) que só conversam pelo Mosquitto. Em cada projeto a lógica pura fica num módulo próprio, testado sem broker; o arquivo principal só cuida de argumentos, rede e saída.

**Stack:** Python 3.14 (código compatível com ≥ 3.10), paho-mqtt 2.x, Mosquitto, Tkinter, pytest.

**Spec:** [docs/design.md](design.md) — leia junto com este plano.

## Restrições globais

- `paho-mqtt>=2,<3`, sempre com `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)`.
- Nenhum projeto importa código de outro. Exceção: `tests/test_demo_integracao.py`.
- Tópicos, QoS, retain e payloads exatamente como na tabela "Contrato MQTT" do design.
- Broker: `--host`/`--port`, senão `MQTT_HOST`/`MQTT_PORT`, senão `localhost:1883`.
- `--interval` padrão 60; no CAT, `--window` padrão `2 × interval`.
- Aumento repentino: `media_atual − media_anterior >= 5` (só subida, só com média anterior). Temperatura alta: `media_atual > 200`.
- Valores arredondados a 1 casa decimal só no payload; comparações usam o valor completo.
- Saídas de console e textos da interface em PT-BR.
- Interface só com Tkinter (biblioteca padrão), sem dependências extras.
- Mensagens de commit terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Foco de revisão

1. **Temperatura não finita ou não numérica** (`NaN`, `Infinity`, `"187"`, `true`) publicada por qualquer cliente → o CAT ignora com aviso. Sem isso, um `NaN` contamina a média por dois ciclos. Teste: Tarefa 2, `test_parse_leitura_invalida`.
2. **Todos os sensores param e depois voltam** → o CAT não publica com janela vazia e não dispara aumento repentino ao retomar. Teste: Tarefa 2, `test_retorno_apos_interrupcao_nao_gera_aumento`.
3. **Evento malformado ou de tipo desconhecido** chegando ao Alarms → aparece como "OUTRO" e a interface não cai. Teste: Tarefa 6, `test_payload_malformado_vira_outro`.
4. **Broker fora do ar ao iniciar** → o processo tenta de novo a cada 2 s em vez de encerrar. Teste: Tarefa 4, `test_conectar_tenta_ate_conseguir` (copiado nas Tarefas 5 e 7).
5. **`--id` com `/`, `+` ou `#`** → o sensor recusa o argumento em vez de publicar num tópico errado ou inválido. Teste: Tarefa 4, `test_id_invalido_e_recusado`.

---

### Tarefa 1: Repositório, ambiente de testes e curvas do sensor

**Arquivos:**
- Criar: `.gitignore`, `pytest.ini`, `requirements-dev.txt`
- Criar: `sensor/cenarios.py`
- Teste: `sensor/tests/test_cenarios.py`

**Interfaces:**
- Produz: `TEMPERATURA_BASE: float = 170.0`, `PERIODO_DEMO: float = 120.0`, `temperatura_demo(t: float) -> float` (sem ruído; aplica `t % PERIODO_DEMO` internamente), `proximo_normal(atual: float, rng: random.Random) -> float`.

- [ ] **Passo 1: preparar o repositório e o ambiente**

```bash
git init
printf '.venv/\n__pycache__/\n.pytest_cache/\n*.mp4\n' > .gitignore
printf 'pytest>=8\n' > requirements-dev.txt
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

O `*.mp4` fica no `.gitignore` até a Tarefa 8, que decide como o vídeo entra no repositório.

`pytest.ini`:

```ini
[pytest]
pythonpath = sensor cat alarms
testpaths = sensor/tests cat/tests alarms/tests tests
addopts = --import-mode=importlib
```

- [ ] **Passo 2: escrever os testes que falham**

```python
import random
import pytest
from cenarios import temperatura_demo, proximo_normal

@pytest.mark.parametrize("t, esperado", [
    (0, 170.0), (39.99, 170.0),      # patamar inicial
    (40, 190.0), (50, 196.0),        # salto e rampa de 0,6 °C/s
    (73.4, 210.0), (119.9, 210.0),   # patamar alto
    (120, 170.0), (120 * 1000 + 45, 193.0),  # repete a cada 120 s
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
```

- [ ] **Passo 3:** rodar `.venv/bin/pytest sensor/tests/test_cenarios.py -v`. Esperado: FAIL (`ModuleNotFoundError: cenarios`).
- [ ] **Passo 4: implementar `sensor/cenarios.py`.** A rampa é `min(210, 190 + 0.6 * (t - 40))` para `40 ≤ t < 120`. `proximo_normal` soma `rng.uniform(-1.5, 1.5)` e limita o resultado a [165, 180].
- [ ] **Passo 5:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 6:** commit dos arquivos criados e de `docs/` (`feat(sensor): curvas de temperatura normal e demo`).

---

### Tarefa 2: Lógica pura do CAT

**Arquivos:**
- Criar: `cat/core.py`
- Teste: `cat/tests/test_core.py`

**Interfaces:**
- Produz:
  - `ResultadoMedia(NamedTuple)`: `media: float`, `n_leituras: int`, `n_sensores: int`.
  - `Mensagem(NamedTuple)`: `topico: str`, `payload: str`, `qos: int`, `retain: bool`.
  - `JanelaTemperaturas(window: float)` com `adicionar(sensor_id: str, temperatura: float, recebido_em: float) -> None` e `media(agora: float) -> ResultadoMedia | None`. Mantém só as leituras em `(agora − window, agora]` e usa `threading.Lock`.
  - `parse_leitura(payload: bytes) -> tuple[str, float] | None`.
  - `avaliar(media_atual: float, media_anterior: float | None, agora: float) -> list[dict]`. Os eventos usam os campos do contrato, com `ts = agora`.
  - `processar_ciclo(janela, media_anterior: float | None, agora: float) -> tuple[ResultadoMedia | None, list[dict], float | None]`. O terceiro valor é a nova média anterior (`None` se a janela estiver vazia).
  - `montar_mensagens(resultado: ResultadoMedia, eventos: list[dict], agora: float) -> list[Mensagem]`. A média vem primeiro, depois os eventos na ordem recebida.
  - Constantes: `LIMIAR_AUMENTO = 5.0`, `LIMITE_ALTA = 200.0`, `TOPICO_MEDIA = "caldeira/cat/media"`, `PREFIXO_EVENTOS = "caldeira/eventos/"`.

- [ ] **Passo 1: escrever os testes que falham**

```python
import json
import pytest
from core import (JanelaTemperaturas, ResultadoMedia, Mensagem, parse_leitura,
                  avaliar, processar_ciclo, montar_mensagens)

def test_media_das_leituras_na_janela():
    j = JanelaTemperaturas(10)
    j.adicionar("s1", 170.0, 100.0); j.adicionar("s2", 180.0, 104.0)
    assert j.media(105.0) == ResultadoMedia(175.0, 2, 2)

def test_leitura_no_limite_inferior_expira():
    j = JanelaTemperaturas(10)
    j.adicionar("s1", 170.0, 100.0); j.adicionar("s1", 190.0, 105.0)
    assert j.media(110.0) == ResultadoMedia(190.0, 1, 1)

def test_janela_vazia():
    assert JanelaTemperaturas(10).media(0.0) is None

def test_conta_sensores_distintos():
    j = JanelaTemperaturas(10)
    for s, ts in [("s1", 1.0), ("s1", 2.0), ("s2", 3.0)]:
        j.adicionar(s, 170.0, ts)
    assert j.media(3.0) == ResultadoMedia(170.0, 3, 2)

def test_parse_leitura_valida():
    assert parse_leitura(b'{"sensor_id": "s1", "temperatura": 187.4, "ts": 1}') == ("s1", 187.4)
    assert parse_leitura(b'{"sensor_id": "s1", "temperatura": 170, "ts": 1}') == ("s1", 170.0)

@pytest.mark.parametrize("payload", [
    b"nao e json", b"\xff", b"[1, 2]", b'{"temperatura": 1}',
    b'{"sensor_id": "s1", "temperatura": "187"}', b'{"sensor_id": "s1", "temperatura": true}',
    b'{"sensor_id": "s1", "temperatura": NaN}', b'{"sensor_id": "s1", "temperatura": Infinity}',
    b'{"sensor_id": "", "temperatura": 170}',
])
def test_parse_leitura_invalida(payload):
    assert parse_leitura(payload) is None

def test_primeira_media_nao_gera_aumento():
    assert avaliar(180.0, None, 0.0) == []
    assert [e["tipo"] for e in avaliar(250.0, None, 0.0)] == ["temperatura-alta"]

def test_diferenca_exatamente_5_dispara():
    assert avaliar(175.0, 170.0, 1.0) == [{"tipo": "aumento-repentino", "media_atual": 175.0,
        "media_anterior": 170.0, "diferenca": 5.0, "ts": 1.0}]

def test_abaixo_de_5_ou_queda_nao_dispara():
    assert avaliar(174.96, 170.0, 0.0) == []   # arredonda para 5.0, mas não atinge 5
    assert avaliar(160.0, 170.0, 0.0) == []

def test_limite_200():
    assert avaliar(200.0, 200.0, 0.0) == []
    assert avaliar(200.1, 200.0, 0.0) == [{"tipo": "temperatura-alta", "media_atual": 200.1,
        "limite": 200, "ts": 0.0}]

def test_ciclo_com_janela_vazia_zera_anterior():
    assert processar_ciclo(JanelaTemperaturas(10), 170.0, 50.0) == (None, [], None)

def test_retorno_apos_interrupcao_nao_gera_aumento():
    j = JanelaTemperaturas(10)
    _, _, anterior = processar_ciclo(j, 170.0, 50.0)
    j.adicionar("s1", 190.0, 55.0)
    resultado, eventos, anterior = processar_ciclo(j, anterior, 56.0)
    assert resultado == ResultadoMedia(190.0, 1, 1) and eventos == [] and anterior == 190.0

def test_mensagens_media_retida_e_eventos_nao():
    eventos = avaliar(203.44, 197.0, 9.0)
    msgs = montar_mensagens(ResultadoMedia(203.44, 6, 3), eventos, 9.0)
    assert [(m.topico, m.qos, m.retain) for m in msgs] == [
        ("caldeira/cat/media", 0, True),
        ("caldeira/eventos/aumento-repentino", 1, False),
        ("caldeira/eventos/temperatura-alta", 1, False)]
    assert json.loads(msgs[0].payload) == {"media": 203.4, "n_leituras": 6, "n_sensores": 3, "ts": 9.0}
```

- [ ] **Passo 2:** rodar `.venv/bin/pytest cat/tests/test_core.py -v`. Esperado: FAIL (`ModuleNotFoundError: core`).
- [ ] **Passo 3: implementar `cat/core.py`.** `parse_leitura` rejeita `bool`, valores não finitos (`math.isfinite`), `sensor_id` que não seja `str` não vazia e qualquer exceção de decodificação. Em `avaliar`, a regra de aumento vem antes da de temperatura alta. Os campos `media_atual`, `media_anterior` e `diferenca` são arredondados com `round(x, 1)` só depois de comparar.
- [ ] **Passo 4:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 5:** commit (`feat(cat): janela deslizante, regras e mensagens`).

---

### Tarefa 3: Teste de integração do cenário demo

**Arquivos:**
- Teste: `tests/test_demo_integracao.py`

**Interfaces:**
- Consome: `temperatura_demo` (Tarefa 1); `JanelaTemperaturas` e `processar_ciclo` (Tarefa 2).

- [ ] **Passo 1: escrever o teste**

```python
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
            j.adicionar(sid, temperatura_demo(ts), ts); p += 1
        _, novos, anterior = processar_ciclo(j, anterior, agora)
        eventos += [(agora % 120, e["tipo"]) for e in novos]
    return eventos

@pytest.mark.parametrize("defasagens", [(0, 0, 0), (0, 1.7, 3.4)])
def test_demo_dispara_os_dois_alarmes(defasagens):
    eventos = simular(defasagens)
    assert {tipo for _, tipo in eventos} == {"aumento-repentino", "temperatura-alta"}
    assert all(40 <= t <= 55 for t, tipo in eventos if tipo == "aumento-repentino")
    assert 55 <= min(t for t, tipo in eventos if tipo == "temperatura-alta") <= 75
```

- [ ] **Passo 2:** rodar `.venv/bin/pytest tests/ -v`. Esperado: PASS nos dois casos. Se falhar, a curva ou a janela está errada: corrija a Tarefa 1 ou 2, não o teste.
- [ ] **Passo 3:** commit (`test: integração do cenário demo sem broker`).

---

### Tarefa 4: Processo do sensor

**Arquivos:**
- Criar: `sensor/sensor.py`, `sensor/requirements.txt` (`paho-mqtt>=2,<3`)
- Teste: `sensor/tests/test_sensor.py`

**Interfaces:**
- Consome: `TEMPERATURA_BASE`, `temperatura_demo` e `proximo_normal` (Tarefa 1).
- Produz (padrão copiado nas Tarefas 5 e 7):
  - `conectar_com_retry(client, host: str, port: int, espera: float = 2.0, dormir=time.sleep) -> None`: tenta `client.connect`; em caso de `OSError`, imprime `Broker indisponível em {host}:{port}, tentando de novo em 2 s...` e tenta de novo.
  - `criar_parser() -> argparse.ArgumentParser`.
- Produz (só do sensor): `montar_payload(sensor_id: str, temperatura: float, ts: float) -> str` e `validar_id(valor: str) -> str` (usado como `type=` do `--id`; lança `argparse.ArgumentTypeError` se o valor estiver vazio ou contiver `/`, `+` ou `#`).

- [ ] **Passo 1: escrever os testes que falham**

```python
import json
import pytest
from sensor import montar_payload, conectar_com_retry, criar_parser

def test_payload_arredonda_temperatura():
    assert json.loads(montar_payload("s1", 187.46, 1.5)) == {"sensor_id": "s1", "temperatura": 187.5, "ts": 1.5}

class ClienteFalho:
    def __init__(self, falhas): self.falhas, self.tentativas = falhas, 0
    def connect(self, host, port):
        self.tentativas += 1
        if self.tentativas <= self.falhas: raise ConnectionRefusedError

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
```

- [ ] **Passo 2:** instalar o paho com `.venv/bin/pip install -r sensor/requirements.txt` e rodar `.venv/bin/pytest sensor/tests/test_sensor.py -v`. Esperado: FAIL (`ModuleNotFoundError: sensor`).
- [ ] **Passo 3: implementar `sensor/sensor.py`.**
  - O padrão de `--host`/`--port` vem do ambiente no momento de criar o parser.
  - `main()` cria o cliente, chama `reconnect_delay_set(1, 10)`, `conectar_com_retry` e `loop_start()`.
  - Publica uma leitura imediatamente e depois a cada `--interval` s, com QoS 1 e sem retain, no tópico `caldeira/sensores/{id}/temperatura`.
  - Valor no cenário demo: `temperatura_demo(time.time()) + rng.uniform(-0.5, 0.5)`. No normal: `proximo_normal`, começando em `TEMPERATURA_BASE`.
  - Imprime `[HH:MM:SS] s1 -> 187.4 °C` a cada envio.
  - Ctrl+C chama `loop_stop()` e `disconnect()` e sai sem traceback.
- [ ] **Passo 4:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 5: verificação manual com broker.** Instale com `brew install mosquitto` e rode `mosquitto -v` num terminal e `mosquitto_sub -t 'caldeira/#' -v` em outro. Depois rode `.venv/bin/python sensor/sensor.py --id s1 --interval 2 --scenario demo`. Esperado: leituras JSON chegando no `mosquitto_sub`. Pare o broker com o sensor rodando e suba de novo: o sensor volta a publicar sozinho. Inicie o sensor com o broker parado: aparece o aviso a cada 2 s.
- [ ] **Passo 6:** commit (`feat(sensor): processo publicador com cenários normal e demo`).

---

### Tarefa 5: Processo do CAT

**Arquivos:**
- Criar: `cat/cat.py`, `cat/requirements.txt` (`paho-mqtt>=2,<3`)
- Teste: `cat/tests/test_cat.py`

**Interfaces:**
- Consome: tudo de `core` (Tarefa 2). Copia o padrão de `conectar_com_retry` (Tarefa 4).
- Produz: `resolver_janela(interval: float, window: float | None) -> float` e `criar_parser()` (`--interval` padrão 60, `--window` padrão `None`, `--host`, `--port`).

- [ ] **Passo 1: escrever os testes que falham**

```python
from cat import resolver_janela, conectar_com_retry

def test_janela_padrao_e_o_dobro_do_intervalo():
    assert resolver_janela(60, None) == 120
    assert resolver_janela(5, None) == 10
    assert resolver_janela(5, 30) == 30
```

Mais o mesmo `test_conectar_tenta_ate_conseguir` da Tarefa 4, importando de `cat`.

- [ ] **Passo 2:** rodar `.venv/bin/pytest cat/tests/test_cat.py -v`. Esperado: FAIL.
- [ ] **Passo 3: implementar `cat/cat.py`.**
  - Conexão e encerramento como no sensor (Tarefa 4): `reconnect_delay_set(1, 10)`, `conectar_com_retry`, `loop_start()`; Ctrl+C sai sem traceback.
  - `on_connect` assina `caldeira/sensores/+/temperatura` com QoS 1 (por isso a assinatura é refeita a cada reconexão).
  - `on_message` chama `parse_leitura`. Se o resultado for `None`, imprime `Leitura inválida em {topico}: {payload!r}`. Se for válido, faz `janela.adicionar(sensor_id, temperatura, time.time())`.
  - O laço principal roda a cada `--interval` s: `processar_ciclo` e, havendo média, `montar_mensagens` e `publish` de cada `Mensagem`.
  - Console por ciclo: `[HH:MM:SS] média 187.5 °C (6 leituras, 3 sensores)`, `[HH:MM:SS] sem leituras na janela` ou `[HH:MM:SS] EVENTO temperatura-alta: média 203.4 °C`.
  - Na inicialização, imprime o intervalo e a janela em uso.
- [ ] **Passo 4:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 5: verificação manual.** Rode o broker, `mosquitto_sub -t 'caldeira/#' -v`, `.venv/bin/python cat/cat.py --interval 5` e dois sensores com `--interval 5 --scenario demo`. Esperado: médias a cada 5 s; o aumento repentino perto de t≈40 s do ciclo; a temperatura alta a partir de t≈60 s. Pare os sensores: aparece "sem leituras na janela" e o CAT não publica. Mande `mosquitto_pub -t caldeira/sensores/x/temperatura -m '{"sensor_id":"x","temperatura":NaN}'`: aparece o aviso de leitura inválida e a média não muda.
- [ ] **Passo 6:** commit (`feat(cat): serviço de média e eventos`).

---

### Tarefa 6: Formatação dos alarmes

**Arquivos:**
- Criar: `alarms/formatacao.py`
- Teste: `alarms/tests/test_formatacao.py`

**Interfaces:**
- Produz:
  - `Alarme(NamedTuple)`: `hora: str`, `tipo: str`, `detalhe: str`, `cor: str`, `linha_console: str`.
  - `formatar_evento(topico: str, payload: bytes) -> Alarme`. O tipo vem do último segmento do tópico. A hora é `time.strftime("%H:%M:%S", time.localtime(ts))`, ou a hora atual se não houver `ts`.
  - `formatar_media(payload: bytes) -> str | None`.
  - `CORES = {"temperatura-alta": "#c62828", "aumento-repentino": "#f9a825", "outro": "#757575"}`.

- [ ] **Passo 1: escrever os testes que falham**

```python
import json, time
from formatacao import formatar_evento, formatar_media, CORES

TS = 1761490985.0
HORA = time.strftime("%H:%M:%S", time.localtime(TS))

def evento(**campos): return json.dumps({**campos, "ts": TS}).encode()

def test_temperatura_alta():
    a = formatar_evento("caldeira/eventos/temperatura-alta",
                        evento(tipo="temperatura-alta", media_atual=203.4, limite=200))
    assert (a.hora, a.tipo, a.detalhe, a.cor) == (HORA, "TEMPERATURA ALTA", "média 203.4 °C (limite 200)", CORES["temperatura-alta"])
    assert a.linha_console == f"[{HORA}] ALARME TEMPERATURA ALTA — média 203.4 °C (limite 200)"

def test_aumento_repentino():
    a = formatar_evento("caldeira/eventos/aumento-repentino",
                        evento(tipo="aumento-repentino", media_atual=180.2, media_anterior=170.1, diferenca=10.1))
    assert (a.tipo, a.detalhe, a.cor) == ("AUMENTO REPENTINO", "média 180.2 °C (+10.1 °C desde 170.1 °C)", CORES["aumento-repentino"])

def test_tipo_desconhecido_vira_outro():
    a = formatar_evento("caldeira/eventos/fogo", evento(tipo="fogo"))
    assert (a.tipo, a.cor) == ("OUTRO (fogo)", CORES["outro"]) and "fogo" in a.detalhe

def test_payload_malformado_vira_outro():
    a = formatar_evento("caldeira/eventos/temperatura-alta", b"\xffnao json")
    assert a.tipo == "OUTRO (temperatura-alta)" and a.cor == CORES["outro"]

def test_media():
    assert formatar_media(b'{"media": 187.5, "n_leituras": 6, "n_sensores": 3, "ts": 1}') == "Média atual: 187.5 °C (3 sensores)"
    assert formatar_media(b'{"media": 170.0, "n_leituras": 2, "n_sensores": 1, "ts": 1}') == "Média atual: 170.0 °C (1 sensor)"
    assert formatar_media(b"lixo") is None
```

- [ ] **Passo 2:** rodar `.venv/bin/pytest alarms/tests/test_formatacao.py -v`. Esperado: FAIL.
- [ ] **Passo 3: implementar `alarms/formatacao.py`.** Um evento conhecido com payload malformado (sem os campos esperados) cai no caminho "outro". Nesse caminho, o detalhe é o payload decodificado com `errors="replace"`, cortado em 200 caracteres.
- [ ] **Passo 4:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 5:** commit (`feat(alarms): formatação de eventos e média`).

---

### Tarefa 7: Processo do Alarms (console e Tkinter)

**Arquivos:**
- Criar: `alarms/alarms.py`, `alarms/requirements.txt` (`paho-mqtt>=2,<3`)
- Teste: `alarms/tests/test_alarms.py`

**Interfaces:**
- Consome: `formatar_evento`, `formatar_media` e `Alarme` (Tarefa 6). Copia o padrão de `conectar_com_retry` (Tarefa 4).
- Produz: `criar_parser()` (`--host`, `--port`, `--no-gui`).

- [ ] **Passo 1: escrever os testes que falham.** Copie `test_conectar_tenta_ate_conseguir` importando de `alarms` e acrescente:

```python
from alarms import criar_parser

def test_no_gui():
    assert criar_parser().parse_args(["--no-gui"]).no_gui is True
    assert criar_parser().parse_args([]).no_gui is False
```

- [ ] **Passo 2:** rodar `.venv/bin/pytest alarms/tests/test_alarms.py -v`. Esperado: FAIL.
- [ ] **Passo 3: implementar `alarms/alarms.py`.**
  - Conexão como no sensor (Tarefa 4): `reconnect_delay_set(1, 10)`, `conectar_com_retry`, `loop_start()`; Ctrl+C sai sem traceback.
  - `on_connect` assina `caldeira/eventos/#` com QoS 1 e `caldeira/cat/media` com QoS 0.
  - Os callbacks colocam na `queue.Queue` tuplas `("evento", Alarme)`, `("media", str)` e `("conexao", bool)` (esta vem de `on_connect`/`on_disconnect`).
  - Todo alarme sai no console via `print(alarme.linha_console)`.
  - Com `--no-gui`, a thread principal só espera Ctrl+C.
  - Sem `--no-gui`, a janela tem o título `Alarms — Caldeira` e o layout da seção 4 do design.
  - A tabela é um `Treeview` com colunas Hora, Tipo e Detalhe. Cada linha recebe uma `tag` com a cor de fundo do alarme e entra com `insert("", 0, ...)`, ficando no topo.
  - A faixa do último alarme usa a cor do tipo. O botão "Limpar" apaga a tabela e a faixa.
  - A fila é lida a cada 100 ms com `root.after`.
  - Fechar a janela chama `loop_stop()` e `disconnect()`.
- [ ] **Passo 4:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 5: verificação manual.** Com o broker, o CAT e dois sensores demo rodando (`--interval 5`), abra `.venv/bin/python alarms/alarms.py`. Esperado: a média aparece no topo logo ao abrir (vem retida); depois surge um alarme âmbar e em seguida linhas vermelhas, também no console. Teste também:
  - `mosquitto_pub -t caldeira/eventos/fogo -m 'qualquer coisa'` → linha cinza "OUTRO (fogo)".
  - Parar e subir o broker → o status alterna entre desconectado e conectado, e os alarmes voltam a chegar.
  - Reabrir o Alarms → alarmes antigos não reaparecem.
  - `--no-gui` → só o console.
- [ ] **Passo 6:** commit (`feat(alarms): interface Tkinter e console`).

---

### Tarefa 8: README e ensaio do vídeo

**Arquivos:**
- Criar: `README.md`

- [ ] **Passo 1: escrever o `README.md`.**
  - Descrição curta e diagrama de tópicos (copiado do design).
  - Pré-requisitos: Python ≥ 3.10 e Mosquitto.
  - Instalação: venv e os três `requirements.txt`.
  - Um comando por processo para a demo, na ordem do roteiro da seção 5 do design.
  - Como rodar os testes (`.venv/bin/pytest`).
  - Explicação da janela proporcional e da regra "só subida" do aumento repentino.
  - Espaço para o link do vídeo.
- [ ] **Passo 2:** rodar `.venv/bin/pytest -v`. Esperado: tudo PASS.
- [ ] **Passo 3: ensaio completo.** Siga o roteiro do design com três sensores demo e cronometre um ciclo de 120 s. Esperado: os dois alarmes aparecem na janela. Ao encerrar um sensor, `n_sensores` cai para 2.
- [ ] **Passo 4:** commit (`docs: README com instruções e demo`).
- [ ] **Passo 5 (usuário):** gravar o vídeo (Cmd+Shift+5) e publicar o repositório no GitHub com o link no README.
  - Se o arquivo tiver até 100 MB, tire `*.mp4` do `.gitignore` e faça commit do vídeo.
  - Se for maior, anexe a uma Release e coloque o link no README.
