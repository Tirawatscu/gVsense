#!/usr/bin/env python3
"""
Timing Alignment Test - Prove MCU timestamps align with real time
"""

import requests
import time
import json
from datetime import datetime

def get_timing_status():
    try:
        response = requests.get('http://localhost:5000/api/timing/status', timeout=5)
        return response.json()
    except:
        return None

def get_mcu_status():
    try:
        response = requests.get('http://localhost:5000/api/mcu/calibration/status', timeout=5)
        return response.json()
    except:
        return None

def test_alignment():
    print("🕐 TIMING ALIGNMENT PROOF")
    print("=" * 50)
    
    # Get current system time
    system_time = time.time()
    print(f"📅 Current system time: {datetime.fromtimestamp(system_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
    
    # Get timing status
    timing = get_timing_status()
    if not timing:
        print("❌ Cannot connect to timing service")
        return
    
    # Get MCU status
    mcu = get_mcu_status()
    if not mcu:
        print("❌ Cannot connect to MCU service")
        return
    
    print(f"\n📊 MCU Status:")
    print(f"   Timing Source: {mcu['mcu_status']['timing_source']}")
    print(f"   PPS Valid: {mcu['mcu_status']['pps_valid']}")
    print(f"   Calibration: {mcu['mcu_status']['calibration_ppm']} ppm ({mcu['mcu_status']['calibration_source']})")
    print(f"   Accuracy: ±{mcu['mcu_status']['timing_accuracy_us']/1000}ms")
    
    print(f"\n📈 Timing Health:")
    health = timing['timestamp_health']
    print(f"   Last Timestamp: {datetime.fromtimestamp(health['last_timestamp']/1000).strftime('%H:%M:%S.%f')[:-3]}")
    print(f"   Offset: {health['offset_ms']:+.1f} ms")
    print(f"   Precise Offset: {health['offset_precise_ms']:+.1f} ms")
    
    print(f"\n🎯 Quality Metrics:")
    controller = timing['controller']
    print(f"   Error Measurements: {controller['measurements_taken']} taken")
    print(f"   Average Error: {controller['avg_error_ms']:.3f} ms")
    print(f"   Max Error: {controller['max_error_ms']:.3f} ms")
    print(f"   Corrections Applied: {controller['corrections_applied']}")
    
    print(f"\n📡 System Health:")
    system_health = timing['system_health']
    print(f"   Overall Status: {system_health['overall_status']}")
    print(f"   Reference Quality: {system_health['reference_quality']}")
    print(f"   Stability: {system_health['stability']}")
    
    # Alignment assessment
    print(f"\n🔬 ALIGNMENT ASSESSMENT:")
    if abs(health['offset_ms']) < 10:
        print("✅ EXCELLENT: MCU timestamps are well-aligned with real time")
    elif abs(health['offset_ms']) < 50:
        print("✅ GOOD: MCU timestamps are reasonably aligned with real time")
    else:
        print("❌ POOR: MCU timestamps are significantly misaligned")
    
    if controller['avg_error_ms'] < 1:
        print("✅ EXCELLENT: Timing system maintains sub-millisecond accuracy")
    elif controller['avg_error_ms'] < 5:
        print("✅ GOOD: Timing system maintains millisecond accuracy")
    else:
        print("❌ POOR: Timing system has significant timing errors")

if __name__ == "__main__":
    test_alignment()
