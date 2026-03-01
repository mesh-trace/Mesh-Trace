import json
import logging
import paho.mqtt.client as mqtt    # pyright: ignore[reportMissingImports]
from ..config import AWS_IOT_ENDPOINT, MQTT_TOPIC, MQTT_QOS
from ..config import AWS_CA_CERT, AWS_DEVICE_CERT, AWS_PRIVATE_KEY

logger = logging.getLogger(__name__)

# Paho MQTT return codes for publish() - rc=4 means client not connected
MQTT_RC_MEANINGS = {
    0: "Success (queued)",
    -1: "Connection lost / No connection (MQTT_ERR_NO_CONN)",
    1: "Protocol error",
    2: "Invalid client id",
    3: "Server unavailable",
    4: "Client not connected - connection lost or not yet established",
    5: "Message queue full",
}


def _on_connect(client, userdata, flags, *args):
    """Callback when MQTT client connects or fails to connect. Compatible with paho-mqtt 1.x and 2.x."""
    rc = args[0] if args else 0
    if rc == 0:
        logger.info("MQTT on_connect: CONNECTED successfully")
    else:
        logger.error("MQTT on_connect: FAILED reason_code=%s - %s", rc, mqtt.error_string(rc))


def _on_disconnect(client, userdata, *args):
    """Callback when MQTT client disconnects. Compatible with paho-mqtt 1.x and 2.x."""
    rc = args[0] if args else 0
    if rc == 0:
        logger.info("MQTT on_disconnect: Clean disconnect")
    else:
        logger.warning("MQTT on_disconnect: Unexpected disconnect reason_code=%s - %s", rc, mqtt.error_string(rc))


class AWSIoTPublisher:
    def __init__(self, certs):
        logger.info("Initializing AWS IoT MQTT client: endpoint=%s topic=%s", AWS_IOT_ENDPOINT, MQTT_TOPIC)
        try:
            self.client = mqtt.Client()
            self.client.on_connect = _on_connect
            self.client.on_disconnect = _on_disconnect
            self.client.tls_set(
                ca_certs=certs["ca"],
                certfile=certs["cert"],
                keyfile=certs["key"]
            )
            logger.debug("TLS configured: ca=%s cert=%s key=%s", certs.get("ca"), certs.get("cert"), certs.get("key"))
            self.client.connect(AWS_IOT_ENDPOINT, 8883)
            logger.debug("Connected to AWS IoT endpoint on port 8883")
            self.client.loop_start()
            logger.info("MQTT client loop started")
        except Exception as e:
            logger.error("Failed to initialize AWS IoT MQTT client: %s", e, exc_info=True)
            raise

    def _is_connected(self):
        """Check if MQTT client is connected (may be False briefly after connect until CONNACK)."""
        return getattr(self.client, "is_connected", lambda: False)()

    def publish(self, payload):
        try:
            payload_str = json.dumps(payload)
            payload_len = len(payload_str)

            # Detailed payload logging for debugging
            logger.info(
                "MQTT publish attempt: topic=%s qos=%d payload_len=%d bytes",
                MQTT_TOPIC, MQTT_QOS, payload_len
            )
            logger.debug("Payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else "not dict")
            # Log payload summary (alert, node_id, severity, timestamp) + full payload for small msgs
            summary = {
                "alert": payload.get("alert"),
                "node_id": payload.get("node_id"),
                "severity": payload.get("severity"),
                "timestamp": payload.get("timestamp"),
                "location": payload.get("location"),
                "pre_crash_buffer_len": len(payload.get("pre_crash_buffer", [])) if isinstance(payload.get("pre_crash_buffer"), list) else None,
            }
            logger.info("Payload summary: %s", json.dumps(summary, default=str))
            if payload_len <= 500:
                logger.info("Full payload: %s", payload_str)
            else:
                logger.info("Payload (truncated 500 chars): %s...", payload_str[:500])

            # Check connection state before publish
            connected = self._is_connected()
            logger.info("MQTT connection state before publish: is_connected=%s", connected)
            if not connected:
                logger.error("MQTT client NOT CONNECTED - cannot publish. Check TLS certs, endpoint, network.")

            result = self.client.publish(
                MQTT_TOPIC,
                payload_str,
                qos=MQTT_QOS
            )

            rc_meaning = MQTT_RC_MEANINGS.get(result.rc, f"Unknown rc={result.rc}")
            if result.rc == 0:
                logger.info("MQTT publish queued: topic=%s mid=%s", MQTT_TOPIC, result.mid)
            else:
                logger.error(
                    "MQTT publish failed: rc=%s mid=%s - %s | topic=%s payload_len=%d",
                    result.rc, result.mid, rc_meaning, MQTT_TOPIC, payload_len
                )
                logger.error("Full payload for failed publish: %s", payload_str[:2000])
        except Exception as e:
            logger.error("Exception during MQTT publish: %s", e, exc_info=True)
            raise

