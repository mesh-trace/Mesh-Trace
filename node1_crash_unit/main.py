import time
import json
import socket
from datetime import datetime, timezone, timedelta

from .config import (
    NODE_ID,
    IMPACT_THRESHOLD,
    ACCEL_THRESHOLD,
)

from .sensors.mpu6050 import MPU6050
from .sensors.impact_sensor import ImpactSensor
from .sensors.gps import GPS
from .storage.blackbox_logger import BlackboxLogger
from .cloud.mqtt_client import AWSIoTPublisher
from .lora.lora_tx import LoRaCrashTX


# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


def is_network_available():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False


class CrashDetectionUnit:
    def __init__(self):
        print("Initializing Crash Detection Unit...")

        self.mpu = MPU6050()
        self.impact = ImpactSensor()
        self.gps = GPS()

        self.blackbox = BlackboxLogger()
        self.cloud_client = AWSIoTPublisher()
        self.lora_tx = LoRaCrashTX()

        self.data_buffer = []  # pre-crash rolling buffer
        self.buffer_size = 20

        print("Crash Detection Unit initialized successfully")

    def read_sensors(self):
        accel = self.mpu.read_acceleration()
        impact = self.impact.read()
        gps_data = self.gps.get_position()

        sensor_data = {
            "accelerometer": accel,
            "impact": impact,
            "gps": gps_data,
            "node_id": NODE_ID
        }

        return sensor_data

    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        impact = sensor_data.get("impact")

        if not accel:
            return False, "NONE", 0.0

        ax = accel["x"]
        ay = accel["y"]
        az = accel["z"]

        accel_mag = (ax ** 2 + ay ** 2 + az ** 2) ** 0.5
        print(f"[DEBUG] Accel magnitude: {accel_mag:.2f} m/s²")

        if impact and accel_mag >= ACCEL_THRESHOLD:
            if accel_mag >= 25:
                severity = "HIGH"
            elif accel_mag >= 15:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            return True, severity, accel_mag

        return False, "NONE", accel_mag

    def handle_crash(self, sensor_data, severity, accel_mag):
        gps = sensor_data.get("gps")

        crash_payload = {
            "type": "crash_alert",
            "node_id": NODE_ID,
            "timestamp": datetime.now(IST).isoformat(),

            "location": {
                "latitude": gps["latitude"],
                "longitude": gps["longitude"]
            } if gps and gps["latitude"] else None,

            "data": {
                "severity": severity,
                "confidence": round(accel_mag, 2),
                "sensors": sensor_data,
                "pre_crash_buffer": list(self.data_buffer)
            }
        }

        print(f"🚨 CRASH DETECTED | Severity: {severity}")

        self.blackbox.log_crash(crash_payload)

        if is_network_available():
            print("[INFO] Network available → sending to AWS IoT")
            try:
                self.cloud_client.publish(crash_payload)
                print("[SUCCESS] Crash sent to AWS IoT")
            except Exception as e:
                print("[ERROR] AWS failed → fallback to LoRa:", e)
                self.lora_tx.send_payload(crash_payload)
        else:
            print("[WARN] No network → sending crash via LoRa")
            self.lora_tx.send_payload(crash_payload)

    def run(self):
        print("Starting crash detection loop...")

        try:
            while True:
                sensor_data = self.read_sensors()

                self.data_buffer.append(sensor_data)
                if len(self.data_buffer) > self.buffer_size:
                    self.data_buffer.pop(0)

                crash, severity, accel_mag = self.detect_crash(sensor_data)

                if crash:
                    self.handle_crash(sensor_data, severity, accel_mag)
                    time.sleep(5)  # debounce after crash

                time.sleep(0.2)

        except KeyboardInterrupt:
            print("Shutting down gracefully...")
            self.cleanup()

    def cleanup(self):
        self.mpu.cleanup()
        self.impact.cleanup()
        self.gps.cleanup()
        print("Cleanup completed")


def main():
    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()
