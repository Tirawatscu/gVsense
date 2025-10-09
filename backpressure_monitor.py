#!/usr/bin/env python3
"""
Backpressure Monitor for gVsense
Monitors MCU buffer overflows and implements backpressure awareness
"""

import time
import logging
from typing import Dict, Any, Optional, Callable
from collections import deque
import threading

logger = logging.getLogger(__name__)

class BackpressureMonitor:
    """Monitor MCU buffer overflows and implement backpressure awareness"""
    
    def __init__(self, 
                 overflow_threshold: int = 5,  # Alert after 5 overflows
                 recovery_threshold: int = 30,  # Recovery after 30 seconds without overflow
                 max_history: int = 1000):
        self.overflow_threshold = overflow_threshold
        self.recovery_threshold = recovery_threshold
        self.max_history = max_history
        
        # State tracking
        self.mcu_buffer_overflows = 0
        self.mcu_samples_skipped = 0
        self.mcu_pps_valid = False
        self.mcu_timing_source = "UNKNOWN"
        self.mcu_boot_id = 0
        self.mcu_stream_id = 0
        
        # Backpressure state
        self.backpressure_active = False
        self.backpressure_start_time = None
        self.last_overflow_time = None
        self.last_recovery_time = None
        
        # History tracking
        self.overflow_history = deque(maxlen=max_history)
        self.sample_rate_history = deque(maxlen=100)  # Last 100 samples
        
        # Callbacks
        self.backpressure_callback: Optional[Callable] = None
        self.recovery_callback: Optional[Callable] = None
        self.overflow_callback: Optional[Callable] = None
        
        # Threading
        self.lock = threading.Lock()
        
    def update_mcu_status(self, stat_data: Dict[str, Any]):
        """Update MCU status from STAT line"""
        with self.lock:
            # Extract MCU status
            self.mcu_buffer_overflows = stat_data.get('buffer_overflows', 0)
            self.mcu_samples_skipped = stat_data.get('samples_skipped_due_to_overflow', 0)
            self.mcu_pps_valid = stat_data.get('pps_valid', False)
            self.mcu_timing_source = stat_data.get('timing_source', 'UNKNOWN')
            self.mcu_boot_id = stat_data.get('boot_id', 0)
            self.mcu_stream_id = stat_data.get('stream_id', 0)
            
            # Check for new overflows
            if self.mcu_buffer_overflows > 0:
                self._handle_overflow()
                
            # Check for recovery
            self._check_recovery()
            
    def _handle_overflow(self):
        """Handle buffer overflow detection"""
        current_time = time.time()
        
        # Record overflow event
        overflow_event = {
            'timestamp': current_time,
            'buffer_overflows': self.mcu_buffer_overflows,
            'samples_skipped': self.mcu_samples_skipped,
            'timing_source': self.mcu_timing_source,
            'pps_valid': self.mcu_pps_valid
        }
        
        self.overflow_history.append(overflow_event)
        self.last_overflow_time = current_time
        
        # Check if backpressure should be activated
        if not self.backpressure_active:
            # Count recent overflows
            recent_overflows = sum(1 for event in self.overflow_history 
                                 if current_time - event['timestamp'] < 60)  # Last 60 seconds
            
            if recent_overflows >= self.overflow_threshold:
                self._activate_backpressure()
                
        # Call overflow callback
        if self.overflow_callback:
            self.overflow_callback(overflow_event)
            
    def _activate_backpressure(self):
        """Activate backpressure mode"""
        self.backpressure_active = True
        self.backpressure_start_time = time.time()
        
        logger.warning(f"Backpressure activated: {self.mcu_buffer_overflows} overflows, "
                      f"{self.mcu_samples_skipped} samples skipped")
        
        if self.backpressure_callback:
            self.backpressure_callback({
                'active': True,
                'start_time': self.backpressure_start_time,
                'buffer_overflows': self.mcu_buffer_overflows,
                'samples_skipped': self.mcu_samples_skipped,
                'timing_source': self.mcu_timing_source
            })
            
    def _check_recovery(self):
        """Check for recovery from backpressure"""
        if not self.backpressure_active:
            return
            
        current_time = time.time()
        
        # Check if we've had no overflows for recovery threshold
        if self.last_overflow_time and (current_time - self.last_overflow_time) > self.recovery_threshold:
            self._deactivate_backpressure()
            
    def _deactivate_backpressure(self):
        """Deactivate backpressure mode"""
        self.backpressure_active = False
        self.last_recovery_time = time.time()
        
        duration = self.last_recovery_time - self.backpressure_start_time if self.backpressure_start_time else 0
        
        logger.info(f"Backpressure deactivated after {duration:.1f} seconds")
        
        if self.recovery_callback:
            self.recovery_callback({
                'active': False,
                'duration': duration,
                'recovery_time': self.last_recovery_time,
                'buffer_overflows': self.mcu_buffer_overflows,
                'samples_skipped': self.mcu_samples_skipped
            })
            
    def update_sample_rate(self, samples_per_second: float):
        """Update sample rate for monitoring"""
        with self.lock:
            self.sample_rate_history.append({
                'timestamp': time.time(),
                'rate': samples_per_second
            })
            
    def get_backpressure_status(self) -> Dict[str, Any]:
        """Get current backpressure status"""
        with self.lock:
            current_time = time.time()
            
            # Calculate recent overflow rate
            recent_overflows = sum(1 for event in self.overflow_history 
                                 if current_time - event['timestamp'] < 60)
            
            # Calculate average sample rate
            if self.sample_rate_history:
                recent_rates = [entry['rate'] for entry in self.sample_rate_history 
                               if current_time - entry['timestamp'] < 10]
                avg_sample_rate = sum(recent_rates) / len(recent_rates) if recent_rates else 0
            else:
                avg_sample_rate = 0
                
            return {
                'backpressure_active': self.backpressure_active,
                'backpressure_start_time': self.backpressure_start_time,
                'last_overflow_time': self.last_overflow_time,
                'last_recovery_time': self.last_recovery_time,
                'mcu_buffer_overflows': self.mcu_buffer_overflows,
                'mcu_samples_skipped': self.mcu_samples_skipped,
                'mcu_timing_source': self.mcu_timing_source,
                'mcu_pps_valid': self.mcu_pps_valid,
                'recent_overflows': recent_overflows,
                'avg_sample_rate': avg_sample_rate,
                'overflow_history_count': len(self.overflow_history)
            }
            
    def get_overflow_statistics(self) -> Dict[str, Any]:
        """Get overflow statistics"""
        with self.lock:
            if not self.overflow_history:
                return {
                    'total_overflows': 0,
                    'overflow_rate_per_minute': 0,
                    'avg_samples_skipped_per_overflow': 0,
                    'timing_source_distribution': {},
                    'pps_valid_during_overflows': 0
                }
                
            current_time = time.time()
            
            # Calculate statistics
            total_overflows = len(self.overflow_history)
            time_span = current_time - self.overflow_history[0]['timestamp'] if self.overflow_history else 1
            overflow_rate_per_minute = (total_overflows / time_span) * 60
            
            # Calculate average samples skipped per overflow
            total_samples_skipped = sum(event['samples_skipped'] for event in self.overflow_history)
            avg_samples_skipped_per_overflow = total_samples_skipped / total_overflows if total_overflows > 0 else 0
            
            # Timing source distribution
            timing_sources = {}
            for event in self.overflow_history:
                source = event['timing_source']
                timing_sources[source] = timing_sources.get(source, 0) + 1
                
            # PPS valid during overflows
            pps_valid_count = sum(1 for event in self.overflow_history if event['pps_valid'])
            
            return {
                'total_overflows': total_overflows,
                'overflow_rate_per_minute': overflow_rate_per_minute,
                'avg_samples_skipped_per_overflow': avg_samples_skipped_per_overflow,
                'timing_source_distribution': timing_sources,
                'pps_valid_during_overflows': pps_valid_count,
                'time_span_seconds': time_span
            }
            
    def reset_statistics(self):
        """Reset overflow statistics"""
        with self.lock:
            self.overflow_history.clear()
            self.sample_rate_history.clear()
            self.mcu_buffer_overflows = 0
            self.mcu_samples_skipped = 0
            self.backpressure_active = False
            self.backpressure_start_time = None
            self.last_overflow_time = None
            self.last_recovery_time = None
            
    def should_throttle(self) -> bool:
        """Determine if data processing should be throttled"""
        with self.lock:
            if not self.backpressure_active:
                return False
                
            # Throttle if backpressure is active and we're in a critical state
            return (self.mcu_timing_source == "PPS_ACTIVE" and 
                    self.mcu_samples_skipped > 100)
                    
    def get_throttle_factor(self) -> float:
        """Get throttle factor (0.0 = no throttling, 1.0 = full throttling)"""
        with self.lock:
            if not self.backpressure_active:
                return 0.0
                
            # Calculate throttle factor based on overflow severity
            if self.mcu_samples_skipped > 1000:
                return 0.8  # Heavy throttling
            elif self.mcu_samples_skipped > 100:
                return 0.5  # Moderate throttling
            else:
                return 0.2  # Light throttling

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create monitor
    monitor = BackpressureMonitor()
    
    # Setup callbacks
    def on_backpressure(data):
        print(f"Backpressure activated: {json.dumps(data, indent=2)}")
        
    def on_recovery(data):
        print(f"Backpressure recovered: {json.dumps(data, indent=2)}")
        
    def on_overflow(data):
        print(f"Overflow detected: {json.dumps(data, indent=2)}")
        
    monitor.backpressure_callback = on_backpressure
    monitor.recovery_callback = on_recovery
    monitor.overflow_callback = on_overflow
    
    # Simulate MCU status updates
    print("Simulating MCU status updates...")
    
    # Normal operation
    monitor.update_mcu_status({
        'buffer_overflows': 0,
        'samples_skipped_due_to_overflow': 0,
        'pps_valid': True,
        'timing_source': 'PPS_ACTIVE',
        'boot_id': 123,
        'stream_id': 456
    })
    
    # Simulate overflows
    for i in range(10):
        monitor.update_mcu_status({
            'buffer_overflows': i + 1,
            'samples_skipped_due_to_overflow': i * 10,
            'pps_valid': True,
            'timing_source': 'PPS_ACTIVE',
            'boot_id': 123,
            'stream_id': 456
        })
        time.sleep(0.1)
        
    # Check status
    status = monitor.get_backpressure_status()
    print(f"Backpressure status: {json.dumps(status, indent=2)}")
    
    # Check statistics
    stats = monitor.get_overflow_statistics()
    print(f"Overflow statistics: {json.dumps(stats, indent=2)}")
    
    print("Backpressure monitoring test completed!")
