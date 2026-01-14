#!/usr/bin/env python3
"""
Example usage of GPS location tracking with InfluxDB
Demonstrates how to integrate GPSUpdater with InfluxWriter
"""

import time
from influx_writer import InfluxWriter
from gps_updater import GPSUpdater


class MockGPSReader:
    """
    Mock GPS reader for demonstration purposes
    Replace this with your actual GPS reading implementation
    """
    
    def __init__(self):
        self.latitude = 13.7563
        self.longitude = 100.5018
        self.altitude = 45.2
        self.satellites = 8
        
    def get_location(self):
        """
        Get current GPS location
        Returns dict with GPS data or None if no fix
        
        Replace this with your actual GPS reading code, for example:
        - Reading from serial GPS module
        - Reading from GPS daemon (gpsd)
        - Reading from system location services
        """
        # Simulate slight GPS drift for demo
        import random
        drift = random.uniform(-0.0001, 0.0001)
        
        return {
            'valid': True,
            'latitude': self.latitude + drift,
            'longitude': self.longitude + drift,
            'altitude': self.altitude + random.uniform(-1, 1),
            'accuracy': random.uniform(1.5, 3.5),
            'satellites': self.satellites
        }


def main():
    """Example main function showing GPS integration"""
    
    # Initialize InfluxDB writer
    influx_writer = InfluxWriter(
        url="http://localhost:8086",
        token="your-influxdb-token",  # Replace with your token
        org="your-org",                # Replace with your org
        bucket="seismic-data",
        measurement="seismic",
        tags={
            'sensor_id': 'sensor_001',
            'site': 'Site_A'
        }
    )
    
    # Create GPS reader (replace with your actual GPS implementation)
    gps_reader = MockGPSReader()
    
    # Create GPS updater (updates every 60 seconds)
    gps_updater = GPSUpdater(
        influx_writer=influx_writer,
        gps_reader=gps_reader,
        interval_seconds=60  # Update every minute
    )
    
    # Start GPS updater
    gps_updater.start()
    
    try:
        # Your main seismic data acquisition loop
        sequence = 0
        print("Starting data acquisition... (Press Ctrl+C to stop)")
        
        while True:
            # Simulate reading seismic data at 100 Hz
            timestamp_ms = int(time.time() * 1000)
            channel_values = [1000, 1050, 980]  # Replace with actual ADC readings
            
            # Write seismic sample
            influx_writer.write_seismic_sample(
                timestamp=timestamp_ms,
                sequence=sequence,
                channel_values=channel_values
            )
            
            sequence += 1
            
            # Print status every 1000 samples
            if sequence % 1000 == 0:
                stats = influx_writer.get_stats()
                gps_stats = gps_updater.get_stats()
                print(f"Samples: {sequence}, "
                      f"InfluxDB points: {stats['points_written']}, "
                      f"GPS updates: {gps_stats['update_count']}")
            
            # Sleep to simulate 100 Hz sample rate
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\nStopping...")
    
    finally:
        # Cleanup
        gps_updater.stop()
        influx_writer.flush()
        influx_writer.close()
        print("Shutdown complete")


if __name__ == "__main__":
    main()
