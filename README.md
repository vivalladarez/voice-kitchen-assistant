# voice-kitchen-assistant

MVP de um assistente de voz para apoio ao preparo de receitas em uma cozinha conectada, integrando comandos por voz, respostas faladas e sensores simulados em ESP32.

## Arquitetura

```
Microfone do notebook
        ↓
Python reconhece comando
        ↓
Python responde por voz
        ↓
Python envia comando via MQTT
        ↓
ESP32 simulado no Wokwi
        ↓
OLED / LED / buzzer / sensor DHT22
```

## Estrutura

```
voice-kitchen-assistant/
├── assistant/
│   ├── main.py              # voz + respostas + MQTT
│   ├── requirements.txt
│   └── recipes.py           # passos da receita
├── controller/
│   ├── esp32_wokwi.ino      # controlador ESP32
│   ├── diagram.json         # circuito do Wokwi
│   ├── libraries.txt        # dependências Wokwi
│   └── wokwi.toml
└── README.md
```

## Comandos de voz

| Comando | Resposta | Ação MQTT |
|---------|----------|-----------|
| "começar receita" | "Vamos começar. Primeiro, aqueça a panela." | `start` |
| "próximo passo" | Próximo passo da receita | `next` |
| "temperatura" | "A temperatura atual é X graus." | — |
| temperatura > 40°C | "Cuidado, a panela está quente." | `alert` |

## Tecnologias

| Camada | Tecnologia |
|--------|------------|
| Assistente | Python, SpeechRecognition, pyttsx3 |
| Comunicação | MQTT (`test.mosquitto.org`) |
| Controlador | ESP32 (Wokwi) |
| Sensores | DHT22 (temperatura/umidade) |
| Feedback | OLED SSD1306, LED, buzzer |

## Como rodar

### 1. ESP32 no Wokwi

1. Abra [Wokwi](https://wokwi.com) e importe a pasta `controller/`.
2. Inicie a simulação — o ESP32 conecta ao Wi-Fi `Wokwi-GUEST` e publica temperatura a cada 5 s no tópico `kitchen/temperature`.

Para simular calor, clique no sensor DHT22 no diagrama e aumente a temperatura acima de 40°C.

### 2. Assistente Python

```bash
cd assistant
python -m venv .venv

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
python main.py
```

**Nota (Windows):** se `PyAudio` falhar na instalação, use:

```bash
pip install pipwin
pipwin install pyaudio
```

### 3. Testar sem microfone (MQTT manual)

Com a simulação Wokwi rodando:

```bash
mosquitto_sub -h test.mosquitto.org -t kitchen/temperature
mosquitto_pub -h test.mosquitto.org -t kitchen/command -m start
```

## Tópicos MQTT

| Tópico | Direção | Payload |
|--------|---------|---------|
| `kitchen/temperature` | ESP32 → Python | `{"temperature":28.0,"humidity":50.0}` |
| `kitchen/command` | Python → ESP32 | `start`, `next`, `alert` |
| `kitchen/status` | ESP32 → (monitor) | `{"status":"started","last_command":"start"}` |

## Receita de exemplo

A receita padrão é **Arroz simples**, com 6 passos definidos em `assistant/recipes.py`. Edite esse arquivo para trocar a receita ou os passos.
