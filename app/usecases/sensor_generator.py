from __future__ import annotations

import csv
import random
import threading
import time
from datetime import datetime, timezone
from itertools import cycle
from pathlib import Path

import paho.mqtt.client as mqtt

from app.shared.sensor_models import (
    EnvironmentalPayload,
    EnvironmentalSensor,
    ParkingPayload,
    ParkingSensor,
    RoadSurfacePayload,
    RoadSurfaceSensor,
    SensorLocation,
    SensorMetadata,
    SmartEnergySensor,
    SmartEnergyPayload,
    SensorType,
    TrafficLightPayload,
    TrafficLightSensor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "data" / "reference_samples"


class ReferenceBasedSyntheticFactory:
    def __init__(self, reference_dir: Path | None = None, seed: int = 42):
        self.reference_dir = reference_dir or REFERENCE_DIR  # Папка з невеликими навчальними open-data sample-файлами.
        self.rng = random.Random(seed)  # Фіксоване зерно дає відтворювані синтетичні набори для демонстрації.
        self.parking_rows = self._load_csv("transport_parking_reference.csv")  # Базові transport/parking записи.
        self.traffic_light_rows = self._load_csv("traffic_light_reference.csv")  # Базові записи для світлофорів.
        self.environmental_rows = self._load_csv("environmental_reference.csv")  # Базові екологічні записи.
        self.energy_rows = self._load_csv("energy_reference.csv")  # Базові енергетичні записи.
        self._parking_index = 0  # Ручний курсор для циклічного проходу по reference rows.
        self._traffic_index = 0  # Ручний курсор для циклічного проходу по reference rows.
        self._environmental_index = 0  # Ручний курсор для циклічного проходу по reference rows.
        self._energy_index = 0  # Ручний курсор для циклічного проходу по reference rows.

    def _load_csv(self, filename: str) -> list[dict[str, str]]:
        csv_path = self.reference_dir / filename  # Формуємо шлях до reference-файлу всередині репозиторію.
        with csv_path.open("r", encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))  # Завантажуємо в пам'ять, бо sample-файли тут навмисно малі.

    def _next_row(self, rows: list[dict[str, str]], index_attr: str) -> dict[str, str]:
        if not rows:
            raise ValueError("Reference dataset is empty.")
        index = getattr(self, index_attr)  # Зчитуємо поточну позицію в обраному списку sample-даних.
        row = rows[index % len(rows)]  # Повертаємось на початок, якщо потрібно більше рядків, ніж є у sample.
        setattr(self, index_attr, index + 1)  # Пересуваємо курсор до наступного synthetic-запису.
        return row

    def _noise(self, base: float, delta: float, minimum: float | None = None) -> float:
        value = base + self.rng.uniform(-delta, delta)  # Додаємо обмежений випадковий шум до reference-значення.
        if minimum is not None:
            value = max(minimum, value)  # Не допускаємо фізично неможливих або надто малих значень.
        return value

    def _jitter_location(self, latitude: float, longitude: float) -> tuple[float, float]:
        return (
            round(self._noise(latitude, 0.0002), 6),  # Трохи змінюємо широту в межах реалістичної локальної зони.
            round(self._noise(longitude, 0.0002), 6),  # Трохи змінюємо довготу в межах реалістичної локальної зони.
        )

    @staticmethod
    def _base_metadata(sensor_id: str, device_id: str, tags: list[str]) -> SensorMetadata:
        return SensorMetadata(
            sensor_id=sensor_id,  # Логічний ідентифікатор сенсора в предметній області.
            device_id=device_id,  # Ідентифікатор синтетичного пристрою або контролера.
            vendor="AcademicSynthetic",  # Позначає, що дані згенеровані для лабораторної роботи.
            model="reference-noise-v1",  # Фіксує підхід до синтетичної генерації.
            sampling_interval_sec=2,  # Базовий інтервал синтетичних вимірювань.
            status="active",  # У лабораторній вважаємо сенсори активними.
            tags=tags,  # Теги допомагають маршрутизувати і фільтрувати повідомлення.
        )

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))  # Нормалізуємо UTC-рядок у datetime для Pydantic.

    def build_road_surface_sensor(self) -> RoadSurfaceSensor:
        latitude, longitude = self._jitter_location(50.4501, 30.5234)  # Базова точка біля контрольованого маршруту.
        return RoadSurfaceSensor(
            sensor_type=SensorType.ROAD_SURFACE,  # Legacy-сумісний транспортний тип сенсора.
            metadata=self._base_metadata("road-sensor-01", "vehicle-01", ["road", "legacy"]),  # Повторно використовується у backward-compatible flow.
            location=SensorLocation(
                latitude=latitude,  # Локація з невеликим випадковим відхиленням.
                longitude=longitude,  # Локація з невеликим випадковим відхиленням.
                road_segment_id="R-102",  # Фіксований ідентифікатор сегмента для прикладів road monitoring.
            ),
            timestamp=datetime.now(timezone.utc),  # Генеруємо поточний час, бо цей сенсор повністю синтетичний.
            payload=RoadSurfacePayload(
                x=round(self._noise(2.0, 3.0), 2),  # Імітоване прискорення по осі X.
                y=round(self._noise(0.5, 2.5), 2),  # Імітоване прискорення по осі Y.
                z=round(self._noise(2.5, 2.5, minimum=0.1), 2),  # Імітоване прискорення по осі Z.
            ),
        )

    def build_parking_sensor(self) -> ParkingSensor:
        row = self._next_row(self.parking_rows, "_parking_index")  # Беремо наступний рядок із transport reference sample.
        total_slots = int(row["total_slots"])  # Місткість беремо напряму з reference sample.
        occupied_slots = int(
            min(
                total_slots,  # Зайняті місця не можуть перевищувати фізичну місткість.
                max(
                    0,  # Зайняті місця не можуть бути від'ємними.
                    round(self._noise(float(row["occupied_slots"]), 4.0)),  # Додаємо невеликий шум до reference occupancy.
                ),
            )
        )
        free_slots = total_slots - occupied_slots  # Підтримуємо арифметичну узгодженість між місткістю і зайнятістю.
        latitude, longitude = self._jitter_location(float(row["latitude"]), float(row["longitude"]))  # Трохи змінюємо координати сенсора.
        return ParkingSensor(
            sensor_type=SensorType.PARKING,  # Універсальний тип parking-сенсора.
            metadata=self._base_metadata("parking-01", "parking-camera-01", ["parking", row["area"].lower().replace(" ", "-")]),  # Теги відображають зону паркінгу.
            location=SensorLocation(
                latitude=latitude,  # Локація з невеликим відхиленням.
                longitude=longitude,  # Локація з невеликим відхиленням.
                area=row["area"],  # Зберігаємо назву зони з reference data.
            ),
            timestamp=self._parse_timestamp(row["timestamp"]),  # Повторно використовуємо часову структуру reference-рядка.
            payload=ParkingPayload(
                total_slots=total_slots,  # Зберігаємо reference-місткість.
                occupied_slots=occupied_slots,  # Зберігаємо зайнятість після додавання шуму.
                free_slots=free_slots,  # Обчислюється з total_slots і occupied_slots.
                occupancy_rate=round(occupied_slots / total_slots, 3),  # Обчислена нормалізована заповненість.
                barrier_state=self.rng.choice(["open", "closed"]),  # Імітований стан шлагбаума.
                queue_length=self.rng.randint(0, 8),  # Імітована довжина черги.
            ),
        )

    def build_traffic_light_sensor(self) -> TrafficLightSensor:
        row = self._next_row(self.traffic_light_rows, "_traffic_index")  # Беремо наступний рядок із reference sample для світлофора.
        latitude, longitude = self._jitter_location(float(row["latitude"]), float(row["longitude"]))  # Додаємо невеликий шум до координат.
        vehicle_count = int(max(0, round(self._noise(float(row["vehicle_count"]), 6.0))))  # Імітуємо зміну транспортного потоку.
        cycle_time_sec = 60  # Фіксований спрощений цикл для лабораторної версії.
        remaining_time_sec = self.rng.randint(0, cycle_time_sec)  # Імітуємо поточну позицію всередині циклу.
        return TrafficLightSensor(
            sensor_type=SensorType.TRAFFIC_LIGHT,  # Універсальний тип сенсора світлофора.
            metadata=self._base_metadata(
                row["intersection_id"],  # Ідентифікатор перехрестя з reference стає sensor_id.
                f"controller-{row['intersection_id'].lower()}",  # Формуємо device_id контролера.
                ["intersection", "traffic-light"],  # Предметні теги для фільтрації.
            ),
            location=SensorLocation(
                latitude=latitude,  # Локація з невеликим відхиленням.
                longitude=longitude,  # Локація з невеликим відхиленням.
                road_segment_id=row["intersection_id"],  # Логічна прив'язка до контрольованого вузла дороги.
            ),
            timestamp=self._parse_timestamp(row["timestamp"]),  # Зберігаємо часову структуру reference sample.
            payload=TrafficLightPayload(
                current_phase=row["current_phase"],  # Зберігаємо фазу з reference data.
                vehicle_count=vehicle_count,  # Використовуємо транспортне навантаження після noise.
                remaining_time_sec=remaining_time_sec,  # Імітований залишок часу фази.
                cycle_time_sec=cycle_time_sec,  # Фіксована довжина циклу.
                pedestrian_request=row["pedestrian_request"].strip().lower() == "true",  # Перетворюємо CSV-рядок у boolean.
                fault_detected=False,  # У навчальному прикладі тримаємо номінальний стан.
            ),
        )

    def build_environmental_sensor(self) -> EnvironmentalSensor:
        row = self._next_row(self.environmental_rows, "_environmental_index")  # Беремо наступний екологічний reference-рядок.
        latitude, longitude = self._jitter_location(float(row["latitude"]), float(row["longitude"]))  # Додаємо невеликий шум до координат.
        return EnvironmentalSensor(
            sensor_type=SensorType.ENVIRONMENTAL,  # Комбінований тип екологічного моніторингу.
            metadata=self._base_metadata("env-station-01", "env-station-01", ["environmental", "air-weather"]),  # Ідентичність екологічної станції.
            location=SensorLocation(
                latitude=latitude,  # Локація з невеликим відхиленням.
                longitude=longitude,  # Локація з невеликим відхиленням.
                area="Environmental Zone",  # Проста читабельна назва зони.
            ),
            timestamp=self._parse_timestamp(row["timestamp"]),  # Зберігаємо формат часу з reference data.
            payload=EnvironmentalPayload(
                temperature_c=round(self._noise(float(row["temperature_c"]), 1.5), 2),  # Додаємо noise до температури відносно open-data baseline.
                humidity_pct=round(self._noise(float(row["humidity_pct"]), 3.5, minimum=0.0), 2),  # Додаємо noise до вологості.
                pm2_5=round(self._noise(float(row["pm2_5"]), 2.0, minimum=0.0), 2),  # Додаємо noise до PM2.5.
                pm10=round(self._noise(float(row["pm10"]), 3.0, minimum=0.0), 2),  # Додаємо noise до PM10.
                co2_ppm=round(self._noise(float(row["co2_ppm"]), 35.0, minimum=250.0), 2),  # Додаємо noise до CO2.
            ),
        )

    def build_energy_sensor(self) -> SmartEnergySensor:
        row = self._next_row(self.energy_rows, "_energy_index")  # Беремо наступний енергетичний reference-рядок.
        latitude, longitude = self._jitter_location(float(row["latitude"]), float(row["longitude"]))  # Додаємо невеликий шум до координат.
        return SmartEnergySensor(
            sensor_type=SensorType.SMART_GRID,  # Універсальний тип smart-grid сенсора.
            metadata=self._base_metadata("grid-node-01", "transformer-01", ["energy", "smart-grid"]),  # Ідентичність енергетичного вузла.
            location=SensorLocation(
                latitude=latitude,  # Локація з невеликим відхиленням.
                longitude=longitude,  # Локація з невеликим відхиленням.
                area="Grid Sector A",  # Читабельна назва енергетичної зони.
            ),
            timestamp=self._parse_timestamp(row["timestamp"]),  # Зберігаємо часову структуру reference data.
            payload=SmartEnergyPayload(
                voltage_v=round(self._noise(float(row["voltage_v"]), 4.0, minimum=0.0), 2),  # Додаємо noise до напруги відносно open-data baseline.
                current_a=round(self._noise(float(row["current_a"]), 1.2, minimum=0.0), 2),  # Додаємо noise до сили струму.
                power_kw=round(self._noise(float(row["power_kw"]), 2.5, minimum=0.0), 2),  # Додаємо noise до потужності.
                frequency_hz=round(self._noise(float(row["frequency_hz"]), 0.08, minimum=45.0), 2),  # Додаємо noise до частоти мережі.
                transformer_temp_c=round(
                    self._noise(float(row["transformer_temp_c"]), 2.0, minimum=-20.0),  # Додаємо noise до температури трансформатора.
                    2,
                ),
                outage_detected=False,  # Синтетичний стан нормальної роботи.
            ),
        )


