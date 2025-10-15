#!/usr/bin/env python3
"""
Fix for UI offset calculation issue
The problem is that the UI is comparing calibrated MCU timestamps with GPS time incorrectly
"""

import requests
import time
import json
from datetime import datetime

def get_current_status():
    """Get current system status"""
    try:
        # Get calibration status
        cal_url = "http://localhost:5000/api/mcu/calibration/status"
        cal_response = requests.get(cal_url, timeout=10)
        cal_data = cal_response.json() if cal_response.status_code == 200 else {}
        
        # Get GPS alignment
        gps_url = "http://localhost:5000/api/gps/alignment"
        gps_response = requests.get(gps_url, timeout=10)
        gps_data = gps_response.json() if gps_response.status_code == 200 else {}
        
        # Get general status
        status_url = "http://localhost:5000/api/status"
        status_response = requests.get(status_url, timeout=10)
        status_data = status_response.json() if status_response.status_code == 200 else {}
        
        return {
            'calibration': cal_data,
            'gps_alignment': gps_data,
            'status': status_data
        }
    except Exception as e:
        print(f"Error getting status: {e}")
        return None

def analyze_offset_issue():
    """Analyze the offset calculation issue"""
    print("=== Analyzing UI Offset Calculation Issue ===")
    print()
    
    data = get_current_status()
    if not data:
        print("❌ Could not get system status")
        return
    
    # Extract key information
    mcu_status = data['calibration'].get('mcu_status', {})
    gps_alignment = data['gps_alignment'].get('gps_alignment', {})
    mcu_performance = data['gps_alignment'].get('mcu_performance', {})
    
    print("=== Current System State ===")
    print(f"MCU Calibration PPM: {mcu_status.get('calibration_ppm', 'N/A')}")
    print(f"MCU Calibration Source: {mcu_status.get('calibration_source', 'N/A')}")
    print(f"MCU Timing Source: {mcu_status.get('timing_source', 'N/A')}")
    print(f"MCU PPS Valid: {mcu_status.get('pps_valid', 'N/A')}")
    print()
    
    print("=== GPS Alignment Calculation ===")
    print(f"GPS Time: {gps_alignment.get('gps_time', 'N/A')}")
    print(f"MCU Time: {gps_alignment.get('mcu_time', 'N/A')}")
    print(f"GPS-MCU Alignment: {gps_alignment.get('gps_mcu_alignment_ms', 'N/A')}ms")
    print()
    
    print("=== Problem Analysis ===")
    
    # Check if MCU timestamp is 0 (the main issue)
    mcu_time = gps_alignment.get('mcu_time', 0)
    if mcu_time == 0:
        print("🔴 ISSUE FOUND: MCU timestamp is 0.0")
        print("   This means the timestamp generator is not properly initialized")
        print("   or the MCU timestamp is not being captured correctly.")
        print()
        print("   The UI offset calculation is:")
        print("   offset = (mcu_timestamp - gps_time) * 1000")
        print("   But if mcu_timestamp = 0, then:")
        print(f"   offset = (0 - {gps_alignment.get('gps_time', 'N/A')}) * 1000")
        print(f"   offset = -{gps_alignment.get('gps_time', 'N/A')} * 1000")
        print(f"   offset = {gps_alignment.get('gps_mcu_alignment_ms', 'N/A')}ms")
        print()
        print("   This explains why the offset is growing over time!")
        print("   The GPS time increases, so the offset becomes more negative.")
        print()
    
    # Check calibration status
    calibration_ppm = mcu_status.get('calibration_ppm', 0)
    calibration_source = mcu_status.get('calibration_source', 'NONE')
    
    if calibration_source == 'PPS_LIVE':
        print("✅ MCU is actively calibrating from PPS")
        print(f"   Current calibration: {calibration_ppm:.3f} ppm")
        print("   This means the MCU timestamps are already calibrated")
        print("   and should be accurate relative to GPS time.")
        print()
    
    print("=== Root Cause ===")
    print("The UI offset calculation has a fundamental flaw:")
    print("1. MCU sends calibrated timestamps (already corrected for oscillator drift)")
    print("2. UI tries to compare these calibrated timestamps with GPS time")
    print("3. But the timestamp generator is not properly initialized")
    print("4. So mcu_timestamp = 0, causing the offset to be -gps_time")
    print("5. As GPS time increases, the offset becomes more negative")
    print()
    
    print("=== Solution ===")
    print("The fix needs to be in the web server code:")
    print("1. Fix the timestamp generator initialization")
    print("2. Properly capture MCU timestamps from the data stream")
    print("3. Use the actual MCU timestamps for offset calculation")
    print("4. Account for the fact that MCU timestamps are already calibrated")
    print()

def monitor_offset_trend():
    """Monitor the offset trend over time to confirm the issue"""
    print("=== Monitoring Offset Trend ===")
    print("This will show how the offset changes over time")
    print("Press Ctrl+C to stop")
    print("-" * 60)
    
    try:
        start_time = time.time()
        while True:
            data = get_current_status()
            if data:
                gps_alignment = data['gps_alignment'].get('gps_alignment', {})
                mcu_time = gps_alignment.get('mcu_time', 0)
                gps_time = gps_alignment.get('gps_time', 0)
                offset_ms = gps_alignment.get('gps_mcu_alignment_ms', 0)
                
                elapsed = time.time() - start_time
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Elapsed: {elapsed:.1f}s | "
                      f"MCU Time: {mcu_time:.3f} | "
                      f"GPS Time: {gps_time:.3f} | "
                      f"Offset: {offset_ms:.1f}ms")
                
                if mcu_time == 0:
                    print("  ⚠️  MCU timestamp is still 0 - this confirms the issue!")
                
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped")

if __name__ == "__main__":
    analyze_offset_issue()
    print("\n" + "="*60)
    monitor_offset_trend()
