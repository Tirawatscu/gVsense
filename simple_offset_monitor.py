#!/usr/bin/env python3
"""
Simple GPS-MCU offset monitor - focuses on key timing metrics
"""

import requests
import time
from datetime import datetime
from collections import deque
import statistics

def monitor_timing(interval=5, duration_minutes=30):
    """Monitor timing offset and stability"""
    
    api_url = "http://localhost:5000"
    offsets = deque(maxlen=100)
    start_time = time.time()
    
    print("╔═══════════════════════════════════════════════════════════════════════════╗")
    print("║              📊 GPS-MCU TIMING OFFSET MONITOR                              ║")
    print("╚═══════════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Monitoring interval: {interval}s | Duration: {duration_minutes} minutes")
    print("Press Ctrl+C to stop...")
    print()
    
    try:
        while (time.time() - start_time) < (duration_minutes * 60):
            try:
                # Get GPS alignment data
                r = requests.get(f"{api_url}/api/gps/alignment", timeout=2)
                data = r.json()
                
                if data['status'] == 'ok':
                    gps_align = data['gps_alignment']
                    mcu_perf = data['mcu_performance']
                    perf_assess = data['performance_assessment']
                    
                    offset_ms = gps_align['gps_mcu_alignment_ms']
                    offsets.append(offset_ms)
                    
                    # Calculate statistics
                    if len(offsets) > 1:
                        avg_offset = statistics.mean(offsets)
                        std_offset = statistics.stdev(offsets)
                        min_offset = min(offsets)
                        max_offset = max(offsets)
                        range_offset = max_offset - min_offset
                    else:
                        avg_offset = offset_ms
                        std_offset = 0
                        min_offset = offset_ms
                        max_offset = offset_ms
                        range_offset = 0
                    
                    # Clear screen and print status
                    print("\033[2J\033[H")  # Clear screen
                    print("╔═══════════════════════════════════════════════════════════════════════════╗")
                    print("║              📊 GPS-MCU TIMING OFFSET MONITOR                              ║")
                    print("╚═══════════════════════════════════════════════════════════════════════════╝")
                    print()
                    
                    runtime = time.time() - start_time
                    print(f"⏱️  Runtime: {int(runtime//60)}m {int(runtime%60)}s | Samples: {len(offsets)}")
                    print(f"📅  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print()
                    
                    print("🎯 CURRENT OFFSET")
                    print("━" * 79)
                    print(f"  GPS-MCU Offset:       {offset_ms:+.2f} ms")
                    print(f"  GPS Time:             {gps_align['gps_time']:.3f} s")
                    print(f"  MCU Time:             {gps_align['mcu_time']:.3f} s")
                    print()
                    
                    print("📊 STATISTICAL ANALYSIS")
                    print("━" * 79)
                    print(f"  Average Offset:       {avg_offset:+.2f} ms")
                    print(f"  Std Deviation:        {std_offset:.2f} ms")
                    print(f"  Min Offset:           {min_offset:+.2f} ms")
                    print(f"  Max Offset:           {max_offset:+.2f} ms")
                    print(f"  Range (Max-Min):      {range_offset:.2f} ms")
                    print()
                    
                    print("🔧 MCU PERFORMANCE")
                    print("━" * 79)
                    print(f"  Timing Source:        {mcu_perf['timing_source']}")
                    print(f"  PPS Valid:            {'✅ Yes' if mcu_perf['pps_valid'] else '❌ No'}")
                    print(f"  Calibration PPM:      {mcu_perf['calibration_ppm']:.2f} ppm ({mcu_perf['calibration_source']})")
                    print(f"  GPS Frequency Error:  {gps_align['frequency_error_ppm']:+.3f} ppm")
                    print(f"  GPS RMS Offset:       {gps_align['rms_offset_ms']:.3f} ms")
                    print()
                    
                    print(f"🎯 PERFORMANCE ASSESSMENT: {perf_assess['grade']} {perf_assess['status_emoji']}")
                    print("━" * 79)
                    print(f"  Score:  {perf_assess['score']}/100")
                    print(f"  Status: {perf_assess['summary']}")
                    print()
                    
                    # Analysis
                    if std_offset < 1.0:
                        stability = "✅ EXCELLENT - Offset is very stable"
                    elif std_offset < 5.0:
                        stability = "✅ GOOD - Offset is reasonably stable"
                    elif std_offset < 10.0:
                        stability = "⚠️  FAIR - Some offset variation"
                    else:
                        stability = "🔴 POOR - High offset variation"
                    
                    print("💡 ANALYSIS")
                    print("━" * 79)
                    print(f"  Stability: {stability}")
                    
                    if abs(avg_offset) > 40 and std_offset < 5.0:
                        print(f"  Note: ~{abs(avg_offset):.0f}ms constant offset is likely GPS NMEA processing delay")
                        print(f"        This is NORMAL and doesn't affect relative timing accuracy")
                    elif abs(avg_offset) < 5 and std_offset < 1.0:
                        print(f"  Status: Excellent absolute timing alignment!")
                    
                    print()
                    print("Press Ctrl+C to stop...")
                
                time.sleep(interval)
                
            except requests.exceptions.RequestException as e:
                print(f"\n⚠️  Warning: Could not fetch timing data: {e}")
                time.sleep(interval)
                
    except KeyboardInterrupt:
        print("\n\n" + "═" * 79)
        print("MONITORING STOPPED - FINAL SUMMARY")
        print("═" * 79)
        
        if len(offsets) > 1:
            avg_offset = statistics.mean(offsets)
            std_offset = statistics.stdev(offsets)
            min_offset = min(offsets)
            max_offset = max(offsets)
            range_offset = max_offset - min_offset
            
            print(f"\n📊 TIMING OFFSET SUMMARY ({len(offsets)} samples)")
            print(f"   Runtime:           {int((time.time() - start_time) / 60)} minutes")
            print(f"   Average Offset:    {avg_offset:+.2f} ms")
            print(f"   Std Deviation:     {std_offset:.2f} ms")
            print(f"   Range:             {range_offset:.2f} ms ({min_offset:+.2f} to {max_offset:+.2f})")
            
            if std_offset < 1.0:
                print(f"\n   ✅ RESULT: Offset is STABLE (σ={std_offset:.2f}ms)")
                if abs(avg_offset) > 40:
                    print(f"   💡 The {abs(avg_offset):.0f}ms constant offset is GPS NMEA latency (normal)")
                    print(f"   ✅ This doesn't affect PPS-based timing accuracy (±1μs)")
            elif std_offset < 5.0:
                print(f"\n   ✅ RESULT: Offset is REASONABLY STABLE (σ={std_offset:.2f}ms)")
            else:
                print(f"\n   ⚠️  RESULT: Offset has HIGH VARIANCE (σ={std_offset:.2f}ms)")
                print(f"   🔍 Consider investigating GPS signal quality or PPS stability")
        
        print("\n" + "═" * 79)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor GPS-MCU timing offset")
    parser.add_argument('--interval', type=int, default=5,
                       help='Monitoring interval in seconds (default: 5)')
    parser.add_argument('--duration', type=int, default=30,
                       help='Monitoring duration in minutes (default: 30)')
    
    args = parser.parse_args()
    
    monitor_timing(interval=args.interval, duration_minutes=args.duration)
