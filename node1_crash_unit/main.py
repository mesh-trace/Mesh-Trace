import time
import socket
import logging
from datetime import datetime, timezone, timedelta
from collections import deque

from .config import (
    NODE_ID,
    SAMPLE_RATE,
    PRE_CRASH_DURATION,
    AWS_CA_CERT,
    AWS_DEVICE_CERT,
    AWS_PRIVATE_KEY,
    TEMPERATURE_SENSOR_PIN,
    GPS_SERIAL_PORT,
    GPS_BAUDRATE,
    setup_logging,
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


# Logging
logger = logging.getLogger(__name__)


# NETWORK CHECK

def is_network_available(host="8.8.8.8", port=53, timeout=2):
    try:
        logger.debug("Checking network availability: host=%s port=%s timeout=%s", host, port, timeout)
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.close()
        logger.debug("Network available")
        return True
    except Exception as e:
        logger.debug("Network unavailable: %s", e)
        return False


# CRASH DETECTION UNIT

class CrashDetectionUnit:
    def __init__(self):
        logger.info("Initializing Mesh-Trace Crash Detection Unit...")

        # Sensors
        logger.debug("Initializing sensors: MPU6050, ImpactSensor, TemperatureSensor, GPSSensor")
        self.mpu6050 = MPU6050()
        self.impact_sensor = ImpactSensor(IMPACT_SENSOR_PINS)
        self.temperature_sensor = TemperatureSensor(pin=TEMPERATURE_SENSOR_PIN)
        self.gps_sensor = GPSSensor(port=GPS_SERIAL_PORT, baudrate=GPS_BAUDRATE)
        logger.debug("Sensors initialized")

        # GPS cache
        self.last_known_gps = None

        # Cloud
        logger.debug("Initializing AWS IoT MQTT client")
        self.cloud_client = AWSIoTPublisher(
            certs={
                "ca": AWS_CA_CERT,
                "cert": AWS_DEVICE_CERT,
                "key": AWS_PRIVATE_KEY
            }
        )

        # LoRa
        logger.debug("Initializing LoRa transmitter")
        self.lora_tx = LoRaCrashTX()

        # Blackbox
        logger.debug("Initializing blackbox logger")
        self.blackbox = BlackboxLogger()

        # Pre-crash buffer
        buffer_size = PRE_CRASH_DURATION * SAMPLE_RATE
        self.data_buffer = deque(maxlen=buffer_size)
        logger.debug("Pre-crash buffer size: %d samples (%.1f s)", buffer_size, PRE_CRASH_DURATION)

        logger.info("System initialized successfully")

    # SENSOR READ

    def read_all_sensors(self):
        logger.debug("Reading all sensors")
        accel = self.mpu6050.read_acceleration()
        gyro = self.mpu6050.read_gyroscope()
        temperature = self.temperature_sensor.read()
        logger.debug("Accel=%s Gyro=%s Temp=%s", accel, gyro, temperature)

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
            logger.debug("GPS fix: lat=%s lon=%s sats=%s", self.last_known_gps.get("latitude"), self.last_known_gps.get("longitude"), self.last_known_gps.get("satellites"))
        else:
            logger.debug("No GPS fix, using last_known_gps=%s", self.last_known_gps)

        data = {
            "timestamp": datetime.now(IST).isoformat(),
            "node_id": NODE_ID,
            "accelerometer": accel,
            "gyroscope": gyro,
            "temperature": temperature,
            "gps": self.last_known_gps
        }
        logger.debug("Sensor data assembled: timestamp=%s", data["timestamp"])
        return data

    # CRASH CORRELATION (MPU6050 + SW420)

    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        if not accel:
            logger.debug("detect_crash: no accelerometer data, skipping")
            return False, None, None

        ax, ay, az = accel["x"], accel["y"], accel["z"]
        accel_mag = (ax ** 2 + ay ** 2 + az ** 2) ** 0.5
        logger.debug("Accel magnitude: %.2f m/s² (x=%.2f y=%.2f z=%.2f)", accel_mag, ax, ay, az)

        impact_confirmed = self.impact_sensor.detect_impact(
            accel_magnitude=accel_mag,
            timestamp=time.time()
        )

        if not impact_confirmed:
            logger.debug("Impact not confirmed (SB420 + accel correlation failed)")
            return False, None, None

        # Severity logic
        if accel_mag < 15:
            severity = "LOW"
        elif accel_mag < 25:
            severity = "MEDIUM"
        else:
            severity = "HIGH"
        logger.info("Crash confirmed: severity=%s accel_mag=%.2f m/s²", severity, accel_mag)

        return True, severity, accel_mag

    # HANDLE CRASH

    def handle_crash(self, sensor_data, severity, accel_mag):
        logger.info("handle_crash: severity=%s accel_mag=%.2f", severity, accel_mag)
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
        logger.debug("Crash payload: location=%s buffer_len=%d", crash_payload.get("location"), len(crash_payload.get("pre_crash_buffer", [])))

        # Always log locally
        logger.debug("Logging crash to blackbox")
        self.blackbox.log_crash(crash_payload)

        if is_network_available():
            logger.info("Network available → sending to AWS IoT")
            try:
                self.cloud_client.publish(crash_payload)
                logger.info("Crash sent to AWS IoT successfully")
            except Exception as e:
                logger.error("AWS publish failed, falling back to LoRa: %s", e, exc_info=True)
                self.lora_tx.send_payload(crash_payload)
        else:
            logger.warning("No network → sending crash via LoRa relay")
            self.lora_tx.send_payload(crash_payload)

    # MAIN LOOP

    def run(self):
        interval = 1 / SAMPLE_RATE
        logger.info("Starting crash detection loop: sample_rate=%d Hz interval=%.3f s", SAMPLE_RATE, interval)
        loop_count = 0

        try:
            while True:
                loop_count += 1
                logger.debug("Loop iteration %d", loop_count)

                sensor_data = self.read_all_sensors()

                self.blackbox.log(sensor_data, log_type="sensor")
                self.data_buffer.append(sensor_data)
                logger.debug("Buffer size: %d/%d", len(self.data_buffer), self.data_buffer.maxlen)

                is_crash, severity, accel_mag = self.detect_crash(sensor_data)

                if is_crash:
                    logger.warning("CRASH DETECTED | Severity: %s", severity)
                    self.handle_crash(sensor_data, severity, accel_mag)
                    logger.debug("Post-crash cooldown: sleeping 5s")
                    time.sleep(5)

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt: shutting down gracefully (loop_count=%d)", loop_count)
            self.cleanup()

    # CLEANUP

    def cleanup(self):
        logger.info("Cleaning up resources")
        try:
            self.mpu6050.cleanup()
            logger.debug("MPU6050 cleanup done")
        except Exception as e:
            logger.warning("MPU6050 cleanup error: %s", e)

        try:
            self.gps_sensor.cleanup()
            logger.debug("GPS cleanup done")
        except Exception as e:
            logger.warning("GPS cleanup error: %s", e)

        self.blackbox.close()
        logger.info("Resources cleaned up")


# ENTRY POINT
def main():
    setup_logging()
    logger.info("=" * 60)
    logger.info("Mesh-Trace | Node-1 Crash Detection Unit")
    logger.info("Raspberry Pi Zero WH")
    logger.info("Timezone: IST (UTC +05:30)")
    logger.info("=" * 60)

    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()
