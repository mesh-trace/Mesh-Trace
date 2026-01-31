import time
from datetime import datetime, timezone
from collections import deque

from .config import (
    NODE_ID,
    SAMPLE_RATE,
    PRE_CRASH_DURATION,
    IMPACT_THRESHOLD,
    AWS_CA_CERT,
    AWS_DEVICE_CERT,
    AWS_PRIVATE_KEY
)

from .sensors.mpu6050 import MPU6050
from .sensors.impact_sensor import ImpactSensor
from .config import IMPACT_SENSOR_PINS
from .sensors.temperature import TemperatureSensor
from .sensors.gps import GPSSensor

from .storage.blackbox_logger import BlackboxLogger
from .cloud.mqtt_client import AWSIoTPublisher


class CrashDetectionUnit:
    def __init__(self):
        print("Initializing Crash Detection Unit...")

        # Sensors
        self.mpu6050 = MPU6050()
        self.impact_sensor = ImpactSensor(IMPACT_SENSOR_PINS)
        self.temperature_sensor = TemperatureSensor()
        self.gps_sensor = GPSSensor()

        # Cache last valid GPS fix ✅
        self.last_known_gps = None

        # Cloud
        self.cloud_client = AWSIoTPublisher(
            certs={
                "ca": AWS_CA_CERT,
                "cert": AWS_DEVICE_CERT,
                "key": AWS_PRIVATE_KEY
            }
        )

        # Blackbox
        self.blackbox = BlackboxLogger()

        # Pre-crash buffer
        self.data_buffer = deque(
            maxlen=PRE_CRASH_DURATION * SAMPLE_RATE
        )

        print("Crash Detection Unit initialized successfully")

    # --------------------------------------------------
    # SENSOR COLLECTION
    # --------------------------------------------------
    def read_all_sensors(self):
        accel = self.mpu6050.read_acceleration()
        gyro = self.mpu6050.read_gyroscope()
        impact = self.impact_sensor.read()
        temperature = self.temperature_sensor.read()

        # ✅ GPS WITH CACHE (FIX)
        gps_raw = self.gps_sensor.get_position()

        if gps_raw and gps_raw.get("fix_quality", 0) > 0:
            self.last_known_gps = {
                "latitude": gps_raw.get("latitude"),
                "longitude": gps_raw.get("longitude"),
                "altitude": gps_raw.get("altitude"),
                "satellites": gps_raw.get("satellites"),
                "fix_quality": gps_raw.get("fix_quality"),
            }

        gps = self.last_known_gps

        if gps:
            print(f"[DEBUG] Using GPS lat={gps['latitude']}, lon={gps['longitude']}")
        else:
            print("[DEBUG] GPS not fixed yet")

        sensor_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": NODE_ID,
            "impact": impact,
            "accelerometer": accel,
            "gyroscope": gyro,
            "temperature": temperature,
            "gps": gps
        }

        return sensor_data

    # --------------------------------------------------
    # CRASH DETECTION
    # --------------------------------------------------
    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        impact = sensor_data.get("impact")

        if not accel:
            return False, 0.0

        ax = accel["x"]
        ay = accel["y"]
        az = accel["z"]

        accel_mag = (ax**2 + ay**2 + az**2) ** 0.5
        print(f"[DEBUG] accel_mag = {accel_mag:.2f} m/s²")

        if accel_mag >= IMPACT_THRESHOLD or impact:
            return True, 0.95

        return False, 0.0

    # --------------------------------------------------
    # HANDLE CRASH
    # --------------------------------------------------
    def handle_crash(self, sensor_data, confidence):
        gps = sensor_data.get("gps")

        location = {
            "latitude": gps["latitude"],
            "longitude": gps["longitude"]
        } if gps else None

        crash_payload = {
            "alert": "VEHICLE CRASH DETECTED",
            "node_id": NODE_ID,
            "confidence": confidence,
            "location": location,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "crash_data": sensor_data,
            "pre_crash_buffer": list(self.data_buffer)
        }

        print("[DEBUG] Crash payload GPS:", location)

        try:
            self.cloud_client.publish(crash_payload)
            print("Crash alert sent to cloud")
        except Exception as e:
            print("Cloud publish failed:", e)

        self.blackbox.log_crash(crash_payload)

    # --------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------
    def run(self):
        print("Starting crash detection loop...")
        interval = 1 / SAMPLE_RATE

        try:
            while True:
                sensor_data = self.read_all_sensors()

                self.blackbox.log(sensor_data, log_type="sensor")
                self.data_buffer.append(sensor_data)

                is_crash, confidence = self.detect_crash(sensor_data)

                if is_crash:
                    print("🚨 CRASH DETECTED 🚨")
                    self.handle_crash(sensor_data, confidence)
                    time.sleep(5)

                time.sleep(interval)

        except KeyboardInterrupt:
            print("Shutting down gracefully...")
            self.cleanup()

    # --------------------------------------------------
    # CLEANUP
    # --------------------------------------------------
    def cleanup(self):
        try:
            self.mpu6050.cleanup()
        except Exception:
            pass

        try:
            self.gps_sensor.cleanup()
        except Exception:
            pass

        self.blackbox.close()
        print("Resources cleaned up")


def main():
    print("=" * 50)
    print("Mesh-Trace | Node-1 Crash Detection Unit")
    print("Raspberry Pi Zero WH")
    print("=" * 50)

    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()
