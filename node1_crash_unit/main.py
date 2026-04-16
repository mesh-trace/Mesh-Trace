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
IST_OFFSET_MS = 5 * 3600 * 1000 + 30 * 60 * 1000   # 19800000 ms

# Logging
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# NETWORK CHECK
# ──────────────────────────────────────────────

def is_network_available(host="8.8.8.8", port=53, timeout=2):
    try:
        logger.debug("Checking network: host=%s port=%s timeout=%s", host, port, timeout)
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.close()
        logger.debug("Network available")
        return True
    except Exception as e:
        logger.debug("Network unavailable: %s", e)
        return False


# ──────────────────────────────────────────────
# CRASH DETECTION UNIT
# ──────────────────────────────────────────────

class CrashDetectionUnit:

    def __init__(self):
        logger.info("Initializing Mesh-Trace Crash Detection Unit...")

        self.mpu6050            = MPU6050()
        self.impact_sensor      = ImpactSensor(IMPACT_SENSOR_PINS)
        self.temperature_sensor = TemperatureSensor(pin=TEMPERATURE_SENSOR_PIN)
        self.gps_sensor         = GPSSensor(port=GPS_SERIAL_PORT, baudrate=GPS_BAUDRATE)

        self.last_known_gps = None

        self.cloud_client = AWSIoTPublisher(
            certs={
                "ca":   AWS_CA_CERT,
                "cert": AWS_DEVICE_CERT,
                "key":  AWS_PRIVATE_KEY,
            }
        )

        self.lora_tx  = LoRaCrashTX()
        self.blackbox = BlackboxLogger()

        buffer_size      = PRE_CRASH_DURATION * SAMPLE_RATE
        self.data_buffer = deque(maxlen=buffer_size)
        logger.debug("Pre-crash buffer: %d samples (%.1f s)", buffer_size, PRE_CRASH_DURATION)

        self.telemetry_interval  = 60
        self.last_telemetry_time = time.time()

        logger.info("System initialized successfully")

    # ──────────────────────────────────────────
    # SENSOR READ
    # ──────────────────────────────────────────

    def read_all_sensors(self):
        accel       = self.mpu6050.read_acceleration()
        gyro        = self.mpu6050.read_gyroscope()
        temperature = self.temperature_sensor.read()

        gps_raw = self.gps_sensor.get_position()
        if gps_raw and gps_raw.get("fix_quality", 0) > 0:
            self.last_known_gps = {
                "latitude":    gps_raw.get("latitude"),
                "longitude":   gps_raw.get("longitude"),
                "altitude":    gps_raw.get("altitude"),
                "satellites":  gps_raw.get("satellites"),
                "fix_quality": gps_raw.get("fix_quality"),
            }
        else:
            logger.debug("No GPS fix — using cached: %s", self.last_known_gps)

        return {
            "timestamp":     datetime.now(IST).isoformat(),
            "node_id":       NODE_ID,
            "accelerometer": accel,
            "gyroscope":     gyro,
            "temperature":   temperature,
            "gps":           self.last_known_gps,
        }

    # ──────────────────────────────────────────
    # CRASH DETECTION
    # ──────────────────────────────────────────

    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        if not accel:
            return False, None, None

        ax, ay, az = accel["x"], accel["y"], accel["z"]
        accel_mag  = (ax**2 + ay**2 + az**2) ** 0.5

        impact_confirmed = self.impact_sensor.detect_impact(
            accel_magnitude=accel_mag,
            timestamp=time.time(),
        )
        if not impact_confirmed:
            return False, None, None

        if accel_mag < 15:
            severity = "LOW"
        elif accel_mag < 25:
            severity = "MEDIUM"
        else:
            severity = "HIGH"

        logger.info("Crash confirmed: severity=%s accel_mag=%.2f m/s²", severity, accel_mag)
        return True, severity, accel_mag

    # ──────────────────────────────────────────
    # HANDLE CRASH  — unchanged from working version
    # ──────────────────────────────────────────

    def handle_crash(self, sensor_data, severity, accel_mag):
        logger.info("handle_crash: severity=%s accel_mag=%.2f", severity, accel_mag)

        gps = sensor_data.get("gps")
        has_gps_fix = (
            gps is not None
            and gps.get("latitude")  is not None
            and gps.get("longitude") is not None
        )

        crash_payload = {
        "nodeId":    NODE_ID,
        "timestamp": int(time.time() * 1000) + IST_OFFSET_MS,  # UTC + 5:30 in ms
        "type":      "crash",
        "lat":       gps["latitude"]  if has_gps_fix else None,
        "lng":       gps["longitude"] if has_gps_fix else None,
        "severity":  severity.lower(),           # 'low' / 'medium' / 'high'
        }

        logger.info(
            "Crash payload: node_Id=%s severity=%s lat=%s lng=%s",
            crash_payload["nodeId"], crash_payload["severity"],
            crash_payload["lat"], crash_payload["lng"],
        )

        self.blackbox.log_crash(crash_payload)

        if is_network_available():
            if self.cloud_client.safe_publish(crash_payload):
                logger.info("Crash sent to AWS IoT successfully")
            else:
                logger.warning("safe_publish failed → LoRa fallback")
                self.lora_tx.send_payload(crash_payload)
        else:
            logger.warning("No network → LoRa fallback")
            self.lora_tx.send_payload(crash_payload)


    def send_periodic_telemetry(self, sensor_data):
        try:
            accel = sensor_data.get("accelerometer", {})
            ax    = accel.get("x", 0)
            ay    = accel.get("y", 0)
            az    = accel.get("z", 0)
            accel_mag = round((ax**2 + ay**2 + az**2) ** 0.5, 3)

            gps = sensor_data.get("gps")
            has_gps_fix = (
                gps is not None
                and gps.get("latitude")  is not None
                and gps.get("longitude") is not None
            )

            payload = {
            "nodeId":    NODE_ID,
            "timestamp": int(time.time() * 1000) + IST_OFFSET_MS,  # UTC + 5:30 in ms
            "type":      "telemetry",
            "lat":       gps["latitude"]  if has_gps_fix else None,
            "lng":       gps["longitude"] if has_gps_fix else None,
            "battery":   100,
            }

            if not is_network_available():
                logger.warning("Periodic telemetry skipped: network unavailable")
                return

            if self.cloud_client.safe_publish(payload):
                logger.info(
                    "Telemetry published: accel_mag=%.2f gps=%s battery=%s status=online",
                    accel_mag,
                    f"{gps['latitude']:.4f},{gps['longitude']:.4f}"
                    if has_gps_fix else "no fix",
                    payload["battery"],
                )
            else:
                logger.warning("Telemetry publish failed")

        except Exception as e:
            logger.warning("Telemetry error (suppressed): %s", e, exc_info=True)

    # ──────────────────────────────────────────
    # MAIN LOOP
    # ──────────────────────────────────────────

    def run(self):
        interval = 1 / SAMPLE_RATE
        logger.info(
            "Starting loop: sample_rate=%d Hz interval=%.3f s",
            SAMPLE_RATE, interval,
        )
        loop_count = 0

        try:
            while True:
                current_time = time.time()
                loop_count  += 1

                sensor_data = self.read_all_sensors()

                self.blackbox.log(sensor_data, log_type="sensor")
                self.data_buffer.append(sensor_data)

                is_crash, severity, accel_mag = self.detect_crash(sensor_data)

                if is_crash:
                    logger.warning("CRASH DETECTED | Severity: %s", severity)
                    self.handle_crash(sensor_data, severity, accel_mag)
                    time.sleep(5)   # post-crash cooldown

                if current_time - self.last_telemetry_time >= self.telemetry_interval:
                    self.send_periodic_telemetry(sensor_data)
                    self.last_telemetry_time = current_time

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt: shutting down (loop_count=%d)", loop_count)
            self.cleanup()

    # ──────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────

    def cleanup(self):
        logger.info("Cleaning up resources")
        try:
            self.mpu6050.cleanup()
        except Exception as e:
            logger.warning("MPU6050 cleanup error: %s", e)
        try:
            self.gps_sensor.cleanup()
        except Exception as e:
            logger.warning("GPS cleanup error: %s", e)
        self.blackbox.close()
        logger.info("Cleanup done")


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

def main():
    setup_logging()
    logger.info("=" * 60)
    logger.info("Mesh-Trace | Node-1 Crash Detection Unit")
    logger.info("Raspberry Pi Zero WH  |  Timezone: IST (UTC+05:30)")
    logger.info("=" * 60)
    unit = CrashDetectionUnit()
    unit.run()


if __name__ == "__main__":
    main()