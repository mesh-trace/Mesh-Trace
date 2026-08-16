# MESHTRACE

**A low-cost IoT vehicle crash detection and emergency alert system with LoRa mesh fallback for low-connectivity zones.**

MESH-TRACE detects vehicle crashes in real time using multi-sensor fusion, classifies severity, and delivers alerts to a cloud backend within seconds — over WiFi when available, or over a cooperative LoRa V2V/V2I relay network when it isn't.

![Mesh-Trace Crash Detection System — end-to-end pipeline from vehicle monitoring to cloud alert dashboard](assets/architecture-overview.png)

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Hardware](#hardware)
- [Crash Detection Algorithm](#crash-detection-algorithm)
- [Communication Paths](#communication-paths)
- [Payload Schema](#payload-schema)
- [Cloud Backend](#cloud-backend)
- [Repository Structure](#repository-structure)
- [Setup](#setup)
- [Configuration](#configuration)
- [Running](#running)
- [Testing](#testing)
- [Acknowledgements](#acknowledgements)

---

## Overview

Road accidents remain a leading cause of preventable death, and delayed emergency response is a major contributing factor — especially in rural and semi-urban areas with poor connectivity. MESH-TRACE is a low-cost alternative to proprietary systems like eCall or OnStar, built entirely on off-the-shelf hardware and a serverless AWS backend.

Key features:

- **Multi-sensor fusion** crash detection (MPU6050 accelerometer + SW420 vibration sensors) to minimize false positives
- **Three-tier communication fallback**: direct WiFi → V2I (roadside LoRa relay) → V2V (neighbouring vehicle relay)
- **Serverless AWS backend**: IoT Core, Lambda, DynamoDB, S3, SNS
- **Local blackbox logging** — persistent JSONL logs independent of network availability
- **GPS-tagged, severity-classified crash alerts** delivered via email within ~500 ms–900 ms depending on path

---

## System Architecture

```
Sensors → Node 1 Fusion Engine → Crash Payload
              │
              ├── WiFi/MQTT (primary) ────────────────► AWS IoT Core
              │                                                │
              └── LoRa (fallback) ──► LAP (V2I) or             │
                                       Neighbour Node 1 (V2V) ──┘
                                                                 │
                                                                 ▼
                                              Lambda → DynamoDB / S3 / SNS Email
```

| Component | Hardware | Role |
|---|---|---|
| Node 1 (Vehicle) | Raspberry Pi Zero WH | Crash detector, sensor fusion, primary MQTT publisher, V2V relay candidate |
| LAP (Infrastructure) | ESP32 + SX1278 | V2I relay: fixed roadside LoRa receiver, WiFi uplink to AWS |
| Node 2 (Relay vehicle) | Raspberry Pi Zero WH + SX1278 | V2V relay: neighbouring vehicle, receives LoRa, forwards if connected |
| Cloud | AWS (ap-south-1) | IoT Core, Lambda, DynamoDB, S3, SNS |

---

## Hardware

Node 1 fuses data from four sensors:

| Sensor | Interface | Purpose |
|---|---|---|
| MPU6050 | I2C, up to 100 Hz | Primary crash sensor — X/Y/Z acceleration |
| SW420 (×4) | GPIO (digital) | Physical impact confirmation gate |
| NEO-6M GPS | UART @ 9600 baud | Crash location; last known fix cached on dropout |
| DHT22 | GPIO | Ambient temperature/humidity telemetry only |

LoRa radio: **SX1278**, 433 MHz, SF7, BW 125 kHz, CR 4/5, sync word `0x12`, CRC on, preamble 8 symbols — identical on both Node 1 (Python `SX127x` driver) and the ESP32 relay (`arduino-LoRa`). Any parameter mismatch causes total packet loss.

> **Design note:** `board_config.py` uses a `LazySpiDev` wrapper that delays SPI `open()` until the first transaction, ensuring the GPIO reset pulse completes before the SPI bus opens. Without this, the SX1278 reports SF=0/BW=0 and all register reads are garbage.

---

## Crash Detection Algorithm

Runs inside the 100 Hz main loop on Node 1. Relay nodes (LAPs and V2V vehicles) perform **no** crash detection — they only forward pre-classified events.

**Stage 1 — Acceleration Magnitude Gate**

```
a = √(ax² + ay² + az²)
```

Samples below `T_abs = 5.0 m/s²` are discarded immediately (configurable via `ACCELERATION_THRESHOLD`).

**Stage 2 — Sudden Delta Check**

A rolling baseline (last ~20 samples) filters out constant gravity (~9.8 m/s²). Only a *sudden spike* above baseline (`delta ≥ ACCELERATION_DELTA_THRESHOLD`, default 8.0 m/s²) proceeds — this is what separates a real impact from a steady high reading.

**Stage 3 — SW420 Physical Correlation**

A crash is confirmed only if an SW420 vibration sensor also triggers within a correlation window (±0.5 s / configurable), eliminating false positives from software glitches or slow road bumps. A cooldown period (default 30 s) prevents duplicate alerts after a confirmed crash.

**Severity classification:**

| Band | Acceleration magnitude |
|---|---|
| LOW | < 15 m/s² |
| MEDIUM | 15–25 m/s² |
| HIGH | ≥ 25 m/s² |

---

## Communication Paths

Node 1 does not negotiate a relay path — it transmits opportunistically in priority order:

1. **Direct WiFi/MQTT** — if a TCP probe to `8.8.8.8:53` succeeds, publish directly to AWS IoT Core
2. **V2I (LoRa Access Point)** — nearest fixed roadside ESP32 receives, validates, and relays over its own WiFi
3. **V2V (neighbouring vehicle)** — a nearby Node 1 receives the LoRa packet, checks its own connectivity, and relays on the originating node's behalf (single-hop only)
4. **Local blackbox preservation** — if no relay is reachable, the event is still logged to disk

Both a LAP and a V2V relay may forward the same packet; AWS deduplicates via the DynamoDB composite key `(nodeId, timestamp)`.

---

## Payload Schema

**Crash payload:**
```json
{
  "nodeId": "mesh-trace-node-001",
  "type": "crash",
  "timestamp": 1712345678000,
  "lat": 18.498,
  "lng": 73.949,
  "severity": "high"
}
```

**Telemetry payload** (sent every 60s):
```json
{
  "nodeId": "mesh-trace-node-001",
  "type": "telemetry",
  "timestamp": 1712345678000,
  "lat": 18.498,
  "lng": 73.949,
  "battery": 100
}
```

`timestamp` is always Unix milliseconds shifted to IST (`int(time.time() * 1000) + 19800000`). `severity` is lowercase; `nodeId` is camelCase; `lat`/`lng` are flat floats (`null` if no GPS fix). Relay nodes inject `relay.type` (`'V2I'` or `'V2V'`), `relay.nodeId`, `relay.rssi`, and `relay.snr` — this field is absent on direct WiFi publishes.

All messages publish to `meshtrace/nodes/{nodeId}/data` over MQTT QoS 1 / TLS port 8883.

---

## Cloud Backend

- **AWS IoT Core** — receives MQTT messages on `meshtrace/nodes/+/data`, triggers Lambda via IoT Rule
- **Lambda** (`aws_lambda.py`) — validates payloads, normalizes legacy formats, writes to DynamoDB and S3 independently (isolated try/except so one failure doesn't block the other), and dispatches an SNS email alert
- **DynamoDB** — `Nodes` table (latest state per node) and `Crashes` table (append-only, PK: `nodeId`, SK: `timestamp`)
- **S3** — raw payload archive at `crashes/{nodeId}/{timestamp}.json`
- **SNS** — formatted incident email with severity, coordinates, Google Maps link, and sensor readings at impact

---

## Repository Structure

```
node1_crash_unit/
├── main.py                    # Entry point — main sensor loop, crash handling
├── config.py                  # Environment-driven configuration & thresholds
├── test_runner.py             # Standalone crash payload test sender
├── sensors/
│   ├── mpu6050.py             # I2C accelerometer/gyroscope
│   ├── impact_sensor.py       # SW420 sensor fusion logic
│   ├── temperature.py         # DHT22 interface
│   └── gps.py                 # NEO-6M NMEA parsing
├── storage/
│   └── blackbox_logger.py     # Persistent JSONL logging with rotation
├── cloud/
│   ├── mqtt_client.py         # AWS IoT MQTT publisher (with retry/reconnect)
│   ├── aws_lambda.py          # Lambda handler (crash/health/status processing)
│   └── mqtt_payload_format.json
├── lora/
│   └── lora_tx.py             # SX1278 LoRa transmitter
└── board_config.py            # SPI/GPIO board setup (LazySpiDev fix)

esp32/
└── esp32.ino                  # LAP / V2I-V2V relay firmware (LoRa RX → MQTT)
```

---

## Setup

### Node 1 (Raspberry Pi Zero WH)

**Requirements:** Python 3, I2C/SPI/UART enabled via `raspi-config`

```bash
pip install paho-mqtt python-dotenv smbus2 pynmea2 pyserial RPi.GPIO boto3
```

Clone the [`SX127x` Python driver](https://github.com/mayeranalytics/pySX127x) into a `lora_driver/` folder alongside this project (referenced by `lora_tx.py`).

### ESP32 Relay (LAP / Node 2)

**Arduino libraries:** `WiFi`, `WiFiClientSecure`, `PubSubClient`, `SPI`, `LoRa` (sandeepmistry/arduino-LoRa), `ArduinoJson`, `esp_task_wdt`

Create a `secret.h` with your WiFi credentials, AWS IoT endpoint, thing name, and X.509 certificates (see `secret.h` structure in this repo — **do not commit real credentials**).

### AWS

1. Provision two IoT Things (Pi node + ESP32 relay), each with its own certificate
2. Create an IoT Rule: `SELECT * FROM 'meshtrace/nodes/+/data'` → trigger Lambda
3. Deploy `aws_lambda.py` with environment variables: `S3_BUCKET`, `DYNAMODB_TABLE`, `SNS_TOPIC_ARN`, `NODE_STATUS_TABLE`
4. Create the DynamoDB tables and S3 bucket referenced above

---

## Configuration

All runtime configuration is via environment variables (`.env` file, see `config.py`):

| Variable | Default | Description |
|---|---|---|
| `NODE_ID` | `mesh-trace-node-001` | Unique node identifier |
| `IMPACT_SENSOR_PINS` | `22,23,24,25` | SW420 GPIO pins |
| `ACCELERATION_THRESHOLD` | `5.0` | Stage 1 absolute gate (m/s²) |
| `ACCELERATION_DELTA_THRESHOLD` | `3.0` | Stage 2 sudden-spike delta (m/s²) |
| `CRASH_COOLDOWN_SECONDS` | `10` | Cooldown after confirmed crash |
| `SAMPLE_RATE` | `100` | Main loop frequency (Hz) |
| `AWS_IOT_ENDPOINT` | — | AWS IoT Core endpoint |
| `AWS_CA_CERT` / `AWS_DEVICE_CERT` / `AWS_PRIVATE_KEY` | — | Paths to TLS certs |
| `GPS_SERIAL_PORT` | `/dev/ttyS0` | GPS UART port |
| `BLACKBOX_LOG_PATH` | `./logs/` | Local log directory |

---

## Running

```bash
# On the Raspberry Pi
python -m node1_crash_unit.main
```

Node 1 will initialize sensors, connect to AWS IoT, and begin the 100 Hz sensing loop. On crash confirmation it logs locally, attempts direct publish, and falls back to LoRa if unavailable. Every 60 s it also sends a telemetry heartbeat.

## Testing

A standalone test sender is included to verify the AWS pipeline without triggering a physical crash:

```bash
python -m node1_crash_unit.test_runner
```

This publishes a hardcoded high-severity crash payload using the project's own `AWSIoTPublisher`, useful for validating CloudWatch, DynamoDB, and SNS email delivery end-to-end.

---

## Authors

- **Avdhut Gogawale**
- **Vinaykumar Takankhar**
- **Soham Valunjkar**

Department of Electronics & Telecommunication Engineering, P.E.S's Modern College of Engineering, Pune, India.

## Acknowledgements

Department of Electronics & Telecommunication Engineering, P.E.S's Modern College of Engineering, Pune, and the open-source communities behind `paho-mqtt`, `arduino-LoRa`, `pynmea2`, and the `SX127x` Python driver.

## License

Add a license of your choice (e.g. MIT) before making this repository public.
