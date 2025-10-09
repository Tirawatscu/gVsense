#!/usr/bin/env python3
"""
Integrated Acquisition System
Combines all new components into a unified system for web server integration
"""

import time
import logging
import threading
from typing import Dict, Any, Optional, List, Callable
from collections import deque

# Import all new components
from fast_serial_reader import FastSerialReader
from crc_verification import CRCVerifier, BinaryFrameParser
from backpressure_monitor import BackpressureMonitor
from utc_stamping import UTCStamper, UTCTimeManager
from qc_flags import QCManager, QualityLevel
from reconstruction_utils import DataReconstructor
from session_logger import SessionLogger
from bounded_adjustments import BoundedAdjustmentController
from mcu_timing import MCUTimingProcessor, MCUTimingManager
from mcu_pll_controller import MCUPLLController
from calibration_storage import CalibrationStorage

logger = logging.getLogger(__name__)

class IntegratedAcquisitionSystem:
    """Integrated acquisition system combining all new components"""
    
    def __init__(self, port: str, baudrate: int = 921600, device_id: str = "XIAO-1234"):
        self.port = port
        self.baudrate = baudrate
        self.device_id = device_id
        
        # Core components
        self.serial_reader = FastSerialReader(port, baudrate)
        self.crc_verifier = CRCVerifier()
        self.binary_parser = BinaryFrameParser()
        self.backpressure_monitor = BackpressureMonitor()
        self.utc_stamper = UTCStamper()
        self.utc_manager = UTCTimeManager()
        self.qc_manager = QCManager()
        self.reconstructor = DataReconstructor()
        self.session_logger = SessionLogger()
        self.adjustment_controller = BoundedAdjustmentController()
        self.mcu_timing_manager = MCUTimingManager()
        self.mcu_pll_controller = MCUPLLController()
        self.calibration_storage = CalibrationStorage()
        
        # State tracking
        self.is_running = False
        self.is_connected = False
        self.current_session = None
        
        # Data buffers
        self.sample_buffer = deque(maxlen=10000)
        self.stat_buffer = deque(maxlen=1000)
        
        # Callbacks
        self.sample_callback: Optional[Callable] = None
        self.status_callback: Optional[Callable] = None
        self.error_callback: Optional[Callable] = None
        
        # Threading
        self.lock = threading.Lock()
        
    def start(self) -> bool:
        """Start the integrated acquisition system"""
        try:
            # Connect serial reader
            if not self.serial_reader.connect():
                return False
                
            # Setup callbacks
            self.serial_reader.sample_callback = self._handle_sample
            self.serial_reader.meta_callback = self._handle_meta_message
            self.serial_reader.error_callback = self._handle_error
            
            # Start serial reader
            self.serial_reader.start()
            
            # Start monitoring thread
            self.is_running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            
            self.is_connected = True
            logger.info("Integrated acquisition system started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start integrated acquisition system: {e}")
            return False
            
    def stop(self):
        """Stop the integrated acquisition system"""
        self.is_running = False
        
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join(timeout=2.0)
            
        self.serial_reader.stop()
        self.serial_reader.disconnect()
        
        self.is_connected = False
        logger.info("Integrated acquisition system stopped")
        
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.is_running:
            try:
                # Process serial queue
                processed = self.serial_reader.process_queue()
                
                # Update MCU status
                self._update_mcu_status()
                
                # Sleep briefly
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(0.1)
                
    def _handle_sample(self, sample_data: Dict[str, Any]):
        """Handle incoming sample data"""
        try:
            # Process with MCU timing
            enhanced_sample = self.mcu_timing_manager.process_sample(sample_data)
            
            # Process with QC
            qc_data = self.qc_manager.process_sample(enhanced_sample)
            
            # Add QC data to sample
            enhanced_sample.update(qc_data)
            
            # Reconstruct missing samples if needed
            reconstructed_samples = self.reconstructor.process_sample(enhanced_sample)
            
            # Log sample to session
            self.session_logger.log_sample(enhanced_sample)
            
            # Add to buffer
            with self.lock:
                self.sample_buffer.append(enhanced_sample)
                
            # Call user callback
            if self.sample_callback:
                self.sample_callback(enhanced_sample)
                
            # Add reconstructed samples
            for recon_sample in reconstructed_samples:
                with self.lock:
                    self.sample_buffer.append(recon_sample)
                    
                if self.sample_callback:
                    self.sample_callback(recon_sample)
                    
        except Exception as e:
            logger.error(f"Error handling sample: {e}")
            
    def _handle_meta_message(self, msg_type: str, data: Dict[str, Any]):
        """Handle meta messages (STAT, SESSION, BOOT, etc.)"""
        try:
            if msg_type == 'STAT':
                self._handle_stat_message(data)
            elif msg_type == 'SESSION':
                self._handle_session_message(data)
            elif msg_type == 'BOOT':
                self._handle_boot_message(data)
            elif msg_type == 'OFLOW':
                self._handle_oflow_message(data)
                
        except Exception as e:
            logger.error(f"Error handling meta message: {e}")
            
    def _handle_stat_message(self, data: Dict[str, Any]):
        """Handle STAT message"""
        # Update backpressure monitor
        self.backpressure_monitor.update_mcu_status(data)
        
        # Update MCU PLL controller
        self.mcu_pll_controller.update_mcu_status(data)
        
        # Update adjustment controller
        self.adjustment_controller.update_mcu_status(data)
        
        # Add to buffer
        with self.lock:
            self.stat_buffer.append(data)
            
        # Call user callback
        if self.status_callback:
            self.status_callback('STAT', data)
            
    def _handle_session_message(self, data: Dict[str, Any]):
        """Handle SESSION message"""
        # Start new session
        self.session_logger.start_session(data)
        
        # Call user callback
        if self.status_callback:
            self.status_callback('SESSION', data)
            
    def _handle_boot_message(self, data: Dict[str, Any]):
        """Handle BOOT message"""
        # Handle boot handshake
        self._handle_boot_handshake(data)
        
        # Call user callback
        if self.status_callback:
            self.status_callback('BOOT', data)
            
    def _handle_oflow_message(self, data: Dict[str, Any]):
        """Handle OFLOW message"""
        # Update backpressure monitor
        self.backpressure_monitor.update_mcu_status(data)
        
        # Call user callback
        if self.status_callback:
            self.status_callback('OFLOW', data)
            
    def _handle_boot_handshake(self, boot_data: Dict[str, Any]):
        """Handle boot handshake"""
        try:
            # Load stored calibration
            stored_cal = self.calibration_storage.load_calibration(self.device_id)
            
            if stored_cal:
                # Send calibration to MCU
                ppm_value = stored_cal['ppm']
                command = f"SET_CAL_PPM:{ppm_value:.2f}"
                self.serial_reader.send_command(command)
                
                logger.info(f"Boot handshake: sent calibration {ppm_value} ppm to MCU")
                
        except Exception as e:
            logger.error(f"Boot handshake failed: {e}")
            
    def _handle_error(self, error: Exception):
        """Handle errors"""
        logger.error(f"Serial reader error: {error}")
        
        if self.error_callback:
            self.error_callback(error)
            
    def _update_mcu_status(self):
        """Update MCU status from latest STAT data"""
        try:
            if self.stat_buffer:
                latest_stat = self.stat_buffer[-1]
                
                # Update all components with latest status
                self.backpressure_monitor.update_mcu_status(latest_stat)
                self.mcu_pll_controller.update_mcu_status(latest_stat)
                self.adjustment_controller.update_mcu_status(latest_stat)
                
        except Exception as e:
            logger.error(f"Error updating MCU status: {e}")
            
    def send_command(self, command: str) -> bool:
        """Send command to MCU"""
        return self.serial_reader.send_command(command)
        
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        with self.lock:
            return {
                'is_running': self.is_running,
                'is_connected': self.is_connected,
                'device_id': self.device_id,
                'port': self.port,
                'baudrate': self.baudrate,
                'sample_buffer_size': len(self.sample_buffer),
                'stat_buffer_size': len(self.stat_buffer),
                'serial_stats': self.serial_reader.get_stats(),
                'backpressure_status': self.backpressure_monitor.get_backpressure_status(),
                'qc_statistics': self.qc_manager.get_quality_statistics(),
                'session_statistics': self.session_logger.get_session_statistics(),
                'mcu_timing_status': self.mcu_timing_manager.get_timing_status(),
                'mcu_pll_status': self.mcu_pll_controller.get_rate_status(),
                'adjustment_status': self.adjustment_controller.get_adjustment_statistics(),
                'utc_status': self.utc_stamper.get_calibration_status()
            }
            
    def get_recent_samples(self, count: int = 100) -> List[Dict[str, Any]]:
        """Get recent samples"""
        with self.lock:
            return list(self.sample_buffer)[-count:]
            
    def get_recent_stats(self, count: int = 50) -> List[Dict[str, Any]]:
        """Get recent status messages"""
        with self.lock:
            return list(self.stat_buffer)[-count:]
            
    def set_calibration(self, ppm_value: float, source: str = "manual", notes: str = "") -> bool:
        """Set calibration"""
        try:
            # Save to storage
            success = self.calibration_storage.save_calibration(
                self.device_id, ppm_value, source, notes=notes
            )
            
            if success:
                # Send to MCU
                command = f"SET_CAL_PPM:{ppm_value:.2f}"
                return self.serial_reader.send_command(command)
                
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
                # Send to MCU
                return self.serial_reader.send_command("CLEAR_CAL")
                
            return False
            
        except Exception as e:
            logger.error(f"Failed to clear calibration: {e}")
            return False

