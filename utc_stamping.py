#!/usr/bin/env python3
"""
UTC Stamping Policy with MCU Timestamp as Primary Time Axis
Implements precise UTC conversion for seismic data
"""

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import threading
from collections import deque

logger = logging.getLogger(__name__)

class UTCStamper:
    """UTC stamping with MCU timestamp as primary time axis"""
    
    def __init__(self, 
                 utc_offset_hours: float = 0.0,
                 max_calibration_age: float = 300.0,  # 5 minutes
                 max_drift_threshold: float = 1.0):    # 1 second
        self.utc_offset_hours = utc_offset_hours
        self.max_calibration_age = max_calibration_age
        self.max_drift_threshold = max_drift_threshold
        
        # Calibration state
        self.mcu_to_utc_offset = 0.0  # Microseconds
        self.calibration_time = 0.0   # Unix timestamp when calibrated
        self.calibration_valid = False
        
        # Drift tracking
        self.drift_history = deque(maxlen=100)
        self.last_drift_check = 0.0
        
        # Threading
        self.lock = threading.Lock()
        
    def calibrate_from_pps(self, mcu_timestamp_us: int, pps_time: datetime) -> bool:
        """Calibrate MCU timestamp to UTC using PPS signal
        
        Args:
            mcu_timestamp_us: MCU timestamp in microseconds
            pps_time: PPS time in UTC
            
        Returns:
            True if calibration successful
        """
        with self.lock:
            try:
                # Convert PPS time to Unix timestamp
                pps_unix = pps_time.timestamp()
                
                # Calculate offset: MCU_timestamp + offset = UTC_timestamp
                mcu_timestamp_s = mcu_timestamp_us / 1_000_000.0
                self.mcu_to_utc_offset = pps_unix - mcu_timestamp_s
                
                self.calibration_time = time.time()
                self.calibration_valid = True
                
                logger.info(f"UTC calibration from PPS: offset={self.mcu_to_utc_offset:.6f}s")
                return True
                
            except Exception as e:
                logger.error(f"Failed to calibrate from PPS: {e}")
                return False
                
    def calibrate_from_system_time(self, mcu_timestamp_us: int, system_time: datetime) -> bool:
        """Calibrate MCU timestamp to UTC using system time
        
        Args:
            mcu_timestamp_us: MCU timestamp in microseconds
            system_time: System time in UTC
            
        Returns:
            True if calibration successful
        """
        with self.lock:
            try:
                # Convert system time to Unix timestamp
                system_unix = system_time.timestamp()
                
                # Calculate offset
                mcu_timestamp_s = mcu_timestamp_us / 1_000_000.0
                self.mcu_to_utc_offset = system_unix - mcu_timestamp_s
                
                self.calibration_time = time.time()
                self.calibration_valid = True
                
                logger.info(f"UTC calibration from system time: offset={self.mcu_to_utc_offset:.6f}s")
                return True
                
            except Exception as e:
                logger.error(f"Failed to calibrate from system time: {e}")
                return False
                
    def stamp_sample(self, mcu_timestamp_us: int, arrival_time: Optional[float] = None) -> Dict[str, Any]:
        """Convert MCU timestamp to UTC timestamp
        
        Args:
            mcu_timestamp_us: MCU timestamp in microseconds
            arrival_time: Optional arrival time for drift calculation
            
        Returns:
            Dictionary with UTC timestamp and metadata
        """
        with self.lock:
            if not self.calibration_valid:
                return self._stamp_without_calibration(mcu_timestamp_us, arrival_time)
                
            # Check calibration age
            current_time = time.time()
            calibration_age = current_time - self.calibration_time
            
            if calibration_age > self.max_calibration_age:
                logger.warning(f"Calibration too old: {calibration_age:.1f}s > {self.max_calibration_age}s")
                return self._stamp_without_calibration(mcu_timestamp_us, arrival_time)
                
            # Convert MCU timestamp to UTC
            mcu_timestamp_s = mcu_timestamp_us / 1_000_000.0
            utc_timestamp_s = mcu_timestamp_s + self.mcu_to_utc_offset
            
            # Create UTC datetime
            utc_datetime = datetime.fromtimestamp(utc_timestamp_s, tz=timezone.utc)
            
            # Calculate drift if arrival time provided
            drift_us = 0.0
            if arrival_time is not None:
                expected_arrival = utc_timestamp_s
                actual_arrival = arrival_time
                drift_us = (actual_arrival - expected_arrival) * 1_000_000
                
                # Track drift history
                self.drift_history.append({
                    'timestamp': current_time,
                    'drift_us': drift_us,
                    'mcu_timestamp_us': mcu_timestamp_us
                })
                
            return {
                'utc_timestamp': utc_datetime,
                'utc_timestamp_s': utc_timestamp_s,
                'utc_timestamp_us': int(utc_timestamp_s * 1_000_000),
                'mcu_timestamp_us': mcu_timestamp_us,
                'calibration_valid': True,
                'calibration_age_s': calibration_age,
                'drift_us': drift_us,
                'time_source': 'MCU_CALIBRATED'
            }
            
    def _stamp_without_calibration(self, mcu_timestamp_us: int, arrival_time: Optional[float] = None) -> Dict[str, Any]:
        """Stamp sample without calibration (fallback)"""
        current_time = time.time()
        
        # Use arrival time as fallback
        if arrival_time is not None:
            utc_datetime = datetime.fromtimestamp(arrival_time, tz=timezone.utc)
            utc_timestamp_s = arrival_time
        else:
            utc_datetime = datetime.fromtimestamp(current_time, tz=timezone.utc)
            utc_timestamp_s = current_time
            
        return {
            'utc_timestamp': utc_datetime,
            'utc_timestamp_s': utc_timestamp_s,
            'utc_timestamp_us': int(utc_timestamp_s * 1_000_000),
            'mcu_timestamp_us': mcu_timestamp_us,
            'calibration_valid': False,
            'calibration_age_s': float('inf'),
            'drift_us': 0.0,
            'time_source': 'ARRIVAL_TIME_FALLBACK'
        }
        
    def get_drift_statistics(self) -> Dict[str, Any]:
        """Get drift statistics"""
        with self.lock:
            if not self.drift_history:
                return {
                    'drift_count': 0,
                    'avg_drift_us': 0.0,
                    'max_drift_us': 0.0,
                    'min_drift_us': 0.0,
                    'drift_std_us': 0.0
                }
                
            drifts = [entry['drift_us'] for entry in self.drift_history]
            
            return {
                'drift_count': len(drifts),
                'avg_drift_us': sum(drifts) / len(drifts),
                'max_drift_us': max(drifts),
                'min_drift_us': min(drifts),
                'drift_std_us': self._calculate_std(drifts),
                'recent_drifts': drifts[-10:] if len(drifts) >= 10 else drifts
            }
            
    def _calculate_std(self, values: list) -> float:
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0.0
            
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
        
    def check_drift_threshold(self) -> bool:
        """Check if drift exceeds threshold"""
        with self.lock:
            if not self.drift_history:
                return False
                
            recent_drifts = [entry['drift_us'] for entry in self.drift_history 
                           if time.time() - entry['timestamp'] < 60]  # Last 60 seconds
            
            if not recent_drifts:
                return False
                
            max_drift = max(abs(drift) for drift in recent_drifts)
            return max_drift > (self.max_drift_threshold * 1_000_000)  # Convert to microseconds
            
    def get_calibration_status(self) -> Dict[str, Any]:
        """Get calibration status"""
        with self.lock:
            current_time = time.time()
            calibration_age = current_time - self.calibration_time if self.calibration_valid else float('inf')
            
            return {
                'calibration_valid': self.calibration_valid,
                'calibration_age_s': calibration_age,
                'mcu_to_utc_offset_s': self.mcu_to_utc_offset,
                'max_calibration_age_s': self.max_calibration_age,
                'drift_threshold_us': self.max_drift_threshold * 1_000_000,
                'drift_exceeds_threshold': self.check_drift_threshold()
            }
            
    def reset_calibration(self):
        """Reset calibration"""
        with self.lock:
            self.calibration_valid = False
            self.mcu_to_utc_offset = 0.0
            self.calibration_time = 0.0
            self.drift_history.clear()
            logger.info("UTC calibration reset")

