import smbus2 as smbus 
import time

class MPU6050:
    def __init__(self, bus=1, address=0x68):
        self.bus = smbus.SMBus(bus)
        self.address = address

        # Wake up MPU6050
        self.bus.write_byte_data(self.address, 0x6B, 0x00)
        time.sleep(0.1)

        # Set accelerometer range to ±2g (best for testing)
        self.bus.write_byte_data(self.address, 0x1C, 0x00)

    def _read_word(self, reg):
        high = self.bus.read_byte_data(self.address, reg)
        low = self.bus.read_byte_data(self.address, reg + 1)
        value = (high << 8) + low
        if value >= 0x8000:
            value = -((65535 - value) + 1)
        return value

    def read_acceleration(self):
        ax = self._read_word(0x3B) / 16384.0 * 9.81
        ay = self._read_word(0x3D) / 16384.0 * 9.81
        az = self._read_word(0x3F) / 16384.0 * 9.81

        return {
            "x": ax,
            "y": ay,
            "z": az
        }
