#!/usr/bin/env python3
"""
Enhanced Host Acquisition with Calibration Management
Extends HostTimingSeismicAcquisition with Pi-side calibration storage
"""

import time
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from calibration_storage import CalibrationStorage

# Import the existing host acquisition class
from host_timing_acquisition import HostTimingSeismicAcquisition

logger = logging.getLogger(__name__)

class EnhancedHostAcquisition(HostTimingSeismicAcquisition):
    """Enhanced host acquisition with calibration management"""
    
    def __init__(self, port=None, baudrate=921600, device_id="XIAO-1234"):
        super().__init__(port, baudrate)
        self.device_id = device_id
        self.calibration_storage = CalibrationStorage()
        
        # Calibration state
        self.mcu_calibration_valid = False
        self.mcu_calibration_ppm = 0.0
        self.mcu_calibration_source = "NONE"
        self.mcu_timing_source = "INTERNAL_RAW"
        self.mcu_pps_valid = False
        self.mcu_pps_age_ms = 0
        self.mcu_boot_id = None
        self.mcu_firmware_version = None
        
        # Calibration management
        self.calibration_push_enabled = True
        self.last_calibration_update = 0
        self.stable_pps_start_time = None
        self.stable_pps_threshold_ms = 600000  # 10 minutes
        
        # Threading
        self.calibration_thread = None
        self.stop_calibration_thread = False
        
    def start(self):
        """Start acquisition with calibration management"""
        # Start calibration monitoring thread
        self.stop_calibration_thread = False
        self.calibration_thread = threading.Thread(target=self._calibration_monitor, daemon=True)
        self.calibration_thread.start()
        
        # Start the main acquisition
        super().start()
        
    def stop(self):
        """Stop acquisition and calibration monitoring"""
        self.stop_calibration_thread = True
        if self.calibration_thread:
            self.calibration_thread.join(timeout=1.0)
        super().stop()
        
    def _calibration_monitor(self):
        """Monitor MCU status and manage calibration"""
        logger.info("Calibration monitor started")
        
        while not self.stop_calibration_thread:
            try:
                # Get current MCU status
                self._get_mcu_status()
                
                # Handle calibration based on current state
                self._handle_calibration_logic()
                
                # Sleep for 1 second
                time.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Error in calibration monitor: {e}")
                time.sleep(5.0)  # Longer sleep on error
                
        logger.info("Calibration monitor stopped")
        
    def _get_mcu_status(self):
        """Get current MCU status via GET_TIMING_STATUS command"""
        try:
            if not self.serial_port or not self.serial_port.is_open:
                return
                
            # Send GET_TIMING_STATUS command
            self.serial_port.write(b"GET_TIMING_STATUS\n")
            self.serial_port.flush()
            
            # Read response (with timeout)
            start_time = time.time()
            response = ""
            
            while time.time() - start_time < 2.0:  # 2 second timeout
                if self.serial_port.in_waiting > 0:
                    char = self.serial_port.read(1).decode('utf-8', errors='ignore')
                    response += char
                    
                    if char == '\n':
                        break
                time.sleep(0.01)
                
            # Parse response
            self._parse_status_response(response.strip())
            
        except Exception as e:
            logger.debug(f"Failed to get MCU status: {e}")
            
    def _parse_status_response(self, response: str):
        """Parse MCU status response"""
        if not response.startswith("STATUS:"):
            return
            
        try:
            # Parse STATUS: format
            parts = response[7:].split(',')  # Remove "STATUS:" prefix
            
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    
                    if key == 'timing_source':
                        self.mcu_timing_source = value
                    elif key == 'accuracy_us':
                        pass  # We don't need to store this
                    elif key == 'calibration_ppm':
                        self.mcu_calibration_ppm = float(value)
                    elif key == 'calibration_valid':
                        self.mcu_calibration_valid = value == '1'
                    elif key == 'calibration_source':
                        self.mcu_calibration_source = value
                    elif key == 'pps_valid':
                        self.mcu_pps_valid = value == '1'
                    elif key == 'pps_age_ms':
                        self.mcu_pps_age_ms = int(value)
                    elif key == 'boot_id':
                        self.mcu_boot_id = value
                        
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse status response: {e}")
            
    def _handle_calibration_logic(self):
        """Handle calibration logic based on current state"""
        current_time = time.time()
        
        # Check if we have stable PPS
        if self.mcu_timing_source == "PPS_ACTIVE" and self.mcu_pps_valid:
            if self.stable_pps_start_time is None:
                self.stable_pps_start_time = current_time
                logger.info("PPS lock detected, starting stability timer")
                
            # Check if PPS has been stable long enough
            if (current_time - self.stable_pps_start_time) * 1000 > self.stable_pps_threshold_ms:
                # PPS has been stable for threshold time
                self._update_calibration_from_pps()
                
        else:
            # PPS not stable, reset timer
            if self.stable_pps_start_time is not None:
                logger.info("PPS lost, resetting stability timer")
                self.stable_pps_start_time = None
                
        # Handle boot/reconnect handshake
        if self.mcu_boot_id and not self.mcu_calibration_valid and not self.mcu_pps_valid:
            self._handle_boot_handshake()
            
    def _update_calibration_from_pps(self):
        """Update calibration.json when PPS is stable and ppm changed"""
        try:
            # Load current stored calibration
            stored_cal = self.calibration_storage.load_calibration(self.device_id)
            
            if stored_cal is None:
                # No stored calibration, save current PPS calibration
                self.calibration_storage.save_calibration(
                    self.device_id, 
                    self.mcu_calibration_ppm, 
                    "pps",
                    notes=f"Stable PPS lock for {self.stable_pps_threshold_ms/60000:.1f} minutes"
                )
                logger.info(f"Saved new PPS calibration: {self.mcu_calibration_ppm} ppm")
                
            else:
                # Check if ppm changed significantly
                ppm_diff = abs(self.mcu_calibration_ppm - stored_cal['ppm'])
                
                if ppm_diff >= 0.5:  # 0.5 ppm threshold
                    self.calibration_storage.save_calibration(
                        self.device_id,
                        self.mcu_calibration_ppm,
                        "pps",
                        notes=f"PPS calibration update: {ppm_diff:.2f} ppm change"
                    )
                    logger.info(f"Updated PPS calibration: {self.mcu_calibration_ppm} ppm (change: {ppm_diff:.2f} ppm)")
                    
        except Exception as e:
            logger.error(f"Failed to update calibration from PPS: {e}")
            
    def _handle_boot_handshake(self):
        """Handle boot/reconnect handshake"""
        try:
            # Load stored calibration
            stored_cal = self.calibration_storage.load_calibration(self.device_id)
            
            if stored_cal and self.calibration_push_enabled:
                # Push stored calibration to MCU
                ppm_value = stored_cal['ppm']
                self._send_calibration_to_mcu(ppm_value)
                
                logger.info(f"Boot handshake: pushed calibration {ppm_value} ppm to MCU")
                
        except Exception as e:
            logger.error(f"Failed to handle boot handshake: {e}")
            
    def _send_calibration_to_mcu(self, ppm_value: float):
        """Send calibration to MCU via SET_CAL_PPM command"""
        try:
            if not self.serial_port or not self.serial_port.is_open:
                return False
                
            command = f"SET_CAL_PPM:{ppm_value:.2f}\n"
            self.serial_port.write(command.encode())
            self.serial_port.flush()
            
            # Wait for response
            start_time = time.time()
            response = ""
            
            while time.time() - start_time < 2.0:  # 2 second timeout
                if self.serial_port.in_waiting > 0:
                    char = self.serial_port.read(1).decode('utf-8', errors='ignore')
                    response += char
                    
                    if char == '\n':
                        break
                time.sleep(0.01)
                
            if "OK:Pi calibration set" in response:
                logger.info(f"Successfully sent calibration {ppm_value} ppm to MCU")
                return True
            else:
                logger.warning(f"MCU rejected calibration: {response.strip()}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send calibration to MCU: {e}")
            return False
            
    def set_calibration(self, ppm_value: float, source: str = "manual", notes: str = "") -> bool:
        """Manually set calibration"""
        try:
            # Save to storage
            success = self.calibration_storage.save_calibration(
                self.device_id, ppm_value, source, notes=notes
            )
            
            if success:
                # Send to MCU if connected
                if self.serial_port and self.serial_port.is_open:
                    self._send_calibration_to_mcu(ppm_value)
                    
                logger.info(f"Set calibration: {ppm_value} ppm from {source}")
                return True
            else:
                logger.error(f"Failed to save calibration: {ppm_value} ppm")
                return False
                
        except Exception as e:
            logger.error(f"Failed to set calibration: {e}")
            return False
            
    def clear_calibration(self) -> bool:
        """Clear calibration"""
        try:
            # Clear from storage
            success = self.calibration_storage.clear_calibration(self.device_id)
            
            if success:
                # Send CLEAR_CAL to MCU if connected
                if self.serial_port and self.serial_port.is_open:
                    self.serial_port.write(b"CLEAR_CAL\n")
                    self.serial_port.flush()
                    
                logger.info("Cleared calibration")
                return True
            else:
                logger.error("Failed to clear calibration")
                return False
                
        except Exception as e:
            logger.error(f"Failed to clear calibration: {e}")
            return False
            
    def get_calibration_status(self) -> Dict[str, Any]:
        """Get current calibration status"""
        stored_cal = self.calibration_storage.load_calibration(self.device_id)
        
        return {
            "device_id": self.device_id,
            "mcu_calibration_valid": self.mcu_calibration_valid,
            "mcu_calibration_ppm": self.mcu_calibration_ppm,
            "mcu_calibration_source": self.mcu_calibration_source,
            "mcu_timing_source": self.mcu_timing_source,
            "mcu_pps_valid": self.mcu_pps_valid,
            "mcu_pps_age_ms": self.mcu_pps_age_ms,
            "stored_calibration": stored_cal,
            "stable_pps": self.stable_pps_start_time is not None
        }

# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Host Acquisition with Calibration")
    parser.add_argument("--port", help="Serial port")
    parser.add_argument("--device-id", default="XIAO-1234", help="Device ID")
    parser.add_argument("--baudrate", type=int, default=921600, help="Baud rate")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create enhanced acquisition
    acquisition = EnhancedHostAcquisition(
        port=args.port,
        baudrate=args.baudrate,
        device_id=args.device_id
    )
    
    try:
        acquisition.start()
        
        # Keep running
        while True:
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        print("\nShutting down...")
        acquisition.stop()
