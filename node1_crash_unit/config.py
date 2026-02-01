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
IMPACT_SENSOR_PINS = get_int_list('IMPACT_SENSOR_PINS', [22, 23, 24, 25])
# MPU6050_I2C_ADDRESS: 104 decimal = 0x68 hex
MPU6050_I2C_ADDRESS = int(os.getenv('MPU6050_I2C_ADDRESS', '104'))
MPU6050_I2C_BUS = int(os.getenv('MPU6050_I2C_BUS', '1'))
TEMPERATURE_SENSOR_PIN = int(os.getenv('TEMPERATURE_SENSOR_PIN', '4'))
GPS_SERIAL_PORT = os.getenv('GPS_SERIAL_PORT', '/dev/ttyS0')
GPS_BAUDRATE = int(os.getenv('GPS_BAUDRATE', '9600'))

# Crash Detection Thresholds (threshold-based, no AI)
IMPACT_THRESHOLD = float(os.getenv('IMPACT_THRESHOLD', '11.0'))
ACCELERATION_THRESHOLD = float(os.getenv('ACCELERATION_THRESHOLD', '9.8'))

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

# Storage Configuration
BLACKBOX_LOG_PATH = os.getenv('BLACKBOX_LOG_PATH', './logs/')
BLACKBOX_MAX_SIZE_MB = int(os.getenv('BLACKBOX_MAX_SIZE_MB', '50'))
BLACKBOX_ROTATION_COUNT = int(os.getenv('BLACKBOX_ROTATION_COUNT', '5'))

# Cloud Configuration
AWS_IOT_ENDPOINT = os.getenv('AWS_IOT_ENDPOINT')
MQTT_TOPIC = os.getenv('MQTT_TOPIC', 'mesh-trace/crash-alerts/node-001')
MQTT_QOS = int(os.getenv('MQTT_QOS', '1'))

# Network Configuration
MESH_NETWORK_ID = os.getenv('MESH_NETWORK_ID', 'mesh-trace-001')
NODE_ID = os.getenv('NODE_ID', 'mesh-trace-node-001')

# Debug Configuration
DEBUG_MODE = get_bool('DEBUG_MODE', False)
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# AWS IoT Certificates
AWS_CA_CERT = os.getenv('AWS_CA_CERT')
AWS_DEVICE_CERT = os.getenv('AWS_DEVICE_CERT')
AWS_PRIVATE_KEY = os.getenv('AWS_PRIVATE_KEY')

if not AWS_CA_CERT or not AWS_DEVICE_CERT or not AWS_PRIVATE_KEY:
    raise EnvironmentError("AWS IoT certificate paths not set")
