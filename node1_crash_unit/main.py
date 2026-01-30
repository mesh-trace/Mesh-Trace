"""
Main crash detection loop for Node 1 (Raspberry Pi Zero WH)

Flow:
1. Read sensors continuously
2. Detect crash
3. Always log locally (blackbox)
4. IF internet available:
       → Send data directly to AWS IoT (MQTT)
   ELSE:
       → Send data via LoRa to relay node (Node-2)
"""

import json
import time
import signal
import sys
import socket
from collections import deque
from datetime import datetime

from config import *

from sensors.impact_sensor import ImpactSensor
from sensors.mpu6050 import MPU6050
from sensors.temperature import TemperatureSensor
from sensors.gps import GPSSensor

from lora.lora_tx import LoRaTransmitter
from storage.blackbox_logger import BlackboxLogger

from cloud.mqtt_client import AWSIoTPublisher   # you already planned this


# -------------------------------------------------------------------
# Internet connectivity check
# -------------------------------------------------------------------
def is_internet_available(host="8.8.8.8", port=53, timeout=2):
    """
    Lightweight internet connectivity check
    Returns True if internet is available
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False


# -------------------------------------------------------------------
# Crash Detection Unit
# -------------------------------------------------------------------
class CrashDetectionUnit:

    def __init__(self):
        print("Initializing Crash Detection Unit...")

        # Sensors
        self.impact_sensor = ImpactSensor(IMPACT_SENSOR_PINS)
        self.mpu6050 = MPU6050(MPU6050_I2C_ADDRESS, MPU6050_I2C_BUS)
        self.temperature_sensor = TemperatureSensor(TEMPERATURE_SENSOR_PIN)
        self.gps_sensor = GPSSensor(GPS_SERIAL_PORT, GPS_BAUDRATE)

        # LoRa (fallback path)
        self.lora_tx = LoRaTransmitter(
            frequency=LORA_FREQUENCY,
            spreading_factor=LORA_SPREADING_FACTOR,
            bandwidth=LORA_BANDWIDTH,
            coding_rate=LORA_CODING_RATE,
            power=LORA_POWER,
            cs_pin=LORA_CS_PIN,
            reset_pin=LORA_RESET_PIN,
            dio0_pin=LORA_DIO0_PIN
        )

        # Cloud MQTT (primary path)
        self.cloud_client = AWSIoTPublisher({
            "ca": AWS_CA_CERT,  
            "cert": AWS_DEVICE_CERT,    
            "key": AWS_PRIVATE_KEY  
        })

        # Storage
        self.blackbox = BlackboxLogger(BLACKBOX_LOG_PATH)

        # Pre-crash buffer
        self.data_buffer = deque(maxlen=BUFFER_SIZE)

        self.running = True

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        print("Crash Detection Unit initialized successfully")

    # ----------------------------------------------------------------
    def signal_handler(self, sig, frame):
        print("\nShutting down gracefully...")
        self.running = False
        self.cleanup()
        sys.exit(0)

    # ----------------------------------------------------------------
    def read_all_sensors(self):
        try:
            return {
                "timestamp": datetime.now().isoformat(),
                "impact": self.impact_sensor.read(),
                "accelerometer": self.mpu6050.read_acceleration(),
                "gyroscope": self.mpu6050.read_gyroscope(),
                "temperature": self.temperature_sensor.read(),
                "gps": self.gps_sensor.get_position(),
                "node_id": NODE_ID
            }
        except Exception as e:
            print(f"Sensor read error: {e}")
            return None

    # ----------------------------------------------------------------
    def detect_crash(self, sensor_data):
        """
        Simple threshold-based crash detection (testing phase)
        """
        if not sensor_data:
            return False, 0.0

        if sensor_data["impact"] and sensor_data["impact"] > IMPACT_THRESHOLD:
            return True, 0.95

        return False, 0.0

    # ----------------------------------------------------------------
    def handle_crash(self, sensor_data, confidence):
        print(f"🚨 CRASH DETECTED | Confidence: {confidence:.2f}")

        crash_package = {
            "type": "crash_alert",
            "node_id": NODE_ID,
            "timestamp": datetime.now().isoformat(),
            "confidence": confidence,
            "crash_data": sensor_data,
            "pre_crash_buffer": list(self.data_buffer)[
                -PRE_CRASH_DURATION * SAMPLE_RATE:
            ]
        }

        # Always log locally
        self.blackbox.log_crash(crash_package)

        # Decide path
        if is_internet_available():
            print("🌐 Internet available → sending directly to cloud")

            self.cloud_client.publish(crash_package)
            print("✅ Crash data sent to AWS IoT")

        else:
            print("📡 No internet → sending via LoRa relay")

            self.lora_tx.send(json.dumps(crash_package))
            print("📤 Crash data transmitted via LoRa")

    # ----------------------------------------------------------------
    def run(self):
        print("Starting crash detection loop...")
        sample_interval = 1.0 / SAMPLE_RATE

        while self.running:
            loop_start = time.time()

            sensor_data = self.read_all_sensors()
            if sensor_data:
                self.data_buffer.append(sensor_data)
                self.blackbox.log(sensor_data, log_type="sensor")

                is_crash, confidence = self.detect_crash(sensor_data)
                if is_crash:
                    self.handle_crash(sensor_data, confidence)

            elapsed = time.time() - loop_start
            time.sleep(max(0, sample_interval - elapsed))

    # ----------------------------------------------------------------
    def cleanup(self):
        print("Cleaning up resources...")
        self.impact_sensor.cleanup()
        self.mpu6050.cleanup()
        self.temperature_sensor.cleanup()
        self.gps_sensor.cleanup()
        self.lora_tx.cleanup()
        self.blackbox.close()


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------
def main():
    print("=" * 50)
    print("Mesh-Trace | Node-1 Crash Detection Unit")
    print("Raspberry Pi Zero WH")
    print("=" * 50)

    unit = CrashDetectionUnit()

    try:
        unit.run()
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        unit.cleanup()


if __name__ == "__main__":
    main()
