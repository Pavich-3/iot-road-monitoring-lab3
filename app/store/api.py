from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, field_validator
from sqlalchemy import BigInteger, Column, DateTime, Float, Integer, MetaData, String, Table, create_engine, delete, insert, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import select

from app.shared.sensor_models import SensorMessage, SensorReadingInDB
from config import POSTGRES_DB, POSTGRES_HOST, POSTGRES_PASSWORD, POSTGRES_PORT, POSTGRES_USER


app = FastAPI(title="IoT Road Monitoring Store")

DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)
engine = create_engine(DATABASE_URL)
metadata = MetaData()

processed_agent_data = Table(
    "processed_agent_data",
    metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("road_state", String),
    Column("x", Float),
    Column("y", Float),
    Column("z", Float),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("timestamp", DateTime),
)

sensor_readings = Table(
    "sensor_readings",
    metadata,
    Column("id", BigInteger, primary_key=True, index=True),  # Первинний ключ універсальної таблиці.
    Column("sensor_id", String, nullable=False),  # Індексований логічний ідентифікатор сенсора.
    Column("sensor_type", String, nullable=False),  # Тип сенсора для фільтрації різних доменів.
    Column("device_id", String, nullable=False),  # Ідентифікатор фізичного пристрою-джерела.
    Column("schema_version", String, nullable=False),  # Версія схеми, що зберігається з кожним повідомленням.
    Column("latitude", Float, nullable=False),  # Винесена з location широта для швидкої фільтрації.
    Column("longitude", Float, nullable=False),  # Винесена з location довгота для швидкої фільтрації.
    Column("altitude_m", Float),  # Необов'язкова винесена висота.
    Column("area", String),  # Необов'язкова винесена назва зони.
    Column("road_segment_id", String),  # Необов'язкова винесена прив'язка до дороги або перехрестя.
    Column("status", String),  # Винесений статус пристрою для моніторингу.
    Column("payload", JSONB, nullable=False),  # Предметний блок вимірювань.
    Column("metadata", JSONB, nullable=False),  # Повний блок технічних метаданих.
    Column("recorded_at", DateTime(timezone=True), nullable=False),  # Початковий час вимірювання.
    Column("received_at", DateTime(timezone=True), nullable=False),  # Час отримання Store-сервісом.
    Column("created_at", DateTime(timezone=True), nullable=False),  # Час вставки запису в БД.
)


class ProcessedAgentDataInDB(BaseModel):
    id: int
    road_state: str
    x: float
    y: float
    z: float
    latitude: float
    longitude: float
    timestamp: datetime


class ProcessedAgentData(BaseModel):
    road_state: str
    x: float
    y: float
    z: float
    latitude: float
    longitude: float
    timestamp: datetime

    @classmethod
    @field_validator("timestamp", mode="before")
    def check_timestamp(cls, value):
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Invalid timestamp format. Expected ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)."
            ) from exc


legacy_subscriptions: set[WebSocket] = set()
sensor_reading_subscriptions: set[WebSocket] = set()

sensor_message_adapter = TypeAdapter(SensorMessage)
sensor_message_batch_adapter = TypeAdapter(list[SensorMessage])


@app.on_event("startup")
def create_tables() -> None:
    # create_all достатньо для лабораторної, бо тут потрібен лише легкий автоматичний bootstrap.
    metadata.create_all(engine)  # Автоматично створюємо таблиці для лабораторного запуску.


@app.websocket("/ws/")
async def legacy_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    legacy_subscriptions.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        legacy_subscriptions.discard(websocket)


@app.websocket("/ws/sensor_readings")
async def sensor_readings_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    sensor_reading_subscriptions.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        sensor_reading_subscriptions.discard(websocket)


async def broadcast_to_subscribers(subscriptions: set[WebSocket], data: dict[str, Any]) -> None:
    disconnected = set()

    for websocket in subscriptions:
        try:
            await websocket.send_json(data)
        except Exception:
            disconnected.add(websocket)

    for websocket in disconnected:
        subscriptions.discard(websocket)


async def send_legacy_data_to_subscribers(data: dict[str, Any]) -> None:
    await broadcast_to_subscribers(legacy_subscriptions, data)


async def send_sensor_reading_to_subscribers(data: dict[str, Any]) -> None:
    await broadcast_to_subscribers(sensor_reading_subscriptions, data)


