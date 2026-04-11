"""
Impact sensor interface with sensor fusion
Detects high G-force impacts using SB420 digital sensors correlated with MPU6050 accelerometer data
"""

import time
import logging
from collections import deque
from typing import Optional, List

try:
    import RPi.GPIO as GPIO  # pyright: ignore[reportMissingModuleSource]
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
                 accel_threshold: float = 5.0,  # m/s² — must be well above gravity (9.8 m/s²)
                 delta_threshold: float = 3.0,   # m/s² — minimum SUDDEN CHANGE vs recent baseline
                 correlation_window: float = 0.5, # seconds — window to correlate SB420 + accel
                 debounce_time: float = 0.05,     # seconds (50ms debounce)
                 cooldown_time: float = 30.0,     # seconds — no re-trigger for 30s after crash
                 baseline_window: int = 20):      # samples — rolling window to compute baseline
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
        

        
        # GPIO state
        self.gpio_initialized = False
        self.gpio_mode_set = False
        
        self.accel_threshold  = accel_threshold
        self.delta_threshold  = delta_threshold
        self.correlation_window = correlation_window
        self.debounce_time    = debounce_time
        self.cooldown_time    = cooldown_time
        self.baseline_window  = baseline_window

        # Sensor fusion state tracking
        self.sb420_triggers       = deque(maxlen=10)   # Recent SB420 trigger events
        self.last_impact_time     = 0.0                # Timestamp of last confirmed impact
        self.last_sb420_read_time = {}                 # Per-sensor debounce timestamps
        self.accel_baseline         = deque(maxlen=baseline_window)  # Rolling baseline magnitudes
        self._startup_ignore_until  = 0.0   # Ignore SB420 until this timestamp (startup drain)
        
        # Initialize GPIO if available
        if GPIO_AVAILABLE and self.pins:
            try:
                GPIO.setwarnings(False)  # suppress "channel already in use" on restart
                if not self.gpio_mode_set:
                    GPIO.setmode(GPIO.BCM)
                    self.gpio_mode_set = True

                for pin in self.pins:
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                    self.last_sb420_read_time[pin] = 0.0

                self.gpio_initialized = True

                # Drain any stale HIGH states on startup — SB420 can latch HIGH after power-on
                # Read and discard initial states before the main loop starts
                time.sleep(0.1)
                stale = [p for p in self.pins if GPIO.input(p)]
                if stale:
                    logger.warning(
                        "SB420 startup drain: pins %s were HIGH at init — ignoring for 2s", stale
                    )
                    self._startup_ignore_until = time.time() + 2.0
                else:
                    self._startup_ignore_until = 0.0

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
            # Skip if still in startup drain window
            if current_time < self._startup_ignore_until:
                return triggers

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
        Detect a REAL crash using two-stage fusion:

        Stage 1 — Sudden delta check:
            Compute rolling baseline from recent samples (last ~20 readings ≈ last 20 loop cycles).
            A crash produces a SUDDEN SPIKE above baseline, not a steady high value.
            Normal gravity (~9.8 m/s²) always sits in the baseline → delta stays near zero → no trigger.
            A real impact (e.g. 25 m/s²) spikes way above baseline (delta ~15 m/s²) → triggers.

        Stage 2 — SB420 physical correlation:
            Confirm that an SB420 sensor also fired within the correlation window.
            Eliminates false positives from software glitches or slow vibration.

        Stage 3 — Cooldown:
            30s cooldown prevents duplicate alerts after a real crash.
        """
        if timestamp is None:
            timestamp = time.time()

        # --- Always update baseline with current reading (before cooldown check) ---
        self.accel_baseline.append(accel_magnitude)

        # --- Cooldown: ignore everything for 30s after a confirmed crash ---
        if timestamp - self.last_impact_time < self.cooldown_time:
            return False

        # --- Read and store SB420 triggers ---
        current_triggers = self._read_sb420_sensors()
        for trigger_time, sensor_id in current_triggers:
            self.sb420_triggers.append((trigger_time, sensor_id))

        # --- Stage 1: absolute threshold check ---
        if accel_magnitude < self.accel_threshold:
            logger.debug("detect_impact: accel %.2f below threshold %.2f — no crash",
                         accel_magnitude, self.accel_threshold)
            return False

        # --- Stage 2: sudden delta check vs rolling baseline ---
        if len(self.accel_baseline) >= 5:
            # Exclude the current reading from baseline average
            recent = list(self.accel_baseline)[:-1]
            baseline_avg = sum(recent) / len(recent)
            delta = accel_magnitude - baseline_avg
            logger.debug("detect_impact: accel=%.2f baseline=%.2f delta=%.2f (need delta>=%.2f)",
                         accel_magnitude, baseline_avg, delta, self.delta_threshold)
            if delta < self.delta_threshold:
                # High accel but no sudden change — just gravity or slow vibration
                return False

        # --- Stage 3: SB420 correlation ---
        for trigger_time, sensor_id in self.sb420_triggers:
            time_diff = abs(timestamp - trigger_time)
            if time_diff <= self.correlation_window:
                self.last_impact_time = timestamp
                baseline_avg = sum(self.accel_baseline) / len(self.accel_baseline) if self.accel_baseline else 0
                logger.warning(
                    f"CRASH CONFIRMED: Sensor {sensor_id} (pin {self.pins[sensor_id] if sensor_id < len(self.pins) else '?'}), "
                    f"Accel: {accel_magnitude:.2f} m/s², "
                    f"Baseline: {baseline_avg:.2f} m/s², "
                    f"Delta: {accel_magnitude - baseline_avg:.2f} m/s², "
                    f"SB420 time diff: {time_diff*1000:.1f}ms"
                )
                return True

        logger.debug("detect_impact: accel exceeded threshold but no SB420 correlation")
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