class UTCTimeManager:
    """Manager for UTC time operations"""
    
    def __init__(self):
        self.stamper = UTCStamper()
        self.pps_enabled = False
        self.system_time_sync_enabled = True
        
    def enable_pps_sync(self, pps_gpio_pin: int = 18):
        """Enable PPS synchronization"""
        # This would interface with PPS GPIO
        self.pps_enabled = True
        logger.info(f"PPS synchronization enabled on GPIO {pps_gpio_pin}")
        
    def disable_pps_sync(self):
        """Disable PPS synchronization"""
        self.pps_enabled = False
        logger.info("PPS synchronization disabled")
        
    def sync_with_system_time(self):
        """Sync with system time"""
        if not self.system_time_sync_enabled:
            return False
            
        try:
            # Get current system time
            system_time = datetime.now(timezone.utc)
            
            # Use current time as MCU timestamp (approximation)
            mcu_timestamp_us = int(time.time() * 1_000_000)
            
            return self.stamper.calibrate_from_system_time(mcu_timestamp_us, system_time)
            
        except Exception as e:
            logger.error(f"Failed to sync with system time: {e}")
            return False
            
    def process_pps_signal(self, mcu_timestamp_us: int):
        """Process PPS signal for calibration"""
        if not self.pps_enabled:
            return False
            
        try:
            # Get current UTC time (should be aligned with PPS)
            pps_time = datetime.now(timezone.utc)
            
            return self.stamper.calibrate_from_pps(mcu_timestamp_us, pps_time)
            
        except Exception as e:
            logger.error(f"Failed to process PPS signal: {e}")
            return False

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create UTC stamper
    stamper = UTCStamper()
    
    # Simulate calibration
    print("Simulating UTC calibration...")
    
    # Calibrate with PPS
    mcu_timestamp = int(time.time() * 1_000_000)
    pps_time = datetime.now(timezone.utc)
    
    success = stamper.calibrate_from_pps(mcu_timestamp, pps_time)
    print(f"PPS calibration success: {success}")
    
    # Stamp some samples
    print("\nStamping samples...")
    
    for i in range(5):
        sample_timestamp = mcu_timestamp + (i * 10000)  # 10ms intervals
        arrival_time = time.time() + (i * 0.01)
        
        result = stamper.stamp_sample(sample_timestamp, arrival_time)
        print(f"Sample {i}: {result['utc_timestamp']} (drift: {result['drift_us']:.1f}μs)")
        
    # Check status
    status = stamper.get_calibration_status()
    print(f"\nCalibration status: {json.dumps(status, indent=2)}")
    
    # Check drift statistics
    drift_stats = stamper.get_drift_statistics()
    print(f"Drift statistics: {json.dumps(drift_stats, indent=2)}")
    
    print("UTC stamping test completed!")
