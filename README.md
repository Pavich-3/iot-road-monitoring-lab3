# IoT Road Monitoring Lab 3

Lab 3 extends the existing pipeline from lab 2 with Grafana dashboards over PostgreSQL.

## Services

- `mqtt` - Eclipse Mosquitto broker
- `postgres_db` - PostgreSQL 16 with `sensor_readings`
- `pgadmin` - DB inspection UI
- `store` - FastAPI persistence API
- `hub` - batch delivery to store
- `edge` - synthetic generation and edge processing
- `grafana` - dashboards for monitoring

## Run

```bash
docker compose -f docker/docker-compose.yaml up --build
```

## Endpoints

- Store API: `http://localhost:8000`
- pgAdmin: `http://localhost:5050`
- Grafana: `http://localhost:3000`

## Grafana Login

- user: `admin`
- password: `admin`

## Provisioned Content

- datasource: `PostgreSQL Road Monitoring`
- dashboards:
  - `System Overview`
  - `Parking Monitoring`
  - `Traffic Monitoring`

## Verification

1. Open Grafana and go to `Connections -> Data sources`.
2. Confirm datasource `PostgreSQL Road Monitoring` is present and healthy.
3. Open `Dashboards -> Lab 3 Monitoring`.
4. Check that charts render after `edge`, `hub`, and `store` start producing data.
