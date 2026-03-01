import smbus2 as smbus
import logging
import time

logger = logging.getLogger(__name__)


class MPU6050:
    def __init__(self, bus=1, address=0x68):
        logger.debug("MPU6050 init: bus=%d address=0x%02x", bus, address)
        self.bus = smbus.SMBus(bus)
        self.address = address

        # Wake up MPU6050
        self.bus.write_byte_data(self.address, 0x6B, 0x00)
        time.sleep(0.1)
        logger.debug("MPU6050 woke up")

        # Set accelerometer range to ±2g (best for testing)
        self.bus.write_byte_data(self.address, 0x1C, 0x00)
        logger.info("MPU6050 initialized: bus=%d addr=0x%02x range=±2g", bus, address)

    def _read_word(self, reg):
        high = self.bus.read_byte_data(self.address, reg)
        low = self.bus.read_byte_data(self.address, reg + 1)
        value = (high << 8) + low
        if value >= 0x8000:
            value = -((65535 - value) + 1)
        return value

    def read_acceleration(self):
        try:
            ax = self._read_word(0x3B) / 16384.0 * 9.81
            ay = self._read_word(0x3D) / 16384.0 * 9.81
            az = self._read_word(0x3F) / 16384.0 * 9.81
            result = {"x": ax, "y": ay, "z": az}
            logger.debug("Accel read: x=%.2f y=%.2f z=%.2f m/s²", ax, ay, az)
            return result
        except Exception as e:
            logger.error("MPU6050 read_acceleration failed: %s", e, exc_info=True)
            return {"x": 0.0, "y": 0.0, "z": 0.0}
    def read_gyroscope(self):
        """
        Gyroscope not used for crash detection currently.  Return zeros to keep system stable.
        """
        logger.debug("Gyro read: zeros (not used for crash detection)")
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    def cleanup(self):
        """Placeholder cleanup for compatibility."""
        logger.debug("MPU6050 cleanup (no-op)")
