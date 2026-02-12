import time
import math
import json
import socket
from datetime import datetime, timezone

from .config import (
    IMPACT_SENSOR_PINS,
    ACCELERATION_THRESHOLD,
    NODE_ID,
    DEBUG_MODE
)

from .sensors.mpu6050 import MPU6050
from .sensors.impact_sensor import ImpactSensor
from .sensors.gps import GPSSensor

from .config import AWS_CA_CERT, AWS_DEVICE_CERT, AWS_PRIVATE_KEY
from .cloud.mqtt_client import AWSIoTPublisher
from .storage.blackbox_logger import BlackboxLogger
from .lora.lora_tx import LoRaCrashTX


class CrashDetectionUnit:
    def __init__(self):
        self.mpu = MPU6050()
        self.impact = ImpactSensor(IMPACT_SENSOR_PINS)
        self.gps = GPSSensor()
        self.blackbox = BlackboxLogger()

        self.aws = AWSIoTPublisher({
            "ca": AWS_CA_CERT,
            "cert": AWS_DEVICE_CERT,
            "key": AWS_PRIVATE_KEY
        })

        self.lora = LoRaCrashTX()

    # ----------------------------
    # Network check
    # ----------------------------
    def network_available(self) -> bool:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            return True
        except OSError:
            return False

    # ----------------------------
    # Severity logic
    # ----------------------------
    def calculate_severity(self, accel_mag: float) -> str:
        if accel_mag < 12:
            return "LOW"
        elif accel_mag < 18:
            return "MEDIUM"
        else:
            return "HIGH"

    # ----------------------------
    # Main loop
    # ----------------------------
    def run(self):
        print("[INFO] Crash Detection Unit started")

        while True:
            accel = self.mpu.read_acceleration()
            impact_event = self.impact.read()

            accel_mag = math.sqrt(
                accel["x"] ** 2 +
                accel["y"] ** 2 +
                accel["z"] ** 2
            )

            if DEBUG_MODE:
                print(f"[DEBUG] Accel magnitude: {accel_mag:.2f} m/s²")

            # ✅ Crash Correlation Logic
            if impact_event and accel_mag >= ACCELERATION_THRESHOLD:
                print("🚨 CRASH DETECTED 🚨")

                severity = self.calculate_severity(accel_mag)
                gps_data = self.gps.get_position()

                timestamp_utc = datetime.now(timezone.utc).isoformat()

                # ✅ LAMBDA-COMPATIBLE PAYLOAD
                payload = {
                    "type": "crash_alert",   # REQUIRED by Lambda
                    "node_id": NODE_ID,
                    "timestamp": timestamp_utc,
                    "location": {
                        "latitude": gps_data["latitude"] if gps_data else None,
                        "longitude": gps_data["longitude"] if gps_data else None
                    },
                    "data": {
                        "severity": severity,
                        "acceleration_magnitude": round(accel_mag, 2)
                    }
                }

                print("[DEBUG] Payload:", json.dumps(payload, indent=2))

                # Always log locally
                self.blackbox.log_crash(payload)
                print("[INFO] Crash event logged locally")

                # Network decision
                if self.network_available():
                    print("[INFO] Network available → sending to AWS IoT")
                    try:
                        self.aws.publish(payload)
                        print("[SUCCESS] Crash sent to AWS IoT")
                    except Exception as e:
                        print("[ERROR] AWS publish failed → sending via LoRa:", e)
                        self.lora.send_payload(payload)
                else:
                    print("[WARN] No network → sending via LoRa")
                    self.lora.send_payload(payload)
                    print("[SUCCESS] Crash sent via LoRa")

                time.sleep(5)  # prevent duplicate alerts

            time.sleep(0.1)


def main():
    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()
