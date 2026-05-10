from __future__ import annotations

from app.shared.sensor_models import (
    ParkingSensor,
    RoadSurfacePayload,
    RoadSurfaceSensor,
    SensorMessage,
    SensorType,
    TrafficLightSensor,
)


def classify_road_state(x: float, y: float, z: float) -> str:
    peak_value = max(abs(x), abs(y), abs(z))  # Legacy-евристика бере найбільший стрибок прискорення.

    if peak_value > 4.0:  # Сильний удар зазвичай відповідає вибоїні.
        return "pothole"
    if peak_value > 1.5:  # Середня вібрація зазвичай означає нерівність покриття.
        return "roughness"
    return "normal"  # Невелика вібрація вважається нормальним станом дороги.


def process_sensor_message(sensor_message: SensorMessage) -> SensorMessage:
    if sensor_message.sensor_type == SensorType.ROAD_SURFACE:
        assert isinstance(sensor_message, RoadSurfaceSensor)  # Звужуємо union-тип для безпечного доступу до payload.
        payload = sensor_message.payload  # Беремо поточні значення, схожі на акселерометричні.
        road_state = classify_road_state(payload.x, payload.y, payload.z)  # Обчислюємо семантичний стан дороги.
        return sensor_message.model_copy(
            update={
                "payload": RoadSurfacePayload(
                    x=payload.x,  # Зберігаємо вихідну компоненту X.
                    y=payload.y,  # Зберігаємо вихідну компоненту Y.
                    z=payload.z,  # Зберігаємо вихідну компоненту Z.
                    road_state=road_state,  # Додаємо обчислений стан для наступних сервісів.
                )
            }
        )

    if sensor_message.sensor_type == SensorType.PARKING:
        assert isinstance(sensor_message, ParkingSensor)  # Явне звуження залишене для кращого пояснення на захисті.
        return sensor_message  # Parking-повідомлення вже валідні після Pydantic-валідації.

    if sensor_message.sensor_type == SensorType.TRAFFIC_LIGHT:
        assert isinstance(sensor_message, TrafficLightSensor)  # Явне звуження залишене для кращого пояснення на захисті.
        return sensor_message  # Для світлофорів у цій лабораторній використовується pass-through.

    return sensor_message  # Інші підтримані типи можуть проходити без змін.
