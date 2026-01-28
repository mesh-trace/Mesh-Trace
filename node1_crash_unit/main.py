"""
Main crash detection loop for Node 1 (Raspberry Pi Zero WH)
Sensor testing and cloud hopping: monitors sensors, threshold-based crash detection, LoRa TX to cloud
"""

import json
import time
import signal
import sys
from collections import deque
from datetime import datetime

from config import *
from sensors.impact_sensor import ImpactSensor
from sensors.mpu6050 import MPU6050
from sensors.temperature import TemperatureSensor
from sensors.gps import GPSSensor
from lora.lora_tx import LoRaTransmitter
from storage.blackbox_logger import BlackboxLogger


class CrashDetectionUnit:
    def __init__(self):
        """Initialize all sensors and systems"""
        print("Initializing Crash Detection Unit...")
        
        # Initialize sensors
        self.impact_sensor = ImpactSensor(IMPACT_SENSOR_PINS)  # pyright: ignore[reportUndefinedVariable]
        self.mpu6050 = MPU6050(MPU6050_I2C_ADDRESS, MPU6050_I2C_BUS)
        self.temperature_sensor = TemperatureSensor(TEMPERATURE_SENSOR_PIN)
        self.gps_sensor = GPSSensor(GPS_SERIAL_PORT, GPS_BAUDRATE)
        
        # Cloud hopping: LoRa transmitter
        self.lora_tx = LoRaTransmitter(
            frequency=LORA_FREQUENCY,
            spreading_factor=LORA_SPREADING_FACTOR,
            bandwidth=LORA_BANDWIDTH,
            coding_rate=LORA_CODING_RATE,
            power=LORA_POWER,
            cs_pin=LORA_CS_PIN,
            reset_pin=LORA_RESET_PIN,
            dio0_pin=LORA_DIO0_PIN
        )
        
        # Initialize storage
        self.blackbox = BlackboxLogger(BLACKBOX_LOG_PATH)
        
        # Data buffer for pre-crash data
        self.data_buffer = deque(maxlen=BUFFER_SIZE)
        
        # State
        self.running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        print("Crash Detection Unit initialized successfully")
    
    def signal_handler(self, sig, frame):
        """Handle shutdown signals gracefully"""
        print("\nShutting down gracefully...")
        self.running = False
        self.cleanup()
        sys.exit(0)
    
    def read_all_sensors(self):
        """Read data from all sensors"""
        try:
            sensor_data = {
                'timestamp': datetime.now().isoformat(),
                'impact': self.impact_sensor.read(),
                'accelerometer': self.mpu6050.read_acceleration(),
                'gyroscope': self.mpu6050.read_gyroscope(),
                'temperature': self.temperature_sensor.read(),
                'gps': self.gps_sensor.get_position(),
                'node_id': NODE_ID
            }
            return sensor_data
        except Exception as e:
            print(f"Error reading sensors: {e}")
            return None
    
    def detect_crash(self, sensor_data):
        """Threshold-based crash detection (no AI)"""
        if not sensor_data:
            return False, 0.0
        
        # Impact trigger
        impact = sensor_data.get('impact') or 0.0
        if impact and impact > IMPACT_THRESHOLD:
            return True, 0.95
        
        # Optional: accelerometer magnitude threshold
        accel = sensor_data.get('accelerometer') or {}
        mag = accel.get('magnitude') or 0.0
        if mag > ACCELERATION_THRESHOLD:
            return True, 0.9
        
        return False, 0.0
    
    def handle_crash(self, sensor_data, confidence):
        """Handle crash: log to blackbox, transmit via LoRa (cloud hopping)"""
        print(f"🚨 CRASH DETECTED! Confidence: {confidence:.2%}")
        
        crash_package = {
            'crash_data': sensor_data,
            'pre_crash_buffer': list(self.data_buffer)[-PRE_CRASH_DURATION * SAMPLE_RATE:],
            'timestamp': datetime.now().isoformat(),
            'confidence': confidence,
            'node_id': NODE_ID
        }
        
        self.blackbox.log_crash(crash_package)
        
        # Cloud hopping: send plain payload via LoRa (no encryption/hashing)
        lora_payload = {
            'type': 'crash_alert',
            'data': crash_package,
            'node_id': NODE_ID,
            'timestamp': crash_package['timestamp']
        }
        self.lora_tx.send(json.dumps(lora_payload))
        print("Crash alert transmitted via LoRa")
    
    def cleanup(self):
        """Cleanup resources on shutdown"""
        print("Cleaning up resources...")
        self.impact_sensor.cleanup()
        self.mpu6050.cleanup()
        self.temperature_sensor.cleanup()
        self.gps_sensor.cleanup()
        self.lora_tx.cleanup()
        self.blackbox.close()
    
    def run(self):
        """Main detection loop"""
        print("Starting crash detection loop...")
        sample_interval = 1.0 / SAMPLE_RATE
        
        while self.running:
            loop_start = time.time()
            
            # Read all sensors
            sensor_data = self.read_all_sensors()
            
            if sensor_data:
                # Add to circular buffer
                self.data_buffer.append(sensor_data)

                self.blackbox.log(sensor_data, log_type="sensor")
                print(sensor_data)
                
                # Check for crash
                is_crash, confidence = self.detect_crash(sensor_data)
                
                if is_crash:
                    self.handle_crash(sensor_data, confidence)
            
            # Maintain sample rate
            elapsed = time.time() - loop_start
            sleep_time = max(0, sample_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
            
            


def main():
    """Entry point"""
    print("=" * 50)
    print("Mesh-Trace Crash Detection Unit - Node 1")
    print("Raspberry Pi Zero WH")
    print("=" * 50)
    
    unit = CrashDetectionUnit()
    
    try:
        unit.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        unit.cleanup()


if __name__ == "__main__":
    main()
