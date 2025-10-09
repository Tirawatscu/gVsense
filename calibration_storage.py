#!/usr/bin/env python3
"""
Calibration Storage Module for gVsense
Provides atomic JSON storage for oscillator calibration data
"""

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)

class CalibrationStorage:
    """Atomic calibration storage with JSON persistence"""
    
    def __init__(self, base_dir: str = "/var/lib/gvsense"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_device_dir(self, device_id: str) -> Path:
        """Get device-specific directory"""
        device_dir = self.base_dir / device_id
        device_dir.mkdir(parents=True, exist_ok=True)
        return device_dir
    
    def _get_calibration_file(self, device_id: str) -> Path:
        """Get calibration.json file path for device"""
        return self._get_device_dir(device_id) / "calibration.json"
    
    def load_calibration(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Load calibration data for device"""
        cal_file = self._get_calibration_file(device_id)
        
        if not cal_file.exists():
            logger.debug(f"No calibration file found for device {device_id}")
            return None
            
        try:
            with open(cal_file, 'r') as f:
                data = json.load(f)
                
            # Validate required fields
            required_fields = ['version', 'device_id', 'ppm', 'source']
            if not all(field in data for field in required_fields):
                logger.warning(f"Invalid calibration file for device {device_id}: missing required fields")
                return None
                
            logger.debug(f"Loaded calibration for {device_id}: {data['ppm']} ppm from {data['source']}")
            return data
            
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load calibration for device {device_id}: {e}")
            return None
    
    def save_calibration(self, device_id: str, ppm: float, source: str, 
                        temp_ref_c: float = 25.0, ppm_vs_temp: float = 0.0,
                        notes: str = "") -> bool:
        """Atomically save calibration data"""
        cal_file = self._get_calibration_file(device_id)
        
        data = {
            "version": 1,
            "device_id": device_id,
            "last_update_utc": datetime.utcnow().isoformat() + "Z",
            "source": source,  # "pps", "manual", "learned"
            "ppm": ppm,
            "temp_ref_c": temp_ref_c,
            "ppm_vs_temp": ppm_vs_temp,
            "notes": notes
        }
        
        try:
            # Atomic write: write to temp file, fsync, then rename
            with tempfile.NamedTemporaryFile(mode='w', dir=cal_file.parent, 
                                           delete=False, suffix='.tmp') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
                temp_file = f.name
            
            # Atomic rename
            os.rename(temp_file, cal_file)
            
            logger.info(f"Saved calibration for {device_id}: {ppm} ppm from {source}")
            return True
            
        except (IOError, OSError) as e:
            logger.error(f"Failed to save calibration for device {device_id}: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_file' in locals():
                    os.unlink(temp_file)
            except OSError:
                pass
            return False
    
    def clear_calibration(self, device_id: str) -> bool:
        """Remove calibration file for device"""
        cal_file = self._get_calibration_file(device_id)
        
        try:
            if cal_file.exists():
                cal_file.unlink()
                logger.info(f"Cleared calibration for device {device_id}")
            return True
        except OSError as e:
            logger.error(f"Failed to clear calibration for device {device_id}: {e}")
            return False
    
    def list_devices(self) -> list:
        """List all devices with calibration data"""
        devices = []
        
        try:
            for device_dir in self.base_dir.iterdir():
                if device_dir.is_dir():
                    cal_file = device_dir / "calibration.json"
                    if cal_file.exists():
                        devices.append(device_dir.name)
        except OSError as e:
            logger.error(f"Failed to list devices: {e}")
            
        return devices
    
    def get_calibration_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get calibration info without loading full data"""
        cal_file = self._get_calibration_file(device_id)
        
        if not cal_file.exists():
            return None
            
        try:
            stat = cal_file.stat()
            return {
                "device_id": device_id,
                "file_size": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "exists": True
            }
        except OSError:
            return None

# CLI interface
def main():
    """Command-line interface for calibration management"""
    import argparse
    
    parser = argparse.ArgumentParser(description="gVsense Calibration Management")
    parser.add_argument("command", choices=["read", "set", "clear", "list"], 
                       help="Command to execute")
    parser.add_argument("device_id", nargs="?", help="Device ID")
    parser.add_argument("--ppm", type=float, help="PPM value for set command")
    parser.add_argument("--source", default="manual", choices=["pps", "manual", "learned"],
                       help="Calibration source")
    parser.add_argument("--note", default="", help="Notes for calibration")
    parser.add_argument("--base-dir", default="/var/lib/gvsense", 
                       help="Base directory for calibration storage")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    storage = CalibrationStorage(args.base_dir)
    
    if args.command == "read":
        if not args.device_id:
            parser.error("Device ID required for read command")
            
        cal_data = storage.load_calibration(args.device_id)
        if cal_data:
            print(f"Device: {cal_data['device_id']}")
            print(f"PPM: {cal_data['ppm']}")
            print(f"Source: {cal_data['source']}")
            print(f"Last Update: {cal_data['last_update_utc']}")
            print(f"Notes: {cal_data.get('notes', '')}")
        else:
            print(f"No calibration found for device {args.device_id}")
            return 1
            
    elif args.command == "set":
        if not args.device_id or args.ppm is None:
            parser.error("Device ID and --ppm required for set command")
            
        success = storage.save_calibration(args.device_id, args.ppm, args.source, 
                                         notes=args.note)
        if success:
            print(f"Calibration set for {args.device_id}: {args.ppm} ppm")
        else:
            print(f"Failed to set calibration for {args.device_id}")
            return 1
            
    elif args.command == "clear":
        if not args.device_id:
            parser.error("Device ID required for clear command")
            
        success = storage.clear_calibration(args.device_id)
        if success:
            print(f"Calibration cleared for {args.device_id}")
        else:
            print(f"Failed to clear calibration for {args.device_id}")
            return 1
            
    elif args.command == "list":
        devices = storage.list_devices()
        if devices:
            print("Devices with calibration data:")
            for device_id in devices:
                info = storage.get_calibration_info(device_id)
                if info:
                    print(f"  {device_id}: {info['modified_time']}")
        else:
            print("No devices with calibration data found")
    
    return 0

if __name__ == "__main__":
    exit(main())
