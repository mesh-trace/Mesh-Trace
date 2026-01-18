"""
Temperature sensor interface (DS18B20)
Monitors device temperature for thermal protection and diagnostics
"""

import os
import time
from glob import glob


class TemperatureSensor:
    """Interface for DS18B20 temperature sensor"""
    
    BASE_DIR = '/sys/bus/w1/devices/'
    DEVICE_FILE = '/w1_slave'
    
    def __init__(self, pin=None):
        """
        Initialize DS18B20 temperature sensor
        
        Args:
            pin: GPIO pin (for DS18B20, this is typically pin 4)
        """
        self.pin = pin
        self.device_file = None
        self.initialized = False
        
        # Try to find DS18B20 device
        device_folders = glob(self.BASE_DIR + '28*')
        if device_folders:
            self.device_file = device_folders[0] + self.DEVICE_FILE
            self.initialized = True
        else:
            print("Warning: DS18B20 temperature sensor not found")
    
    def _read_temp_raw(self):
        """Read raw temperature data from sensor"""
        if not self.initialized or not os.path.exists(self.device_file):
            return None
        
        try:
            with open(self.device_file, 'r') as f:
                lines = f.readlines()
            return lines
        except Exception as e:
            print(f"Error reading temperature sensor: {e}")
            return None
    
    def read(self):
        """
        Read temperature in Celsius
        
        Returns:
            float: Temperature in Celsius (or None if unavailable)
        """
        if not self.initialized:
            return None
        
        lines = self._read_temp_raw()
        if lines is None or len(lines) < 2:
            return None
        
        # Check for valid data (CRC check passed)
        if lines[0].strip()[-3:] != 'YES':
            time.sleep(0.2)
            lines = self._read_temp_raw()
            if lines is None or len(lines) < 2:
                return None
        
        # Extract temperature
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos + 2:]
            temp_c = float(temp_string) / 1000.0
            return round(temp_c, 2)
        
        return None
    
    def read_fahrenheit(self):
        """Read temperature in Fahrenheit"""
        temp_c = self.read()
        if temp_c is None:
            return None
        return round((temp_c * 9.0 / 5.0) + 32.0, 2)
    
    def cleanup(self):
        """Cleanup resources"""
        self.initialized = False
