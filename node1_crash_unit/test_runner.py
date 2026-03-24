"""Standalone MQTT publisher for synthetic telemetry/crash payloads (test topic only)."""

import logging
import time
from datetime import datetime, timedelta, timezone

from .cloud import mqtt_client as mqtt_client_module
from .cloud.mqtt_client import AWSIoTPublisher
from .config import (
    AWS_CA_CERT,
    AWS_DEVICE_CERT,
    AWS_PRIVATE_KEY,
    NODE_ID,
)

logger = logging.getLogger(__name__)

TEST_MQTT_TOPIC = "mesh-trace/test-runner"

IST = timezone(timedelta(hours=5, minutes=30))


def get_timestamp() -> str:
    return datetime.now(IST).isoformat()


def build_telemetry():
    return {
        "type": "LIVE_TELEMETRY",
        "node_id": NODE_ID,
        "timestamp": get_timestamp(),
        "temperature": {"temperature": 30, "humidity": 60},
        "accelerometer": {"x": 0.5, "y": 0.2, "z": 9.8},
        "gyroscope": {"x": 0.0, "y": 0.0, "z": 0.0},
        "gps": {
            "latitude": 18.5204,
            "longitude": 73.8567,
            "satellites": 10,
            "fix_quality": 1,
        },
    }


def build_crash():
    return {
        "alert": "VEHICLE_CRASH_DETECTED",
        "node_id": NODE_ID,
        "severity": "HIGH",
        "acceleration_magnitude": 28.5,
        "location": {
            "latitude": 18.5204,
            "longitude": 73.8567,
        },
        "timestamp": get_timestamp(),
    }


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("Test runner starting; MQTT topic overridden to %s", TEST_MQTT_TOPIC)
    mqtt_client_module.MQTT_TOPIC = TEST_MQTT_TOPIC

    publisher = AWSIoTPublisher(
        certs={
            "ca": AWS_CA_CERT,
            "cert": AWS_DEVICE_CERT,
            "key": AWS_PRIVATE_KEY,
        }
    )

    for i in range(1, 5):
        payload = build_telemetry()
        ok = publisher.safe_publish(payload)
        if ok:
            logger.info("Telemetry %d/4 published successfully", i)
        else:
            logger.warning("Telemetry %d/4 publish failed (continuing)", i)
        if i < 4:
            time.sleep(5)

    crash_payload = build_crash()
    ok = publisher.safe_publish(crash_payload)
    if ok:
        logger.info("Crash payload published successfully")
    else:
        logger.warning("Crash payload publish failed (continuing)")

    logger.info("Test runner finished")


if __name__ == "__main__":
    run()
