"""
Impact sensor interface with sensor fusion
Detects high G-force impacts using SB420 digital sensors correlated with MPU6050 accelerometer data
"""

import time
import logging
from collections import deque
from typing import Optional, List

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available (running on non-Pi system)")

# Configure logging
logger = logging.getLogger(__name__)


class ImpactSensor:
    """
    Interface for impact detection using SB420 sensors with MPU6050 sensor fusion
    
    Sensor Fusion Logic:
    - SB420 sensors provide digital triggers (high G-force detection)
    - MPU6050 provides continuous accelerometer magnitude
    - Impact is confirmed ONLY when:
      1. Any SB420 sensor triggers (digital HIGH)
      2. Accelerometer magnitude exceeds threshold
      3. Both occur within correlation time window
    - Debouncing and cooldown prevent false positives and duplicate triggers
    """
    
    def __init__(self, pins: Optional[List[int]] = None, pin: Optional[int] = None,
                 accel_threshold: float = 7.0,  # m/s² threshold for impact confirmation
                 correlation_window: float = 0.2,  # seconds (200ms window)
                 debounce_time: float = 0.05,  # seconds (50ms debounce)
                 cooldown_time: float = 1.0):  # seconds (1s cooldown between impacts)
        """
        Initialize impact sensor system with multiple SB420 sensors
        
        Args:
            pins: List of GPIO pin numbers for SB420 sensors (supports 4 sensors)
            pin: Single GPIO pin (for backward compatibility)
            accel_threshold: Acceleration magnitude threshold in m/s² for impact confirmation
            correlation_window: Time window in seconds to correlate SB420 trigger with accelerometer
            debounce_time: Minimum time between SB420 trigger events to prevent noise
            cooldown_time: Minimum time between confirmed impact detections
        """
        # Handle both list of pins and single pin for backward compatibility
        if pins is not None:
            self.pins = pins if isinstance(pins, list) else [pins]
        elif pin is not None:
            self.pins = [pin]
        else:
            self.pins = []
        
        # Limit to 4 sensors as specified
        if len(self.pins) > 4:
            logger.warning(f"More than 4 pins provided, using first 4: {self.pins[:4]}")
            self.pins = self.pins[:4]
        
        self.accel_threshold = accel_threshold
        self.correlation_window = correlation_window
        self.debounce_time = debounce_time
        self.cooldown_time = cooldown_time
        
        # GPIO state
        self.gpio_initialized = False
        self.gpio_mode_set = False
        
        # Sensor fusion state tracking
        self.sb420_triggers = deque(maxlen=10)  # Recent SB420 trigger events: (timestamp, sensor_id)
        self.last_impact_time = 0.0  # Timestamp of last confirmed impact
        self.last_sb420_read_time = {}  # Track last read time per sensor for debouncing
        
        # Initialize GPIO if available
        if GPIO_AVAILABLE and self.pins:
            try:
                if not self.gpio_mode_set:
                    GPIO.setmode(GPIO.BCM)
                    self.gpio_mode_set = True
                
                for pin in self.pins:
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                    self.last_sb420_read_time[pin] = 0.0
                
                self.gpio_initialized = True
                logger.info(f"Initialized {len(self.pins)} SB420 impact sensors on pins: {self.pins}")
            except Exception as e:
                logger.error(f"Error initializing GPIO pins: {e}")
                self.gpio_initialized = False
    
    def _read_sb420_sensors(self) -> List[tuple]:
        """
        Read all SB420 sensors and return active triggers
        
        Returns:
            List of (timestamp, sensor_id) tuples for sensors that are currently HIGH
        """
        triggers = []
        current_time = time.time()
        
        if not GPIO_AVAILABLE or not self.gpio_initialized:
            return triggers
        
        try:
            for idx, pin in enumerate(self.pins):
                # Debounce: ignore triggers too close together
                last_read = self.last_sb420_read_time.get(pin, 0.0)
                if current_time - last_read < self.debounce_time:
                    continue
                
                # Read digital state (HIGH = impact detected)
                if GPIO.input(pin):
                    triggers.append((current_time, idx))
                    self.last_sb420_read_time[pin] = current_time
                    logger.debug(f"SB420 sensor {idx} (pin {pin}) triggered at {current_time:.3f}")
        
        except Exception as e:
            logger.error(f"Error reading SB420 sensors: {e}")
        
        return triggers
    
    def detect_impact(self, accel_magnitude: float, timestamp: Optional[float] = None) -> bool:
        """
        Detect impact using sensor fusion: SB420 trigger + accelerometer magnitude correlation
        
        This is the main detection method that correlates SB420 digital triggers with
        MPU6050 accelerometer data to reduce false positives from vibration/noise.
        
        Args:
            accel_magnitude: Acceleration magnitude from MPU6050 in m/s²
            timestamp: Optional timestamp (uses current time if not provided)
        
        Returns:
            bool: True if impact is confirmed, False otherwise
        
        Detection Logic:
        1. Check cooldown period (prevent duplicate triggers)
        2. Read current SB420 sensor states
        3. Store any SB420 triggers with timestamp
        4. Correlate: Check if SB420 trigger exists within correlation window
           AND accelerometer magnitude exceeds threshold
        5. If both conditions met, confirm impact and log event
        """
        if timestamp is None:
            timestamp = time.time()
        
        # Cooldown check: prevent duplicate impact detections
        if timestamp - self.last_impact_time < self.cooldown_time:
            return False
        
        # Read current SB420 sensor states (non-blocking)
        current_triggers = self._read_sb420_sensors()
        
        # Store new triggers
        for trigger_time, sensor_id in current_triggers:
            self.sb420_triggers.append((trigger_time, sensor_id))
        
        # Check if accelerometer magnitude exceeds threshold
        accel_exceeds_threshold = accel_magnitude >= self.accel_threshold
        
        if not accel_exceeds_threshold:
            return False
        
        # Correlation: Check if any SB420 trigger occurred within correlation window
        # Look for triggers that happened close to current time (within window)
        for trigger_time, sensor_id in self.sb420_triggers:
            time_diff = abs(timestamp - trigger_time)
            
            # Check if trigger is within correlation window
            if time_diff <= self.correlation_window:
                # Both conditions met: SB420 triggered AND accelerometer exceeded threshold
                # Confirm impact
                self.last_impact_time = timestamp
                
                # Log impact event
                logger.warning(
                    f"IMPACT DETECTED: Sensor {sensor_id} (pin {self.pins[sensor_id]}), "
                    f"Accel: {accel_magnitude:.2f} m/s², "
                    f"Time diff: {time_diff*1000:.1f}ms, "
                    f"Timestamp: {timestamp:.3f}"
                )
                
                return True
        
        return False
    
    def read(self):
        """
        Read impact sensor value (backward compatibility method)
        
        This method maintains compatibility with existing main.py code.
        It checks SB420 sensors and returns a value if any are triggered.
        
        Returns:
            float: G-force value (10.0 if triggered, 0.0 otherwise) or None if unavailable
        """
        if not GPIO_AVAILABLE or not self.gpio_initialized:
            return None
        
        try:
            # Check if any SB420 sensor is currently HIGH
            for pin in self.pins:
                if GPIO.input(pin):
                    return 10.0  # Default high impact value for backward compatibility
            
            return 0.0
        except Exception as e:
            logger.error(f"Error reading impact sensor: {e}")
            return None
    
    def get_active_sensors(self) -> List[int]:
        """
        Get list of currently active (triggered) SB420 sensor IDs
        
        Returns:
            List of sensor indices (0-3) that are currently HIGH
        """
        active = []
        if not GPIO_AVAILABLE or not self.gpio_initialized:
            return active
        
        try:
            for idx, pin in enumerate(self.pins):
                if GPIO.input(pin):
                    active.append(idx)
        except Exception as e:
            logger.error(f"Error reading active sensors: {e}")
        
        return active
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        if GPIO_AVAILABLE and self.gpio_initialized:
            try:
                # Only cleanup if we set the mode
                if self.gpio_mode_set:
                    # Note: GPIO.cleanup() cleans all pins, so be careful in multi-sensor setups
                    # For safety, we'll only cleanup if this is the only user
                    # In production, consider using GPIO.remove_event_detect() instead
                    GPIO.cleanup()
                    self.gpio_mode_set = False
                self.gpio_initialized = False
                logger.info("GPIO resources cleaned up")
            except Exception as e:
                logger.error(f"Error during GPIO cleanup: {e}")
