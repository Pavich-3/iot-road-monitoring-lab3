from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # Дозволяє імпорти з репозиторію при прямому запуску script-файлу.

from app.shared.sensor_models import EnvironmentalSensor, ParkingSensor, SmartEnergySensor, TrafficLightSensor
from app.usecases.sensor_generator import ReferenceBasedSyntheticFactory


GENERATED_DIR = REPO_ROOT / "data" / "generated"


def parking_row_from_message(message: ParkingSensor) -> dict[str, object]:
    return {
        "timestamp": message.timestamp.isoformat(),  # Зберігаємо згенерований час як текст для CSV.
        "total_slots": message.payload.total_slots,  # Зберігаємо місткість паркінгу.
        "occupied_slots": message.payload.occupied_slots,  # Зберігаємо зайнятість.
        "free_slots": message.payload.free_slots,  # Зберігаємо обчислену кількість вільних місць.
        "occupancy_rate": message.payload.occupancy_rate,  # Зберігаємо нормалізовану заповненість.
        "barrier_state": message.payload.barrier_state,  # Зберігаємо стан шлагбаума.
        "queue_length": message.payload.queue_length,  # Зберігаємо оцінку довжини черги.
        "area": message.location.area,  # Зберігаємо назву зони.
        "latitude": message.location.latitude,  # Зберігаємо координати для аналізу.
        "longitude": message.location.longitude,  # Зберігаємо координати для аналізу.
    }


def traffic_light_row_from_message(message: TrafficLightSensor) -> dict[str, object]:
    return {
        "timestamp": message.timestamp.isoformat(),  # Зберігаємо згенерований час як текст для CSV.
        "intersection_id": message.metadata.sensor_id,  # Зберігаємо ідентифікатор перехрестя з reference data.
        "current_phase": message.payload.current_phase,  # Зберігаємо фазу світлофора.
        "vehicle_count": message.payload.vehicle_count,  # Зберігаємо транспортне навантаження.
        "remaining_time_sec": message.payload.remaining_time_sec,  # Зберігаємо таймер поточної фази.
        "cycle_time_sec": message.payload.cycle_time_sec,  # Зберігаємо повну довжину циклу.
        "pedestrian_request": message.payload.pedestrian_request,  # Зберігаємо стан запиту пішохода.
        "latitude": message.location.latitude,  # Зберігаємо координати для аналізу.
        "longitude": message.location.longitude,  # Зберігаємо координати для аналізу.
    }


def environmental_row_from_message(message: EnvironmentalSensor) -> dict[str, object]:
    return {
        "timestamp": message.timestamp.isoformat(),  # Зберігаємо згенерований час як текст для CSV.
        "temperature_c": message.payload.temperature_c,  # Зберігаємо температуру після noise.
        "humidity_pct": message.payload.humidity_pct,  # Зберігаємо вологість після noise.
        "pm2_5": message.payload.pm2_5,  # Зберігаємо концентрацію PM2.5 після noise.
        "pm10": message.payload.pm10,  # Зберігаємо концентрацію PM10 після noise.
        "co2_ppm": message.payload.co2_ppm,  # Зберігаємо концентрацію CO2 після noise.
        "latitude": message.location.latitude,  # Зберігаємо координати для аналізу.
        "longitude": message.location.longitude,  # Зберігаємо координати для аналізу.
    }


