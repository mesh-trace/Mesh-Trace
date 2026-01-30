import json
import time
import paho.mqtt.client as mqtt  
from ..config import AWS_IOT_ENDPOINT, MQTT_TOPIC, MQTT_QOS
from ..config import AWS_CA_CERT, AWS_DEVICE_CERT, AWS_PRIVATE_KEY

class AWSIoTPublisher:
    def __init__(self, certs):
        self.client = mqtt.Client()
        self.client.tls_set(
            ca_certs=certs["ca"],
            certfile=certs["cert"],
            keyfile=certs["key"]
        )
        self.client.connect(AWS_IOT_ENDPOINT, 8883)
        self.client.loop_start()

    def publish(self, payload):
        self.client.publish(
            MQTT_TOPIC,
            json.dumps(payload),
            qos=MQTT_QOS
        )

