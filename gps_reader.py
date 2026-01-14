#!/usr/bin/env python3
"""
GPS Reader for gVSense
Reads GPS coordinates from gpsd or NMEA serial
"""

import logging
import subprocess
import re


class GPSReader:
    """
    Reads GPS coordinates from system GPS daemon (gpsd) or NMEA
    """
    
    def __init__(self, method='gpsd'):
        """
        Initialize GPS reader
        
        Args:
            method: 'gpsd' (recommended) or 'nmea_serial'
        """
        self.method = method
        self.logger = logging.getLogger(__name__)
        self._last_valid_location = None
        
    def get_location(self):
        """
        Get current GPS location
        
        Returns:
            dict with keys:
                - valid (bool): True if GPS fix is available
                - latitude (float): Latitude in decimal degrees
                - longitude (float): Longitude in decimal degrees
                - altitude (float, optional): Altitude in meters
                - accuracy (float, optional): Accuracy in meters
                - satellites (int, optional): Number of satellites
        """
        if self.method == 'gpsd':
            return self._read_from_gpsd()
        elif self.method == 'cgps':
            return self._read_from_cgps()
        else:
            self.logger.error(f"Unknown GPS reading method: {self.method}")
            return {'valid': False}
    
    def _read_from_gpsd(self):
        """Read GPS data from gpsd using gpsmon or gpspipe"""
        try:
            # Try using gpspipe to get JSON output from gpsd
            result = subprocess.run(
                ['gpspipe', '-w', '-n', '10'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0:
                # Parse JSON output
                import json
                for line in result.stdout.split('\n'):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get('class') == 'TPV':  # Time-Position-Velocity report
                            mode = data.get('mode', 0)
                            if mode >= 2:  # 2D or 3D fix
                                location = {
                                    'valid': True,
                                    'latitude': data.get('lat', 0.0),
                                    'longitude': data.get('lon', 0.0),
                                    'altitude': data.get('alt'),
                                    'accuracy': data.get('epx'),  # Estimated position error
                                }
                                
                                # Try to get satellite count from SKY report
                                if data.get('satellites'):
                                    location['satellites'] = len(data.get('satellites', []))
                                
                                self._last_valid_location = location
                                return location
                    except json.JSONDecodeError:
                        continue
            
            # If no valid fix but we have a cached location, return it
            if self._last_valid_location:
                self.logger.warning("Using last known GPS location")
                return self._last_valid_location
            
            return {'valid': False}
            
        except FileNotFoundError:
            self.logger.error("gpspipe not found. Install gpsd: sudo apt-get install gpsd gpsd-clients")
            return {'valid': False}
        except subprocess.TimeoutExpired:
            self.logger.warning("GPS read timeout")
            if self._last_valid_location:
                return self._last_valid_location
            return {'valid': False}
        except Exception as e:
            self.logger.error(f"Error reading from gpsd: {e}")
            return {'valid': False}
    
    def _read_from_cgps(self):
        """Read GPS data using cgps command (simpler but less reliable)"""
        try:
            result = subprocess.run(
                ['cgps', '-s'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                # Parse cgps output
                lat = None
                lon = None
                alt = None
                satellites = None
                
                for line in result.stdout.split('\n'):
                    if 'Latitude:' in line:
                        match = re.search(r'([-+]?\d+\.\d+)', line)
                        if match:
                            lat = float(match.group(1))
                    elif 'Longitude:' in line:
                        match = re.search(r'([-+]?\d+\.\d+)', line)
                        if match:
                            lon = float(match.group(1))
                    elif 'Altitude:' in line:
                        match = re.search(r'([-+]?\d+\.?\d*)', line)
                        if match:
                            alt = float(match.group(1))
                    elif 'Satellites' in line:
                        match = re.search(r'(\d+)', line)
                        if match:
                            satellites = int(match.group(1))
                
                if lat is not None and lon is not None:
                    location = {
                        'valid': True,
                        'latitude': lat,
                        'longitude': lon,
                        'altitude': alt,
                        'satellites': satellites
                    }
                    self._last_valid_location = location
                    return location
            
            return {'valid': False}
            
        except Exception as e:
            self.logger.error(f"Error reading GPS with cgps: {e}")
            return {'valid': False}


class MockGPSReader:
    """
    Mock GPS reader for testing without hardware
    Returns fixed coordinates with slight random drift
    """
    
    def __init__(self, latitude=13.7563, longitude=100.5018, altitude=45.2):
        """
        Initialize mock GPS reader with fixed coordinates
        
        Args:
            latitude: Base latitude
            longitude: Base longitude
            altitude: Base altitude in meters
        """
        self.latitude = latitude
        self.longitude = longitude
        self.altitude = altitude
        self.logger = logging.getLogger(__name__)
        
    def get_location(self):
        """Get mock GPS location with random drift"""
        import random
        
        # Simulate slight GPS drift (~10 meters)
        drift = random.uniform(-0.0001, 0.0001)
        
        return {
            'valid': True,
            'latitude': self.latitude + drift,
            'longitude': self.longitude + drift,
            'altitude': self.altitude + random.uniform(-1, 1),
            'accuracy': random.uniform(1.5, 3.5),
            'satellites': random.randint(6, 12)
        }


# Auto-detect best GPS reader
def create_gps_reader(mock_coordinates=None):
    """
    Create appropriate GPS reader based on system configuration
    
    Args:
        mock_coordinates: If provided, use MockGPSReader with these coordinates
                         Format: (latitude, longitude, altitude)
    
    Returns:
        GPSReader or MockGPSReader instance
    """
    logger = logging.getLogger(__name__)
    
    if mock_coordinates:
        lat, lon, alt = mock_coordinates
        logger.info(f"Using mock GPS reader at ({lat}, {lon})")
        return MockGPSReader(lat, lon, alt)
    
    # Check if gpsd is available
    try:
        result = subprocess.run(['which', 'gpspipe'], capture_output=True, timeout=1)
        if result.returncode == 0:
            logger.info("Using gpsd for GPS coordinates")
            return GPSReader(method='gpsd')
    except:
        pass
    
    # Fallback to mock if no GPS available
    logger.warning("No GPS hardware detected, using mock GPS reader")
    return MockGPSReader()
