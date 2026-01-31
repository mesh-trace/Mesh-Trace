"""
GPS sensor interface for Mesh-Trace
Provides latitude and longitude for crash reporting
Compatible with Raspberry Pi Zero WH and GN* NMEA sentences
"""

import serial
import time

try:
    import pynmea2
    NMEA_AVAILABLE = True
except ImportError:
    NMEA_AVAILABLE = False
    print("Warning: pynmea2 not available - GPS disabled")


class GPSSensor:
    def __init__(self, port="/dev/ttyS0", baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.initialized = False

        self.last_position = {
            "latitude": None,
            "longitude": None,
            "altitude": None,
            "speed": None,
            "course": None,
            "timestamp": None,
            "satellites": 0,
            "fix_quality": 0
        }

        self._initialize()

    def _initialize(self):
        try:
            self.serial_conn = serial.Serial(
                self.port,
                self.baudrate,
                timeout=1
            )
            self.initialized = True
            time.sleep(1.0)
        except Exception as e:
            print(f"Warning: Could not initialize GPS: {e}")
            self.initialized = False

    def _update_from_nmea(self, line):
        if not NMEA_AVAILABLE:
            return

        try:
            msg = pynmea2.parse(line)

            # GGA → fix, satellites, altitude
            if isinstance(msg, pynmea2.types.talker.GGA):
                if msg.gps_qual and int(msg.gps_qual) > 0:
                    self.last_position["latitude"] = msg.latitude
                    self.last_position["longitude"] = msg.longitude
                    self.last_position["altitude"] = float(msg.altitude) if msg.altitude else None
                    self.last_position["satellites"] = int(msg.num_sats) if msg.num_sats else 0
                    self.last_position["fix_quality"] = int(msg.gps_qual)
                    self.last_position["timestamp"] = time.time()

            # RMC → speed, course, validity
            elif isinstance(msg, pynmea2.types.talker.RMC):
                if msg.status == "A":
                    self.last_position["latitude"] = msg.latitude
                    self.last_position["longitude"] = msg.longitude
                    self.last_position["speed"] = float(msg.spd_over_grnd) if msg.spd_over_grnd else None
                    self.last_position["course"] = float(msg.true_course) if msg.true_course else None
                    self.last_position["timestamp"] = time.time()

        except pynmea2.ParseError:
            pass
        except Exception:
            pass

    def get_position(self):
        if not self.initialized or not self.serial_conn:
            return self.last_position.copy()

        try:
            start = time.time()

            # Read for up to 500 ms
            while time.time() - start < 0.5:
                if self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode(
                        "utf-8", errors="ignore"
                    ).strip()

                    if line.startswith("$"):
                        self._update_from_nmea(line)

                time.sleep(0.01)

        except Exception as e:
            print(f"GPS read error: {e}")

        return self.last_position.copy()

    def has_fix(self):
        return (
            self.last_position["fix_quality"] > 0 and
            self.last_position["latitude"] is not None and
            self.last_position["longitude"] is not None
        )

    def cleanup(self):
        if self.serial_conn:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.initialized = False
