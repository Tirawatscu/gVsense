#!/usr/bin/env python3
"""
Monitor the calibration drift fix by tracking offset changes over time
"""

import requests
import time
import json
from datetime import datetime
import csv

def get_calibration_status():
    """Get current calibration status"""
    try:
        url = "http://localhost:5000/api/mcu/calibration/status"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error getting calibration status: {e}")
        return None

def get_timing_status():
    """Get timing status"""
    try:
        url = "http://localhost:5000/api/status"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error getting timing status: {e}")
        return None

def monitor_drift_fix(duration_minutes=30, check_interval=30):
    """Monitor the drift fix for a specified duration"""
    print(f"Monitoring calibration drift fix for {duration_minutes} minutes...")
    print("This will help verify that the offset no longer grows over time")
    print("-" * 80)
    
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    
    # CSV file for logging
    csv_filename = f"drift_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    with open(csv_filename, 'w', newline='') as csvfile:
        fieldnames = ['timestamp', 'elapsed_minutes', 'calibration_ppm', 'timing_source', 
                     'pps_valid', 'pps_age_ms', 'timing_accuracy_us', 'offset_stable']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        previous_ppm = None
        stable_count = 0
        
        try:
            while time.time() < end_time:
                current_time = time.time()
                elapsed_minutes = (current_time - start_time) / 60.0
                
                # Get calibration status
                cal_status = get_calibration_status()
                timing_status = get_timing_status()
                
                if not cal_status or not timing_status:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error getting status")
                    time.sleep(check_interval)
                    continue
                
                mcu_status = cal_status.get('mcu_status', {})
                mcu_timing = timing_status.get('mcu_timing', {})
                
                # Extract key metrics
                calibration_ppm = mcu_status.get('calibration_ppm', 0.0)
                timing_source = mcu_status.get('timing_source', 'UNKNOWN')
                pps_valid = mcu_status.get('pps_valid', False)
                pps_age_ms = mcu_status.get('pps_age_ms', 0)
                timing_accuracy_us = mcu_timing.get('accuracy_us', 1000000)
                
                # Check if calibration is stable
                offset_stable = "UNKNOWN"
                if previous_ppm is not None:
                    ppm_change = abs(calibration_ppm - previous_ppm)
                    if ppm_change < 0.001:  # Less than 0.001 ppm change
                        stable_count += 1
                        offset_stable = "STABLE"
                    else:
                        stable_count = 0
                        offset_stable = "DRIFTING"
                else:
                    offset_stable = "INITIAL"
                
                # Display status
                status_icon = "✓" if offset_stable == "STABLE" else "⚠" if offset_stable == "DRIFTING" else "?"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Elapsed: {elapsed_minutes:.1f}min | "
                      f"PPM: {calibration_ppm:.6f} | "
                      f"Source: {timing_source} | "
                      f"PPS: {'✓' if pps_valid else '✗'} ({pps_age_ms}ms) | "
                      f"Accuracy: {timing_accuracy_us}μs | "
                      f"Stable: {status_icon} ({stable_count})")
                
                # Log to CSV
                writer.writerow({
                    'timestamp': datetime.now().isoformat(),
                    'elapsed_minutes': round(elapsed_minutes, 2),
                    'calibration_ppm': calibration_ppm,
                    'timing_source': timing_source,
                    'pps_valid': pps_valid,
                    'pps_age_ms': pps_age_ms,
                    'timing_accuracy_us': timing_accuracy_us,
                    'offset_stable': offset_stable
                })
                csvfile.flush()
                
                # Check for issues
                if pps_age_ms > 2000:  # 2 seconds
                    print(f"  ⚠️  PPS age high: {pps_age_ms}ms")
                
                if timing_source != "PPS_ACTIVE":
                    print(f"  ⚠️  Not in PPS_ACTIVE mode: {timing_source}")
                
                if abs(calibration_ppm) > 50:
                    print(f"  ⚠️  High calibration value: {calibration_ppm:.6f} ppm")
                
                # Store for next iteration
                previous_ppm = calibration_ppm
                
                time.sleep(check_interval)
                
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
        except Exception as e:
            print(f"Error in monitoring: {e}")
    
    print(f"\nMonitoring completed. Data saved to: {csv_filename}")
    
    # Summary
    if stable_count > 0:
        print(f"✅ Calibration remained stable for {stable_count} consecutive measurements")
    else:
        print("⚠️  Calibration showed some variation during monitoring")
    
    return csv_filename

if __name__ == "__main__":
    import sys
    
    duration = 30  # Default 30 minutes
    interval = 30  # Default 30 seconds
    
    if len(sys.argv) > 1:
        duration = int(sys.argv[1])
    if len(sys.argv) > 2:
        interval = int(sys.argv[2])
    
    print(f"Starting drift monitoring: {duration} minutes, checking every {interval} seconds")
    monitor_drift_fix(duration, interval)