# Compatibility wrapper for existing web server
class HostTimingSeismicAcquisition:
    """Compatibility wrapper for existing web server"""
    
    def __init__(self, port=None, baudrate=921600):
        self.integrated_system = IntegratedAcquisitionSystem(port or "/dev/ttyUSB0", baudrate)
        
        # Compatibility attributes
        self.port = port
        self.baudrate = baudrate
        self.is_running = False
        self.is_connected = False
        
    def start(self):
        """Start acquisition"""
        success = self.integrated_system.start()
        self.is_running = success
        self.is_connected = success
        return success
        
    def stop(self):
        """Stop acquisition"""
        self.integrated_system.stop()
        self.is_running = False
        self.is_connected = False
        
    def get_status(self):
        """Get status"""
        return self.integrated_system.get_status()
        
    def get_recent_samples(self, count=100):
        """Get recent samples"""
        return self.integrated_system.get_recent_samples(count)
        
    def get_recent_stats(self, count=50):
        """Get recent status messages"""
        return self.integrated_system.get_recent_stats(count)
        
    def send_command(self, command):
        """Send command"""
        return self.integrated_system.send_command(command)
        
    def set_calibration(self, ppm_value, source="manual", notes=""):
        """Set calibration"""
        return self.integrated_system.set_calibration(ppm_value, source, notes)
        
    def clear_calibration(self):
        """Clear calibration"""
        return self.integrated_system.clear_calibration()

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create integrated system
    system = IntegratedAcquisitionSystem("/dev/ttyUSB0", 921600, "XIAO-1234")
    
    # Setup callbacks
    def sample_callback(sample):
        print(f"Sample: {sample['timestamp_us']}, channels: {sample['channels']}")
        
    def status_callback(msg_type, data):
        print(f"{msg_type}: {data}")
        
    system.sample_callback = sample_callback
    system.status_callback = status_callback
    
    try:
        # Start system
        if system.start():
            print("Integrated system started")
            
            # Run for a while
            time.sleep(10)
            
            # Check status
            status = system.get_status()
            print(f"Status: {json.dumps(status, indent=2)}")
            
        else:
            print("Failed to start integrated system")
            
    except KeyboardInterrupt:
        print("\nShutting down...")
        system.stop()
