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

        # Sensors
        logger.debug("Initializing sensors: MPU6050, ImpactSensor, TemperatureSensor, GPSSensor")
        self.mpu6050           = MPU6050()
        self.impact_sensor     = ImpactSensor(IMPACT_SENSOR_PINS)
        self.temperature_sensor = TemperatureSensor(pin=TEMPERATURE_SENSOR_PIN)
        self.gps_sensor        = GPSSensor(port=GPS_SERIAL_PORT, baudrate=GPS_BAUDRATE)
        logger.debug("Sensors initialized")

        # GPS cache — reuse last known fix when current read has no fix
        self.last_known_gps = None

        # Cloud MQTT
        logger.debug("Initializing AWS IoT MQTT client")
        self.cloud_client = AWSIoTPublisher(
            certs={
                "ca":   AWS_CA_CERT,
                "cert": AWS_DEVICE_CERT,
                "key":  AWS_PRIVATE_KEY,
            }
        )

        # LoRa fallback
        logger.debug("Initializing LoRa transmitter")
        self.lora_tx = LoRaCrashTX()

        # Blackbox local storage
        logger.debug("Initializing blackbox logger")
        self.blackbox = BlackboxLogger()

        # Pre-crash ring buffer
        buffer_size = PRE_CRASH_DURATION * SAMPLE_RATE
        self.data_buffer = deque(maxlen=buffer_size)
        logger.debug("Pre-crash buffer: %d samples (%.1f s)", buffer_size, PRE_CRASH_DURATION)

        # Telemetry timer — send live sensor data every 60 s for dashboard
        self.telemetry_interval  = 60
        self.last_telemetry_time = time.time()

        logger.info("System initialized successfully")

    # ──────────────────────────────────────────
    # SENSOR READ
    # ──────────────────────────────────────────

    def read_all_sensors(self):
        logger.debug("Reading all sensors")
        accel       = self.mpu6050.read_acceleration()
        gyro        = self.mpu6050.read_gyroscope()
        temperature = self.temperature_sensor.read()
        logger.debug("Accel=%s Gyro=%s Temp=%s", accel, gyro, temperature)

        # GPS with last-known-fix cache
        gps_raw = self.gps_sensor.get_position()
        if gps_raw and gps_raw.get("fix_quality", 0) > 0:
            self.last_known_gps = {
                "latitude":    gps_raw.get("latitude"),
                "longitude":   gps_raw.get("longitude"),
                "altitude":    gps_raw.get("altitude"),
                "satellites":  gps_raw.get("satellites"),
                "fix_quality": gps_raw.get("fix_quality"),
            }
            logger.debug(
                "GPS fix: lat=%s lon=%s sats=%s",
                self.last_known_gps.get("latitude"),
                self.last_known_gps.get("longitude"),
                self.last_known_gps.get("satellites"),
            )
        else:
            logger.debug("No GPS fix — using cached: %s", self.last_known_gps)

        data = {
            "timestamp":     datetime.now(IST).isoformat(),
            "node_id":       NODE_ID,
            "accelerometer": accel,
            "gyroscope":     gyro,
            "temperature":   temperature,
            "gps":           self.last_known_gps,
        }
        logger.debug("Sensor data assembled: timestamp=%s", data["timestamp"])
        return data

    # ──────────────────────────────────────────
    # CRASH DETECTION (MPU6050 + SW420 fusion)
    # ──────────────────────────────────────────

    def detect_crash(self, sensor_data):
        accel = sensor_data.get("accelerometer")
        if not accel:
            logger.debug("detect_crash: no accelerometer data, skipping")
            return False, None, None

        ax = accel["x"]
        ay = accel["y"]
        az = accel["z"]
        accel_mag = (ax**2 + ay**2 + az**2) ** 0.5
        logger.debug(
            "Accel magnitude: %.2f m/s² (x=%.2f y=%.2f z=%.2f)",
            accel_mag, ax, ay, az,
        )

        impact_confirmed = self.impact_sensor.detect_impact(
            accel_magnitude=accel_mag,
            timestamp=time.time(),
        )

        if not impact_confirmed:
            logger.debug("Impact not confirmed (SW420 + accel correlation failed)")
            return False, None, None

        # Severity bands
        if accel_mag < 15:
            severity = "LOW"
        elif accel_mag < 25:
            severity = "MEDIUM"
        else:
            severity = "HIGH"

        logger.info("Crash confirmed: severity=%s accel_mag=%.2f m/s²", severity, accel_mag)
        return True, severity, accel_mag

    # ──────────────────────────────────────────
    # HANDLE CRASH
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
            # Routing keys — Console Lambda checks these
            "type":  "crash_alert",            # routes to handle_crash() in Lambda
            "alert": "VEHICLE_CRASH_DETECTED", # legacy fallback key also supported

            # Identity & severity
            "node_id":                NODE_ID,
            "severity":               severity,
            "acceleration_magnitude": round(accel_mag, 2),

            # Location — top-level for Lambda extract_sensors()
            "location": {
                "latitude":  gps["latitude"],
                "longitude": gps["longitude"],
            } if has_gps_fix else None,

            # Timestamps
            "timestamp": datetime.now(IST).isoformat(),

            # Full sensor snapshot at crash moment
            "data": sensor_data,

            # Pre-crash ring buffer
            "pre_crash_buffer": list(self.data_buffer),
        }

        # Log payload summary before sending
        logger.info(
            "Crash payload: node_id=%s severity=%s location=%s "
            "pre_crash_buffer=%d samples payload_approx=%d bytes",
            crash_payload["node_id"],
            crash_payload["severity"],
            crash_payload["location"],
            len(crash_payload["pre_crash_buffer"]),
            len(str(crash_payload)),
        )
        logger.debug("Crash payload keys: %s", list(crash_payload.keys()))

        # Always write to local blackbox first
        logger.debug("Logging crash to blackbox")
        self.blackbox.log_crash(crash_payload)

        # Attempt cloud publish; fall back to LoRa if unavailable
        if is_network_available():
            logger.info("Network available → sending crash to AWS IoT")
            if self.cloud_client.safe_publish(crash_payload):
                logger.info("Crash sent to AWS IoT successfully")
            else:
                logger.warning("safe_publish failed → falling back to LoRa")
                self.lora_tx.send_payload(crash_payload)
        else:
            logger.warning("No network → sending crash via LoRa relay")
            self.lora_tx.send_payload(crash_payload)

    # ──────────────────────────────────────────
    # PERIODIC TELEMETRY
    # ──────────────────────────────────────────

    def send_periodic_telemetry(self, sensor_data):
        """
        Send a live sensor snapshot to AWS every 60 s for dashboard monitoring.
        Payload includes all fields the Console Lambda handle_telemetry() needs
        to write to the Nodes DynamoDB table:
          - type, node_id, timestamp       (routing + identity)
          - accelerometer, accel_magnitude (sensor state)
          - gps                            (location object)
          - location                       (explicit lat/lon for Lambda extract_sensors)
          - battery                        (Nodes table battery fields)
          - temperature, gyroscope         (extra sensor data)
        """
        try:
            accel  = sensor_data.get("accelerometer", {})
            ax     = accel.get("x", 0)
            ay     = accel.get("y", 0)
            az     = accel.get("z", 0)
            accel_mag = round((ax**2 + ay**2 + az**2) ** 0.5, 3)

            gps = sensor_data.get("gps")
            has_gps_fix = (
                gps is not None
                and gps.get("latitude")  is not None
                and gps.get("longitude") is not None
            )

            # ── FIX: added 'location' and 'battery' fields ──────────────────
            # Console Lambda handle_telemetry() calls extract_sensors() which
            # reads body.get("location") for lat/lon, and body.get("battery")
            # for battery_pct, voltage_v, status → written to Nodes table.
            # Without these two fields the Nodes table had no GPS and no battery.
            # ────────────────────────────────────────────────────────────────
            payload = {
                # Routing
                "type":    "LIVE_TELEMETRY",
                "node_id": NODE_ID,
                "timestamp": datetime.now(IST).isoformat(),

                # Accelerometer
                "accelerometer":          sensor_data.get("accelerometer"),
                "acceleration_magnitude": accel_mag,

                # Other sensors
                "gyroscope":   sensor_data.get("gyroscope"),
                "temperature": sensor_data.get("temperature"),

                # GPS object (full, for Lambda gps_data fallback)
                "gps": gps,

                # FIX 1 — explicit location dict for Lambda extract_sensors()
                "location": {
                    "latitude":  gps["latitude"],
                    "longitude": gps["longitude"],
                } if has_gps_fix else None,

                # FIX 2 — battery block for Nodes table
                # Replace the hardcoded values below with real readings
                # if your hardware supports battery monitoring.
                "battery": {
                    "battery_pct": 100,   # replace with actual % if available
                    "voltage_v":   3.7,   # replace with actual voltage if available
                    "status":      "ok",  # ok / low / critical
                },
            }

            if not is_network_available():
                logger.warning("Periodic telemetry skipped: network unavailable")
                return

            if self.cloud_client.safe_publish(payload):
                logger.info(
                    "Periodic telemetry published: accel_mag=%.2f gps=%s temp=%s",
                    accel_mag,
                    (f"{gps['latitude']:.4f},{gps['longitude']:.4f}"
                     if has_gps_fix else "no fix"),
                    sensor_data.get("temperature", {}).get("temperature"),
                )
            else:
                logger.warning("Periodic telemetry publish failed")

        except Exception as e:
            logger.warning("Periodic telemetry error (suppressed): %s", e, exc_info=True)

    # ──────────────────────────────────────────
    # MAIN LOOP
    # ──────────────────────────────────────────

    def run(self):
        interval = 1 / SAMPLE_RATE
        logger.info(
            "Starting crash detection loop: sample_rate=%d Hz interval=%.3f s",
            SAMPLE_RATE, interval,
        )
        loop_count = 0

        try:
            while True:
                current_time = time.time()
                loop_count  += 1
                logger.debug("Loop iteration %d", loop_count)

                sensor_data = self.read_all_sensors()

                self.blackbox.log(sensor_data, log_type="sensor")
                self.data_buffer.append(sensor_data)
                logger.debug(
                    "Buffer: %d/%d",
                    len(self.data_buffer),
                    self.data_buffer.maxlen,
                )

                is_crash, severity, accel_mag = self.detect_crash(sensor_data)

                if is_crash:
                    logger.warning("CRASH DETECTED | Severity: %s", severity)
                    self.handle_crash(sensor_data, severity, accel_mag)
                    logger.debug("Post-crash cooldown: sleeping 5 s")
                    time.sleep(5)

                # Periodic telemetry every telemetry_interval seconds
                if current_time - self.last_telemetry_time >= self.telemetry_interval:
                    self.send_periodic_telemetry(sensor_data)
                    self.last_telemetry_time = current_time

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info(
                "KeyboardInterrupt: shutting down (loop_count=%d)",
                loop_count,
            )
            self.cleanup()

    # ──────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────

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


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

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