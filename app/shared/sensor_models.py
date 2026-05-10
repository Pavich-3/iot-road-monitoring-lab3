from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SensorType(str, Enum):
    ROAD_SURFACE = "road_surface"  # Legacy-сумісний тип сенсора для моніторингу дорожнього покриття.
    PARKING = "parking"  # Тип сенсора для моніторингу зайнятості та доступу до паркінгу.
    TRAFFIC_LIGHT = "traffic_light"  # Тип сенсора контролера світлофора або перехрестя.
    ENVIRONMENTAL = "environmental"  # Комбінований тип екологічного моніторингу для цієї лабораторної.
    WEATHER = "weather"  # Зарезервований тип погодного сенсора для подальшого розширення.
    SMART_GRID = "smart_grid"  # Тип сенсора енергетичної інфраструктури або smart energy.
    AIR_QUALITY = "air_quality"  # Зарезервований окремий тип сенсора якості повітря.
    WATER_MONITORING = "water_monitoring"  # Зарезервований тип сенсора моніторингу води.


class SensorLocation(BaseModel):
    latitude: float  # Основна географічна координата для карти та збереження.
    longitude: float  # Основна географічна координата для карти та збереження.
    altitude_m: float | None = None  # Необов'язкова висота для сенсорів, де це потрібно.
    area: str | None = None  # Зрозуміла людині назва зони, району або паркінгу.
    road_segment_id: str | None = None  # Необов'язковий ідентифікатор дороги або перехрестя.


class SensorMetadata(BaseModel):
    sensor_id: str  # Логічний ідентифікатор сенсора в предметній області.
    device_id: str  # Ідентифікатор фізичного або програмного пристрою, що створив повідомлення.
    gateway_id: str | None = None  # Необов'язковий ідентифікатор проміжного gateway.
    vendor: str | None = None  # Назва виробника для трасування джерела.
    model: str | None = None  # Назва моделі сенсора або контролера.
    firmware_version: str | None = None  # Необов'язкова версія ПЗ для діагностики.
    sampling_interval_sec: int | None = None  # Очікуваний інтервал вимірювання в секундах.
    status: Literal["active", "inactive", "maintenance"] = "active"  # Поточний стан роботи пристрою.
    tags: list[str] = Field(default_factory=list)  # Гнучкі мітки для фільтрації та групування.


class SensorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")  # Невідомі ключі payload відхиляються під час валідації.


class RoadSurfacePayload(SensorPayload):
    x: float  # Компонента прискорення по осі X.
    y: float  # Компонента прискорення по осі Y.
    z: float  # Компонента прискорення по осі Z.
    road_state: str | None = None  # Похідний стан дороги, який додається на Edge-рівні.


class ParkingPayload(SensorPayload):
    total_slots: int  # Загальна місткість контрольованої парковки.
    occupied_slots: int  # Кількість зайнятих місць.
    free_slots: int  # Кількість вільних місць.
    occupancy_rate: float  # Відносна заповненість у діапазоні 0.0..1.0.
    barrier_state: Literal["open", "closed", "unknown"] = "unknown"  # Стан в'їзного шлагбаума.
    queue_length: int = 0  # Орієнтовна кількість авто в черзі на в'їзд.

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.total_slots < 0 or self.occupied_slots < 0 or self.free_slots < 0:  # Від'ємні значення місткості є некоректними.
            raise ValueError("Parking capacity values must be non-negative.")
        if self.occupied_slots + self.free_slots != self.total_slots:  # Сума зайнятих і вільних місць має дорівнювати місткості.
            raise ValueError("occupied_slots + free_slots must equal total_slots.")
        if not 0.0 <= self.occupancy_rate <= 1.0:  # Нормалізована заповненість не може виходити за логічні межі.
            raise ValueError("occupancy_rate must be between 0.0 and 1.0.")
        return self


class TrafficLightPayload(SensorPayload):
    current_phase: Literal["red", "yellow", "green", "blinking"]  # Поточна видима фаза світлофора.
    vehicle_count: int = 0  # Орієнтовна кількість автомобілів з reference/open traffic data.
    remaining_time_sec: int  # Час, що залишився до зміни поточної фази.
    cycle_time_sec: int  # Повна тривалість циклу світлофора.
    pedestrian_request: bool = False  # Ознака того, що є запит від пішохода.
    fault_detected: bool = False  # Спрощений прапорець несправності контролера.

    @model_validator(mode="after")
    def validate_cycle(self):
        if self.remaining_time_sec < 0 or self.cycle_time_sec <= 0:  # Часові значення мають залишатися фізично коректними.
            raise ValueError("Traffic light timing values must be positive.")
        if self.remaining_time_sec > self.cycle_time_sec:  # Залишок фази не може перевищувати повний цикл.
            raise ValueError("remaining_time_sec cannot exceed cycle_time_sec.")
        if self.vehicle_count < 0:  # Від'ємна кількість авто є некоректною.
            raise ValueError("vehicle_count must be non-negative.")
        return self


