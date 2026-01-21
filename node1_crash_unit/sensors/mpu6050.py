"""
MPU6050 6-axis accelerometer and gyroscope interface
Provides acceleration and rotation data for crash detection
"""

try:
    import smbus  # pyright: ignore[reportMissingImports]
    I2C_AVAILABLE = True
except ImportError:
    I2C_AVAILABLE = False
    print("Warning: smbus not available (running on non-Pi system)")

import time


class MPU6050:
    """Interface for MPU6050 IMU sensor"""
    
    # MPU6050 Registers
    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B
    GYRO_XOUT_H = 0x43
    
    def __init__(self, address=0x68, bus=1):
        """
        Initialize MPU6050 sensor
        
        Args:
            address: I2C address of MPU6050 (default 0x68)
            bus: I2C bus number (default 1 for Pi)
        """
        self.address = address
        self.bus_num = bus
        self.i2c_bus = None
        self.initialized = False
        
        if I2C_AVAILABLE:
            try:
                self.i2c_bus = smbus.SMBus(bus)
                self._initialize_mpu6050()
                self.initialized = True
            except Exception as e:
                print(f"Warning: Could not initialize MPU6050: {e}")
    
    def _initialize_mpu6050(self):
        """Configure MPU6050 registers"""
        if not I2C_AVAILABLE or not self.i2c_bus:
            return
        
        try:
            # Wake up the MPU6050 (sleep bit = 0)
            self.i2c_bus.write_byte_data(self.address, self.PWR_MGMT_1, 0)
            
            # Set sample rate to 1kHz / (1 + 7) = 125Hz
            self.i2c_bus.write_byte_data(self.address, self.SMPLRT_DIV, 7)
            
            # Configure accelerometer (+/- 8g)
            self.i2c_bus.write_byte_data(self.address, self.ACCEL_CONFIG, 0x10)
            
            # Configure gyroscope (+/- 500 deg/s)
            self.i2c_bus.write_byte_data(self.address, self.GYRO_CONFIG, 0x08)
            
            # Configure filter (44Hz bandwidth)
            self.i2c_bus.write_byte_data(self.address, self.CONFIG, 0x03)
            
            time.sleep(0.1)  # Allow sensor to stabilize
        except Exception as e:
            print(f"Error configuring MPU6050: {e}")
    
    def _read_word_2c(self, addr):
        """Read 16-bit signed value from register"""
        if not I2C_AVAILABLE or not self.i2c_bus:
            return 0
        
        try:
            high = self.i2c_bus.read_byte_data(self.address, addr)
            low = self.i2c_bus.read_byte_data(self.address, addr + 1)
            val = (high << 8) + low
            if val >= 0x8000:
                return -((65535 - val) + 1)
            else:
                return val
        except Exception as e:
            print(f"Error reading from MPU6050: {e}")
            return 0
    
    def read_acceleration(self):
        """
        Read acceleration data
        
        Returns:
            dict: {'x': float, 'y': float, 'z': float} in m/s²
        """
        if not self.initialized:
            return {'x': 0.0, 'y': 0.0, 'z': 0.0}
        
        # Read accelerometer data (16-bit values)
        accel_x = self._read_word_2c(self.ACCEL_XOUT_H)
        accel_y = self._read_word_2c(self.ACCEL_XOUT_H + 2)
        accel_z = self._read_word_2c(self.ACCEL_XOUT_H + 4)
        
        # Convert to m/s² (8g range: 16384 LSB/g)
        accel_scale = 16384.0
        accel_x = (accel_x / accel_scale) * 9.80665
        accel_y = (accel_y / accel_scale) * 9.80665
        accel_z = (accel_z / accel_scale) * 9.80665
        
        return {
            'x': round(accel_x, 3),
            'y': round(accel_y, 3),
            'z': round(accel_z, 3),
            'magnitude': round((accel_x**2 + accel_y**2 + accel_z**2)**0.5, 3)
        }
    
    def read_gyroscope(self):
        """
        Read gyroscope data
        
        Returns:
            dict: {'x': float, 'y': float, 'z': float} in deg/s
        """
        if not self.initialized:
            return {'x': 0.0, 'y': 0.0, 'z': 0.0}
        
        # Read gyroscope data (16-bit values)
        gyro_x = self._read_word_2c(self.GYRO_XOUT_H)
        gyro_y = self._read_word_2c(self.GYRO_XOUT_H + 2)
        gyro_z = self._read_word_2c(self.GYRO_XOUT_H + 4)
        
        # Convert to deg/s (500 deg/s range: 65.5 LSB/deg/s)
        gyro_scale = 65.5
        gyro_x = gyro_x / gyro_scale
        gyro_y = gyro_y / gyro_scale
        gyro_z = gyro_z / gyro_scale
        
        return {
            'x': round(gyro_x, 3),
            'y': round(gyro_y, 3),
            'z': round(gyro_z, 3),
            'magnitude': round((gyro_x**2 + gyro_y**2 + gyro_z**2)**0.5, 3)
        }
    
    def cleanup(self):
        """Cleanup I2C resources"""
        self.initialized = False
        # Note: smbus doesn't require explicit cleanup
