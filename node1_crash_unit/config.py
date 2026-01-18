"""
Configuration file for the crash detection unit (Node 1)
Raspberry Pi Zero WH settings and thresholds
"""

# Hardware Configuration
RASPBERRY_PI_MODEL = "Zero WH"

# Sensor Configuration
IMPACT_SENSOR_PIN = 18
MPU6050_I2C_ADDRESS = 0x68
MPU6050_I2C_BUS = 1
TEMPERATURE_SENSOR_PIN = 4  # DS18B20 GPIO pin
GPS_SERIAL_PORT = "/dev/ttyAMA0"
GPS_BAUDRATE = 9600

# Crash Detection Thresholds
IMPACT_THRESHOLD = 5.0  # G-force threshold for impact detection
ACCELERATION_THRESHOLD = 9.8  # m/s² (1G baseline)
ROTATION_THRESHOLD = 500  # deg/s for angular velocity
CRASH_CONFIDENCE_THRESHOLD = 0.85  # AI classifier confidence

# Sampling Configuration
SAMPLE_RATE = 100  # Hz
BUFFER_SIZE = 1000  # Number of samples to keep in buffer
PRE_CRASH_DURATION = 5  # seconds of data to save before crash

# LoRa Configuration
LORA_FREQUENCY = 915.0  # MHz (adjust for your region)
LORA_SPREADING_FACTOR = 7
LORA_BANDWIDTH = 125000
LORA_CODING_RATE = 5
LORA_POWER = 14  # dBm
LORA_CS_PIN = 8
LORA_RESET_PIN = 25
LORA_DIO0_PIN = 24

# Security Configuration
ENCRYPTION_KEY_SIZE = 32  # bytes (256-bit key)
HASH_ALGORITHM = "sha256"
ENABLE_ENCRYPTION = True

# Storage Configuration
BLACKBOX_LOG_PATH = "/var/log/mesh-trace/"
BLACKBOX_MAX_SIZE_MB = 50
BLACKBOX_ROTATION_COUNT = 5

# Cloud Configuration
AWS_IOT_ENDPOINT = "your-iot-endpoint.iot.region.amazonaws.com"
MQTT_TOPIC = "mesh-trace/node1/crash"
MQTT_QOS = 1
CLOUD_REPORT_INTERVAL = 300  # seconds between health reports

# Network Configuration
MESH_NETWORK_ID = "mesh-trace-001"
NODE_ID = "node1"

# Debug Configuration
DEBUG_MODE = False
LOG_LEVEL = "INFO"
