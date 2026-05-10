from __future__ import annotations

import logging

import paho.mqtt.client as mqtt
from pydantic import TypeAdapter

from app.shared.sensor_models import SensorMessage
from app.usecases.sensor_processing import process_sensor_message


class UniversalSensorMQTTAdapter:
    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        sensor_data_topic: str,
        sensor_readings_topic: str,
    ):
        self.broker_host = broker_host  # Хост MQTT для підписки та публікації.
        self.broker_port = broker_port  # Порт MQTT для підписки та публікації.
        self.sensor_data_topic = sensor_data_topic  # Вхідний universal topic із сирими сенсорними даними.
        self.sensor_readings_topic = sensor_readings_topic  # Вихідний topic з обробленими даними для Hub.
        self.client = mqtt.Client()  # Окремий MQTT-клієнт для universal flow.
        self.sensor_message_adapter = TypeAdapter(SensorMessage)  # Валідує повний discriminated union для сенсорів.

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logging.info("Universal sensor adapter connected to MQTT broker")
            self.client.subscribe(self.sensor_data_topic)
            logging.info("Subscribed to universal sensor topic: %s", self.sensor_data_topic)
        else:
            logging.error("Failed to connect universal sensor adapter to MQTT broker: %s", rc)

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")  # Перетворюємо MQTT-байти на JSON-рядок.
            sensor_message = self.sensor_message_adapter.validate_json(payload)  # Парсимо і валідовуємо SensorMessage.
            processed_message = process_sensor_message(sensor_message)  # Застосовуємо легку Edge-логіку.
            publish_result = self.client.publish(
                self.sensor_readings_topic,  # Надсилаємо валідоване або збагачене повідомлення далі.
                processed_message.model_dump_json(),  # Серіалізуємо назад у JSON для MQTT-транспорту.
            )
            if publish_result[0] != 0:
                logging.error(
                    "Failed to publish processed universal sensor message to %s",
                    self.sensor_readings_topic,
                )
        except Exception as exc:
            logging.exception("Error processing universal sensor message: %s", exc)

    def connect(self) -> None:
        self.client.on_connect = self.on_connect  # Реєструємо callback підключення до MQTT.
        self.client.on_message = self.on_message  # Реєструємо callback отримання повідомлень.
        self.client.connect(self.broker_host, self.broker_port, 60)  # Відкриваємо з'єднання з брокером.

    def start(self) -> None:
        self.client.loop_start()  # Запускаємо MQTT-мережевий потік.

    def stop(self) -> None:
        self.client.loop_stop()  # Зупиняємо MQTT-мережевий потік.
        self.client.disconnect()  # Коректно відключаємось від брокера.
