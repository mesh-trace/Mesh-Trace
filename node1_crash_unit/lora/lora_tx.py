"""
LoRa transmitter module
Handles LoRa radio communication for mesh network
"""

import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

LORA_LIB = None
try:
    from LoRa import LoRa
    LORA_LIBRARY_AVAILABLE = True
    LORA_LIB = "lora"
except ImportError:
    try:
        import board
        import busio
        import digitalio
        from adafruit_rfm9x import RFM9x
        LORA_LIBRARY_AVAILABLE = True
        LORA_LIB = "adafruit"
    except ImportError:
        LORA_LIBRARY_AVAILABLE = False
        print("Warning: LoRa libraries not available")


class LoRaTransmitter:
    """LoRa radio transmitter for mesh communication"""
    
    def __init__(self, frequency=915.0, spreading_factor=7, bandwidth=125000,
                 coding_rate=5, power=14, cs_pin=8, reset_pin=25, dio0_pin=24):
        """
        Initialize LoRa transmitter
        
        Args:
            frequency: Operating frequency in MHz
            spreading_factor: LoRa spreading factor (7-12)
            bandwidth: Signal bandwidth in Hz
            coding_rate: Error correction coding rate (5-8)
            power: Transmission power in dBm
            cs_pin: Chip select GPIO pin
            reset_pin: Reset GPIO pin
            dio0_pin: DIO0 interrupt pin
        """
        self.frequency = frequency
        self.spreading_factor = spreading_factor
        self.bandwidth = bandwidth
        self.coding_rate = coding_rate
        self.power = power
        self.cs_pin = cs_pin
        self.reset_pin = reset_pin
        self.dio0_pin = dio0_pin
        
        self.radio = None
        self.initialized = False
        
        self._initialize()
    
    def _initialize(self):
        """Initialize LoRa radio hardware"""
        if not LORA_LIBRARY_AVAILABLE:
            print("Warning: LoRa libraries not available - running in simulation mode")
            self.initialized = False
            return
        
        try:
            if LORA_LIB == "adafruit" and GPIO_AVAILABLE and LORA_LIBRARY_AVAILABLE:
                # Initialize SPI and GPIO
                spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
                cs = digitalio.DigitalInOut(board.D8)  # CS pin
                reset = digitalio.DigitalInOut(board.D25)  # Reset pin
                
                # Create RFM9x instance
                self.radio = RFM9x(
                    spi, cs, reset, self.frequency,
                    spreading_factor=self.spreading_factor,
                    coding_rate=self.coding_rate,
                    baudrate=self.bandwidth
                )
                self.radio.tx_power = self.power
                self.initialized = True
                print(f"LoRa radio initialized at {self.frequency} MHz")
            else:
                # Fallback initialization (would need LoRa.py library)
                print("LoRa initialization requires specific hardware library")
                self.initialized = False
        except Exception as e:
            print(f"Warning: Could not initialize LoRa radio: {e}")
            self.initialized = False
    
    def send(self, payload):
        """
        Send data via LoRa
        
        Args:
            payload: String or bytes data to transmit
            
        Returns:
            bool: True if transmission successful, False otherwise
        """
        if not self.initialized:
            print(f"[SIMULATION] LoRa TX: {payload[:50]}...")
            return False
        
        try:
            # Convert payload to bytes if needed
            if isinstance(payload, str):
                payload_bytes = payload.encode('utf-8')
            else:
                payload_bytes = payload
            
            # Send via LoRa radio
            if self.radio:
                # RFM9x send
                self.radio.send(payload_bytes)
                print(f"LoRa transmission sent: {len(payload_bytes)} bytes")
                return True
            else:
                print("LoRa radio not initialized")
                return False
        except Exception as e:
            print(f"Error transmitting via LoRa: {e}")
            return False
    
    def send_with_retry(self, payload, max_retries=3):
        """
        Send data with retry logic
        
        Args:
            payload: Data to transmit
            max_retries: Maximum number of retry attempts
            
        Returns:
            bool: True if transmission successful
        """
        for attempt in range(max_retries):
            if self.send(payload):
                return True
            time.sleep(0.5 * (attempt + 1))  # Exponential backoff
        
        print(f"Failed to transmit after {max_retries} attempts")
        return False
    
    def set_power(self, power):
        """
        Set transmission power
        
        Args:
            power: Power level in dBm
        """
        self.power = power
        if self.radio and hasattr(self.radio, 'tx_power'):
            self.radio.tx_power = power
    
    def get_signal_strength(self):
        """
        Get received signal strength (RSSI) if available
        
        Returns:
            float: RSSI in dBm (or None if unavailable)
        """
        if self.radio and hasattr(self.radio, 'rssi'):
            return self.radio.rssi
        return None
    
    def cleanup(self):
        """Cleanup LoRa resources"""
        self.initialized = False
        self.radio = None
