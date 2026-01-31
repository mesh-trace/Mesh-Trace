import time
from datetime import datetime
from collections import deque

from config import (
    NODE_ID,
    SAMPLE_RATE,
    PRE_CRASH_DURATION,
    IMPACT_THRESHOLD,
)

from sensors.mpu6050 import MPU6050
from sensors.impact_sensor import ImpactSensor
from sensors.temperature import TemperatureSensor
from sensors.gps import GPSSensor

from storage.blackbox_logger import BlackboxLogger
from cloud.mqtt_client import AWSIoTPublisher


class CrashDetectionUnit:
    def __init__(self):
        print("Initializing Crash Detection Unit...")

        # Sensors
        self.mpu6050 = MPU6050()
        self.impact_sensor = ImpactSensor()
        self.temperature_sensor = TemperatureSensor()
        self.gps_sensor = GPSSensor()

        # Cloud
        self.cloud_client = AWSIoTPublisher()

        # Blackbox
        self.blackbox = BlackboxLogger()

        # Circular buffer for pre-crash data
        self.data_buffer = deque(
            maxlen=PRE_CRASH_DURATION * SAMPLE_RATE
        )

        print("Crash Detection Unit initialized successfully")

    # -----------------------------
    # SENSOR COLLECTION
    # -----------------------------
    def read_all_sensors(self):
        accel = self.mpu6050.read_acceleration()
        gyro = self.mpu6050.read_gyroscope()
        impact = self.impact_sensor.read()
        temperature = self.temperature_sensor.read()

        # ---- GPS (FIXED) ----
        gps_raw = self.gps_sensor.get_position()

        if gps_raw and gps_raw.get("fix_quality", 0) > 0:
            gps = {
                "latitude": gps_raw.get("latitude"),
                "longitude": gps_raw.get("longitude"),
                "altitude": gps_raw.get("altitude"),
                "satellites": gps_raw.get("satellites"),
                "fix_quality": gps_raw.get("fix_quality"),
            }
        else:
            gps = None

        sensor_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "impact": impact,
            "accelerometer": accel,
            "gyroscope": gyro,
            "temperature": temperature,
            "gps": gps,
            "node_id": NODE_ID,
        }

        return sensor_data

    # -----------------------------
    # CRASH DETECTION LOGIC
    # -----------------------------
    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        impact = sensor_data.get("impact")

        if not accel:
            return False, 0.0

        ax = accel["x"]
        ay = accel["y"]
        az = accel["z"]

        accel_mag = (ax ** 2 + ay ** 2 + az ** 2) ** 0.5
        print(f"[DEBUG] accel_mag = {accel_mag:.2f} m/s²")

        if accel_mag >= IMPACT_THRESHOLD or impact:
            return True, 0.95

        return False, 0.0

    # -----------------------------
    # CRASH HANDLER
    # -----------------------------
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
            "timestamp": datetime.utcnow().isoformat(),
            "crash_data": sensor_data,
            "pre_crash_buffer": list(self.data_buffer)
        }

        print("[DEBUG] Crash GPS location:", location)

        # Send to cloud (primary path)
        try:
            self.cloud_client.publish(crash_payload)
            print("Crash alert sent to cloud")
        except Exception as e:
            print("Cloud publish failed:", e)
            print("Fallback (LoRa / mesh) can be triggered here")

        # Log to blackbox
        self.blackbox.log_event(crash_payload)

    # -----------------------------
    # MAIN LOOP
    # -----------------------------
    def run(self):
        print("Starting crash detection loop...")
        interval = 1 / SAMPLE_RATE

        try:
            while True:
                sensor_data = self.read_all_sensors()

                self.data_buffer.append(sensor_data)
                self.blackbox.log_data(sensor_data)

                is_crash, confidence = self.detect_crash(sensor_data)

                if is_crash:
                    print("🚨 CRASH DETECTED 🚨")
                    self.handle_crash(sensor_data, confidence)
                    time.sleep(5)  # prevent repeated alerts

                time.sleep(interval)

        except KeyboardInterrupt:
            print("Shutting down gracefully...")
            self.cleanup()

    # -----------------------------
    # CLEANUP
    # -----------------------------
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


# -----------------------------
# ENTRY POINT
# -----------------------------
def main():
    print("=" * 50)
    print("Mesh-Trace | Node-1 Crash Detection Unit")
    print("Raspberry Pi Zero WH")
    print("=" * 50)

    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()
