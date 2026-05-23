"""
Assistente de voz para preparo de receitas — MVP.

Escuta comandos pelo microfone, responde por voz e envia ações ao ESP32 via MQTT.
"""

import argparse
import json
import os
import threading
import time

import paho.mqtt.client as mqtt
import pyttsx3
import speech_recognition as sr

from recipes import RECIPE, TEMP_WARNING_C, TEMP_WARNING_MSG

TOPIC_TEMP = "kitchen/temperature"
TOPIC_CMD = "kitchen/command"

# Brokers públicos (algumas redes bloqueiam test.mosquitto.org na porta 1883)
MQTT_BROKERS = [
    (os.environ.get("MQTT_BROKER", "test.mosquitto.org"), int(os.environ.get("MQTT_PORT", "1883"))),
    ("broker.hivemq.com", 1883),
    ("mqtt.eclipseprojects.io", 1883),
]

COMMANDS = {
    "começar receita": "start",
    "começar a receita": "start",
    "comecar receita": "start",
    "comecar a receita": "start",
    "iniciar receita": "start",
    "próximo passo": "next",
    "proximo passo": "next",
    "temperatura": "temperature",
    "qual a temperatura": "temperature",
}

DEMO_START_TEMP = 32.0
DEMO_TEMP_STEP = 4.0
DEMO_TEMP_INTERVAL_S = 8


