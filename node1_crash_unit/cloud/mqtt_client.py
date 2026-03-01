import json
import logging
import time
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

# Safe publish retry config
MAX_RETRIES = 3
RECONNECT_WAIT_S = 2
BACKOFF_BASE_S = 1


class AWSIoTPublisher:
    def __init__(self, certs):
        logger.info("Initializing AWS IoT MQTT client: endpoint=%s topic=%s", AWS_IOT_ENDPOINT, MQTT_TOPIC)
        self.connected = False
        try:
            self.client = mqtt.Client()
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
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

    def _on_connect(self, client, userdata, flags, *args):
        """Callback when MQTT client connects or fails. Compatible with paho-mqtt 1.x and 2.x."""
        rc = args[0] if args else 0
        if rc == 0:
            self.connected = True
            logger.info("MQTT on_connect: CONNECTED successfully")
        else:
            self.connected = False
            logger.error("MQTT on_connect: FAILED reason_code=%s - %s", rc, mqtt.error_string(rc))

    def _on_disconnect(self, client, userdata, *args):
        """Callback when MQTT client disconnects. Compatible with paho-mqtt 1.x and 2.x."""
        self.connected = False
        rc = args[0] if args else 0
        if rc == 0:
            logger.info("MQTT on_disconnect: Clean disconnect")
        else:
            logger.warning("MQTT on_disconnect: Unexpected reason_code=%s - %s", rc, mqtt.error_string(rc))

    def _is_connected(self):
        """Check connection state; prefer our flag, fallback to client.is_connected()."""
        return self.connected or getattr(self.client, "is_connected", lambda: False)()

    def safe_publish(self, payload):
        """
        Publish with reconnect and retry. Never raises.
        Returns True if published successfully, False if all retries failed.
        """
        try:
            payload_str = json.dumps(payload)
            payload_len = len(payload_str)
            logger.info("safe_publish: topic=%s qos=%d payload_len=%d", MQTT_TOPIC, MQTT_QOS, payload_len)
        except Exception as e:
            logger.error("safe_publish: payload serialization failed: %s", e)
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if not self._is_connected():
                    logger.warning("safe_publish attempt %d/%d: not connected, reconnecting...", attempt, MAX_RETRIES)
                    try:
                        self.client.reconnect()
                        time.sleep(RECONNECT_WAIT_S)
                    except Exception as e:
                        logger.warning("Reconnect failed: %s", e)
                        if attempt < MAX_RETRIES:
                            delay = BACKOFF_BASE_S * (2 ** (attempt - 1))
                            logger.info("Retrying in %.1fs...", delay)
                            time.sleep(delay)
                        continue

                result = self.client.publish(MQTT_TOPIC, payload_str, qos=MQTT_QOS)
                if result.rc == 0:
                    logger.info("safe_publish: success mid=%s", result.mid)
                    return True
                rc_meaning = MQTT_RC_MEANINGS.get(result.rc, f"Unknown rc={result.rc}")
                logger.warning("safe_publish attempt %d/%d failed: rc=%s - %s", attempt, MAX_RETRIES, result.rc, rc_meaning)
            except Exception as e:
                logger.warning("safe_publish attempt %d/%d exception: %s", attempt, MAX_RETRIES, e, exc_info=True)

            if attempt < MAX_RETRIES:
                delay = BACKOFF_BASE_S * (2 ** (attempt - 1))
                logger.info("Retrying in %.1fs...", delay)
                time.sleep(delay)

        logger.error("safe_publish: all %d attempts failed", MAX_RETRIES)
        return False

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

