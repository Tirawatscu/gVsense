#!/usr/bin/env python3
"""
Diagnose timestamp interval issues
"""

def analyze_interval_issue(observed_interval_ms=20, configured_rate_hz=100):
    """
    Analyze why timestamps show wrong interval
    """
    
    print(f"\n{'='*70}")
    print(f"TIMESTAMP INTERVAL DIAGNOSIS")
    print(f"{'='*70}\n")
    
    print(f"Configuration:")
    print(f"  Configured rate: {configured_rate_hz}Hz")
    print(f"  Expected interval: {1000/configured_rate_hz}ms")
    print(f"  Observed interval: {observed_interval_ms}ms")
    print(f"  Observed rate: {1000/observed_interval_ms}Hz")
    print()
    
    # Calculate what rate would produce observed interval
    implied_rate = 1000.0 / observed_interval_ms
    
    print(f"Analysis:")
    print(f"  ❌ Mismatch detected!")
    print(f"  Timestamp generator thinks rate is: {implied_rate}Hz")
    print(f"  But you configured: {configured_rate_hz}Hz")
    print()
    
    print(f"Possible causes:")
    print(f"  1. Timestamp generator expected_rate not updated")
    print(f"  2. Rate set before timestamp generator initialized")
    print(f"  3. Different rate stored in device vs timestamp generator")
    print()
    
    print(f"What's happening:")
    print(f"  • MCU sends samples at {configured_rate_hz}Hz (correct)")
    print(f"  • Timestamp generator thinks rate is {implied_rate}Hz (wrong)")
    print(f"  • Each sequence increment = {1000/implied_rate}ms timestamp increment")
    print(f"  • Result: {observed_interval_ms}ms intervals instead of {1000/configured_rate_hz}ms")
    print()
    
    print(f"Fix:")
    print(f"  Ensure timestamp generator's expected_rate is set to {configured_rate_hz}Hz")
    print(f"  This should happen automatically in start_stream_at_rate()")
    print()
    
    print(f"{'='*70}\n")


def generate_fix_script():
    """Generate a fix to ensure rate is properly set"""
    
    print(f"\n{'='*70}")
    print(f"FIX: Add rate synchronization check")
    print(f"{'='*70}\n")
    
    fix_code = '''
# Add to web_server.py in start_stream():

# CRITICAL: Ensure timestamp generator rate matches streaming rate
if seismic and hasattr(seismic, 'timing_adapter'):
    try:
        actual_rate = config.get('stream_rate', 100.0)
        seismic.timing_adapter.timestamp_generator.update_rate(actual_rate)
        print(f"✅ Timestamp generator rate set to {actual_rate}Hz")
        print(f"   Expected interval: {1000/actual_rate}ms")
    except Exception as e:
        print(f"⚠️  Warning: Could not update timestamp generator rate: {e}")
'''
    
    print("Add this code to ensure the rate is properly synchronized:")
    print(fix_code)
    
    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║           TIMESTAMP INTERVAL DIAGNOSTIC TOOL                         ║
║                                                                      ║
║  Diagnose why InfluxDB shows wrong timestamp intervals              ║
╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    # Analyze the reported issue
    print("\n🔍 ANALYZING YOUR ISSUE:")
    print("  You configured: 100Hz (10ms interval)")
    print("  InfluxDB shows: 20ms interval")
    print()
    
    analyze_interval_issue(observed_interval_ms=20, configured_rate_hz=100)
    
    generate_fix_script()
    
    print("\n📊 VERIFICATION:")
    print("After applying the fix:")
    print("  1. Check timestamp generator rate:")
    print("     seismic.timing_adapter.timestamp_generator.expected_rate")
    print("     Should show: 100.0")
    print()
    print("  2. Check expected interval:")
    print("     seismic.timing_adapter.timestamp_generator.expected_interval_s")
    print("     Should show: 0.01 (10ms)")
    print()
    print("  3. Monitor InfluxDB intervals")
    print("     Should show: 10ms intervals (not 20ms)")
    print()

