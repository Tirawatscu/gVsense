#!/usr/bin/env python3
"""
QC Flags: Gap Detection, Quality Mapping, Overflow Tracking
Quality control system for seismic data
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
from enum import Enum
import threading

logger = logging.getLogger(__name__)

class QualityLevel(Enum):
    """Quality levels for seismic data"""
    EXCELLENT = "excellent"      # PPS locked, no issues
    GOOD = "good"               # Minor issues, acceptable
    FAIR = "fair"               # Some issues, degraded
    POOR = "poor"               # Significant issues
    UNACCEPTABLE = "unacceptable"  # Critical issues

class QCFlag(Enum):
    """Quality control flags"""
    GAP_DETECTED = "gap_detected"
    OVERFLOW_DETECTED = "overflow_detected"
    TIMING_DRIFT = "timing_drift"
    PPS_LOST = "pps_lost"
    CALIBRATION_INVALID = "calibration_invalid"
    BUFFER_OVERFLOW = "buffer_overflow"
    CRC_ERROR = "crc_error"
    SEQUENCE_ERROR = "sequence_error"
    TEMPERATURE_DRIFT = "temperature_drift"
    SAMPLE_RATE_ERROR = "sample_rate_error"

class QCManager:
    """Quality control manager for seismic data"""
    
    def __init__(self, 
                 expected_sample_rate: float = 100.0,
                 gap_threshold_ms: float = 50.0,
                 drift_threshold_us: float = 1000.0,
                 max_gap_history: int = 1000):
        self.expected_sample_rate = expected_sample_rate
        self.gap_threshold_ms = gap_threshold_ms
        self.drift_threshold_us = drift_threshold_us
        self.max_gap_history = max_gap_history
        
        # State tracking
        self.last_timestamp_us = 0
        self.last_sequence = 0
        self.last_arrival_time = 0.0
        self.sample_count = 0
        self.gap_count = 0
        self.overflow_count = 0
        
        # Quality tracking
        self.current_quality = QualityLevel.EXCELLENT
        self.active_flags = set()
        self.quality_history = deque(maxlen=1000)
        
        # Gap detection
        self.gap_history = deque(maxlen=max_gap_history)
        self.expected_interval_us = int(1_000_000 / expected_sample_rate)
        
        # Threading
        self.lock = threading.Lock()
        
    def process_sample(self, sample_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process sample and generate QC flags
        
        Args:
            sample_data: Sample data with timestamp, sequence, etc.
            
        Returns:
            QC data with flags and quality level
        """
        with self.lock:
            timestamp_us = sample_data.get('timestamp_us', 0)
            sequence = sample_data.get('sequence', 0)
            arrival_time = sample_data.get('arrival_time', time.time())
            
            # Initialize QC data
            qc_data = {
                'timestamp_us': timestamp_us,
                'sequence': sequence,
                'arrival_time': arrival_time,
                'flags': [],
                'quality_level': QualityLevel.EXCELLENT,
                'gap_detected': False,
                'overflow_detected': False,
                'timing_drift_us': 0.0,
                'sample_rate_error': 0.0
            }
            
            # Check for gaps
            if self.last_timestamp_us > 0:
                gap_us = timestamp_us - self.last_timestamp_us
                expected_gap_us = self.expected_interval_us
                gap_error_us = abs(gap_us - expected_gap_us)
                
                if gap_error_us > (self.gap_threshold_ms * 1000):
                    qc_data['gap_detected'] = True
                    qc_data['flags'].append(QCFlag.GAP_DETECTED)
                    
                    # Record gap
                    self.gap_history.append({
                        'timestamp': arrival_time,
                        'gap_us': gap_us,
                        'expected_gap_us': expected_gap_us,
                        'gap_error_us': gap_error_us
                    })
                    
                    self.gap_count += 1
                    
            # Check sequence
            if self.last_sequence > 0:
                expected_sequence = (self.last_sequence + 1) % 65536
                if sequence != expected_sequence:
                    qc_data['flags'].append(QCFlag.SEQUENCE_ERROR)
                    
            # Check timing drift
            if self.last_arrival_time > 0:
                expected_arrival = self.last_arrival_time + (1.0 / self.expected_sample_rate)
                actual_arrival = arrival_time
                drift_us = (actual_arrival - expected_arrival) * 1_000_000
                
                if abs(drift_us) > self.drift_threshold_us:
                    qc_data['timing_drift_us'] = drift_us
                    qc_data['flags'].append(QCFlag.TIMING_DRIFT)
                    
            # Check sample rate
            if self.last_arrival_time > 0:
                time_diff = arrival_time - self.last_arrival_time
                if time_diff > 0:
                    actual_rate = 1.0 / time_diff
                    rate_error = abs(actual_rate - self.expected_sample_rate)
                    qc_data['sample_rate_error'] = rate_error
                    
                    if rate_error > (self.expected_sample_rate * 0.1):  # 10% error
                        qc_data['flags'].append(QCFlag.SAMPLE_RATE_ERROR)
                        
            # Update state
            self.last_timestamp_us = timestamp_us
            self.last_sequence = sequence
            self.last_arrival_time = arrival_time
            self.sample_count += 1
            
            # Determine quality level
            qc_data['quality_level'] = self._determine_quality_level(qc_data['flags'])
            
            # Update quality history
            self.quality_history.append({
                'timestamp': arrival_time,
                'quality': qc_data['quality_level'],
                'flags': qc_data['flags'].copy()
            })
            
            return qc_data
            
    def _determine_quality_level(self, flags: List[QCFlag]) -> QualityLevel:
        """Determine quality level based on flags"""
        if not flags:
            return QualityLevel.EXCELLENT
            
        # Count critical flags
        critical_flags = {QCFlag.PPS_LOST, QCFlag.CALIBRATION_INVALID, QCFlag.CRC_ERROR}
        critical_count = sum(1 for flag in flags if flag in critical_flags)
        
        if critical_count > 0:
            return QualityLevel.UNACCEPTABLE
            
        # Count major flags
        major_flags = {QCFlag.GAP_DETECTED, QCFlag.OVERFLOW_DETECTED, QCFlag.BUFFER_OVERFLOW}
        major_count = sum(1 for flag in flags if flag in major_flags)
        
        if major_count > 2:
            return QualityLevel.POOR
        elif major_count > 0:
            return QualityLevel.FAIR
            
        # Count minor flags
        minor_flags = {QCFlag.TIMING_DRIFT, QCFlag.SAMPLE_RATE_ERROR, QCFlag.SEQUENCE_ERROR}
        minor_count = sum(1 for flag in flags if flag in minor_flags)
        
        if minor_count > 1:
            return QualityLevel.FAIR
        elif minor_count > 0:
            return QualityLevel.GOOD
            
        return QualityLevel.EXCELLENT
        
    def update_mcu_status(self, stat_data: Dict[str, Any]):
        """Update QC based on MCU status"""
        with self.lock:
            # Check for overflows
            buffer_overflows = stat_data.get('buffer_overflows', 0)
            samples_skipped = stat_data.get('samples_skipped_due_to_overflow', 0)
            
            if buffer_overflows > self.overflow_count:
                self.overflow_count = buffer_overflows
                self.active_flags.add(QCFlag.BUFFER_OVERFLOW)
                
            if samples_skipped > 0:
                self.active_flags.add(QCFlag.OVERFLOW_DETECTED)
                
            # Check PPS status
            pps_valid = stat_data.get('pps_valid', False)
            if not pps_valid:
                self.active_flags.add(QCFlag.PPS_LOST)
            else:
                self.active_flags.discard(QCFlag.PPS_LOST)
                
            # Check calibration status
            calibration_valid = stat_data.get('calibration_valid', False)
            if not calibration_valid:
                self.active_flags.add(QCFlag.CALIBRATION_INVALID)
            else:
                self.active_flags.discard(QCFlag.CALIBRATION_INVALID)
                
    def get_quality_statistics(self) -> Dict[str, Any]:
        """Get quality statistics"""
        with self.lock:
            if not self.quality_history:
                return {
                    'total_samples': 0,
                    'quality_distribution': {},
                    'gap_count': 0,
                    'overflow_count': 0,
                    'active_flags': []
                }
                
            # Calculate quality distribution
            quality_dist = {}
            for entry in self.quality_history:
                quality = entry['quality']
                quality_dist[quality.value] = quality_dist.get(quality.value, 0) + 1
                
            # Calculate recent quality (last 100 samples)
            recent_quality = [entry['quality'] for entry in list(self.quality_history)[-100:]]
            recent_quality_dist = {}
            for quality in recent_quality:
                recent_quality_dist[quality.value] = recent_quality_dist.get(quality.value, 0) + 1
                
            return {
                'total_samples': self.sample_count,
                'quality_distribution': quality_dist,
                'recent_quality_distribution': recent_quality_dist,
                'gap_count': self.gap_count,
                'overflow_count': self.overflow_count,
                'active_flags': [flag.value for flag in self.active_flags],
                'gap_history_count': len(self.gap_history)
            }
            
    def get_gap_statistics(self) -> Dict[str, Any]:
        """Get gap statistics"""
        with self.lock:
            if not self.gap_history:
                return {
                    'total_gaps': 0,
                    'avg_gap_error_us': 0.0,
                    'max_gap_error_us': 0.0,
                    'gap_rate_per_minute': 0.0
                }
                
            # Calculate gap statistics
            gap_errors = [entry['gap_error_us'] for entry in self.gap_history]
            total_gaps = len(gap_errors)
            
            if total_gaps == 0:
                return {
                    'total_gaps': 0,
                    'avg_gap_error_us': 0.0,
                    'max_gap_error_us': 0.0,
                    'gap_rate_per_minute': 0.0
                }
                
            avg_gap_error = sum(gap_errors) / total_gaps
            max_gap_error = max(gap_errors)
            
            # Calculate gap rate
            time_span = self.gap_history[-1]['timestamp'] - self.gap_history[0]['timestamp']
            gap_rate_per_minute = (total_gaps / time_span) * 60 if time_span > 0 else 0
            
            return {
                'total_gaps': total_gaps,
                'avg_gap_error_us': avg_gap_error,
                'max_gap_error_us': max_gap_error,
                'gap_rate_per_minute': gap_rate_per_minute,
                'recent_gaps': gap_errors[-10:] if len(gap_errors) >= 10 else gap_errors
            }
            
    def reset_statistics(self):
        """Reset QC statistics"""
        with self.lock:
            self.last_timestamp_us = 0
            self.last_sequence = 0
            self.last_arrival_time = 0.0
            self.sample_count = 0
            self.gap_count = 0
            self.overflow_count = 0
            self.quality_history.clear()
            self.gap_history.clear()
            self.active_flags.clear()
            
    def get_current_quality(self) -> QualityLevel:
        """Get current quality level"""
        with self.lock:
            if not self.quality_history:
                return QualityLevel.EXCELLENT
                
            # Return most recent quality
            return self.quality_history[-1]['quality']

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create QC manager
    qc_manager = QCManager(expected_sample_rate=100.0)
    
    # Simulate sample processing
    print("Simulating sample processing...")
    
    base_timestamp = int(time.time() * 1_000_000)
    base_time = time.time()
    
    for i in range(100):
        # Normal sample
        sample_data = {
            'timestamp_us': base_timestamp + (i * 10000),  # 10ms intervals
            'sequence': i,
            'arrival_time': base_time + (i * 0.01)
        }
        
        qc_data = qc_manager.process_sample(sample_data)
        
        if qc_data['flags']:
            print(f"Sample {i}: {qc_data['quality_level'].value} - {[flag.value for flag in qc_data['flags']]}")
            
    # Simulate gap
    print("\nSimulating gap...")
    gap_sample = {
        'timestamp_us': base_timestamp + (100 * 10000) + 50000,  # 50ms gap
        'sequence': 100,
        'arrival_time': base_time + (100 * 0.01) + 0.05
    }
    
    qc_data = qc_manager.process_sample(gap_sample)
    print(f"Gap sample: {qc_data['quality_level'].value} - {[flag.value for flag in qc_data['flags']]}")
    
    # Check statistics
    quality_stats = qc_manager.get_quality_statistics()
    print(f"\nQuality statistics: {json.dumps(quality_stats, indent=2)}")
    
    gap_stats = qc_manager.get_gap_statistics()
    print(f"Gap statistics: {json.dumps(gap_stats, indent=2)}")
    
    print("QC flags test completed!")
