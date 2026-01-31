"""
GPS sensor interface
Provides location data for crash reporting
"""

import serial  # pyright: ignore[reportMissingModuleSource]
import time
try:
    from pynmea2 import parse  # pyright: ignore[reportMissingImports]
    NMEA_AVAILABLE = True
except ImportError:
    NMEA_AVAILABLE = False
    print("Warning: pynmea2 not available - GPS parsing will be limited")


class GPSSensor:
    """Interface for GPS module"""
    
    def __init__(self, port="/dev/ttyS0", baudrate=9600):
        """
        Initialize GPS sensor
        
        Args:
            port: Serial port path (default /dev/ttyAMA0 for Pi)
            baudrate: Serial communication baudrate (default 9600)
        """
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.initialized = False
        
        # GPS data cache
        self.last_position = {
            'latitude': None,
            'longitude': None,
            'altitude': None,
            'speed': None,
            'course': None,
            'timestamp': None,
            'satellites': 0,
            'fix_quality': 0
        }
        
        self._initialize()
    
    def _initialize(self):
        """Initialize serial connection to GPS"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            self.initialized = True
            time.sleep(0.5)  # Allow GPS to initialize
        except Exception as e:
            print(f"Warning: Could not initialize GPS: {e}")
            self.initialized = False
    
    def _parse_nmea(self, line):
        """Parse NMEA sentence"""
        if not NMEA_AVAILABLE:
            # Basic parsing without pynmea2
            if line.startswith('$GPGGA'):
                parts = line.split(',')
                if len(parts) >= 10:
                    try:
                        lat_raw = parts[2]
                        lat_dir = parts[3]
                        lon_raw = parts[4]
                        lon_dir = parts[5]
                        fix_quality = int(parts[6]) if parts[6] else 0
                        satellites = int(parts[7]) if parts[7] else 0
                        
                        if fix_quality > 0 and lat_raw and lon_raw:
                            # Convert NMEA format to decimal degrees
                            lat_deg = float(lat_raw[:2])
                            lat_min = float(lat_raw[2:])
                            latitude = lat_deg + (lat_min / 60.0)
                            if lat_dir == 'S':
                                latitude = -latitude
                            
                            lon_deg = float(lon_raw[:3])
                            lon_min = float(lon_raw[3:])
                            longitude = lon_deg + (lon_min / 60.0)
                            if lon_dir == 'W':
                                longitude = -longitude
                            
                            altitude = float(parts[9]) if parts[9] else None
                            
                            return {
                                'latitude': latitude,
                                'longitude': longitude,
                                'altitude': altitude,
                                'satellites': satellites,
                                'fix_quality': fix_quality
                            }
                    except (ValueError, IndexError):
                        pass
            return None
        else:
            # Use pynmea2 for parsing
            try:
                msg = parse(line)
                if hasattr(msg, 'latitude') and hasattr(msg, 'longitude'):
                    return {
                        'latitude': msg.latitude if msg.latitude else None,
                        'longitude': msg.longitude if msg.longitude else None,
                        'altitude': msg.altitude if hasattr(msg, 'altitude') else None,
                        'satellites': msg.num_sats if hasattr(msg, 'num_sats') else 0,
                        'fix_quality': int(msg.gps_qual) if hasattr(msg, 'gps_qual') else 0
                    }
            except Exception:
                pass
        
        return None
    
    def get_position(self):
        """
        Get current GPS position
        
        Returns:
            dict: GPS position data with latitude, longitude, altitude, etc.
        """
        if not self.initialized or not self.serial_conn:
            return self.last_position.copy()
        
        try:
            # Read available NMEA sentences
            start_time = time.time()
            while time.time() - start_time < 0.5:  # 500ms timeout
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    
                    if line.startswith('$GP'):
                        parsed = self._parse_nmea(line)
                        if parsed:
                            self.last_position.update(parsed)
                            self.last_position['timestamp'] = time.time()
                            break
                
                time.sleep(0.01)
            
            return self.last_position.copy()
        except Exception as e:
            print(f"Error reading GPS: {e}")
            return self.last_position.copy()
    
    def has_fix(self):
        """Check if GPS has a valid fix"""
        return (self.last_position['fix_quality'] > 0 and
                self.last_position['latitude'] is not None and
                self.last_position['longitude'] is not None)
    
    def cleanup(self):
        """Close serial connection"""
        if self.serial_conn and self.initialized:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.initialized = False