class KitchenAssistant:
    def __init__(self, *, mqtt_enabled: bool = True, demo: bool = False) -> None:
        self.tts = pyttsx3.init()
        self.tts.setProperty("rate", 160)

        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        self.current_step = -1
        self.last_temperature: float | None = None
        self._temp_warned = False
        self._lock = threading.Lock()
        self.demo = demo

        self.mqtt_enabled = mqtt_enabled and not demo
        self.mqtt_connected = False
        self.mqtt: mqtt.Client | None = None
        self._mqtt_stop = threading.Event()

        if demo:
            print("Modo demo — sensor simulado, sem Wokwi/MQTT.")
            threading.Thread(target=self._demo_sensor_loop, daemon=True).start()
        elif mqtt_enabled:
            self._setup_mqtt()
        else:
            print("MQTT desabilitado — assistente só com voz e receita.")

    def _demo_sensor_loop(self) -> None:
        temp = DEMO_START_TEMP
        while True:
            with self._lock:
                self.last_temperature = temp
                should_warn = temp > TEMP_WARNING_C and not self._temp_warned
                if should_warn:
                    self._temp_warned = True

            print(f"Sensor demo: {temp:.0f}°C")
            if should_warn:
                threading.Thread(target=self._handle_hot_pan, daemon=True).start()

            time.sleep(DEMO_TEMP_INTERVAL_S)
            temp += DEMO_TEMP_STEP

    def _setup_mqtt(self) -> None:
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.loop_start()
        threading.Thread(target=self._mqtt_connect_loop, daemon=True).start()

    def _mqtt_connect_loop(self) -> None:
        while not self._mqtt_stop.is_set():
            if self.mqtt is None:
                return
            if self.mqtt_connected:
                time.sleep(2)
                continue

            for host, port in MQTT_BROKERS:
                if self._mqtt_stop.is_set():
                    return
                print(f"MQTT: tentando {host}:{port}...")
                try:
                    self.mqtt.connect_async(host, port, keepalive=60)
                except OSError as exc:
                    print(f"MQTT: falha em {host}:{port} — {exc}")
                    continue

                for _ in range(30):
                    if self.mqtt_connected:
                        print(f"MQTT conectado em {host}:{port}")
                        return
                    time.sleep(0.2)

                try:
                    self.mqtt.disconnect()
                except OSError:
                    pass
                self.mqtt_connected = False

            print("MQTT: sem conexão. Nova tentativa em 10 s...")
            time.sleep(10)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self.mqtt_connected = True
            client.subscribe(TOPIC_TEMP)
            print(f"MQTT conectado — inscrito em {TOPIC_TEMP}")
        else:
            self.mqtt_connected = False
            print(f"MQTT falhou: {reason_code}")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            data = json.loads(msg.payload.decode())
            temp = float(data["temperature"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return

        with self._lock:
            self.last_temperature = temp

            if temp > TEMP_WARNING_C and not self._temp_warned:
                self._temp_warned = True
                threading.Thread(
                    target=self._handle_hot_pan, daemon=True
                ).start()

    def _handle_hot_pan(self) -> None:
        self.speak(TEMP_WARNING_MSG)
        self.publish_command("alert")

    def speak(self, text: str) -> None:
        print(f"Assistente: {text}")
        self.tts.say(text)
        self.tts.runAndWait()

    def publish_command(self, cmd: str) -> None:
        if not self.mqtt_enabled or self.mqtt is None:
            return
        if not self.mqtt_connected:
            print(f"MQTT offline — comando não enviado: {cmd}")
            return
        self.mqtt.publish(TOPIC_CMD, cmd)
        print(f"MQTT → {TOPIC_CMD}: {cmd}")

    def listen(self) -> str | None:
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print("Ouvindo...")
            try:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=6)
            except sr.WaitTimeoutError:
                return None

        try:
            text = self.recognizer.recognize_google(audio, language="pt-BR")
            print(f"Você: {text}")
            return text.lower().strip()
        except sr.UnknownValueError:
            self.speak("Não entendi. Pode repetir?")
        except sr.RequestError as exc:
            print(f"Erro no reconhecimento: {exc}")
            self.speak("Erro ao reconhecer a voz. Tente novamente.")
        return None

    def match_command(self, text: str) -> str | None:
        normalized = text.replace(" a ", " ").replace("  ", " ")

        for phrase, action in COMMANDS.items():
            if phrase in normalized or phrase in text:
                return action

        if any(w in text for w in ("comecar", "começar", "iniciar", "comeca", "começa")) and "receita" in text:
            return "start"
        if any(w in text for w in ("proximo", "próximo", "proxim")) and "passo" in text:
            return "next"
        if "temperatura" in text or "temperatur" in text:
            return "temperature"
        return None

    def handle_start(self) -> None:
        self.current_step = 0
        self._temp_warned = False
        self.publish_command("start")
        self.speak(RECIPE["steps"][0])

    def handle_next(self) -> None:
        if self.current_step < 0:
            self.speak("Nenhuma receita em andamento. Diga começar receita.")
            return

        self.current_step += 1
        if self.current_step >= len(RECIPE["steps"]):
            self.speak("A receita já foi concluída.")
            self.current_step = len(RECIPE["steps"]) - 1
            return

        self.publish_command("next")
        self.speak(RECIPE["steps"][self.current_step])

    def handle_temperature(self) -> None:
        with self._lock:
            temp = self.last_temperature

        if temp is None:
            self.speak("Ainda não recebi a temperatura do sensor.")
            return

        rounded = round(temp)
        self.speak(f"A temperatura atual é {rounded} graus.")

    def process(self, text: str) -> None:
        action = self.match_command(text)
        if action == "start":
            self.handle_start()
        elif action == "next":
            self.handle_next()
        elif action == "temperature":
            self.handle_temperature()
        else:
            self.speak(
                "Comandos disponíveis: começar receita, próximo passo, temperatura."
            )

    def run(self) -> None:
        if self.mqtt_enabled and not self.mqtt_connected:
            print("Aguardando MQTT em segundo plano (voz já funciona)...")

        msg = (
            f"Olá! Assistente de cozinha pronto. "
            f"Receita: {RECIPE['name']}. Diga começar receita para iniciar."
        )
        if self.mqtt_enabled and not self.mqtt_connected:
            msg += " Modo voz ativo; ESP32 quando o MQTT conectar."
        self.speak(msg)

        while True:
            text = self.listen()
            if text:
                self.process(text)
            time.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assistente de cozinha por voz")
    parser.add_argument(
        "--no-mqtt",
        action="store_true",
        help="Roda só voz/receita, sem conectar ao broker MQTT",
    )
    args = parser.parse_args()

    assistant = KitchenAssistant(mqtt_enabled=not args.no_mqtt)
    try:
        assistant.run()
    except KeyboardInterrupt:
        print("\nEncerrando...")
        assistant._mqtt_stop.set()
        if assistant.mqtt is not None:
            assistant.mqtt.loop_stop()
            if assistant.mqtt_connected:
                assistant.mqtt.disconnect()


if __name__ == "__main__":
    main()