class SyntheticSensorGenerator:
    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        topic: str,
        interval_sec: float = 2.0,
        enabled: bool = False,
    ):
        self.broker_host = broker_host  # Хост MQTT-брокера для публікації синтетичних повідомлень.
        self.broker_port = broker_port  # Порт MQTT-брокера для публікації синтетичних повідомлень.
        self.topic = topic  # Сирий universal topic, який читає Edge-адаптер.
        self.interval_sec = interval_sec  # Затримка між синтетичними MQTT-повідомленнями.
        self.enabled = enabled  # Дає змогу вимкнути генератор без зміни коду.
        self.client = mqtt.Client()  # Окремий MQTT-клієнт лише для публікації.
        self.factory = ReferenceBasedSyntheticFactory()  # Побудовник сенсорних повідомлень на основі reference CSV.
        self._stop_event = threading.Event()  # Прапорець коректної зупинки фонового потоку.
        self._thread: threading.Thread | None = None  # Посилання на фоновий потік публікації.
        self._generator_cycle = cycle(
            [
                self.factory.build_road_surface_sensor,  # Legacy-сумісне дорожнє повідомлення.
                self.factory.build_parking_sensor,  # Транспортне / parking-повідомлення.
                self.factory.build_traffic_light_sensor,  # Повідомлення від світлофора.
                self.factory.build_environmental_sensor,  # Екологічне повідомлення.
                self.factory.build_energy_sensor,  # Енергетичне / smart-grid повідомлення.
            ]
        )

    def start(self) -> None:
        if not self.enabled:
            return

        self.client.connect(self.broker_host, self.broker_port, 60)  # Відкриваємо MQTT-з'єднання перед стартом циклу.
        self.client.loop_start()  # Запускаємо MQTT-мережевий цикл у фоні.
        self._thread = threading.Thread(target=self._run, daemon=True)  # Окремий потік не блокує основний Edge-loop.
        self._thread.start()  # Запускаємо безперервну синтетичну публікацію.

    def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()  # Сигналізуємо фоновому потоку про зупинку.
        if self._thread is not None:
            self._thread.join(timeout=2)  # Коротко чекаємо на коректне завершення.
        self.client.loop_stop()  # Зупиняємо MQTT-мережевий цикл.
        self.client.disconnect()  # Коректно закриваємо з'єднання з брокером.

    def _run(self) -> None:
        while not self._stop_event.is_set():
            builder = next(self._generator_cycle)  # Вибираємо наступний тип сенсора по колу.
            message = builder()  # Будуємо вже валідний об'єкт SensorMessage.
            self.client.publish(self.topic, message.model_dump_json())  # Одразу публікуємо готовий JSON у MQTT.
            time.sleep(self.interval_sec)  # Контролюємо швидкість генерації даних.
