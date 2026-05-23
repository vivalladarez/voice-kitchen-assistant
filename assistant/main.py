"""
Assistente de voz para preparo de receitas — MVP.

Escuta comandos pelo microfone, responde por voz e envia ações ao ESP32 via MQTT.
"""

import json
import threading
import time

import paho.mqtt.client as mqtt
import pyttsx3
import speech_recognition as sr

from recipes import RECIPE, TEMP_WARNING_C, TEMP_WARNING_MSG

MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_TEMP = "kitchen/temperature"
TOPIC_CMD = "kitchen/command"

COMMANDS = {
    "começar receita": "start",
    "comecar receita": "start",
    "iniciar receita": "start",
    "próximo passo": "next",
    "proximo passo": "next",
    "temperatura": "temperature",
    "qual a temperatura": "temperature",
}


class KitchenAssistant:
    def __init__(self) -> None:
        self.tts = pyttsx3.init()
        self.tts.setProperty("rate", 160)

        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        self.current_step = -1
        self.last_temperature: float | None = None
        self._temp_warned = False
        self._lock = threading.Lock()

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self.mqtt.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            client.subscribe(TOPIC_TEMP)
            print(f"MQTT conectado — inscrito em {TOPIC_TEMP}")
        else:
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
        for phrase, action in COMMANDS.items():
            if phrase in text:
                return action
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
        self.speak(
            f"Olá! Assistente de cozinha pronto. "
            f"Receita: {RECIPE['name']}. Diga começar receita para iniciar."
        )

        while True:
            text = self.listen()
            if text:
                self.process(text)
            time.sleep(0.3)


def main() -> None:
    assistant = KitchenAssistant()
    try:
        assistant.run()
    except KeyboardInterrupt:
        print("\nEncerrando...")
        assistant.mqtt.loop_stop()
        assistant.mqtt.disconnect()


if __name__ == "__main__":
    main()