class EnvironmentalPayload(SensorPayload):
    temperature_c: float  # Температура повітря у градусах Цельсія.
    humidity_pct: float  # Відносна вологість у відсотках.
    pm2_5: float  # Концентрація дрібнодисперсного пилу PM2.5.
    pm10: float  # Концентрація більш грубого пилу PM10.
    co2_ppm: float  # Концентрація CO2.


class WeatherPayload(SensorPayload):
    temperature_c: float  # Атмосферна температура.
    humidity_pct: float  # Атмосферна вологість.
    pressure_hpa: float  # Атмосферний тиск у гектопаскалях.
    wind_speed_mps: float  # Швидкість вітру в метрах за секунду.
    precipitation_mm: float = 0.0  # Кількість опадів.
    visibility_m: float | None = None  # Дальність видимості.


class SmartGridPayload(SensorPayload):
    voltage_v: float  # Напруга в електромережі.
    current_a: float  # Сила струму.
    power_kw: float  # Миттєва активна потужність.
    frequency_hz: float  # Частота електромережі.
    transformer_temp_c: float | None = None  # Робоча температура трансформатора.
    outage_detected: bool = False  # Спрощений прапорець аварійного відключення.


class AirQualityPayload(SensorPayload):
    pm2_5: float  # Концентрація дрібнодисперсного пилу PM2.5.
    pm10: float  # Концентрація пилу PM10.
    co2_ppm: float  # Концентрація CO2.
    no2_ppb: float | None = None  # Концентрація діоксиду азоту.
    aqi: int  # Індекс якості повітря.


class WaterMonitoringPayload(SensorPayload):
    ph: float  # Кислотність або лужність води.
    turbidity_ntu: float  # Каламутність води в NTU.
    flow_rate_l_s: float  # Швидкість потоку води.
    temperature_c: float | None = None  # Температура води.
    dissolved_oxygen_mg_l: float | None = None  # Рівень розчиненого кисню.
    contamination_detected: bool = False  # Спрощений прапорець забруднення.


class BaseSensor(BaseModel):
    schema_version: str = "1.0"  # Версія схеми payload для сумісності в майбутньому.
    sensor_type: SensorType  # Визначає, яку саме схему payload потрібно застосувати.
    metadata: SensorMetadata  # Спільні метадані джерела або пристрою.
    location: SensorLocation  # Фізичне або логічне розташування сенсора.
    timestamp: datetime  # Час виконання вимірювання.


class RoadSurfaceSensor(BaseSensor):
    sensor_type: Literal[SensorType.ROAD_SURFACE]
    payload: RoadSurfacePayload


class ParkingSensor(BaseSensor):
    sensor_type: Literal[SensorType.PARKING]
    payload: ParkingPayload


class TrafficLightSensor(BaseSensor):
    sensor_type: Literal[SensorType.TRAFFIC_LIGHT]
    payload: TrafficLightPayload


class EnvironmentalSensor(BaseSensor):
    sensor_type: Literal[SensorType.ENVIRONMENTAL]
    payload: EnvironmentalPayload


class WeatherSensor(BaseSensor):
    sensor_type: Literal[SensorType.WEATHER]
    payload: WeatherPayload


class SmartGridSensor(BaseSensor):
    sensor_type: Literal[SensorType.SMART_GRID]
    payload: SmartGridPayload


class AirQualitySensor(BaseSensor):
    sensor_type: Literal[SensorType.AIR_QUALITY]
    payload: AirQualityPayload


class WaterMonitoringSensor(BaseSensor):
    sensor_type: Literal[SensorType.WATER_MONITORING]
    payload: WaterMonitoringPayload


SensorMessage = Annotated[
    Union[
        RoadSurfaceSensor,
        ParkingSensor,
        TrafficLightSensor,
        EnvironmentalSensor,
        WeatherSensor,
        SmartGridSensor,
        AirQualitySensor,
        WaterMonitoringSensor,
    ],
    Field(discriminator="sensor_type"),  # Pydantic вибирає конкретну модель за значенням sensor_type.
]


class SensorReadingInDB(BaseModel):
    id: int  # Первинний ключ запису в базі даних.
    sensor_id: str  # Збережений логічний ідентифікатор сенсора.
    sensor_type: SensorType  # Збережений тип сенсорного об'єкта.
    device_id: str  # Збережений ідентифікатор пристрою-джерела.
    schema_version: str  # Версія схеми збереженого повідомлення.
    latitude: float  # Індексована широта, винесена з location.
    longitude: float  # Індексована довгота, винесена з location.
    altitude_m: float | None = None  # Необов'язкова збережена висота.
    area: str | None = None  # Необов'язкова збережена назва зони.
    road_segment_id: str | None = None  # Необов'язковий збережений ідентифікатор дорожнього сегмента.
    status: str | None = None  # Робочий стан, скопійований з metadata.
    payload: dict[str, Any]  # Предметний payload у JSON-сумісному вигляді.
    metadata: dict[str, Any]  # Повний блок metadata у JSON-сумісному вигляді.
    recorded_at: datetime  # Початковий час вимірювання.
    received_at: datetime  # Час отримання Store-сервісом.
    created_at: datetime  # Час вставки запису в БД.


SmartEnergyPayload = SmartGridPayload
SmartEnergySensor = SmartGridSensor
