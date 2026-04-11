"""
test_crash_payload.py
=====================
Uses only the project's own config + AWSIoTPublisher to send
a hardcoded crash payload — no external dependencies beyond
what main.py already imports.

Place this file inside the node1_crash_unit/ package folder
(same level as main.py), then run from the project root:

    python -m node1_crash_unit.test_crash_payload

Requirements: same as main.py (paho-mqtt, python-dotenv)
"""

import time
import logging

from .config import (
    NODE_ID,
    AWS_CA_CERT,
    AWS_DEVICE_CERT,
    AWS_PRIVATE_KEY,
    setup_logging,
)
from .cloud.mqtt_client import AWSIoTPublisher

# ── Logging ───────────────────────────────────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)

# ── IST offset in milliseconds (UTC + 5:30) ───────────────────────────────────
IST_OFFSET_MS = 5 * 3600 * 1000 + 30 * 60 * 1000   # 19800000 ms

# ── Hardcoded crash payload (exact format from handle_crash in main.py) ───────
CRASH_PAYLOAD = {
    "nodeId":    NODE_ID,
    "timestamp": int(time.time() * 1000) + IST_OFFSET_MS,  # UTC + 5:30 in ms
    "type":      "crash",
    "lat":       18.49831,   # Pune coordinates
    "lng":       73.94994,
    "severity":  "high",     # 'low' / 'medium' / 'high'
}


def main():
    logger.info("=" * 50)
    logger.info("  Mesh-Trace | Test Crash Payload Sender")
    logger.info("=" * 50)
    logger.info("nodeId    : %s", CRASH_PAYLOAD["nodeId"])
    logger.info("timestamp : %s", CRASH_PAYLOAD["timestamp"])
    logger.info("type      : %s", CRASH_PAYLOAD["type"])
    logger.info("lat/lng   : %s / %s", CRASH_PAYLOAD["lat"], CRASH_PAYLOAD["lng"])
    logger.info("severity  : %s", CRASH_PAYLOAD["severity"])
    logger.info("-" * 50)

    # Connect using the project's own AWSIoTPublisher
    client = AWSIoTPublisher(
        certs={
            "ca":   AWS_CA_CERT,
            "cert": AWS_DEVICE_CERT,
            "key":  AWS_PRIVATE_KEY,
        }
    )

    # safe_publish = retries + reconnect, same as main.py uses for crashes
    if client.safe_publish(CRASH_PAYLOAD):
        logger.info("🚀  Crash payload sent successfully!")
        logger.info("    Check CloudWatch / DynamoDB / SNS email")
    else:
        logger.error("💥  Failed to send — check logs above")


if __name__ == "__main__":
    main()