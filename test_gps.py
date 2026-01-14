#!/usr/bin/env python3
"""
Test GPS integration before deploying
"""

import time
from gps_reader import create_gps_reader

def main():
    print("=" * 60)
    print("GPS Integration Test")
    print("=" * 60)
    
    # Test 1: Create GPS reader
    print("\n[Test 1] Creating GPS reader...")
    try:
        gps_reader = create_gps_reader()
        print("✓ GPS reader created successfully")
    except Exception as e:
        print(f"✗ Failed to create GPS reader: {e}")
        return
    
    # Test 2: Read GPS location (5 attempts)
    print("\n[Test 2] Reading GPS location (5 attempts)...")
    success_count = 0
    for i in range(5):
        try:
            location = gps_reader.get_location()
            if location.get('valid'):
                print(f"  Attempt {i+1}: ✓ Got GPS fix")
                print(f"    Latitude:   {location['latitude']:.6f}°")
                print(f"    Longitude:  {location['longitude']:.6f}°")
                if location.get('altitude'):
                    print(f"    Altitude:   {location['altitude']:.1f} m")
                if location.get('satellites'):
                    print(f"    Satellites: {location['satellites']}")
                if location.get('accuracy'):
                    print(f"    Accuracy:   {location['accuracy']:.1f} m")
                success_count += 1
            else:
                print(f"  Attempt {i+1}: ✗ No GPS fix")
            time.sleep(1)
        except Exception as e:
            print(f"  Attempt {i+1}: ✗ Error: {e}")
    
    print(f"\nGPS Success Rate: {success_count}/5 ({success_count*20}%)")
    
    # Test 3: Integration with InfluxDB (optional)
    print("\n[Test 3] Testing with InfluxDB (optional)...")
    try:
        from influx_writer import InfluxWriter
        from gps_updater import GPSUpdater
        import json
        
        # Try to load config
        try:
            with open('config.conf', 'r') as f:
                config = json.load(f)
            influx_config = config.get('data_saving', {}).get('influxdb', {})
            
            if influx_config.get('enabled'):
                print("  Creating InfluxWriter...")
                influx_writer = InfluxWriter(
                    url=influx_config.get('url', 'http://localhost:8086'),
                    token=influx_config.get('token'),
                    org=influx_config.get('org'),
                    bucket=influx_config.get('bucket'),
                    measurement="test_gps",
                    tags=influx_config.get('tags', {})
                )
                
                if influx_writer.connected:
                    print("  ✓ Connected to InfluxDB")
                    
                    # Write a test GPS location
                    location = gps_reader.get_location()
                    if location.get('valid'):
                        success = influx_writer.write_gps_location(
                            timestamp=int(time.time() * 1000),
                            latitude=location['latitude'],
                            longitude=location['longitude'],
                            altitude=location.get('altitude'),
                            accuracy=location.get('accuracy'),
                            satellites=location.get('satellites')
                        )
                        if success:
                            print("  ✓ Successfully wrote GPS location to InfluxDB")
                            print("  Query with:")
                            print(f"    influx query 'from(bucket: \"{influx_config.get('bucket')}\")")
                            print("      |> range(start: -5m)")
                            print("      |> filter(fn: (r) => r[\"_measurement\"] == \"sensor_location\")'")
                        else:
                            print("  ✗ Failed to write GPS location to InfluxDB")
                    else:
                        print("  ✗ No valid GPS fix to write")
                    
                    influx_writer.close()
                else:
                    print("  ✗ Failed to connect to InfluxDB")
                    print("  Check your config.conf InfluxDB settings")
            else:
                print("  ℹ InfluxDB not enabled in config.conf")
        except FileNotFoundError:
            print("  ℹ config.conf not found, skipping InfluxDB test")
    except ImportError as e:
        print(f"  ℹ Skipping InfluxDB test: {e}")
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
    
    if success_count >= 3:
        print("\n✓ GPS is working well! You can proceed with deployment.")
    elif success_count > 0:
        print("\n⚠ GPS is partially working. Check antenna and GPS daemon.")
    else:
        print("\n✗ GPS is not working. Troubleshooting needed:")
        print("  1. Check if gpsd is running: sudo systemctl status gpsd")
        print("  2. Check GPS device: ls -l /dev/ttyACM0")
        print("  3. Test with cgps: cgps -s")
        print("  4. Or use mock GPS in config: \"mock_coordinates\": [lat, lon, alt]")

if __name__ == "__main__":
    main()