def processed_agent_data_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row.id,  # Ідентифікатор legacy-запису.
        "road_state": row.road_state,  # Legacy-класифікований стан дороги.
        "x": row.x,  # Legacy-значення осі X.
        "y": row.y,  # Legacy-значення осі Y.
        "z": row.z,  # Legacy-значення осі Z.
        "latitude": row.latitude,  # Legacy-широта.
        "longitude": row.longitude,  # Legacy-довгота.
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,  # Серіалізація часу у формат ISO-8601.
    }


def sensor_reading_row_to_dict(row) -> dict[str, Any]:
    row_data = row._mapping  # Використовуємо SQLAlchemy Row як mapping для читабельного доступу по ключах.
    return {
        "id": row_data["id"],  # Ідентифікатор універсального запису.
        "sensor_id": row_data["sensor_id"],  # Логічний ідентифікатор сенсора.
        "sensor_type": row_data["sensor_type"],  # Значення типу сенсора.
        "device_id": row_data["device_id"],  # Ідентифікатор фізичного пристрою-джерела.
        "schema_version": row_data["schema_version"],  # Збережена версія схеми.
        "latitude": row_data["latitude"],  # Винесена широта.
        "longitude": row_data["longitude"],  # Винесена довгота.
        "altitude_m": row_data["altitude_m"],  # Винесена висота.
        "area": row_data["area"],  # Винесена назва зони.
        "road_segment_id": row_data["road_segment_id"],  # Винесена транспортна прив'язка.
        "status": row_data["status"],  # Винесений статус пристрою.
        "payload": row_data["payload"],  # Блок payload у JSONB.
        "metadata": row_data["metadata"],  # Блок metadata у JSONB.
        "recorded_at": row_data["recorded_at"].isoformat() if row_data["recorded_at"] else None,  # Безпечний для API timestamp.
        "received_at": row_data["received_at"].isoformat() if row_data["received_at"] else None,  # Безпечний для API timestamp.
        "created_at": row_data["created_at"].isoformat() if row_data["created_at"] else None,  # Безпечний для API timestamp.
    }


def sensor_message_to_insert_values(sensor: SensorMessage) -> dict[str, Any]:
    return {
        "sensor_id": sensor.metadata.sensor_id,  # Винесене індексоване поле.
        "sensor_type": sensor.sensor_type.value,  # Винесене індексоване поле.
        "device_id": sensor.metadata.device_id,  # Винесене індексоване поле.
        "schema_version": sensor.schema_version,  # Зберігаємо версію схеми для сумісності.
        "latitude": sensor.location.latitude,  # Винесене поле location.
        "longitude": sensor.location.longitude,  # Винесене поле location.
        "altitude_m": sensor.location.altitude_m,  # Винесене необов'язкове поле.
        "area": sensor.location.area,  # Винесене необов'язкове поле.
        "road_segment_id": sensor.location.road_segment_id,  # Винесене необов'язкове поле.
        "status": sensor.metadata.status,  # Винесений робочий стан.
        "payload": sensor.payload.model_dump(mode="json"),  # Залишаємо payload гнучким у JSONB.
        "metadata": sensor.metadata.model_dump(mode="json"),  # Зберігаємо повний metadata-блок у JSONB.
        "recorded_at": sensor.timestamp,  # Початковий час сенсорного вимірювання.
    }


@app.get("/")
def root():
    return {"message": "IoT Road Monitoring Store API is running"}


@app.post("/processed_agent_data/", response_model=ProcessedAgentDataInDB)
async def create_processed_agent_data(data: ProcessedAgentData):
    with engine.begin() as connection:
        stmt = (
            insert(processed_agent_data)
            .values(
                road_state=data.road_state,
                x=data.x,
                y=data.y,
                z=data.z,
                latitude=data.latitude,
                longitude=data.longitude,
                timestamp=data.timestamp,
            )
            .returning(processed_agent_data)
        )
        row = connection.execute(stmt).fetchone()

    created_item = processed_agent_data_row_to_dict(row)
    await send_legacy_data_to_subscribers(created_item)
    return created_item


