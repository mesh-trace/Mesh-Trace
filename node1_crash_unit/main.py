import time
import socket
from datetime import datetime, timezone, timedelta
from collections import deque

from .config import (
    NODE_ID,
    SAMPLE_RATE,
    PRE_CRASH_DURATION,
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

from .lora.lora_tx import LoRaCrashTX



# TIMEZONE (IST)

IST = timezone(timedelta(hours=5, minutes=30))


# NETWORK CHECK

def is_network_available(host="8.8.8.8", port=53, timeout=2):
    try:
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


# CRASH DETECTION UNIT

class CrashDetectionUnit:
    def __init__(self):
        print("Initializing Mesh-Trace Crash Detection Unit...")

        # Sensors
        self.mpu6050 = MPU6050()
        self.impact_sensor = ImpactSensor(IMPACT_SENSOR_PINS)
        self.temperature_sensor = TemperatureSensor()
        self.gps_sensor = GPSSensor()

        # GPS cache
        self.last_known_gps = None

        # Cloud
        self.cloud_client = AWSIoTPublisher(
            certs={
                "ca": AWS_CA_CERT,
                "cert": AWS_DEVICE_CERT,
                "key": AWS_PRIVATE_KEY
            }
        )

        # LoRa
        self.lora_tx = LoRaCrashTX()

        # Blackbox
        self.blackbox = BlackboxLogger()

        # Pre-crash buffer
        self.data_buffer = deque(
            maxlen=PRE_CRASH_DURATION * SAMPLE_RATE
        )

        print("System initialized successfully")

    # SENSOR READ

    def read_all_sensors(self):
        accel = self.mpu6050.read_acceleration()
        gyro = self.mpu6050.read_gyroscope()
        temperature = self.temperature_sensor.read()

        # GPS with cache
        gps_raw = self.gps_sensor.get_position()
        if gps_raw and gps_raw.get("fix_quality", 0) > 0:
            self.last_known_gps = {
                "latitude": gps_raw.get("latitude"),
                "longitude": gps_raw.get("longitude"),
                "altitude": gps_raw.get("altitude"),
                "satellites": gps_raw.get("satellites"),
                "fix_quality": gps_raw.get("fix_quality"),
            }

        return {
            "timestamp": datetime.now(IST).isoformat(),
            "node_id": NODE_ID,
            "accelerometer": accel,
            "gyroscope": gyro,
            "temperature": temperature,
            "gps": self.last_known_gps
        }

    # CRASH CORRELATION (MPU6050 + SW420)

    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        if not accel:
            return False, None, None

        ax, ay, az = accel["x"], accel["y"], accel["z"]
        accel_mag = (ax ** 2 + ay ** 2 + az ** 2) ** 0.5

        print(f"[DEBUG] Accel magnitude: {accel_mag:.2f} m/s²")

        impact_confirmed = self.impact_sensor.detect_impact(
            accel_magnitude=accel_mag,
            timestamp=time.time()
        )

        if not impact_confirmed:
            return False, None, None

        # Severity logic
        if accel_mag < 15:
            severity = "LOW"
        elif accel_mag < 25:
            severity = "MEDIUM"
        else:
            severity = "HIGH"

        return True, severity, accel_mag

    # HANDLE CRASH

    def handle_crash(self, sensor_data, severity, accel_mag):
        gps = sensor_data.get("gps")

        crash_payload = {
            "alert": "VEHICLE_CRASH_DETECTED",
            "node_id": NODE_ID,
            "severity": severity,
            "acceleration_magnitude": round(accel_mag, 2),
            "location": {
                "latitude": gps["latitude"],
                "longitude": gps["longitude"]
            } if gps else None,
            "timestamp": datetime.now(IST).isoformat(),
            "crash_data": sensor_data,
            "pre_crash_buffer": list(self.data_buffer)
        }

        # Always log locally
        self.blackbox.log_crash(crash_payload)

        if is_network_available():
            print("[INFO] Network available → sending to AWS IoT")
            try:
                self.cloud_client.publish(crash_payload)
                print("[SUCCESS] Crash sent to AWS IoT")
            except Exception as e:
                print("[ERROR] AWS publish failed, falling back to LoRa:", e)
                self.lora_tx.send_payload(crash_payload)
        else:
            print("[WARN] No network → sending crash via LoRa relay")
            self.lora_tx.send_payload(crash_payload)

    # MAIN LOOP

    def run(self):
        print("Starting crash detection loop...")
        interval = 1 / SAMPLE_RATE

        try:
            while True:
                sensor_data = self.read_all_sensors()

                self.blackbox.log(sensor_data, log_type="sensor")
                self.data_buffer.append(sensor_data)

                is_crash, severity, accel_mag = self.detect_crash(sensor_data)

                if is_crash:
                    print(f"🚨 CRASH DETECTED | Severity: {severity}")
                    self.handle_crash(sensor_data, severity, accel_mag)
                    time.sleep(5)

                time.sleep(interval)

        except KeyboardInterrupt:
            print("Shutting down gracefully...")
            self.cleanup()

    # CLEANUP

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


# ENTRY POINT
def main():
    print("=" * 60)
    print("Mesh-Trace | Node-1 Crash Detection Unit")
    print("Raspberry Pi Zero WH")
    print("Timezone: IST (UTC +05:30)")
    print("=" * 60)

    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()
