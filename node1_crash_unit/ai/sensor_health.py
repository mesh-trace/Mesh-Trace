"""
Sensor health monitoring
Monitors sensor status and data quality for diagnostics
"""

import time
from collections import deque


class SensorHealthMonitor:
    """Monitor health and status of all sensors"""
    
    def __init__(self):
        """Initialize health monitor"""
        self.sensor_history = {
            'impact': deque(maxlen=100),
            'mpu6050': deque(maxlen=100),
            'temperature': deque(maxlen=100),
            'gps': deque(maxlen=100)
        }
        self.last_check_time = {}
        self.error_counts = {
            'impact': 0,
            'mpu6050': 0,
            'temperature': 0,
            'gps': 0
        }
    
    def check_sensor(self, sensor_name, sensor_instance):
        """
        Check health of a specific sensor
        
        Args:
            sensor_name: Name identifier for the sensor
            sensor_instance: Sensor object instance
            
        Returns:
            dict: Health status information
        """
        health_status = {
            'name': sensor_name,
            'status': 'unknown',
            'last_read': None,
            'error_count': self.error_counts.get(sensor_name, 0),
            'data_quality': 'unknown',
            'timestamp': time.time()
        }
        
        try:
            # Try to read from sensor
            if sensor_name == 'impact':
                value = sensor_instance.read()
                if value is not None:
                    health_status['status'] = 'healthy'
                    health_status['last_read'] = value
                    health_status['data_quality'] = 'good'
                else:
                    health_status['status'] = 'degraded'
                    health_status['data_quality'] = 'no_data'
            
            elif sensor_name == 'mpu6050':
                accel = sensor_instance.read_acceleration()
                gyro = sensor_instance.read_gyroscope()
                if accel and gyro:
                    health_status['status'] = 'healthy'
                    health_status['last_read'] = {
                        'accel': accel,
                        'gyro': gyro
                    }
                    # Check if data is reasonable
                    if accel['magnitude'] > 0 and accel['magnitude'] < 100:
                        health_status['data_quality'] = 'good'
                    else:
                        health_status['data_quality'] = 'suspicious'
                        health_status['status'] = 'degraded'
                else:
                    health_status['status'] = 'error'
                    health_status['data_quality'] = 'no_data'
            
            elif sensor_name == 'temperature':
                value = sensor_instance.read()
                if value is not None:
                    health_status['status'] = 'healthy'
                    health_status['last_read'] = value
                    # Check for reasonable temperature range (-40 to 85°C)
                    if -40 <= value <= 85:
                        health_status['data_quality'] = 'good'
                    else:
                        health_status['data_quality'] = 'out_of_range'
                        health_status['status'] = 'warning'
                else:
                    health_status['status'] = 'degraded'
                    health_status['data_quality'] = 'no_data'
            
            elif sensor_name == 'gps':
                position = sensor_instance.get_position()
                if position:
                    health_status['status'] = 'healthy' if sensor_instance.has_fix() else 'no_fix'
                    health_status['last_read'] = position
                    health_status['data_quality'] = 'good' if sensor_instance.has_fix() else 'searching'
                else:
                    health_status['status'] = 'error'
                    health_status['data_quality'] = 'no_data'
            
            # Reset error count on successful read
            if health_status['status'] == 'healthy':
                self.error_counts[sensor_name] = 0
            else:
                self.error_counts[sensor_name] += 1
        
        except Exception as e:
            health_status['status'] = 'error'
            health_status['data_quality'] = 'error'
            health_status['error'] = str(e)
            self.error_counts[sensor_name] = self.error_counts.get(sensor_name, 0) + 1
        
        self.last_check_time[sensor_name] = time.time()
        return health_status
    
    def check_all_sensors(self, impact_sensor, mpu6050_sensor, temp_sensor, gps_sensor):
        """
        Check health of all sensors
        
        Args:
            impact_sensor: ImpactSensor instance
            mpu6050_sensor: MPU6050 instance
            temp_sensor: TemperatureSensor instance
            gps_sensor: GPSSensor instance
            
        Returns:
            dict: Health status for all sensors
        """
        health_report = {
            'timestamp': time.time(),
            'sensors': {},
            'overall_status': 'unknown',
            'warnings': [],
            'errors': []
        }
        
        # Check each sensor
        health_report['sensors']['impact'] = self.check_sensor('impact', impact_sensor)
        health_report['sensors']['mpu6050'] = self.check_sensor('mpu6050', mpu6050_sensor)
        health_report['sensors']['temperature'] = self.check_sensor('temperature', temp_sensor)
        health_report['sensors']['gps'] = self.check_sensor('gps', gps_sensor)
        
        # Determine overall status
        statuses = [s['status'] for s in health_report['sensors'].values()]
        error_count = sum(1 for s in statuses if s == 'error')
        warning_count = sum(1 for s in statuses if s in ['warning', 'degraded'])
        
        if error_count > 0:
            health_report['overall_status'] = 'error'
        elif warning_count > 1:
            health_report['overall_status'] = 'warning'
        elif all(s == 'healthy' or s == 'no_fix' for s in statuses):
            health_report['overall_status'] = 'healthy'
        else:
            health_report['overall_status'] = 'degraded'
        
        # Collect warnings and errors
        for name, sensor_health in health_report['sensors'].items():
            if sensor_health['status'] == 'error':
                health_report['errors'].append(f"{name}: {sensor_health.get('error', 'unknown error')}")
            elif sensor_health['status'] in ['warning', 'degraded']:
                health_report['warnings'].append(f"{name}: {sensor_health['data_quality']}")
        
        return health_report
    
    def get_statistics(self):
        """
        Get sensor statistics and trends
        
        Returns:
            dict: Statistical information about sensors
        """
        stats = {
            'error_counts': self.error_counts.copy(),
            'last_check_times': self.last_check_time.copy()
        }
        return stats