@app.get("/processed_agent_data/{processed_agent_data_id}", response_model=ProcessedAgentDataInDB)
def read_processed_agent_data(processed_agent_data_id: int):
    with engine.begin() as connection:
        stmt = select(processed_agent_data).where(
            processed_agent_data.c.id == processed_agent_data_id
        )
        row = connection.execute(stmt).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="ProcessedAgentData not found")

    return processed_agent_data_row_to_dict(row)


@app.get("/processed_agent_data/", response_model=list[ProcessedAgentDataInDB])
def list_processed_agent_data():
    with engine.begin() as connection:
        stmt = select(processed_agent_data).order_by(processed_agent_data.c.id)
        rows = connection.execute(stmt).fetchall()

    return [processed_agent_data_row_to_dict(row) for row in rows]


@app.put("/processed_agent_data/{processed_agent_data_id}", response_model=ProcessedAgentDataInDB)
def update_processed_agent_data(processed_agent_data_id: int, data: ProcessedAgentData):
    with engine.begin() as connection:
        stmt = (
            update(processed_agent_data)
            .where(processed_agent_data.c.id == processed_agent_data_id)
            .values(
                road_state=data.road_state,
                x=data.x,
                y=data.y,
                z=data.z,
                latitude=data.latitude,
                longitude=data.longitude,
                timestamp=data.timestamp,
            )
            .returning(processed_agent_data)
        )
        row = connection.execute(stmt).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="ProcessedAgentData not found")

    return processed_agent_data_row_to_dict(row)


@app.delete("/processed_agent_data/{processed_agent_data_id}", response_model=ProcessedAgentDataInDB)
def delete_processed_agent_data(processed_agent_data_id: int):
    with engine.begin() as connection:
        stmt = (
            delete(processed_agent_data)
            .where(processed_agent_data.c.id == processed_agent_data_id)
            .returning(processed_agent_data)
        )
        row = connection.execute(stmt).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="ProcessedAgentData not found")

    return processed_agent_data_row_to_dict(row)


@app.post("/sensor_readings", response_model=SensorReadingInDB)
async def create_sensor_reading(sensor_reading_raw: dict[str, Any] = Body(...)):
    sensor_reading = sensor_message_adapter.validate_python(sensor_reading_raw)  # Валідуємо один SensorMessage перед вставкою.
    with engine.begin() as connection:
        stmt = (
            insert(sensor_readings)
                .values(**sensor_message_to_insert_values(sensor_reading))  # Перетворюємо повідомлення у формат вставки в БД.
                .returning(sensor_readings)  # Просимо PostgreSQL повернути створений рядок.
            )
        row = connection.execute(stmt).fetchone()

    created_item = sensor_reading_row_to_dict(row)
    await send_sensor_reading_to_subscribers(created_item)
    return created_item


@app.post("/sensor_readings/batch", response_model=list[SensorReadingInDB])
async def create_sensor_readings_batch(sensor_readings_batch_raw: list[dict[str, Any]] = Body(...)):
    sensor_readings_batch = sensor_message_batch_adapter.validate_python(sensor_readings_batch_raw)  # Валідуємо весь batch перед записом.
    if not sensor_readings_batch:
        return []

    created_rows = []
    with engine.begin() as connection:
        for item in sensor_readings_batch:
            stmt = (
                insert(sensor_readings)
                .values(**sensor_message_to_insert_values(item))  # Готуємо окрему вставку для кожного валідного повідомлення.
                .returning(sensor_readings)  # Повертаємо вставлений рядок для response/WebSocket.
            )
            created_rows.append(connection.execute(stmt).fetchone())

    created_items = [sensor_reading_row_to_dict(row) for row in created_rows]
    for item in created_items:
        await send_sensor_reading_to_subscribers(item)
    return created_items


@app.get("/sensor_readings", response_model=list[SensorReadingInDB])
def list_sensor_readings():
    with engine.begin() as connection:
        stmt = select(sensor_readings).order_by(sensor_readings.c.id)
        rows = connection.execute(stmt).fetchall()

    return [sensor_reading_row_to_dict(row) for row in rows]


@app.get("/sensor_readings/{sensor_reading_id}", response_model=SensorReadingInDB)
def read_sensor_reading(sensor_reading_id: int):
    with engine.begin() as connection:
        stmt = select(sensor_readings).where(sensor_readings.c.id == sensor_reading_id)
        row = connection.execute(stmt).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Sensor reading not found")

    return sensor_reading_row_to_dict(row)
