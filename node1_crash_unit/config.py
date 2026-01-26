"""
Configuration file for the crash detection unit (Node 1)
Raspberry Pi Zero WH settings and thresholds
Loads configuration from environment variables (.env file)
"""

import os
from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]

# Load environment variables from .env file
load_dotenv()


def get_int_list(env_var: str, default: list) -> list:
    """Parse comma-separated integer list from environment variable"""
    value = os.getenv(env_var)
    if value:
        return [int(x.strip()) for x in value.split(',')]
    return default


def get_bool(env_var: str, default: bool) -> bool:
    """Parse boolean from environment variable"""
    value = os.getenv(env_var, '').lower()
    if value in ('true', '1', 'yes', 'on'):
        return True
    elif value in ('false', '0', 'no', 'off'):
        return False
    return default


# Hardware Configuration
RASPBERRY_PI_MODEL = os.getenv('RASPBERRY_PI_MODEL', 'Zero WH')

# Sensor Configuration
IMPACT_SENSOR_PINS = get_int_list('IMPACT_SENSOR_PINS', [18, 23, 24, 25])
# MPU6050_I2C_ADDRESS: 104 decimal = 0x68 hex
MPU6050_I2C_ADDRESS = int(os.getenv('MPU6050_I2C_ADDRESS', '104'))
MPU6050_I2C_BUS = int(os.getenv('MPU6050_I2C_BUS', '1'))
TEMPERATURE_SENSOR_PIN = int(os.getenv('TEMPERATURE_SENSOR_PIN', '4'))
GPS_SERIAL_PORT = os.getenv('GPS_SERIAL_PORT', '/dev/ttyAMA0')
GPS_BAUDRATE = int(os.getenv('GPS_BAUDRATE', '9600'))

# Crash Detection Thresholds
IMPACT_THRESHOLD = float(os.getenv('IMPACT_THRESHOLD', '15.0'))
ACCELERATION_THRESHOLD = float(os.getenv('ACCELERATION_THRESHOLD', '9.8'))
ROTATION_THRESHOLD = int(os.getenv('ROTATION_THRESHOLD', '500'))
CRASH_CONFIDENCE_THRESHOLD = float(os.getenv('CRASH_CONFIDENCE_THRESHOLD', '0.85'))

# Sampling Configuration
SAMPLE_RATE = int(os.getenv('SAMPLE_RATE', '100'))
BUFFER_SIZE = int(os.getenv('BUFFER_SIZE', '1000'))
PRE_CRASH_DURATION = int(os.getenv('PRE_CRASH_DURATION', '5'))

# LoRa Configuration
LORA_FREQUENCY = float(os.getenv('LORA_FREQUENCY', '915.0'))
LORA_SPREADING_FACTOR = int(os.getenv('LORA_SPREADING_FACTOR', '7'))
LORA_BANDWIDTH = int(os.getenv('LORA_BANDWIDTH', '125000'))
LORA_CODING_RATE = int(os.getenv('LORA_CODING_RATE', '5'))
LORA_POWER = int(os.getenv('LORA_POWER', '14'))
LORA_CS_PIN = int(os.getenv('LORA_CS_PIN', '8'))
LORA_RESET_PIN = int(os.getenv('LORA_RESET_PIN', '25'))
LORA_DIO0_PIN = int(os.getenv('LORA_DIO0_PIN', '24'))

# Security Configuration
ENCRYPTION_KEY_SIZE = int(os.getenv('ENCRYPTION_KEY_SIZE', '32'))
HASH_ALGORITHM = os.getenv('HASH_ALGORITHM', 'sha256')
ENABLE_ENCRYPTION = get_bool('ENABLE_ENCRYPTION', True)

# Storage Configuration
BLACKBOX_LOG_PATH = os.getenv('BLACKBOX_LOG_PATH', './logs/')
BLACKBOX_MAX_SIZE_MB = int(os.getenv('BLACKBOX_MAX_SIZE_MB', '50'))
BLACKBOX_ROTATION_COUNT = int(os.getenv('BLACKBOX_ROTATION_COUNT', '5'))

# Cloud Configuration
AWS_IOT_ENDPOINT = os.getenv('AWS_IOT_ENDPOINT', 'your-iot-endpoint.iot.region.amazonaws.com')
MQTT_TOPIC = os.getenv('MQTT_TOPIC', 'mesh-trace/node1/crash')
MQTT_QOS = int(os.getenv('MQTT_QOS', '1'))
CLOUD_REPORT_INTERVAL = int(os.getenv('CLOUD_REPORT_INTERVAL', '300'))

# Network Configuration
MESH_NETWORK_ID = os.getenv('MESH_NETWORK_ID', 'mesh-trace-001')
NODE_ID = os.getenv('NODE_ID', 'node1')

# Debug Configuration
DEBUG_MODE = get_bool('DEBUG_MODE', False)
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