def energy_row_from_message(message: SmartEnergySensor) -> dict[str, object]:
    return {
        "timestamp": message.timestamp.isoformat(),  # Зберігаємо згенерований час як текст для CSV.
        "voltage_v": message.payload.voltage_v,  # Зберігаємо напругу після noise.
        "current_a": message.payload.current_a,  # Зберігаємо струм після noise.
        "power_kw": message.payload.power_kw,  # Зберігаємо потужність після noise.
        "frequency_hz": message.payload.frequency_hz,  # Зберігаємо частоту мережі після noise.
        "transformer_temp_c": message.payload.transformer_temp_c,  # Зберігаємо температуру трансформатора після noise.
        "latitude": message.location.latitude,  # Зберігаємо координати для аналізу.
        "longitude": message.location.longitude,  # Зберігаємо координати для аналізу.
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)  # Стабільний порядок полів спрощує перегляд файлів на захисті.
        writer.writeheader()  # CSV-заголовок зберігає зрозумілу академічну структуру.
        writer.writerows(rows)  # Записуємо всі синтезовані рядки для одного домену.


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic sensor data from lightweight reference CSV samples."
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=100,
        help="Number of rows to generate for each generated CSV file.",
    )
    args = parser.parse_args()

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    factory = ReferenceBasedSyntheticFactory(seed=42)  # Фіксоване зерно дає детерміновані результати для однакової кількості рядків.

    parking_rows: list[dict[str, object]] = []  # Готові CSV-рядки для parking dataset.
    traffic_rows: list[dict[str, object]] = []  # Готові CSV-рядки для traffic light dataset.
    environmental_rows: list[dict[str, object]] = []  # Готові CSV-рядки для environmental dataset.
    energy_rows: list[dict[str, object]] = []  # Готові CSV-рядки для energy dataset.
    jsonl_messages: list[str] = []  # Готові до публікації JSONL-рядки SensorMessage.

    for _ in range(args.rows):
        parking_message = factory.build_parking_sensor()  # Генеруємо parking-повідомлення з transport reference sample.
        traffic_message = factory.build_traffic_light_sensor()  # Генеруємо повідомлення світлофора з transport reference sample.
        environmental_message = factory.build_environmental_sensor()  # Генеруємо environmental-повідомлення з environmental reference sample.
        energy_message = factory.build_energy_sensor()  # Генеруємо energy-повідомлення з energy reference sample.

        parking_rows.append(parking_row_from_message(parking_message))  # Перетворюємо повідомлення у плоский CSV-рядок.
        traffic_rows.append(traffic_light_row_from_message(traffic_message))  # Перетворюємо повідомлення у плоский CSV-рядок.
        environmental_rows.append(environmental_row_from_message(environmental_message))  # Перетворюємо повідомлення у плоский CSV-рядок.
        energy_rows.append(energy_row_from_message(energy_message))  # Перетворюємо повідомлення у плоский CSV-рядок.

        jsonl_messages.extend(
            [
                parking_message.model_dump_json(),  # Готове universal JSON-повідомлення для MQTT.
                traffic_message.model_dump_json(),  # Готове universal JSON-повідомлення для MQTT.
                environmental_message.model_dump_json(),  # Готове universal JSON-повідомлення для MQTT.
                energy_message.model_dump_json(),  # Готове universal JSON-повідомлення для MQTT.
            ]
        )

    write_csv(
        GENERATED_DIR / "parking_synthetic.csv",
        [
            "timestamp",
            "total_slots",
            "occupied_slots",
            "free_slots",
            "occupancy_rate",
            "barrier_state",
            "queue_length",
            "area",
            "latitude",
            "longitude",
        ],
        parking_rows,
    )
    write_csv(
        GENERATED_DIR / "traffic_light_synthetic.csv",
        [
            "timestamp",
            "intersection_id",
            "current_phase",
            "vehicle_count",
            "remaining_time_sec",
            "cycle_time_sec",
            "pedestrian_request",
            "latitude",
            "longitude",
        ],
        traffic_rows,
    )
    write_csv(
        GENERATED_DIR / "environmental_synthetic.csv",
        [
            "timestamp",
            "temperature_c",
            "humidity_pct",
            "pm2_5",
            "pm10",
            "co2_ppm",
            "latitude",
            "longitude",
        ],
        environmental_rows,
    )
    write_csv(
        GENERATED_DIR / "energy_synthetic.csv",
        [
            "timestamp",
            "voltage_v",
            "current_a",
            "power_kw",
            "frequency_hz",
            "transformer_temp_c",
            "latitude",
            "longitude",
        ],
        energy_rows,
    )

    with (GENERATED_DIR / "sensor_messages.jsonl").open("w", encoding="utf-8") as target:
        for line in jsonl_messages:
            target.write(line)  # Записуємо один повний SensorMessage в один рядок.
            target.write("\n")  # Формат JSONL вимагає розділення JSON-об'єктів новим рядком.

    print(f"Generated synthetic datasets in {GENERATED_DIR}")  # Коротко показуємо папку з результатами.
    print(f"Rows per CSV: {args.rows}")  # Підтверджуємо запитаний розмір dataset.
    print(f"Total SensorMessage JSONL lines: {len(jsonl_messages)}")  # Підтверджуємо загальну кількість publishable-повідомлень.


if __name__ == "__main__":
    main()
