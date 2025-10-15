#!/usr/bin/env python3
"""
Monitor MCU calibration status to verify the drift fix is working
"""

import requests
import time
import json
from datetime import datetime

def send_mcu_command(command):
    """Send a command to the MCU via the web API"""
    try:
        # Use the test endpoint to send commands
        url = "http://localhost:5000/api/mcu/calibration/test"
        data = {"command": command}
        
        # For GET commands, we need to modify the endpoint
        if command.startswith("GET_"):
            # We'll need to implement this differently
            return None, "GET commands not supported via this endpoint"
        
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return True, result.get('response', 'No response')
        else:
            return False, f"HTTP {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)

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

def monitor_calibration_drift():
    """Monitor calibration drift over time"""
    print("Monitoring MCU calibration drift...")
    print("Press Ctrl+C to stop")
    print("-" * 80)
    
    start_time = time.time()
    last_cal_base = None
    last_sample_index = None
    
    try:
        while True:
            # Get calibration status
            status = get_calibration_status()
            if not status:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error getting status")
                time.sleep(5)
                continue
            
            mcu_status = status.get('mcu_status', {})
            calibration = status.get('calibration', {})
            
            # Extract key metrics
            current_time = time.time()
            elapsed_minutes = (current_time - start_time) / 60.0
            
            calibration_ppm = mcu_status.get('calibration_ppm', 0.0)
            calibration_valid = mcu_status.get('calibration_valid', False)
            timing_source = mcu_status.get('timing_source', 'UNKNOWN')
            pps_valid = mcu_status.get('pps_valid', False)
            pps_age_ms = mcu_status.get('pps_age_ms', 0)
            
            # Check for sample index and reference updates (from STAT line)
            # These would be in the enhanced STAT line we added
            sample_index = mcu_status.get('sample_index', 0)  # This might not be available yet
            ref_updates = mcu_status.get('reference_updates_count', 0)
            
            # Calculate drift indicators
            drift_info = ""
            if last_cal_base is not None:
                # This would require the detailed calibration info
                pass
            
            # Display status
            print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                  f"Elapsed: {elapsed_minutes:.1f}min | "
                  f"PPM: {calibration_ppm:.3f} | "
                  f"Source: {timing_source} | "
                  f"PPS: {'✓' if pps_valid else '✗'} ({pps_age_ms}ms) | "
                  f"Valid: {'✓' if calibration_valid else '✗'}")
            
            if sample_index > 0:
                print(f"  Sample Index: {sample_index}, Ref Updates: {ref_updates}")
            
            # Check for potential issues
            if pps_age_ms > 5000:  # 5 seconds
                print(f"  ⚠️  PPS age high: {pps_age_ms}ms")
            
            if abs(calibration_ppm) > 50:
                print(f"  ⚠️  High calibration value: {calibration_ppm:.3f} ppm")
            
            # Store current values for next iteration
            last_cal_base = calibration_ppm
            last_sample_index = sample_index
            
            time.sleep(10)  # Check every 10 seconds
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    except Exception as e:
        print(f"Error in monitoring: {e}")

if __name__ == "__main__":
    monitor_calibration_drift()
