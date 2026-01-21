"""
Temperature and humidity sensor interface (DHT22/AM2302)
Monitors ambient temperature and humidity for environmental monitoring
"""

import time
import logging
from typing import Optional, Dict

# Try to import Adafruit_DHT library for DHT22 sensor
try:
    import Adafruit_DHT  # pyright: ignore[reportMissingModuleSource, reportMissingImports]
    DHT_AVAILABLE = True
except ImportError:
    DHT_AVAILABLE = False
    print("Warning: Adafruit_DHT not available (install with: pip install Adafruit_DHT)")

# Try to import GPIO for pin management (optional, but good practice)
try:
    import RPi.GPIO as GPIO  # pyright: ignore[reportMissingModuleSource]
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

# Configure logging
logger = logging.getLogger(__name__)

# DHT22 sensor type constant
DHT_SENSOR_TYPE = Adafruit_DHT.DHT22 if DHT_AVAILABLE else None


class TemperatureSensor:
    """
    Interface for DHT22 (AM2302) temperature and humidity sensor
    
    Features:
    - Non-blocking reads with retry logic
    - Graceful error handling (never crashes system)
    - Read interval control to prevent over-polling
    - Safe GPIO initialization and cleanup
    - Suitable for long-running systemd service
    """
    
    def __init__(self, pin: Optional[int] = None, 
                 read_interval: float = 2.0,
                 max_retries: int = 3):
        """
        Initialize DHT22 temperature and humidity sensor
        
        Args:
            pin: GPIO pin number (BCM numbering, e.g., 4, 17, 27)
                 Common pins: GPIO 4 (physical pin 7)
            read_interval: Minimum seconds between sensor reads (default 2.0)
                          DHT22 requires ~2 seconds between reads
            max_retries: Maximum number of read attempts per read() call (default 3)
        """
        self.pin = pin
        self.read_interval = read_interval
        self.max_retries = max_retries
        
        # State tracking
        self.initialized = False
        self.last_read_time = 0.0
        self.gpio_mode_set = False
        
        # Initialize sensor
        self._initialize()
    
    def _initialize(self):
        """
        Initialize GPIO and verify sensor availability
        
        Safe initialization that never crashes - sets initialized flag
        based on availability of hardware and libraries.
        """
        if not DHT_AVAILABLE:
            logger.warning("Adafruit_DHT library not available - temperature sensor disabled")
            self.initialized = False
            return
        
        if self.pin is None:
            logger.warning("No GPIO pin specified for DHT22 sensor")
            self.initialized = False
            return
        
        # Initialize GPIO mode if available (for consistency with other sensors)
        if GPIO_AVAILABLE:
            try:
                if not self.gpio_mode_set:
                    GPIO.setmode(GPIO.BCM)
                    self.gpio_mode_set = True
                # Note: DHT22 doesn't require explicit GPIO.setup() - Adafruit_DHT handles it
                self.initialized = True
                logger.info(f"DHT22 sensor initialized on GPIO pin {self.pin}")
            except Exception as e:
                logger.error(f"Error initializing GPIO for DHT22: {e}")
                self.initialized = False
        else:
            # Even without GPIO module, Adafruit_DHT might work
            # Set initialized to True and let read() handle errors
            self.initialized = True
            logger.info(f"DHT22 sensor initialized on GPIO pin {self.pin} (GPIO module not available)")
    
    def _read_sensor_with_retry(self) -> tuple[Optional[float], Optional[float]]:
        """
        Read temperature and humidity from DHT22 with retry logic
        
        Returns:
            Tuple of (humidity, temperature) or (None, None) on failure
            Note: Adafruit_DHT returns (humidity, temperature) in that order
        """
        if not DHT_AVAILABLE or not self.initialized or self.pin is None:
            return (None, None)
        
        # Attempt sensor read with retries
        for attempt in range(1, self.max_retries + 1):
            try:
                # Adafruit_DHT.read() returns (humidity, temperature)
                # Can take up to 2 seconds per read, but that's acceptable for sensor read
                # Using read() instead of read_retry() to have control over retry logic
                humidity, temperature = Adafruit_DHT.read(
                    DHT_SENSOR_TYPE, 
                    self.pin
                )
                
                # Check if read was successful (values are not None)
                if humidity is not None and temperature is not None:
                    # Validate reasonable ranges (DHT22 specs: -40 to 80°C, 0-100% RH)
                    if -40.0 <= temperature <= 80.0 and 0.0 <= humidity <= 100.0:
                        return (humidity, temperature)
                    else:
                        logger.warning(
                            f"DHT22 read returned out-of-range values: "
                            f"temp={temperature:.1f}°C, humidity={humidity:.1f}%"
                        )
                
                # If we get here, read failed but no exception
                if attempt < self.max_retries:
                    # Small delay before retry (non-blocking relative to read_interval)
                    # DHT22 needs a brief pause between read attempts
                    time.sleep(0.2)
                    
            except Exception as e:
                logger.warning(f"DHT22 read attempt {attempt}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(0.2)
        
        # All retries failed
        logger.warning(f"DHT22 sensor read failed after {self.max_retries} attempts on GPIO {self.pin}")
        return (None, None)
    
    def read(self) -> Dict[str, Optional[float]]:
        """
        Read temperature and humidity from DHT22 sensor
        
        Implements read interval control to prevent over-polling the sensor.
        DHT22 requires at least 2 seconds between reads for accurate measurements.
        
        Returns:
            Dictionary with keys:
            {
                "temperature": float | None,  # Temperature in Celsius
                "humidity": float | None       # Relative humidity percentage (0-100)
            }
            
            Returns None values if:
            - Sensor not initialized
            - Read interval not met
            - All retry attempts failed
            - Sensor read error occurred
        """
        # Check if sensor is initialized
        if not self.initialized:
            return {"temperature": None, "humidity": None}
        
        # Enforce read interval to prevent over-polling
        current_time = time.time()
        time_since_last_read = current_time - self.last_read_time
        
        if time_since_last_read < self.read_interval:
            # Too soon since last read - return None to indicate no new data
            # This prevents blocking and respects sensor timing requirements
            return {"temperature": None, "humidity": None}
        
        # Attempt to read sensor with retry logic
        humidity, temperature = self._read_sensor_with_retry()
        
        # Update last read time
        self.last_read_time = current_time
        
        # Return structured data
        return {
            "temperature": round(temperature, 2) if temperature is not None else None,
            "humidity": round(humidity, 2) if humidity is not None else None
        }
    
    def read_temperature(self) -> Optional[float]:
        """
        Read only temperature in Celsius (convenience method)
        
        Returns:
            float: Temperature in Celsius, or None if unavailable
        """
        data = self.read()
        return data.get("temperature")
    
    def read_humidity(self) -> Optional[float]:
        """
        Read only humidity percentage (convenience method)
        
        Returns:
            float: Relative humidity percentage (0-100), or None if unavailable
        """
        data = self.read()
        return data.get("humidity")
    
    def read_fahrenheit(self) -> Optional[float]:
        """
        Read temperature in Fahrenheit (convenience method)
        
        Returns:
            float: Temperature in Fahrenheit, or None if unavailable
        """
        temp_c = self.read_temperature()
        if temp_c is None:
            return None
        return round((temp_c * 9.0 / 5.0) + 32.0, 2)
    
    def cleanup(self):
        """
        Cleanup GPIO resources
        
        Releases GPIO resources if they were initialized.
        Safe to call multiple times.
        """
        if GPIO_AVAILABLE and self.gpio_mode_set:
            try:
                # Note: GPIO.cleanup() cleans all pins
                # In multi-sensor setups, coordinate cleanup carefully
                # For DHT22, Adafruit_DHT manages its own GPIO, so cleanup is optional
                # but included for consistency with other sensors
                GPIO.cleanup()
                self.gpio_mode_set = False
                logger.info("GPIO resources cleaned up for DHT22 sensor")
            except Exception as e:
                logger.error(f"Error during GPIO cleanup: {e}")
        
        self.initialized = False
