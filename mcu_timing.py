#!/usr/bin/env python3
"""
MCU Timing: Compute timing from MCU timestamps, not host arrival time
Implements MCU-centric timing for seismic data
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
import threading

logger = logging.getLogger(__name__)

class MCUTimingProcessor:
    """Process timing using MCU timestamps as primary time axis"""
    
    def __init__(self, 
                 expected_sample_rate: float = 100.0,
                 max_timing_offset_us: float = 1000.0,
                 timing_history_size: int = 1000):
        self.expected_sample_rate = expected_sample_rate
        self.expected_interval_us = int(1_000_000 / expected_sample_rate)
        self.max_timing_offset_us = max_timing_offset_us
        self.timing_history_size = timing_history_size
        
        # Timing state
        self.last_mcu_timestamp_us = 0
        self.last_host_arrival_time = 0.0
        self.timing_offset_us = 0.0
        self.timing_offset_valid = False
        
        # Timing history
        self.timing_history = deque(maxlen=timing_history_size)
        self.arrival_jitter_us = deque(maxlen=100)
        
        # Statistics
        self.total_samples = 0
        self.timing_errors = 0
        self.max_timing_error_us = 0.0
        
        # Threading
        self.lock = threading.Lock()
        
    def process_sample(self, sample_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process sample timing using MCU timestamp
        
        Args:
            sample_data: Sample data with MCU timestamp and arrival time
            
        Returns:
            Enhanced sample data with timing information
        """
        with self.lock:
            mcu_timestamp_us = sample_data.get('timestamp_us', 0)
            arrival_time = sample_data.get('arrival_time', time.time())
            
            # Initialize timing data
            timing_data = {
                'mcu_timestamp_us': mcu_timestamp_us,
                'host_arrival_time': arrival_time,
                'timing_offset_us': 0.0,
                'timing_offset_valid': False,
                'arrival_jitter_us': 0.0,
                'timing_error_us': 0.0,
                'time_source': 'MCU_TIMESTAMP'
            }
            
            # Calculate timing offset
            if self.last_mcu_timestamp_us > 0:
                # Calculate expected arrival time based on MCU timestamp
                mcu_time_diff_us = mcu_timestamp_us - self.last_mcu_timestamp_us
                expected_arrival_time = self.last_host_arrival_time + (mcu_time_diff_us / 1_000_000.0)
                
                # Calculate timing offset
                actual_arrival_time = arrival_time
                timing_offset_us = (actual_arrival_time - expected_arrival_time) * 1_000_000
                
                # Validate timing offset
                if abs(timing_offset_us) <= self.max_timing_offset_us:
                    self.timing_offset_us = timing_offset_us
                    self.timing_offset_valid = True
                    timing_data['timing_offset_us'] = timing_offset_us
                    timing_data['timing_offset_valid'] = True
                    
                    # Calculate arrival jitter
                    if len(self.arrival_jitter_us) > 0:
                        avg_jitter = sum(self.arrival_jitter_us) / len(self.arrival_jitter_us)
                        timing_data['arrival_jitter_us'] = abs(timing_offset_us - avg_jitter)
                        
                    self.arrival_jitter_us.append(timing_offset_us)
                    
                else:
                    # Timing offset too large, mark as invalid
                    self.timing_offset_valid = False
                    timing_data['timing_error_us'] = abs(timing_offset_us)
                    self.timing_errors += 1
                    self.max_timing_error_us = max(self.max_timing_error_us, abs(timing_offset_us))
                    
                    logger.warning(f"Large timing offset: {timing_offset_us:.1f}μs > {self.max_timing_offset_us}μs")
                    
            # Update state
            self.last_mcu_timestamp_us = mcu_timestamp_us
            self.last_host_arrival_time = arrival_time
            self.total_samples += 1
            
            # Record timing history
            self.timing_history.append({
                'timestamp': arrival_time,
                'mcu_timestamp_us': mcu_timestamp_us,
                'timing_offset_us': timing_data['timing_offset_us'],
                'timing_offset_valid': timing_data['timing_offset_valid'],
                'arrival_jitter_us': timing_data['arrival_jitter_us']
            })
            
            # Add timing data to sample
            enhanced_sample = sample_data.copy()
            enhanced_sample.update(timing_data)
            
            return enhanced_sample
            
    def get_timing_statistics(self) -> Dict[str, Any]:
        """Get timing statistics"""
        with self.lock:
            if not self.timing_history:
                return {
                    'total_samples': 0,
                    'timing_errors': 0,
                    'max_timing_error_us': 0.0,
                    'avg_timing_offset_us': 0.0,
                    'timing_offset_valid': False
                }
                
            # Calculate statistics
            valid_offsets = [entry['timing_offset_us'] for entry in self.timing_history 
                           if entry['timing_offset_valid']]
            
            if valid_offsets:
                avg_timing_offset = sum(valid_offsets) / len(valid_offsets)
                max_timing_offset = max(abs(offset) for offset in valid_offsets)
                min_timing_offset = min(abs(offset) for offset in valid_offsets)
            else:
                avg_timing_offset = 0.0
                max_timing_offset = 0.0
                min_timing_offset = 0.0
                
            # Calculate arrival jitter
            if self.arrival_jitter_us:
                avg_jitter = sum(self.arrival_jitter_us) / len(self.arrival_jitter_us)
                max_jitter = max(self.arrival_jitter_us)
                min_jitter = min(self.arrival_jitter_us)
            else:
                avg_jitter = 0.0
                max_jitter = 0.0
                min_jitter = 0.0
                
            return {
                'total_samples': self.total_samples,
                'timing_errors': self.timing_errors,
                'max_timing_error_us': self.max_timing_error_us,
                'avg_timing_offset_us': avg_timing_offset,
                'max_timing_offset_us': max_timing_offset,
                'min_timing_offset_us': min_timing_offset,
                'timing_offset_valid': self.timing_offset_valid,
                'avg_arrival_jitter_us': avg_jitter,
                'max_arrival_jitter_us': max_jitter,
                'min_arrival_jitter_us': min_jitter,
                'timing_history_count': len(self.timing_history)
            }
            
    def get_timing_quality(self) -> str:
        """Get timing quality assessment"""
        with self.lock:
            if not self.timing_history:
                return "unknown"
                
            # Get recent timing data
            recent_entries = list(self.timing_history)[-100:]  # Last 100 samples
            valid_entries = [entry for entry in recent_entries if entry['timing_offset_valid']]
            
            if not valid_entries:
                return "poor"
                
            # Calculate quality metrics
            avg_offset = sum(entry['timing_offset_us'] for entry in valid_entries) / len(valid_entries)
            max_offset = max(abs(entry['timing_offset_us']) for entry in valid_entries)
            error_rate = (len(recent_entries) - len(valid_entries)) / len(recent_entries)
            
            # Determine quality level
            if error_rate > 0.1:  # >10% errors
                return "poor"
            elif max_offset > 100.0:  # >100μs offset
                return "fair"
            elif max_offset > 50.0:  # >50μs offset
                return "good"
            else:
                return "excellent"
                
    def reset_statistics(self):
        """Reset timing statistics"""
        with self.lock:
            self.last_mcu_timestamp_us = 0
            self.last_host_arrival_time = 0.0
            self.timing_offset_us = 0.0
            self.timing_offset_valid = False
            self.timing_history.clear()
            self.arrival_jitter_us.clear()
            self.total_samples = 0
            self.timing_errors = 0
            self.max_timing_error_us = 0.0

