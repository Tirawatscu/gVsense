#!/usr/bin/env python3
"""
PPS Monitor Script
Monitors PPS signal status and chrony synchronization
"""

import time
import subprocess
import sys
import os
from datetime import datetime

class PPSMonitor:
    def __init__(self):
        self.pps_device = "/dev/pps0"
        self.monitoring = False
        
    def check_pps_device(self):
        """Check if PPS device exists and is accessible"""
        try:
            if os.path.exists(self.pps_device):
                # Try to read from PPS device
                with open(self.pps_device, 'r') as f:
                    # Non-blocking read
                    f.read(0)
                return True
            return False
        except (OSError, PermissionError):
            return False
    
    def get_chrony_sources(self):
        """Get chrony sources status"""
        try:
            result = subprocess.run(['chronyc', 'sources'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
    
    def get_chrony_tracking(self):
        """Get chrony tracking information"""
        try:
            result = subprocess.run(['chronyc', 'tracking'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
    
    def get_pps_status(self):
        """Get PPS status from chrony"""
        try:
            result = subprocess.run(['chronyc', 'sources'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'PPS' in line or 'GPS' in line:
                        return line.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
    
    def monitor_pps(self, interval=5):
        """Monitor PPS status continuously"""
        print(f"🔍 Starting PPS monitoring (interval: {interval}s)")
        print("Press Ctrl+C to stop")
        print("-" * 80)
        
        self.monitoring = True
        try:
            while self.monitoring:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Check PPS device
                pps_device_ok = self.check_pps_device()
                pps_status = "✅ OK" if pps_device_ok else "❌ Not found"
                
                # Get chrony sources
                sources = self.get_chrony_sources()
                pps_line = None
                if sources:
                    for line in sources.split('\n'):
                        if 'PPS' in line or 'GPS' in line:
                            pps_line = line.strip()
                            break
                
                # Get tracking info
                tracking = self.get_chrony_tracking()
                
                # Display status
                print(f"[{timestamp}] PPS Device: {pps_status}")
                if pps_line:
                    print(f"[{timestamp}] PPS Source: {pps_line}")
                else:
                    print(f"[{timestamp}] PPS Source: Not found")
                
                if tracking:
                    # Extract key tracking info
                    for line in tracking.split('\n'):
                        if 'Reference time' in line or 'System time' in line or 'Last offset' in line:
                            print(f"[{timestamp}] {line.strip()}")
                
                print("-" * 80)
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n🛑 PPS monitoring stopped")
            self.monitoring = False
    
    def get_status_summary(self):
        """Get a summary of PPS status"""
        print("📊 PPS Status Summary")
        print("=" * 50)
        
        # Check PPS device
        pps_device_ok = self.check_pps_device()
        print(f"PPS Device ({self.pps_device}): {'✅ OK' if pps_device_ok else '❌ Not found'}")
        
        # Get chrony sources
        sources = self.get_chrony_sources()
        if sources:
            print("\nChrony Sources:")
            print(sources)
        else:
            print("\nChrony Sources: Not available")
        
        # Get tracking
        tracking = self.get_chrony_tracking()
        if tracking:
            print("\nChrony Tracking:")
            print(tracking)
        else:
            print("\nChrony Tracking: Not available")

def main():
    monitor = PPSMonitor()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "monitor":
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5
            monitor.monitor_pps(interval)
        elif sys.argv[1] == "status":
            monitor.get_status_summary()
        else:
            print("Usage: python3 pps_monitor.py [monitor [interval]|status]")
    else:
        monitor.get_status_summary()

if __name__ == "__main__":
    main()
