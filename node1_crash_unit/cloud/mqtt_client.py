import json
import logging
import paho.mqtt.client as mqtt    # pyright: ignore[reportMissingImports]
from ..config import AWS_IOT_ENDPOINT, MQTT_TOPIC, MQTT_QOS
from ..config import AWS_CA_CERT, AWS_DEVICE_CERT, AWS_PRIVATE_KEY

logger = logging.getLogger(__name__)


class AWSIoTPublisher:
    def __init__(self, certs):
        logger.info("Initializing AWS IoT MQTT client: endpoint=%s topic=%s", AWS_IOT_ENDPOINT, MQTT_TOPIC)
        try:
            self.client = mqtt.Client()
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

    def publish(self, payload):
        try:
            payload_str = json.dumps(payload)
            logger.debug("Publishing to topic=%s qos=%d payload_len=%d", MQTT_TOPIC, MQTT_QOS, len(payload_str))
            result = self.client.publish(
                MQTT_TOPIC,
                payload_str,
                qos=MQTT_QOS
            )
            if result.rc == 0:
                logger.info("MQTT publish successful: topic=%s msg_id=%s", MQTT_TOPIC, result.mid)
            else:
                logger.error("MQTT publish failed: rc=%s mid=%s", result.rc, result.mid)
        except Exception as e:
            logger.error("Exception during MQTT publish: %s", e, exc_info=True)
            raise