class MCUTimingManager:
    """High-level MCU timing manager"""
    
    def __init__(self, expected_sample_rate: float = 100.0):
        self.expected_sample_rate = expected_sample_rate
        self.timing_processor = MCUTimingProcessor(expected_sample_rate)
        
        # Timing calibration
        self.timing_calibration_valid = False
        self.timing_calibration_offset_us = 0.0
        
    def process_sample(self, sample_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process sample with MCU timing"""
        return self.timing_processor.process_sample(sample_data)
        
    def calibrate_timing(self, reference_samples: List[Dict[str, Any]]) -> bool:
        """Calibrate timing using reference samples
        
        Args:
            reference_samples: List of reference samples with known timing
            
        Returns:
            True if calibration successful
        """
        try:
            if len(reference_samples) < 2:
                return False
                
            # Calculate timing offset from reference samples
            offsets = []
            for i in range(1, len(reference_samples)):
                sample1 = reference_samples[i-1]
                sample2 = reference_samples[i]
                
                mcu_time_diff_us = sample2['timestamp_us'] - sample1['timestamp_us']
                expected_arrival_time = sample1['arrival_time'] + (mcu_time_diff_us / 1_000_000.0)
                actual_arrival_time = sample2['arrival_time']
                
                offset_us = (actual_arrival_time - expected_arrival_time) * 1_000_000
                offsets.append(offset_us)
                
            # Calculate average offset
            if offsets:
                self.timing_calibration_offset_us = sum(offsets) / len(offsets)
                self.timing_calibration_valid = True
                
                logger.info(f"Timing calibrated: offset = {self.timing_calibration_offset_us:.1f}μs")
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Timing calibration failed: {e}")
            return False
            
    def get_timing_status(self) -> Dict[str, Any]:
        """Get timing status"""
        stats = self.timing_processor.get_timing_statistics()
        quality = self.timing_processor.get_timing_quality()
        
        return {
            **stats,
            'timing_quality': quality,
            'timing_calibration_valid': self.timing_calibration_valid,
            'timing_calibration_offset_us': self.timing_calibration_offset_us,
            'expected_sample_rate': self.expected_sample_rate,
            'expected_interval_us': self.timing_processor.expected_interval_us
        }

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create MCU timing manager
    timing_manager = MCUTimingManager(expected_sample_rate=100.0)
    
    # Simulate sample processing
    print("Simulating MCU timing processing...")
    
    base_timestamp = int(time.time() * 1_000_000)
    base_time = time.time()
    
    # Process samples
    for i in range(100):
        sample_data = {
            'timestamp_us': base_timestamp + (i * 10000),  # 10ms intervals
            'channels': [i * 100, i * 200],
            'sequence': i,
            'arrival_time': base_time + (i * 0.01) + (i % 10) * 0.001  # Add some jitter
        }
        
        enhanced_sample = timing_manager.process_sample(sample_data)
        
        if i % 20 == 0:  # Print every 20th sample
            print(f"Sample {i}: offset={enhanced_sample['timing_offset_us']:.1f}μs, "
                  f"jitter={enhanced_sample['arrival_jitter_us']:.1f}μs")
                  
    # Check timing status
    status = timing_manager.get_timing_status()
    print(f"\nTiming status: {json.dumps(status, indent=2)}")
    
    # Test calibration
    print("\nTesting timing calibration...")
    reference_samples = []
    for i in range(10):
        sample_data = {
            'timestamp_us': base_timestamp + (i * 10000),
            'arrival_time': base_time + (i * 0.01)
        }
        reference_samples.append(sample_data)
        
    success = timing_manager.calibrate_timing(reference_samples)
    print(f"Calibration success: {success}")
    
    # Check final status
    final_status = timing_manager.get_timing_status()
    print(f"Final status: {json.dumps(final_status, indent=2)}")
    
    print("MCU timing test completed!")
