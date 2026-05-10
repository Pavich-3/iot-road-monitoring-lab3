from __future__ import annotations

import logging
import time
from typing import Any

import paho.mqtt.client as mqtt
import requests
from pydantic import TypeAdapter

from app.shared.sensor_models import SensorMessage
from config import (
    HUB_BATCH_SIZE,
    HUB_BUFFER_BACKEND,
    HUB_ENABLED,
    HUB_MQTT_HOST,
    HUB_MQTT_PORT,
    HUB_SENSOR_READINGS_TOPIC,
    HUB_STORE_BATCH_URL,
)


class InMemorySensorBuffer:
    def __init__(self) -> None:
        self._items: list[SensorMessage] = []  # Буфер у стилі черги, який у лабораторній замінює Redis.

    def add(self, item: SensorMessage) -> int:
        self._items.append(item)  # Додаємо нове валідоване повідомлення в кінець буфера.
        return len(self._items)  # Повертаємо розмір буфера для логування.

    def size(self) -> int:
        return len(self._items)  # Поточна кількість повідомлень у буфері.

    def drain(self, count: int) -> list[SensorMessage]:
        batch = self._items[:count]  # Беремо найстаріші елементи для пакетної відправки.
        self._items = self._items[count:]  # Видаляємо відправлені елементи з буфера в пам'яті.
        return batch

    def push_front(self, items: list[SensorMessage]) -> None:
        self._items = items + self._items  # Повертаємо невдалий batch на початок, щоб зберегти порядок.


class HubService:
    def __init__(self) -> None:
        self.enabled = HUB_ENABLED  # Дає змогу вмикати або вимикати Hub через env без зміни коду.
        self.buffer_backend = HUB_BUFFER_BACKEND  # Винесено в конфіг, щоб потім можна було замінити memory на Redis.
        self.batch_size = HUB_BATCH_SIZE  # Кількість повідомлень перед POST batch у Store.
        self.store_batch_url = HUB_STORE_BATCH_URL  # Endpoint Store-сервісу для пакетної відправки.
        self.topic = HUB_SENSOR_READINGS_TOPIC  # MQTT-topic, який слухає Hub.
        self.client = mqtt.Client()  # Окремий MQTT-клієнт для підписок Hub.
        self.sensor_message_adapter = TypeAdapter(SensorMessage)  # Повторно валідує повідомлення перед буферизацією.
        self.buffer = InMemorySensorBuffer()  # Буферизація, зручна для лабораторної реалізації.

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logging.info("Hub connected to MQTT broker")
            self.client.subscribe(self.topic)
            logging.info("Hub subscribed to topic: %s", self.topic)
        else:
            logging.error("Hub failed to connect to MQTT broker with code: %s", rc)

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")  # Перетворюємо MQTT-байти в JSON-рядок.
            logging.info("Hub received sensor reading from topic %s", msg.topic)

            sensor_message = self.sensor_message_adapter.validate_json(payload)  # Захищаємо Store від некоректних upstream-повідомлень.
            logging.info(
                "Hub validated sensor reading: sensor_id=%s type=%s",
                sensor_message.metadata.sensor_id,
                sensor_message.sensor_type.value,
            )

            buffer_size = self.buffer.add(sensor_message)  # Тимчасово зберігаємо, доки не буде досягнуто розмір batch.
            logging.info(
                "Hub added sensor reading to buffer: backend=%s size=%s",
                self.buffer_backend,
                buffer_size,
            )

            self.flush_if_needed()  # Після кожного додавання пробуємо відправити batch, якщо він готовий.
        except Exception as exc:
            logging.exception("Hub failed to process sensor reading: %s", exc)

    def connect(self) -> None:
        self.client.on_connect = self.on_connect  # Реєструємо callback підключення до MQTT.
        self.client.on_message = self.on_message  # Реєструємо callback отримання MQTT-повідомлень.
        self.client.connect(HUB_MQTT_HOST, HUB_MQTT_PORT, 60)  # Відкриваємо MQTT-з'єднання.

    def start(self) -> None:
        if not self.enabled:
            logging.info("Hub service is disabled via HUB_ENABLED")
            return
        self.client.loop_start()  # Запускаємо MQTT-мережевий цикл у фоновому потоці.

    def stop(self) -> None:
        if not self.enabled:
            return
        self.client.loop_stop()  # Зупиняємо MQTT-мережевий цикл.
        self.client.disconnect()  # Відключаємося від брокера.

    def run_forever(self) -> None:
        if not self.enabled:
            logging.info("Hub service is disabled; exiting")
            return

        self.connect()
        self.start()
        try:
            while True:
                time.sleep(1)  # Тримаємо процес активним, поки MQTT-callback-и працюють у фоні.
        except KeyboardInterrupt:
            self.stop()  # Коректне ручне завершення для локального запуску.

    def flush_if_needed(self) -> None:
        if self.buffer.size() < self.batch_size:
            return  # Продовжуємо накопичення, поки не досягнуто потрібний поріг batch.

        batch = self.buffer.drain(self.batch_size)  # Беремо один готовий batch з початку буфера.
        payload = [item.model_dump(mode="json") for item in batch]  # Перетворюємо об'єкти в HTTP-safe JSON payload.

        try:
            response = requests.post(
                self.store_batch_url,  # Надсилаємо у batch endpoint Store-сервісу.
                json=payload,  # JSON-масив документів SensorMessage.
                timeout=10,  # Для лабораторного розгортання достатньо короткого timeout.
            )
            logging.info("Hub sent batch to Store: size=%s", len(batch))
            logging.info("Store response status: %s", response.status_code)
            response.raise_for_status()  # Активуємо retry-path при будь-якому non-2xx response.
        except requests.RequestException as exc:
            self.buffer.push_front(batch)  # Зберігаємо дані, якщо Store тимчасово недоступний.
            logging.exception("Hub failed to send batch to Store: %s", exc)
