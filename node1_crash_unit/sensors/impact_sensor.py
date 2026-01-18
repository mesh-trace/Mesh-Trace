"""
Impact sensor interface
Detects high G-force impacts using accelerometer or dedicated impact sensor
"""

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available (running on non-Pi system)")


class ImpactSensor:
    """Interface for impact detection sensor"""
    
    def __init__(self, pin=None):
        """
        Initialize impact sensor
        
        Args:
            pin: GPIO pin number for impact sensor (if using digital sensor)
        """
        self.pin = pin
        self.gpio_initialized = False
        
        if GPIO_AVAILABLE and pin is not None:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            self.gpio_initialized = True
    
    def read(self):
        """
        Read impact sensor value
        
        Returns:
            float: G-force value (or None if no impact detected)
        """
        if GPIO_AVAILABLE and self.gpio_initialized:
            # Read digital impact sensor
            if GPIO.input(self.pin):
                # Impact detected - return high value
                return 10.0  # Default high impact value
            return 0.0
        
        # Fallback: return None if sensor not available
        return None
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        if GPIO_AVAILABLE and self.gpio_initialized:
            GPIO.cleanup(self.pin)
            self.gpio_initialized = False
