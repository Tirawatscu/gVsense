#!/usr/bin/env python3
"""
Reconstruction Utilities for Interpolating Missing Samples by Timestamp
Provides gap filling and data reconstruction capabilities
"""

import time
import logging
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
from scipy import interpolate
from scipy.signal import resample
import threading

logger = logging.getLogger(__name__)

class SampleReconstructor:
    """Reconstruct missing samples by timestamp interpolation"""
    
    def __init__(self, 
                 max_gap_samples: int = 100,
                 interpolation_method: str = 'linear',
                 max_reconstruction_time: float = 10.0):
        self.max_gap_samples = max_gap_samples
        self.interpolation_method = interpolation_method
        self.max_reconstruction_time = max_reconstruction_time
        
        # Sample buffer for interpolation
        self.sample_buffer = deque(maxlen=1000)
        self.last_timestamp_us = 0
        self.expected_interval_us = 10000  # 100 Hz default
        
        # Reconstruction statistics
        self.reconstructed_samples = 0
        self.reconstruction_attempts = 0
        self.failed_reconstructions = 0
        
        # Threading
        self.lock = threading.Lock()
        
    def add_sample(self, sample_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Add sample and detect gaps
        
        Args:
            sample_data: Sample data with timestamp, channels, etc.
            
        Returns:
            List of reconstructed samples (if any)
        """
        with self.lock:
            timestamp_us = sample_data.get('timestamp_us', 0)
            channels = sample_data.get('channels', [])
            
            # Add sample to buffer
            self.sample_buffer.append({
                'timestamp_us': timestamp_us,
                'channels': channels,
                'sequence': sample_data.get('sequence', 0),
                'arrival_time': sample_data.get('arrival_time', time.time()),
                'is_reconstructed': False
            })
            
            # Detect gaps and reconstruct
            reconstructed_samples = []
            
            if self.last_timestamp_us > 0:
                gap_samples = self._detect_gap(timestamp_us)
                if gap_samples > 0:
                    reconstructed_samples = self._reconstruct_gap(gap_samples, timestamp_us)
                    
            self.last_timestamp_us = timestamp_us
            return reconstructed_samples
            
    def _detect_gap(self, current_timestamp_us: int) -> int:
        """Detect gap between last and current timestamp"""
        if self.last_timestamp_us == 0:
            return 0
            
        time_diff_us = current_timestamp_us - self.last_timestamp_us
        expected_diff_us = self.expected_interval_us
        
        # Calculate number of missing samples
        gap_samples = int(round(time_diff_us / expected_diff_us)) - 1
        
        return max(0, gap_samples)
        
    def _reconstruct_gap(self, gap_samples: int, current_timestamp_us: int) -> List[Dict[str, Any]]:
        """Reconstruct missing samples in gap"""
        if gap_samples == 0 or gap_samples > self.max_gap_samples:
            return []
            
        self.reconstruction_attempts += 1
        
        try:
            # Get samples for interpolation
            if len(self.sample_buffer) < 2:
                return []
                
            # Use last few samples for interpolation
            interpolation_samples = list(self.sample_buffer)[-10:]  # Last 10 samples
            
            if len(interpolation_samples) < 2:
                return []
                
            # Extract timestamps and channel data
            timestamps = [s['timestamp_us'] for s in interpolation_samples]
            channel_data = [s['channels'] for s in interpolation_samples]
            
            # Reconstruct each channel
            reconstructed_channels = []
            for channel_idx in range(len(channel_data[0])):
                channel_values = [ch[channel_idx] for ch in channel_data]
                
                # Interpolate missing values
                interpolated_values = self._interpolate_channel(
                    timestamps, channel_values, gap_samples, current_timestamp_us
                )
                
                reconstructed_channels.append(interpolated_values)
                
            # Create reconstructed samples
            reconstructed_samples = []
            for i in range(gap_samples):
                sample_timestamp = self.last_timestamp_us + (i + 1) * self.expected_interval_us
                
                # Extract interpolated values for this sample
                sample_channels = [ch[i] for ch in reconstructed_channels]
                
                reconstructed_sample = {
                    'timestamp_us': sample_timestamp,
                    'channels': sample_channels,
                    'sequence': 0,  # Will be filled by caller
                    'arrival_time': time.time(),
                    'is_reconstructed': True,
                    'reconstruction_method': self.interpolation_method,
                    'gap_position': i + 1,
                    'total_gap_samples': gap_samples
                }
                
                reconstructed_samples.append(reconstructed_sample)
                
            self.reconstructed_samples += len(reconstructed_samples)
            return reconstructed_samples
            
        except Exception as e:
            logger.error(f"Failed to reconstruct gap: {e}")
            self.failed_reconstructions += 1
            return []
            
    def _interpolate_channel(self, timestamps: List[int], values: List[float], 
                           gap_samples: int, current_timestamp_us: int) -> List[float]:
        """Interpolate missing values for a single channel"""
        try:
            if self.interpolation_method == 'linear':
                return self._linear_interpolation(timestamps, values, gap_samples, current_timestamp_us)
            elif self.interpolation_method == 'cubic':
                return self._cubic_interpolation(timestamps, values, gap_samples, current_timestamp_us)
            elif self.interpolation_method == 'spline':
                return self._spline_interpolation(timestamps, values, gap_samples, current_timestamp_us)
            else:
                return self._linear_interpolation(timestamps, values, gap_samples, current_timestamp_us)
                
        except Exception as e:
            logger.error(f"Interpolation failed: {e}")
            # Fallback to linear interpolation
            return self._linear_interpolation(timestamps, values, gap_samples, current_timestamp_us)
            
    def _linear_interpolation(self, timestamps: List[int], values: List[float], 
                            gap_samples: int, current_timestamp_us: int) -> List[float]:
        """Linear interpolation"""
        # Create interpolation function
        interp_func = interpolate.interp1d(timestamps, values, kind='linear', 
                                          bounds_error=False, fill_value='extrapolate')
        
        # Generate timestamps for missing samples
        gap_timestamps = []
        for i in range(gap_samples):
            timestamp = self.last_timestamp_us + (i + 1) * self.expected_interval_us
            gap_timestamps.append(timestamp)
            
        # Interpolate values
        interpolated_values = interp_func(gap_timestamps).tolist()
        return interpolated_values
        
    def _cubic_interpolation(self, timestamps: List[int], values: List[float], 
                           gap_samples: int, current_timestamp_us: int) -> List[float]:
        """Cubic interpolation"""
        if len(timestamps) < 4:
            return self._linear_interpolation(timestamps, values, gap_samples, current_timestamp_us)
            
        # Create cubic interpolation function
        interp_func = interpolate.interp1d(timestamps, values, kind='cubic', 
                                          bounds_error=False, fill_value='extrapolate')
        
        # Generate timestamps for missing samples
        gap_timestamps = []
        for i in range(gap_samples):
            timestamp = self.last_timestamp_us + (i + 1) * self.expected_interval_us
            gap_timestamps.append(timestamp)
            
        # Interpolate values
        interpolated_values = interp_func(gap_timestamps).tolist()
        return interpolated_values
        
    def _spline_interpolation(self, timestamps: List[int], values: List[float], 
                            gap_samples: int, current_timestamp_us: int) -> List[float]:
        """Spline interpolation"""
        if len(timestamps) < 3:
            return self._linear_interpolation(timestamps, values, gap_samples, current_timestamp_us)
            
        # Create spline interpolation function
        interp_func = interpolate.UnivariateSpline(timestamps, values, s=0)
        
        # Generate timestamps for missing samples
        gap_timestamps = []
        for i in range(gap_samples):
            timestamp = self.last_timestamp_us + (i + 1) * self.expected_interval_us
            gap_timestamps.append(timestamp)
            
        # Interpolate values
        interpolated_values = interp_func(gap_timestamps).tolist()
        return interpolated_values
        
    def set_expected_interval(self, interval_us: int):
        """Set expected sample interval"""
        with self.lock:
            self.expected_interval_us = interval_us
            
    def get_statistics(self) -> Dict[str, Any]:
        """Get reconstruction statistics"""
        with self.lock:
            success_rate = 0.0
            if self.reconstruction_attempts > 0:
                success_rate = (self.reconstruction_attempts - self.failed_reconstructions) / self.reconstruction_attempts
                
            return {
                'reconstructed_samples': self.reconstructed_samples,
                'reconstruction_attempts': self.reconstruction_attempts,
                'failed_reconstructions': self.failed_reconstructions,
                'success_rate': success_rate,
                'buffer_size': len(self.sample_buffer),
                'expected_interval_us': self.expected_interval_us,
                'interpolation_method': self.interpolation_method
            }
            
    def reset_statistics(self):
        """Reset reconstruction statistics"""
        with self.lock:
            self.reconstructed_samples = 0
            self.reconstruction_attempts = 0
            self.failed_reconstructions = 0
            self.sample_buffer.clear()
            self.last_timestamp_us = 0

class DataReconstructor:
    """High-level data reconstruction manager"""
    
    def __init__(self, 
                 expected_sample_rate: float = 100.0,
                 max_gap_samples: int = 100,
                 interpolation_method: str = 'linear'):
        self.expected_sample_rate = expected_sample_rate
        self.expected_interval_us = int(1_000_000 / expected_sample_rate)
        
        # Create reconstructor
        self.reconstructor = SampleReconstructor(
            max_gap_samples=max_gap_samples,
            interpolation_method=interpolation_method
        )
        
        # Set expected interval
        self.reconstructor.set_expected_interval(self.expected_interval_us)
        
        # Statistics
        self.total_samples_processed = 0
        self.total_gaps_detected = 0
        self.total_samples_reconstructed = 0
        
    def process_sample(self, sample_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process sample and return reconstructed samples"""
        # Add sample to reconstructor
        reconstructed_samples = self.reconstructor.add_sample(sample_data)
        
        # Update statistics
        self.total_samples_processed += 1
        if reconstructed_samples:
            self.total_gaps_detected += 1
            self.total_samples_reconstructed += len(reconstructed_samples)
            
        # Return reconstructed samples
        return reconstructed_samples
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get reconstruction statistics"""
        base_stats = self.reconstructor.get_statistics()
        
        return {
            **base_stats,
            'total_samples_processed': self.total_samples_processed,
            'total_gaps_detected': self.total_gaps_detected,
            'total_samples_reconstructed': self.total_samples_reconstructed,
            'gap_rate': self.total_gaps_detected / self.total_samples_processed if self.total_samples_processed > 0 else 0,
            'reconstruction_rate': self.total_samples_reconstructed / self.total_samples_processed if self.total_samples_processed > 0 else 0
        }
        
    def reset_statistics(self):
        """Reset reconstruction statistics"""
        self.total_samples_processed = 0
        self.total_gaps_detected = 0
        self.total_samples_reconstructed = 0
        self.reconstructor.reset_statistics()

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create reconstructor
    reconstructor = DataReconstructor(expected_sample_rate=100.0, interpolation_method='linear')
    
    # Simulate data with gaps
    print("Simulating data with gaps...")
    
    base_timestamp = int(time.time() * 1_000_000)
    base_time = time.time()
    
    # Normal samples
    for i in range(10):
        sample_data = {
            'timestamp_us': base_timestamp + (i * 10000),  # 10ms intervals
            'channels': [i * 100, i * 200, i * 300],  # 3 channels
            'sequence': i,
            'arrival_time': base_time + (i * 0.01)
        }
        
        reconstructed = reconstructor.process_sample(sample_data)
        if reconstructed:
            print(f"Reconstructed {len(reconstructed)} samples after sample {i}")
            
    # Gap sample (skip 5 samples)
    gap_sample = {
        'timestamp_us': base_timestamp + (15 * 10000),  # Skip 5 samples
        'channels': [1500, 3000, 4500],
        'sequence': 15,
        'arrival_time': base_time + (15 * 0.01)
    }
    
    reconstructed = reconstructor.process_sample(gap_sample)
    print(f"Reconstructed {len(reconstructed)} samples for gap")
    
    # Print reconstructed samples
    for i, sample in enumerate(reconstructed):
        print(f"  Reconstructed {i+1}: {sample['timestamp_us']} - {sample['channels']}")
        
    # Check statistics
    stats = reconstructor.get_statistics()
    print(f"\nReconstruction statistics: {json.dumps(stats, indent=2)}")
    
    print("Reconstruction test completed!")
