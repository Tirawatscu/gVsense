#!/usr/bin/env python3
"""
Test Integration Script
Tests the integration between new components and web server
"""

import time
import logging
import json
from integrated_acquisition import IntegratedAcquisitionSystem

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_integration():
    """Test the integrated acquisition system"""
    print("Testing Integrated Acquisition System...")
    
    # Create system
    system = IntegratedAcquisitionSystem("/dev/ttyUSB0", 921600, "XIAO-1234")
    
    # Setup callbacks
    sample_count = 0
    stat_count = 0
    
    def sample_callback(sample):
        nonlocal sample_count
        sample_count += 1
        if sample_count % 100 == 0:
            print(f"Received {sample_count} samples")
            
    def status_callback(msg_type, data):
        nonlocal stat_count
        stat_count += 1
        print(f"Status: {msg_type} - {data}")
        
    system.sample_callback = sample_callback
    system.status_callback = status_callback
    
    try:
        # Start system
        print("Starting integrated system...")
        if system.start():
            print("✓ System started successfully")
            
            # Run for 30 seconds
            print("Running for 30 seconds...")
            time.sleep(30)
            
            # Check status
            status = system.get_status()
            print(f"\nSystem Status:")
            print(f"  Samples received: {sample_count}")
            print(f"  Status messages: {stat_count}")
            print(f"  Sample buffer size: {status['sample_buffer_size']}")
            print(f"  Stat buffer size: {status['stat_buffer_size']}")
            print(f"  Serial stats: {status['serial_stats']}")
            
            # Test calibration
            print("\nTesting calibration...")
            success = system.set_calibration(12.34, "test", "Integration test")
            print(f"  Calibration set: {success}")
            
            # Test command
            print("\nTesting command...")
            success = system.send_command("GET_CAL")
            print(f"  Command sent: {success}")
            
        else:
            print("✗ Failed to start system")
            
    except KeyboardInterrupt:
        print("\nShutting down...")
        
    finally:
        system.stop()
        print("System stopped")

def test_web_server_compatibility():
    """Test web server compatibility"""
    print("\nTesting Web Server Compatibility...")
    
    try:
        # Import web server components
        from integrated_acquisition import HostTimingSeismicAcquisition
        
        # Create acquisition instance
        acquisition = HostTimingSeismicAcquisition("/dev/ttyUSB0", 921600)
        
        print("✓ Web server compatibility wrapper created")
        
        # Test methods
        print("  Testing start method...")
        # Note: This would require actual hardware
        # success = acquisition.start()
        # print(f"  Start method: {success}")
        
        print("  Testing status method...")
        status = acquisition.get_status()
        print(f"  Status method: {len(status)} fields")
        
        print("✓ Web server compatibility test passed")
        
    except Exception as e:
        print(f"✗ Web server compatibility test failed: {e}")

if __name__ == "__main__":
    print("gVsense Integration Test")
    print("=" * 40)
    
    # Test integration
    test_integration()
    
    # Test web server compatibility
    test_web_server_compatibility()
    
    print("\nIntegration test completed!")
