#!/usr/bin/env python3
"""
Host-Managed Timing Seismic Acquisition with Robust Timestamp Algorithm
Updated to include the advanced timestamp generation system
"""

import serial
import time
import threading
import datetime
import glob
import platform
import logging
import subprocess
from collections import deque
import statistics
import math

# Import the unified timing system
from timing_fix import UnifiedTimingManager, SimplifiedTimestampGenerator, TimingAdapter

# Import the robust timestamp generator (deprecated - will be removed)
class RobustTimestampGenerator:
    """
    DEPRECATED: Advanced timestamp generator with drift compensation and anomaly detection
    This class is deprecated and replaced by SimplifiedTimestampGenerator in timing_fix.py
    It remains here for compatibility but should not be used for new code.
    """
    
    def __init__(self, expected_rate=100.0, max_sequence=65536):
        self.expected_rate = expected_rate
        self.expected_interval = 1.0 / expected_rate
        self.max_sequence = max_sequence
        self.half_sequence_range = max_sequence // 2
        
        # Configuration (must be set before reset())
        self.drift_window_size = 100  # Samples to calculate drift
        self.max_drift_ppm = 1000     # Max allowed drift: 1000 ppm (0.1%)
        self.sequence_gap_threshold = 10  # Max sequence gap before reset
        self.time_jump_threshold = 1.0    # Max time jump (seconds) before reset
        self.outlier_threshold = 0.05     # 50ms threshold for outlier detection
        
        # Timing state
        self.lock = threading.Lock()
        self.reset()
        
        # Statistics
        self.stats = {
            'samples_processed': 0,
            'resets_performed': 0,
            'drift_corrections': 0,
            'sequence_wraparounds': 0,
            'outliers_rejected': 0,
            'large_gaps_detected': 0,
            'mcu_restarts_detected': 0,  # NEW: Track MCU restarts
            'timestamp_continuity_preserved': 0,  # NEW: Track continuity preservation
            'reference_updates_performed': 0
        }
        
    def prime_with_start_time(self, start_time):
        """Pre-sets the synchronized start time to avoid race conditions."""
        with self.lock:
            self.synchronized_start_time_pre_set = start_time
            print(f"Timestamp generator primed with start time: {start_time:.6f}")

    def reset(self):
        """Reset all timing state"""
        with self.lock:
            self.reference_time = None
            self.reference_sequence = None
            self.reference_system_time = None
            
            # Drift tracking
            self.timing_samples = deque(maxlen=self.drift_window_size)
            self.current_drift_rate = 0.0
            self.last_drift_update = 0
            
            # Outlier detection
            self.recent_intervals = deque(maxlen=20)
            
            # State flags
            self.is_initialized = False
            self.last_timestamp = None
            self.last_sequence = None
            self.consecutive_good_samples = 0
            
            # Clear pre-set start time if it exists from a previous run
            if hasattr(self, 'synchronized_start_time_pre_set'):
                self.synchronized_start_time_pre_set = None
            
            # Log throttles
            self._last_precision_log = 0.0
            self._precision_log_interval = 1.0  # seconds
            self._last_anomaly_log = 0.0
            self._anomaly_log_interval = 0.5  # seconds
            self._backward_cluster = 0
        
    def generate_timestamp(self, sequence, timing_manager=None):
        """
        DEPRECATED: This method is no longer used for timestamp generation
        All timestamps now go through the unified timing system via timing_adapter
        
        This method is kept for backward compatibility but should not be called
        """
        print("⚠️  WARNING: Legacy generate_timestamp() called - this should not happen!")
        print(f"   Sequence: {sequence}")
        print(f"   Use self.timing_adapter.generate_timestamp(sequence) instead")
        
        # Fallback to unified system if available
        if hasattr(self, 'timing_adapter'):
            return self.timing_adapter.generate_timestamp(sequence)
        else:
            # Emergency fallback - use current time (NOT quantized)
            print("   EMERGENCY: No timing adapter available, using current time")
            return int(time.time() * 1000)
    
    def _initialize_timing(self, sequence, system_time, timing_manager):
        """Initialize timing with synchronized start approach"""
        # CRITICAL FIX: Use the synchronized start time, not current GPS time
        # This maintains perfect alignment with the MCU's synchronized start
        
        # IMPROVEMENT: Use pre-set start time if available to prevent race condition
        if hasattr(self, 'synchronized_start_time_pre_set') and self.synchronized_start_time_pre_set:
            synchronized_start_time = self.synchronized_start_time_pre_set
            self.synchronized_start_time_pre_set = None  # Consume the pre-set time
            print(f"SYNC INIT: Using pre-set synchronized start time: {synchronized_start_time:.6f}")
        else:
            # Original behavior (fallback): Calculate start time based on first packet arrival
            # This can cause a 1-second jump if packet is delayed over a second boundary.
            current_second = math.floor(system_time)
            synchronized_start_time = current_second + 1.0  # The agreed-upon start time
            print(f"SYNC INIT: WARNING: Using dynamically calculated start time (risk of jump): {synchronized_start_time:.6f}")
        
        print(f"SYNC INIT: System time at init: {system_time:.6f}")
        print(f"SYNC INIT: Using synchronized start as timing reference (NOT current GPS time)")
        
        # Store the synchronized start time as our reference
        self.synchronized_start_time = synchronized_start_time
        self.synchronized_start_millis = int(synchronized_start_time * 1000)
        
        # CRITICAL: Use synchronized start time as reference, not current GPS time
        self.reference_time = synchronized_start_time
        self.reference_sequence = sequence
        self.reference_system_time = system_time
        self.last_sequence = sequence
        self.last_timestamp = synchronized_start_time
        self.is_initialized = True
        self.consecutive_good_samples = 1
        
        # Enhanced precision tracking with synchronized baseline
        self.precision_tracking = {
            'base_reference_time': synchronized_start_time,
            'base_reference_sequence': sequence,
            'total_samples_processed': 0,
            'cumulative_drift_correction': 0.0,
            'last_reference_update': system_time,
            'synchronized_start': True,
            'sync_start_time': synchronized_start_time,
            'initial_gps_offset': 0.0,  # Track initial GPS offset for monitoring
            'last_gps_sync_time': system_time
        }
        
        # Get GPS time for monitoring (but don't use it as reference)
        if timing_manager:
            try:
                gps_time = timing_manager.get_precise_time()
                if gps_time and abs(gps_time - system_time) < 10:
                    initial_gps_offset = synchronized_start_time - gps_time
                    self.precision_tracking['initial_gps_offset'] = initial_gps_offset
                    print(f"SYNC INIT: GPS time: {gps_time:.6f}, offset from sync: {initial_gps_offset*1000:+.1f}ms")
                else:
                    print(f"SYNC INIT: GPS time unavailable or unreliable")
            except Exception as e:
                print(f"SYNC INIT: GPS error: {e}")
        
        # Return the synchronized start time for the MCU
        return int(synchronized_start_time * 1000)
    
    def _calculate_sequence_diff(self, last_seq, current_seq):
        """Calculate sequence difference handling 16-bit wraparound"""
        if current_seq >= last_seq:
            # Normal forward progression
            return current_seq - last_seq
        else:
            # current_seq < last_seq: potential wraparound or backward jump
            # For 16-bit: 65535 -> 0 should be diff=1, not 65536
            forward_diff = (self.max_sequence - last_seq) + current_seq
            backward_diff = last_seq - current_seq
            
            # Choose the smaller difference (more likely to be correct)
            # For 16-bit sequences, half range is 32768
            if forward_diff <= self.half_sequence_range:
                # Likely wraparound (e.g., 65535 -> 0 gives forward_diff = 1)
                self.stats['sequence_wraparounds'] += 1
                
                # FIXED: Only print wraparound message once per wraparound event
                # Check if this is a new wraparound (not a continuation of previous one)
                if not hasattr(self, 'last_wraparound_sequence') or abs(current_seq - self.last_wraparound_sequence) > 100:
                    print(f"📱 Sequence wraparound: {last_seq} → {current_seq} (diff: {forward_diff})")
                    self.last_wraparound_sequence = current_seq
                
                return forward_diff
            else:
                # Large backward jump - likely an error or restart
                now = time.time()
                if not hasattr(self, '_last_anomaly_log'):
                    self._last_anomaly_log = 0.0
                    self._anomaly_log_interval = 0.5
                if (now - self._last_anomaly_log) > self._anomaly_log_interval:
                    print(f"⚠️  Large backward sequence jump: {last_seq} → {current_seq}")
                    self._last_anomaly_log = now
                return -backward_diff
    
    def _detect_anomaly(self, sequence_diff, time_diff):
        """Detect timing and sequence anomalies"""
        # Check if we're in a restart cooldown period (recent reset)
        restart_cooldown = 10.0  # seconds
        if hasattr(self, '_last_reset_time'):
            current_time = time.time()
            if (current_time - self._last_reset_time) < restart_cooldown:
                # During restart cooldown, be more conservative about anomaly detection
                if abs(sequence_diff) > 0 and abs(sequence_diff) < 100:  # Allow small gaps during restart
                    return None
        
        # Check for sequence anomalies
        if abs(sequence_diff) > self.sequence_gap_threshold:
            now = time.time()
            if not hasattr(self, '_last_anomaly_log'):
                self._last_anomaly_log = 0.0
                self._anomaly_log_interval = 0.5
            if (now - self._last_anomaly_log) > self._anomaly_log_interval:
                print(f"⚠️  Large sequence gap: {sequence_diff}")
                self._last_anomaly_log = now
            return f"large_sequence_gap:{sequence_diff}"
        
        # Only flag as anomaly if sequence goes backward AND it's not a small wraparound
        if sequence_diff <= 0:
            if sequence_diff < -self.sequence_gap_threshold:
                now = time.time()
                if not hasattr(self, '_last_anomaly_log'):
                    self._last_anomaly_log = 0.0
                    self._anomaly_log_interval = 0.5
                if (now - self._last_anomaly_log) > self._anomaly_log_interval:
                    print(f"⚠️  Large backward sequence: {sequence_diff}")
                    self._last_anomaly_log = now
                return f"large_sequence_backward:{sequence_diff}"
            elif sequence_diff == 0:
                return f"sequence_duplicate:{sequence_diff}"
        
        # Check for time anomalies only if we have a positive sequence progression
        if sequence_diff > 0:
            expected_time_diff = sequence_diff * self.expected_interval
            time_error = abs(time_diff - expected_time_diff)
            
            if time_diff > self.time_jump_threshold:
                print(f"⚠️  Large time jump: {time_diff:.3f}s")
                return f"large_time_jump:{time_diff:.3f}s"
            
            if time_error > self.outlier_threshold:
                print(f"⚠️  Timing outlier: {time_error*1000:.1f}ms > {self.outlier_threshold*1000:.1f}ms")
                return f"timing_outlier:error_{time_error:.3f}s"
        
        return None
    
    def _handle_anomaly(self, sequence, system_time, anomaly, timing_manager):
        """Handle detected anomaly"""
        if "large_sequence_gap" in anomaly or "large_time_jump" in anomaly:
            # Major anomaly - reset timing reference
            self.stats['resets_performed'] += 1
            self.stats['large_gaps_detected'] += 1
            self._reset_timing_reference(sequence, system_time, timing_manager)
            
            # Immediately update last_sequence and last_timestamp to prevent re-triggering
            self.last_sequence = sequence
            self.last_timestamp = self.reference_time
            
            return int(self.reference_time * 1000)
        
        elif "sequence_backward" in anomaly or "sequence_duplicate" in anomaly:
            # Sequence went backward or duplicated - use interpolated timestamp
            interpolated_time = self.last_timestamp + self.expected_interval
            self._update_state(sequence, interpolated_time, system_time)
            return int(interpolated_time * 1000)
        
        elif "timing_outlier" in anomaly:
            # Timing outlier - use drift-corrected calculation
            self.stats['outliers_rejected'] += 1
            timestamp = self._calculate_timestamp_with_drift_correction(sequence, system_time)
            self._update_state(sequence, timestamp, system_time)
            return int(timestamp * 1000)
        
        else:
            # Unknown anomaly - use safe calculation
            timestamp = self._calculate_timestamp(sequence, system_time)
            self._update_state(sequence, timestamp, system_time)
            return int(timestamp * 1000)
    
    def _is_likely_mcu_restart(self, sequence):
        """Detect if a low sequence number indicates MCU restart vs wraparound"""
        if self.last_sequence is None:
            return False
        
        # If last sequence was high (near max) and current is very low, 
        # but not consecutive, it might be a restart
        if (self.last_sequence > (self.max_sequence * 0.9) and  # Last was > 90% of max
            sequence < 100 and  # Current is very low
            sequence > 10):  # But not 0-10 (which would be normal wraparound)
            return True
        
        # If sequence jumps from high to exactly 0, might be restart
        if self.last_sequence > 1000 and sequence == 0:
            return True
            
        return False

    def _calculate_total_samples_from_base(self, current_sequence):
        """Calculate total samples from base reference with wraparound handling"""
        if not hasattr(self, 'precision_tracking'):
            return -1
        
        base_seq = self.precision_tracking['base_reference_sequence']
        
        # Handle wraparound-safe calculation
        if current_sequence >= base_seq:
            # Normal case: no wraparound
            return current_sequence - base_seq
        else:
            # Wraparound case: calculate through the wraparound
            # For 16-bit: if base=65000 and current=100, total = (65536-65000) + 100 = 636
            samples_to_wrap = self.max_sequence - base_seq
            samples_after_wrap = current_sequence
            total_samples = samples_to_wrap + samples_after_wrap
            
            # Sanity check: if the total seems too large, sequence probably reset
            if total_samples > 100000:  # More than ~16 minutes at 100Hz
                print(f"PRECISION: Large sample count detected ({total_samples}), likely MCU restart")
                # Reset base reference to current position
                self.precision_tracking['base_reference_sequence'] = current_sequence
                self.precision_tracking['base_reference_time'] = (
                    self.precision_tracking['base_reference_time'] + 
                    total_samples * self.expected_interval
                )
                return 0
            
            return total_samples

    def _reset_timing_reference(self, sequence, system_time, timing_manager):
        """Reset timing reference while preserving continuity"""
        print(f"Resetting timing reference - sequence: {sequence}, preserving continuity")
        
        # Check if this might be an MCU restart
        if self._is_likely_mcu_restart(sequence):
            self.stats['mcu_restarts_detected'] += 1
            print(f"Possible MCU restart detected: {self.last_sequence} -> {sequence}")
        
        # Try to maintain timestamp continuity
        if self.last_timestamp:
            new_reference_time = self.last_timestamp + self.expected_interval
            self.stats['timestamp_continuity_preserved'] += 1
        else:
            new_reference_time = system_time
        
        # Apply precise timing if available
        if timing_manager:
            try:
                precise_time = timing_manager.get_precise_time()
                if precise_time and abs(precise_time - system_time) < 10:
                    new_reference_time = precise_time
            except:
                pass
        
        self.reference_time = new_reference_time
        self.reference_sequence = sequence
        self.reference_system_time = system_time
        self.consecutive_good_samples = 0
        
        # Clear drift tracking
        self.timing_samples.clear()
        self.current_drift_rate = 0.0
        
        # Set restart cooldown to prevent rapid resets
        self._last_reset_time = system_time
    
    def _calculate_timestamp(self, sequence, system_time):
        """Calculate timestamp with adaptive intervals and artificial clean timestamps"""
        if not self.is_initialized:
            return system_time
        
        # Calculate sequence difference from reference (handles wraparound)
        sequence_diff = self._calculate_sequence_diff(self.reference_sequence, sequence)
        
        if sequence_diff > 0:
            # Use adaptive interval which can include host rate correction (ppm)
            mcu_interval = self._get_adaptive_interval()
            timestamp = self.reference_time + (sequence_diff * mcu_interval)
            # Round to microsecond precision for stability in floating math
            timestamp = round(timestamp * 1_000_000) / 1_000_000
            return timestamp
        else:
            # Fallback for edge cases
            return self.last_timestamp + self.expected_interval if self.last_timestamp else system_time
    
    def _get_adaptive_interval(self):
        """Get adaptive interval - trust MCU precision over UART measurements"""
        # CRITICAL: Don't use UART timing measurements for interval calculation
        # The MCU generates precise samples using micros(), but UART introduces
        # transmission delays, buffering, and processing latency that corrupt timing
        
        # For scientific precision, trust the MCU's configured sample rate
        # MCU code: precision_timing.sample_interval_us = (uint64_t)(1000000.0 / rate)
        # This generates EXACT intervals regardless of UART transmission timing
        
        # Only use measured intervals for monitoring/diagnostics, not timestamp calculation
        if len(self.recent_intervals) >= 5:
            measured_interval = statistics.median(self.recent_intervals)
            
            # Calculate UART delay (difference between measured and expected)
            uart_delay_ms = (measured_interval - self.expected_interval) * 1000
            
            # Store UART diagnostics but don't use for timing
            if not hasattr(self, 'uart_diagnostics'):
                self.uart_diagnostics = {
                    'measured_interval_ms': 0,
                    'uart_delay_ms': 0,
                    'measurements_count': 0
                }
            
            self.uart_diagnostics['measured_interval_ms'] = measured_interval * 1000
            self.uart_diagnostics['uart_delay_ms'] = uart_delay_ms
            self.uart_diagnostics['measurements_count'] += 1
            
            # Report UART delay for diagnostics
            if self.uart_diagnostics['measurements_count'] % 1000 == 0:
                print(f"UART DIAGNOSTICS: MCU interval: {self.expected_interval*1000:.3f}ms, UART measured: {measured_interval*1000:.3f}ms, delay: {uart_delay_ms:+.3f}ms")
        
        # Start from configured interval
        interval = self.expected_interval
        # Apply host PLL rate adjustment (ppm), if available
        try:
            if hasattr(self, 'timing_manager') and self.timing_manager and hasattr(self.timing_manager, 'get_rate_adjustment_ppm'):
                ppm = float(self.timing_manager.get_rate_adjustment_ppm())
                # Positive ppm -> lengthen interval to slow timestamps
                interval = interval * (1.0 + ppm / 1e6)
        except Exception:
            pass
        # Return adjusted interval
        return interval
    
    def _calculate_timestamp_with_drift_correction(self, sequence, system_time):
        """Calculate timestamp with enhanced drift correction using adaptive intervals"""
        # Use adaptive interval for drift correction as well
        if len(self.recent_intervals) >= 5:
            adaptive_interval = self._get_adaptive_interval()
            sequence_diff = self._calculate_sequence_diff(self.reference_sequence, sequence)
            if sequence_diff > 0:
                timestamp = self.reference_time + (sequence_diff * adaptive_interval)
            else:
                timestamp = self.last_timestamp + adaptive_interval
        else:
            timestamp = self._calculate_timestamp(sequence, system_time)
        
        return timestamp
    
    def _update_drift_tracking(self, sequence_diff, time_diff, system_time):
        """Update drift tracking for long-term accuracy"""
        if sequence_diff > 0 and 0.001 < time_diff < 1.0:  # Reasonable time diff
            actual_interval = time_diff / sequence_diff
            self.recent_intervals.append(actual_interval)
            
            # Update timing samples for drift calculation
            self.timing_samples.append({
                'system_time': system_time,
                'actual_interval': actual_interval,
                'expected_interval': self.expected_interval,
                'sequence_diff': sequence_diff
            })
            
            # Calculate drift every 50 samples
            if len(self.timing_samples) >= 20 and system_time - self.last_drift_update > 5.0:
                self._calculate_drift_rate()
                self.last_drift_update = system_time
    
    def _calculate_drift_rate(self):
        """Calculate drift rate in ppm (parts per million)"""
        if len(self.timing_samples) < 10:
            return
        
        try:
            # Calculate average interval over recent samples
            recent_samples = list(self.timing_samples)[-50:]  # Last 50 samples
            intervals = [s['actual_interval'] for s in recent_samples]
            avg_interval = statistics.mean(intervals)
            
            # Calculate drift in ppm
            drift_ppm = ((avg_interval - self.expected_interval) / self.expected_interval) * 1e6
            
            # Apply smoothing
            if abs(drift_ppm) < self.max_drift_ppm:
                self.current_drift_rate = 0.8 * self.current_drift_rate + 0.2 * drift_ppm
        
        except Exception as e:
            print(f"⚠️  Drift calculation error: {e}")
    
    def _apply_timing_corrections(self, timestamp, timing_manager):
        """Apply timing manager corrections"""
        # This method is deprecated - corrections now handled by unified timing system
        return timestamp
    
    def _update_state(self, sequence, timestamp, system_time):
        """Update internal state with periodic reference time updates"""
        self.last_sequence = sequence
        self.last_timestamp = timestamp
        self.consecutive_good_samples += 1
        self.reference_system_time = system_time
        
        # Update precision tracking (simplified)
        if hasattr(self, 'precision_tracking'):
            self.precision_tracking['total_samples_processed'] += 1
            self.precision_tracking['last_reference_update'] = system_time
        
        # ENHANCED: Sliding reference update to prevent large sequence differences
        # Update reference every 10,000 samples (~100 seconds at 100Hz) to keep sequence diffs manageable
        if self.consecutive_good_samples % 10000 == 0:
            self._update_sliding_reference(sequence, timestamp, system_time)
        
        # ENHANCED: Periodic reference time updates for long-term accuracy
        # Update reference every hour (3600 seconds) to maintain GPS+PPS sync
        time_since_last_ref_update = system_time - (self.precision_tracking.get('last_reference_update', system_time) if hasattr(self, 'precision_tracking') else self.reference_system_time)
        
        if time_since_last_ref_update > 3600:  # 1 hour
            self._update_reference_for_long_term_stability(sequence, timestamp, system_time)
        
        # CLEANED UP: Periodic precision status (every 5000 samples instead of 10000)
        if hasattr(self, 'precision_tracking') and self.precision_tracking['total_samples_processed'] % 5000 == 0:
            total_samples = self.precision_tracking['total_samples_processed']
            runtime_seconds = total_samples * self.expected_interval
            theoretical_time = self.precision_tracking['base_reference_time'] + runtime_seconds
            actual_time = timestamp
            time_error = (actual_time - theoretical_time) * 1000  # Convert to ms
            
            # Get timing accuracy statistics
            accuracy_stats = self.get_timing_accuracy_stats()
            
            # CLEANED UP: More concise status report
            if accuracy_stats:
                print(f"📊 TIMING STATUS: {total_samples:,} samples, {runtime_seconds/60:.1f}min runtime")
                print(f"   Precision: avg±{accuracy_stats['average_error_ms']:+.3f}ms, max±{accuracy_stats['max_error_ms']:+.3f}ms, σ={accuracy_stats['error_std_dev_ms']:.3f}ms")
            else:
                print(f"📊 TIMING STATUS: {total_samples:,} samples, {runtime_seconds/60:.1f}min runtime, error: {time_error:+.3f}ms")
                
            # Report UART diagnostics concisely
            if hasattr(self, 'uart_diagnostics'):
                uart_diag = self.uart_diagnostics
                print(f"   UART: MCU={self.expected_interval*1000:.3f}ms, measured={uart_diag['measured_interval_ms']:.3f}ms, delay={uart_diag['uart_delay_ms']:+.3f}ms")
            else:
                print(f"   MCU: Using exact {self.expected_interval*1000:.3f}ms intervals")
    
    def _update_sliding_reference(self, sequence, timestamp, system_time):
        """Update reference point periodically to keep sequence differences manageable"""
        print(f"📍 Sliding reference update: seq {self.reference_sequence} → {sequence} (after {self.consecutive_good_samples:,} samples)")
        
        # Update reference to current position - this maintains timestamp continuity
        # while preventing sequence differences from growing too large
        self.reference_sequence = sequence
        self.reference_time = timestamp
        self.reference_system_time = system_time
        
        # Reset consecutive good samples counter for next interval
        self.consecutive_good_samples = 0
    
    def _update_reference_for_long_term_stability(self, sequence, current_timestamp, system_time):
        """Maintain long-term stability with GPS monitoring and clock drift compensation"""
        hours_elapsed = (system_time - self.reference_system_time) / 3600.0
        print(f"🕐 Long-term stability check after {hours_elapsed:.1f} hours")
        
        # Get current GPS time for monitoring and drift calculation
        gps_time = None
        if hasattr(self, 'timing_manager') and self.timing_manager:
            try:
                gps_time = self.timing_manager.get_precise_time()
                print(f"   GPS: {gps_time:.6f}, Current: {current_timestamp:.6f}")
            except Exception as e:
                print(f"   ⚠️  GPS error: {e}")
        
        if gps_time:
            # Calculate how much our timestamps have drifted relative to GPS
            gps_drift = current_timestamp - gps_time
            print(f"   GPS drift: {gps_drift*1000:+.1f}ms")
            
            # Calculate expected drift based on synchronized start baseline
            if hasattr(self, 'precision_tracking') and 'initial_gps_offset' in self.precision_tracking:
                initial_offset = self.precision_tracking['initial_gps_offset']
                expected_drift = initial_offset  # Should maintain initial offset
                actual_drift = gps_drift
                drift_error = actual_drift - expected_drift
                
                print(f"   Expected: {expected_drift*1000:+.1f}ms, Actual: {actual_drift*1000:+.1f}ms, Error: {drift_error*1000:+.1f}ms")
                
                # Calculate drift rate in ppm
                if hours_elapsed > 0:
                    drift_rate_ppm = (drift_error / (hours_elapsed * 3600)) * 1e6
                    print(f"   Clock drift rate: {drift_rate_ppm:+.1f} ppm")
                    
                    # Apply gentle correction if drift is noticeable (>20ms)
                    if abs(drift_error) > 0.02:  # 20ms threshold
                        print(f"   🔧 Drift detected ({drift_error*1000:+.1f}ms), applying gentle correction")
                        
                        # GENTLE CORRECTION: Maintain synchronized baseline; correct a fraction of error
                        correction_factor = 0.2  # Correct 20% of the error
                        correction = drift_error * correction_factor
                        
                        # Update reference time with gentle correction
                        corrected_reference_time = self.reference_time - correction
                        
                        print(f"   Applied gentle correction: {correction*1000:+.1f}ms")
                        
                        # Update reference with correction
                        self.reference_time = corrected_reference_time
                        self.reference_sequence = sequence
                        self.reference_system_time = system_time
                        
                        # Update precision tracking
                        self.precision_tracking['last_reference_update'] = system_time
                        self.precision_tracking['cumulative_drift_correction'] += correction
                        self.precision_tracking['last_gps_sync_time'] = system_time
                        
                        self.stats['reference_updates_performed'] = self.stats.get('reference_updates_performed', 0) + 1
                        print(f"   ✅ Gentle correction applied successfully")
                    else:
                        print(f"   ✅ Drift within tolerance ({drift_error*1000:+.1f}ms), no correction needed")
                        # Just update tracking timestamps
                        self.precision_tracking['last_reference_update'] = system_time
                        self.precision_tracking['last_gps_sync_time'] = system_time
                else:
                    print(f"   ⚠️  Insufficient runtime for drift calculation")
                    self.precision_tracking['last_reference_update'] = system_time
            else:
                print(f"   ⚠️  No initial GPS offset available")
                self.precision_tracking['last_reference_update'] = system_time
        else:
            print(f"   ⚠️  No GPS time available, maintaining current reference")
            # Just update the tracking timestamp
            if hasattr(self, 'precision_tracking'):
                self.precision_tracking['last_reference_update'] = system_time
        
        # Report stability status
        if hasattr(self, 'precision_tracking'):
            total_correction = self.precision_tracking.get('cumulative_drift_correction', 0)
            print(f"   Cumulative correction: {total_correction*1000:+.1f}ms over {hours_elapsed:.1f}h")
            
            if abs(total_correction) < 0.01:  # Less than 10ms total correction
                print(f"   ✅ Excellent long-term stability")
            elif abs(total_correction) < 0.1:  # Less than 100ms total correction
                print(f"   ✅ Good long-term stability")
            else:
                print(f"   ⚠️  Significant drift corrections required")
    
    def get_timing_accuracy_stats(self):
        """Get detailed timing accuracy statistics"""
        if not hasattr(self, 'timing_accuracy_tracking'):
            return None
        
        tracking = self.timing_accuracy_tracking
        if tracking['samples_tracked'] == 0:
            return None
        
        errors = list(tracking['timing_errors_ms'])
        
        import statistics
        stats = {
            'samples_tracked': tracking['samples_tracked'],
            'total_error_ms': tracking['total_error_ms'],
            'max_error_ms': tracking['max_error_ms'],
            'average_error_ms': tracking['total_error_ms'] / tracking['samples_tracked'],
            'current_error_ms': errors[-1] if errors else 0,
            'error_std_dev_ms': statistics.stdev(errors) if len(errors) > 1 else 0,
            'min_error_ms': min(errors) if errors else 0,
            'error_range_ms': max(errors) - min(errors) if errors else 0,
            'recent_errors_ms': errors[-10:] if len(errors) >= 10 else errors  # Last 10 errors
        }
        
        return stats
    
    def get_stats(self):
        """Get comprehensive statistics including precision metrics and timing accuracy"""
        with self.lock:
            stats = dict(self.stats)
            stats.update({
                'is_initialized': self.is_initialized,
                'consecutive_good_samples': self.consecutive_good_samples,
                'current_drift_rate_ppm': self.current_drift_rate,
                'timing_samples_count': len(self.timing_samples),
                'recent_intervals_count': len(self.recent_intervals),
                'average_interval': statistics.mean(self.recent_intervals) if self.recent_intervals else 0,
                'last_timestamp': self.last_timestamp,
                'last_sequence': self.last_sequence,
                'expected_interval': self.expected_interval
            })
            
            # Add precision tracking statistics
            if hasattr(self, 'precision_tracking'):
                precision_stats = dict(self.precision_tracking)
                # Calculate runtime precision metrics
                if precision_stats['total_samples_processed'] > 0:
                    runtime_seconds = precision_stats['total_samples_processed'] * self.expected_interval
                    precision_stats['runtime_seconds'] = runtime_seconds
                    precision_stats['runtime_hours'] = runtime_seconds / 3600.0
                    precision_stats['drift_correction_ms'] = precision_stats['cumulative_drift_correction'] * 1000
                
                stats['precision_tracking'] = precision_stats
            
            # Add timing accuracy statistics (artificial vs accurate)
            timing_accuracy = self.get_timing_accuracy_stats()
            if timing_accuracy:
                stats['timing_accuracy'] = timing_accuracy
            
            # Add UART diagnostics
            if hasattr(self, 'uart_diagnostics'):
                stats['uart_diagnostics'] = dict(self.uart_diagnostics)
            
            if self.recent_intervals:
                stats['interval_std_dev'] = statistics.stdev(self.recent_intervals) if len(self.recent_intervals) > 1 else 0
                stats['interval_min'] = min(self.recent_intervals)
                stats['interval_max'] = max(self.recent_intervals)
                # Precision metrics
                interval_error = [(interval - self.expected_interval) for interval in self.recent_intervals]
                stats['timing_precision_ms'] = statistics.stdev(interval_error) * 1000 if len(interval_error) > 1 else 0
                stats['timing_accuracy_ms'] = statistics.mean(interval_error) * 1000 if interval_error else 0
                
                # MCU interval info (always exact)
                stats['mcu_interval_ms'] = self._get_adaptive_interval() * 1000
                stats['using_mcu_precision'] = True
            
            return stats


class HostTimingSeismicAcquisition:
    def __init__(self, port=None, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.connection_lock = threading.RLock()
        self.is_connected = False
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.reconnect_delay = 2.0
        
        # Auto-detect port if not specified
        if port is None:
            self.port = self._auto_detect_port()
        
        self.lock = threading.Lock()
        self.data_callback = None
        self.error_callback = None
        self.status_callback = None
        self.running = False
        self.rx_thread = None
        self.streaming = False
        self.command_response = None
        self.command_event = threading.Event()
        
        # Enhanced connection state tracking
        self.last_successful_read = time.time()
        self.last_any_activity = time.time()
        self.read_timeout_threshold = 30.0
        self.connection_established_time = None
        
        # Buffer for partial line assembly
        self.line_buffer = ""
        
        # UPDATED: Use unified timing system
        # Initialize timing adapter with 10ms quantization for consistent timestamp boundaries
        self.timing_adapter = TimingAdapter(quantization_ms=10)
        self.timing_manager = self.timing_adapter.unified_manager
        self.timestamp_generator = self.timing_adapter.timestamp_generator
        
        # Initialize timing adapter with device
        self.timing_adapter.initialize_with_device(self)
        # Track whether this session started aligned to PPS
        self.pps_started = False
        
        # Sample tracking for precision timestamping
        self.sample_tracking = {
            'stream_start_time': None,
            'stream_start_sequence': None,
            'expected_rate': 100.0,
            'last_sequence': None,
            'sequence_gaps': 0,
            'sample_count': 0,
            'sample_buffer': deque(maxlen=1000)  # Buffer recent samples for analysis
        }
        
        # Connection statistics
        self.connection_stats = {
            'total_reconnects': 0,
            'total_errors': 0,
            'data_packets_received': 0,
            'last_data_time': None,
            'connection_uptime_start': None
        }
        
        # Filter state
        self.current_filter = (None, None)  # (index, name)
        
        # Dithering state
        self.current_dithering = 4  # Default to 4x oversampling
        
        # Connect initially
        self._connect()
        
    def _auto_detect_port(self):
        """Auto-detect the appropriate serial port for different platforms"""
        system = platform.system().lower()
        
        if system == "linux":
            possible_ports = []
            possible_ports.extend(glob.glob('/dev/ttyACM*'))
            possible_ports.extend(glob.glob('/dev/ttyUSB*'))
            possible_ports.extend(glob.glob('/dev/ttyAMA*'))
            possible_ports.extend(glob.glob('/dev/serial/by-id/*'))
            possible_ports.sort(key=lambda x: (not x.startswith('/dev/ttyACM'), x))
            
        elif system == "darwin":
            possible_ports = glob.glob('/dev/cu.usbmodem*')
            possible_ports.extend(glob.glob('/dev/cu.usbserial*'))
            
        elif system == "windows":
            possible_ports = [f'COM{i}' for i in range(1, 21)]
        else:
            possible_ports = ['/dev/ttyACM0', '/dev/ttyUSB0']
        
        if possible_ports:
            print(f"Auto-detected possible ports: {possible_ports}")
            return possible_ports[0]
        else:
            fallback_ports = {
                'linux': '/dev/ttyACM0',
                'darwin': '/dev/cu.usbmodem11301',
                'windows': 'COM3'
            }
            return fallback_ports.get(system, '/dev/ttyACM0')
        
    def _connect(self):
        """Establish serial connection"""
        with self.connection_lock:
            if self.is_connected and self.ser and self.ser.is_open:
                return True
                
            # Clean up any existing connection
            if self.ser:
                try:
                    self.ser.close()
                except:
                    pass
                self.ser = None
                
            print(f"Attempting to open serial port {self.port} at baudrate {self.baudrate}...")
            
            try:
                self.ser = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=0.5,
                    write_timeout=2.0,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False
                )
                
                # Wait for port to stabilize
                time.sleep(0.2)
                
                # Clear buffers
                if self.ser.is_open:
                    for _ in range(3):
                        self.ser.reset_input_buffer()
                        self.ser.reset_output_buffer()
                        time.sleep(0.1)
                    
                current_time = time.time()
                self.is_connected = True
                self.connection_attempts = 0
                self.last_successful_read = current_time
                self.last_any_activity = current_time
                self.connection_established_time = current_time
                self.line_buffer = ""
                
                # Update stats
                self.connection_stats['connection_uptime_start'] = current_time
                if self.connection_stats['total_reconnects'] > 0:
                    self.connection_stats['total_reconnects'] += 1
                
                print(f"Serial port opened successfully: {self.ser}")
                return True
                
            except Exception as e:
                print(f"Failed to open serial port {self.port}: {e}")
                self.is_connected = False
                self.connection_attempts += 1
                self.connection_stats['total_errors'] += 1
                if self.ser:
                    try:
                        self.ser.close()
                    except:
                        pass
                    self.ser = None
                return False
    
    def start_receiver(self):
        """Start the receiver thread to process incoming data"""
        if self.running:
            print("Receiver thread already running")
            return
            
        print("Starting receiver thread...")
        self.running = True
        self.rx_thread = threading.Thread(target=self._receiver_thread, name="SeismicReceiver")
        self.rx_thread.daemon = True
        self.rx_thread.start()
        print("Receiver thread started")
        
    def stop_receiver(self):
        """Stop the receiver thread"""
        if self.running:
            print("Stopping receiver thread...")
            self.running = False
            if self.rx_thread:
                self.rx_thread.join(timeout=3.0)
                if self.rx_thread.is_alive():
                    print("Warning: Receiver thread did not stop cleanly")
            print("Receiver thread stopped")
            
    def _receiver_thread(self):
        """Enhanced receiver thread"""
        while self.running:
            try:
                current_time = time.time()
                
                # Check connection health
                if not self._is_connection_healthy():
                    if not self._reconnect():
                        time.sleep(1.0)
                        continue
                
                with self.connection_lock:
                    if not self.ser or not self.ser.is_open:
                        time.sleep(0.1)
                        continue
                    
                    try:
                        # Check if data is available
                        bytes_waiting = self.ser.in_waiting
                        
                        if bytes_waiting > 0:
                            # Read available data
                            data = self.ser.read(bytes_waiting)
                            if data:
                                self.last_successful_read = current_time
                                self.last_any_activity = current_time
                                self._process_raw_data(data)
                            else:
                                time.sleep(0.01)
                        else:
                            # No data available
                            self.last_any_activity = current_time
                            time.sleep(0.01)
                            
                    except (OSError, serial.SerialException) as e:
                        print(f"Serial communication error: {e}")
                        self.is_connected = False
                        time.sleep(0.5)
                        continue
                        
            except Exception as e:
                print(f"Receiver thread error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.5)

    def _is_connection_healthy(self):
        """Connection health check"""
        with self.connection_lock:
            if not self.is_connected or not self.ser or not self.ser.is_open:
                return False
            
            current_time = time.time()
            
            # If connection was just established, give it time to stabilize
            if (self.connection_established_time and 
                current_time - self.connection_established_time < 5.0):
                return True
            
            # Check for timeout
            timeout = self.read_timeout_threshold
            if current_time - self.last_any_activity > timeout:
                print(f"Connection health check failed: "
                      f"Last activity {current_time - self.last_any_activity:.1f}s ago")
                return False
                
            return True
    
    def _reconnect(self):
        """Reconnection with exponential backoff"""
        if self.connection_attempts >= self.max_connection_attempts:
            print(f"Max reconnection attempts ({self.max_connection_attempts}) reached")
            return False
            
        print(f"Attempting reconnection (attempt {self.connection_attempts + 1}/{self.max_connection_attempts})...")
        
        self.is_connected = False
        delay = min(self.reconnect_delay * (2 ** self.connection_attempts), 10.0)
        print(f"Waiting {delay:.1f}s before reconnection...")
        time.sleep(delay)
        
        self.connection_stats['total_reconnects'] += 1
        return self._connect()

    def _process_raw_data(self, data):
        """Process raw bytes into lines"""
        try:
            text = data.decode('ascii', errors='replace')
            self.line_buffer += text
            
            lines_processed = 0
            while '\n' in self.line_buffer and lines_processed < 100:
                line, self.line_buffer = self.line_buffer.split('\n', 1)
                line = line.strip()
                if line:
                    self._process_line(line)
                    lines_processed += 1
                    
            # Prevent buffer from growing too large
            if len(self.line_buffer) > 10000:
                print("Warning: Line buffer too large, clearing")
                self.line_buffer = ""
                    
        except Exception as e:
            print(f"Error processing raw data: {e}")
            self.line_buffer = ""
            self.connection_stats['total_errors'] += 1

    def _process_line(self, line):
        """Process received data line"""
        self.last_any_activity = time.time()
        
        # Skip corrupted lines
        if len(line) < 3 or line.count('\x00') > 0:
            return
        
        # Check if it's a command/status line (accept a broader set of prefixes)
        if ":" in line:
            prefix, data = line.split(":", 1)
            prefix = prefix.strip()
            data = data.strip()
            
            if prefix == "STATUS":
                self._handle_status_message(data)
                    
            elif prefix == "ERROR":
                print(f"MCU Error: {data}")
                self.command_response = (False, data)
                self.command_event.set()
                
                if self.error_callback:
                    self.error_callback(data)
                    
            elif prefix == "OK":
                print(f"MCU OK: {data}")
                
                # Special handling for streaming commands
                if "Streaming started" in data:
                    self.streaming = True
                    self._reset_sample_tracking()
                elif "Streaming stopped" in data:
                    self.streaming = False
                elif "filter" in data.lower() or "sinc" in data.lower():
                    # Handle filter-related OK responses
                    print(f"✅ Filter command acknowledged: {data}")
                
                self.command_response = (True, data)
                self.command_event.set()
                
            elif prefix == "READY":
                print(f"MCU Ready: {data}")
                self.streaming = False
                
            elif prefix == "TIMING":
                # Response to GET_TIMING_STATUS
                print(f"MCU Timing: {data}")
                # Deliver as command response for callers waiting on GET_TIMING_STATUS
                self.command_response = (True, data)
                self.command_event.set()
            elif prefix == "DEBUG":
                print(f"MCU Debug: {data}")
            elif prefix == "FILTER":
                # Handle filter response from MCU (simple, like other responses)
                print(f"MCU Filter: {data}")
                # Set command response for callers waiting on filter commands
                self.command_response = (True, f"FILTER:{data}")
                self.command_event.set()
            else:
                # Unknown prefix -> treat as data
                self._process_data_line(line)
        else:
            # No colon present -> data line
            self._process_data_line(line)
    
    def _handle_status_message(self, data):
        """Handle STATUS messages from MCU"""
        status = {}
        try:
            for item in data.split(","):
                if "=" in item:
                    key, value = item.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    try:
                        if "." in value:
                            status[key] = float(value)
                        else:
                            status[key] = int(value)
                    except ValueError:
                        status[key] = value
            
            # Update streaming state based on device report
            if 'streaming' in status:
                self.streaming = status['streaming'] == 1
            
            if self.status_callback:
                self.status_callback(status)
                
        except Exception as e:
            print(f"Error parsing status line: {data} - {e}")
    
    def _reset_sample_tracking(self):
        """Reset sample tracking when streaming starts"""
        current_time = time.time()
        self.sample_tracking.update({
            'stream_start_time': current_time,
            'stream_start_sequence': None,
            'last_sequence': None,
            'sequence_gaps': 0,
            'sample_count': 0
        })
        self.sample_tracking['sample_buffer'].clear()
        
        # UPDATED: Reset timestamp generator
        print("Sample tracking reset for new stream. Timestamp generator maintains its primed start time.")
    
    def _process_data_line(self, line):
        """Process enhanced data lines from MCU (sequence,mcu_micros,timing_source,accuracy_us,value1,value2,value3)"""
        try:
            parts = line.split(",")
            if len(parts) >= 6:  # sequence,mcu_micros,timing_source,accuracy_us,value1[,value2,value3]
                sequence = int(parts[0].strip())
                mcu_micros = int(parts[1].strip())
                timing_source = int(parts[2].strip())
                accuracy_us = float(parts[3].strip())
                values = [int(parts[i].strip()) for i in range(4, len(parts))]
                
                # CRITICAL FIX: Global wraparound detection in data pipeline
                if hasattr(self, '_last_processed_sequence') and self._last_processed_sequence is not None:
                    if self._last_processed_sequence == 65535 and sequence == 0:
                        print(f"🚨 GLOBAL WRAPAROUND DETECTION IN DATA PIPELINE: {self._last_processed_sequence} -> {sequence}")
                        print(f"   Forcing timestamp generator recovery to prevent data loss")
                        
                        # Force wraparound recovery in timestamp generator
                        if hasattr(self.timing_adapter, 'timestamp_generator'):
                            self.timing_adapter.timestamp_generator.force_wraparound_recovery(sequence)
                            print(f"   Timestamp generator recovery completed")
                
                self._last_processed_sequence = sequence
                
                # CRITICAL: Generate host timestamp using UNIFIED timing system ONLY
                host_timestamp = self.timing_adapter.generate_timestamp(sequence)
                
                # VERIFY: Timestamp is quantized (should end with 0 for proper quantization)
                quantization_ms = getattr(self.timing_adapter.timestamp_generator, 'quantization_ms', 10)
                if host_timestamp % quantization_ms != 0:
                    print(f"🚨 WARNING: Non-quantized timestamp detected: {host_timestamp}ms (ends with {host_timestamp % quantization_ms})")
                    print(f"   This indicates a timestamp generation bypass!")
                    print(f"   Expected: All timestamps should end with 0")
                    print(f"   Sequence: {sequence}")
                
                # Analyze MCU timing quality
                self._analyze_mcu_timing_quality(sequence, mcu_micros, timing_source, accuracy_us)
                
                # Update stats
                self.connection_stats['data_packets_received'] += 1
                self.connection_stats['last_data_time'] = time.time()
                self.sample_tracking['sample_count'] += 1
                
                # Track sequence for gap detection
                if self.sample_tracking['last_sequence'] is not None:
                    expected_sequence = (self.sample_tracking['last_sequence'] + 1) % 65536
                    if sequence != expected_sequence:
                        gap = self._calculate_sequence_gap(self.sample_tracking['last_sequence'], sequence)
                        self.sample_tracking['sequence_gaps'] += gap
                        print(f"Sequence gap detected: expected {expected_sequence}, got {sequence} (gap: {gap})")
                
                self.sample_tracking['last_sequence'] = sequence
                
                # Store enhanced sample for timing analysis
                timing_info = {
                    'mcu_micros': mcu_micros,
                    'timing_source': timing_source,
                    'accuracy_us': accuracy_us,
                    'source_name': self._get_timing_source_name(timing_source)
                }
                
                sample_info = {
                    'sequence': sequence,
                    'timestamp': host_timestamp,
                    'arrival_time': time.time(),
                    'values': values,
                    'timing_info': timing_info
                }
                self.sample_tracking['sample_buffer'].append(sample_info)
                
                # Call data callback with enhanced timing info
                if self.data_callback:
                    self.data_callback(host_timestamp, sequence, values, timing_info)
            else:
                # Fallback to simple format for backward compatibility
                if len(parts) >= 2:  # At least sequence and one value
                    sequence = int(parts[0].strip())
                    values = [int(parts[i].strip()) for i in range(1, len(parts))]
                    
                    # CRITICAL FIX: Global wraparound detection in fallback data pipeline
                    if hasattr(self, '_last_processed_sequence') and self._last_processed_sequence is not None:
                        if self._last_processed_sequence == 65535 and sequence == 0:
                            print(f"🚨 GLOBAL WRAPAROUND DETECTION IN FALLBACK PIPELINE: {self._last_processed_sequence} -> {sequence}")
                            print(f"   Forcing timestamp generator recovery to prevent data loss")
                            
                            # Force wraparound recovery in timestamp generator
                            if hasattr(self.timing_adapter, 'timestamp_generator'):
                                self.timing_adapter.timestamp_generator.force_wraparound_recovery(sequence)
                                print(f"   Timestamp generator recovery completed")
                    
                    self._last_processed_sequence = sequence
                    
                    # CRITICAL: Generate host timestamp using UNIFIED timing system ONLY
                    host_timestamp = self.timing_adapter.generate_timestamp(sequence)
                    
                    # VERIFY: Timestamp is quantized (should end with 0 for proper quantization)
                    quantization_ms = getattr(self.timing_adapter.timestamp_generator, 'quantization_ms', 10)
                    if host_timestamp % quantization_ms != 0:
                        print(f"🚨 WARNING: Non-quantized timestamp detected: {host_timestamp}ms (ends with {host_timestamp % quantization_ms})")
                        print(f"   This indicates a timestamp generation bypass!")
                        print(f"   Expected: All timestamps should end with 0")
                        print(f"   Sequence: {sequence}")
                    
                    # Update stats
                    self.connection_stats['data_packets_received'] += 1
                    self.connection_stats['last_data_time'] = time.time()
                    self.sample_tracking['sample_count'] += 1
                    
                    # Track sequence for gap detection
                    if self.sample_tracking['last_sequence'] is not None:
                        expected_sequence = (self.sample_tracking['last_sequence'] + 1) % 65536
                        if sequence != expected_sequence:
                            gap = self._calculate_sequence_gap(self.sample_tracking['last_sequence'], sequence)
                            self.sample_tracking['sequence_gaps'] += gap
                            print(f"Sequence gap detected: expected {expected_sequence}, got {sequence} (gap: {gap})")
                    
                    self.sample_tracking['last_sequence'] = sequence
                    
                    # Store sample for timing analysis
                    sample_info = {
                        'sequence': sequence,
                        'timestamp': host_timestamp,
                        'arrival_time': time.time(),
                        'values': values
                    }
                    self.sample_tracking['sample_buffer'].append(sample_info)
                    
                    # Call data callback (legacy format)
                    if self.data_callback:
                        self.data_callback(host_timestamp, sequence, values)
                    
        except Exception as e:
            print(f"Error parsing enhanced data line: {line} - {e}")
            self.connection_stats['total_errors'] += 1

    def _get_timing_source_name(self, source):
        """Get human-readable timing source name"""
        sources = {
            0: "PPS_ACTIVE",      # GPS PPS working (±1μs)
            1: "PPS_HOLDOVER",    # Recent PPS, using prediction (±10μs)
            2: "INTERNAL_CAL",    # Internal osc with PPS calibration (±100μs)
            3: "INTERNAL_RAW"     # Raw internal (±1ms, emergency)
        }
        return sources.get(source, "UNKNOWN")

    def _analyze_mcu_timing_quality(self, sequence, mcu_micros, timing_source, accuracy_us):
        """Monitor MCU timing quality and alert on changes/degradation"""
        
        # Track timing source changes
        if not hasattr(self, 'last_timing_source'):
            self.last_timing_source = timing_source
            self.last_accuracy_us = accuracy_us
        
        if timing_source != self.last_timing_source:
            source_name = self._get_timing_source_name(timing_source)
            print(f"🔄 MCU timing source changed to {source_name} (±{accuracy_us:.1f}μs)")
            self.last_timing_source = timing_source
        
        # Alert on significant accuracy degradation
        if accuracy_us > 100 and self.last_accuracy_us <= 100:  # Crossed 100μs threshold
            print(f"⚠️  MCU timing accuracy degraded: ±{accuracy_us:.1f}μs")
        elif accuracy_us <= 10 and self.last_accuracy_us > 10:  # Improved to scientific grade
            source_name = self._get_timing_source_name(timing_source)
            print(f"✅ MCU timing improved to scientific grade: {source_name} ±{accuracy_us:.1f}μs")
        
        self.last_accuracy_us = accuracy_us
        
        # Store for adaptive controller and monitoring
        self.mcu_timing_quality = {
            'timing_source': timing_source,
            'source_name': self._get_timing_source_name(timing_source),
            'accuracy_us': accuracy_us,
            'pps_available': timing_source <= 1,  # PPS_ACTIVE or PPS_HOLDOVER
            'scientific_grade': accuracy_us < 10,   # < 10μs = scientific grade
            'target_grade': accuracy_us <= 100,     # ≤ 100μs = target grade
            'last_update': time.time()
        }
        
        # Analyze MCU timing vs expected intervals
        if hasattr(self, 'last_mcu_timing') and self.last_mcu_timing:
            # Calculate actual MCU interval
            mcu_interval_us = mcu_micros - self.last_mcu_timing['micros']
            expected_interval_us = self.timestamp_generator.expected_interval * 1e6  # Convert to microseconds
            
            # Handle micros() wraparound (32-bit, wraps every ~71 minutes)
            if mcu_interval_us < 0:
                mcu_interval_us += 4294967296  # 2^32
            
            timing_error_us = mcu_interval_us - expected_interval_us
            
            # Only analyze if interval seems reasonable (avoid startup artifacts)
            if 5000 < mcu_interval_us < 50000:  # Between 5ms and 50ms
                # Store MCU timing statistics
                if not hasattr(self, 'mcu_timing_stats'):
                    self.mcu_timing_stats = {
                        'intervals': deque(maxlen=100),
                        'errors': deque(maxlen=100),
                        'last_analysis': 0
                    }
                
                self.mcu_timing_stats['intervals'].append(mcu_interval_us)
                self.mcu_timing_stats['errors'].append(timing_error_us)
                
                # Periodic analysis and reporting
                current_time = time.time()
                if current_time - self.mcu_timing_stats.get('last_analysis', 0) > 30:  # Every 30 seconds
                    self._report_mcu_timing_analysis()
                    self.mcu_timing_stats['last_analysis'] = current_time
        
        # Store current timing for next comparison
        self.last_mcu_timing = {
            'sequence': sequence,
            'micros': mcu_micros,
            'timing_source': timing_source,
            'accuracy_us': accuracy_us
        }

    def _report_mcu_timing_analysis(self):
        """Report MCU timing analysis"""
        if not hasattr(self, 'mcu_timing_stats') or len(self.mcu_timing_stats['intervals']) < 10:
            return
        
        try:
            import statistics
            
            intervals = list(self.mcu_timing_stats['intervals'])
            errors = list(self.mcu_timing_stats['errors'])
            
            avg_interval = statistics.mean(intervals)
            std_interval = statistics.stdev(intervals) if len(intervals) > 1 else 0
            avg_error = statistics.mean(errors)
            max_error = max([abs(e) for e in errors])
            
            expected_interval_us = self.timestamp_generator.expected_interval * 1e6
            drift_ppm = (avg_error / expected_interval_us) * 1e6
            
            print(f"📊 MCU TIMING ANALYSIS (last {len(intervals)} samples):")
            print(f"   Interval: {avg_interval:.1f}±{std_interval:.1f}μs (expected: {expected_interval_us:.1f}μs)")
            print(f"   Error: avg={avg_error:+.1f}μs, max=±{max_error:.1f}μs, drift={drift_ppm:+.1f}ppm")
            print(f"   Source: {self.mcu_timing_quality.get('source_name', 'Unknown')} (±{self.mcu_timing_quality.get('accuracy_us', 0):.1f}μs)")
            
        except Exception as e:
            print(f"Error in MCU timing analysis: {e}")
    
    def _calculate_sequence_gap(self, last_seq, current_seq):
        """Calculate gap in 16-bit sequence numbers (consistent with RobustTimestampGenerator)"""
        if current_seq >= last_seq:
            gap = current_seq - last_seq - 1
        else:
            # Handle wraparound - use same logic as RobustTimestampGenerator
            forward_diff = (65536 - last_seq) + current_seq
            gap = forward_diff - 1  # Gap is difference minus 1 (expected progression)
        
        print(f"DEBUG: Gap calculation - last: {last_seq}, current: {current_seq}, gap: {gap}")
        return max(0, gap)  # Don't return negative gaps
    
    def _send_command(self, cmd, wait_response=True, timeout=10.0):
        """Send a command to the device"""
        if not self.is_connected:
            if not self._reconnect():
                return (False, "No connection to device")
        
        with self.lock:
            self.command_response = None
            self.command_event.clear()
            
            if ":" not in cmd:
                cmd = f"{cmd}:"
            
            print(f"Sending command: {cmd}")
            try:
                with self.connection_lock:
                    if self.ser and self.ser.is_open:
                        cmd_bytes = f"{cmd}\n".encode('ascii')
                        self.ser.write(cmd_bytes)
                        self.ser.flush()
                        self.last_any_activity = time.time()
                    else:
                        return (False, "Serial port not open")
            except (OSError, serial.SerialException) as e:
                print(f"Error sending command: {e}")
                self.is_connected = False
                self.connection_stats['total_errors'] += 1
                return (False, f"Communication error: {e}")
        
        if wait_response:
            if self.command_event.wait(timeout):
                return self.command_response
            else:
                print(f"Timeout waiting for response to command: {cmd}")
                return (False, "Timeout waiting for response")
        return (True, "Command sent")
    
    # Device control methods
    def set_adc_rate(self, rate_index):
        """Set ADC sample rate (1-16)"""
        if rate_index < 1 or rate_index > 16:
            raise ValueError("Rate index must be between 1 and 16")
            
        result = self._send_command(f"SET_ADC_RATE:{rate_index}")
        if result and not result[0]:
            raise RuntimeError(f"Failed to set ADC rate: {result[1]}")
        return result
        
    def set_gain(self, gain_index):
        """Set ADC gain (1-6)"""
        if gain_index < 1 or gain_index > 6:
            raise ValueError("Gain index must be between 1 and 6")
            
        result = self._send_command(f"SET_GAIN:{gain_index}")
        if result and not result[0]:
            raise RuntimeError(f"Failed to set gain: {result[1]}")
        return result
        
    def set_channels(self, num_channels):
        """Set number of channels (1-3)"""
        if num_channels < 1 or num_channels > 3:
            raise ValueError("Number of channels must be between 1 and 3")
            
        result = self._send_command(f"SET_CHANNELS:{num_channels}")
        if result and not result[0]:
            raise RuntimeError(f"Failed to set channels: {result[1]}")
        return result
        
    def set_filter(self, filter_index):
        """Set ADC digital filter (1-5)"""
        if filter_index < 1 or filter_index > 5:
            raise ValueError("Filter index must be between 1 and 5")
            
        result = self._send_command(f"SET_FILTER:{filter_index}")
        if result and not result[0]:
            raise RuntimeError(f"Failed to set filter: {result[1]}")
        
        # Update cached value on success
        if result and result[0]:
            # Parse the response to get filter name
            try:
                if ':' in result[1]:
                    filter_name = result[1].split(':', 1)[1].strip()
                    self.current_filter = (filter_index, filter_name)
                else:
                    self.current_filter = (filter_index, f"Filter_{filter_index}")
            except Exception as e:
                print(f"Warning: Could not parse filter response: {e}")
                self.current_filter = (filter_index, f"Filter_{filter_index}")
        
        return result
        
    def set_dithering(self, dithering):
        """Set dithering/oversampling (0=off, 2=2x, 3=3x, 4=4x)"""
        if dithering not in [0, 2, 3, 4]:
            raise ValueError("Dithering must be 0 (off), 2, 3, or 4")
            
        result = self._send_command(f"SET_DITHERING:{dithering}")
        if result and not result[0]:
            raise RuntimeError(f"Failed to set dithering: {result[1]}")
        
        # Update cached value on success
        if result and result[0]:
            self.current_dithering = dithering
            
        return result
        
    def get_dithering(self):
        """Get current dithering setting"""
        result = self._send_command("GET_DITHERING")
        if result and result[0]:
            return result[1]  # Return the raw response, let the caller parse it
        return None
        
    def get_filter(self):
        """Get current ADC filter setting"""
        result = self._send_command("GET_FILTER")
        if result and result[0]:
            return result[1]  # Return the raw response, let the caller parse it
        return None
    
    def get_current_filter(self):
        """Get the currently cached filter setting without querying the device"""
        return self.current_filter
        
    def get_current_dithering(self):
        """Get the currently cached dithering setting without querying the device"""
        return self.current_dithering
        
    def start_streaming(self, rate=None):
        """Start continuous data streaming with synchronized start (with fallback)"""
        if self.streaming:
            print("Already streaming, ignoring start request")
            return (True, "Already streaming")
        
        # Update timestamp generator rate
        actual_rate = rate if rate else 100.0
        self.timestamp_generator.update_rate(actual_rate)
        
        # Decide best start method: PPS-locked if both host and MCU report PPS available; otherwise time-sync
        mcu_pps_available = False
        try:
            timing = self._get_mcu_timing_status()
            if timing and isinstance(timing, dict):
                mcu_pps_available = bool(int(timing.get('pps_valid', 0)))
        except Exception as e:
            print(f"WARN: Unable to query MCU timing status: {e}")

        # Check host timing status through unified manager
        timing_status = self.timing_manager.get_status()
        host_pps_available = timing_status['reference_source'] == 'GPS+PPS'

        # If PPS is present on both sides, prefer PPS-locked start
        if mcu_pps_available and host_pps_available:
            pps_wait = 2  # wait for 2 edges for safety
            rate_to_use = int(rate) if rate is not None else 100
            if rate is not None:
                if rate < 1 or rate > 1000:
                    raise ValueError("Streaming rate must be between 1 and 1000 Hz")
                self.sample_tracking['expected_rate'] = rate
                self.timestamp_generator.update_rate(rate)
            else:
                self.sample_tracking['expected_rate'] = 100
                self.timestamp_generator.update_rate(100.0)

            now = time.time()
            start_time = math.ceil(now) + pps_wait
            # Note: Simplified timestamp generator doesn't need priming
            # The unified timing system handles synchronization

            cmd = f"START_STREAM_PPS:{rate_to_use},{pps_wait}"
            print(f"PPS START: MCU+HOST PPS available. Command: {cmd}, start @ {start_time:.6f}")
            result = self._send_command(cmd, timeout=5.0)

            if not result or not result[0]:
                print(f"PPS START: Failed ({result[1] if result else 'timeout'}), falling back to time sync")
            else:
                print("PPS START: Armed for PPS-locked start")
                self.streaming = True
                self.pps_started = True
                # Wait for PPS start time
                wait_time = start_time - time.time()
                if wait_time > 0:
                    print(f"PPS START: Waiting {wait_time:.3f}s for PPS start...")
                    time.sleep(wait_time)
                
                # Start unified timing control after streaming starts
                if hasattr(self, 'timing_adapter'):
                    self.timing_adapter.start_control()
                    
                return result

        # Fallback: Time-based synchronized start at next +2s
        current_time = time.time()
        start_time = math.floor(current_time) + 2.0
        delay_ms = int((start_time - current_time) * 1000)
        print(f"SYNC START: Current time: {current_time:.6f}")
        print(f"SYNC START: Scheduled start time: {start_time:.6f}")
        print(f"SYNC START: Delay: {delay_ms}ms")

        # Note: Simplified timestamp generator doesn't need priming
        # The unified timing system handles synchronization
        self.pps_started = False

        cmd = "START_STREAM_SYNC"
        if rate is not None:
            if rate < 1 or rate > 1000:
                raise ValueError("Streaming rate must be between 1 and 1000 Hz")
            cmd += f":{rate},{delay_ms}"
            self.sample_tracking['expected_rate'] = rate
            self.timestamp_generator.update_rate(rate)
        else:
            cmd += f":100,{delay_ms}"

        print(f"SYNC: Trying synchronized start command: {cmd}")
        result = self._send_command(cmd, timeout=5.0)

        if not result or not result[0]:
            print(f"SYNC: Synchronized start failed ({result[1] if result else 'timeout'})")
            print("FALLBACK: Using legacy START_STREAM command")
            wait_time = (start_time - time.time())
            if wait_time > 0:
                print(f"FALLBACK: Waiting {wait_time:.3f} seconds for synchronized timing...")
                time.sleep(wait_time)
            legacy_cmd = "START_STREAM"
            if rate is not None:
                legacy_cmd += f":{rate}"
            else:
                legacy_cmd += ":100"
            print(f"FALLBACK: Sending legacy command: {legacy_cmd}")
            result = self._send_command(legacy_cmd, timeout=15.0)
            if result and result[0]:
                print("FALLBACK: Legacy streaming started successfully!")
                print("⚠️  NOTE: Update MCU firmware for full synchronized start support")
                self.streaming = True
                self._reset_sample_tracking()
            else:
                print(f"FALLBACK: Legacy streaming also failed: {result}")
                return result
        else:
            print("SYNC: Synchronized streaming started successfully!")
            self.streaming = True
            # The 'OK' handler will call _reset_sample_tracking
            wait_time = (start_time - time.time())
            if wait_time > 0:
                print(f"SYNC: Waiting {wait_time:.3f} seconds for synchronized start...")
                time.sleep(wait_time)
                print(f"SYNC: Synchronized sampling should now be active!")
            else:
                print(f"WARNING: Synchronized start time has already passed")
        
        # Start unified timing control after streaming starts
        if hasattr(self, 'timing_adapter'):
            self.timing_adapter.start_control()
            
        return result
        
    def stop_streaming(self):
        """Stop continuous data streaming"""
        if not self.streaming:
            print("Not streaming, ignoring stop request")
            return (True, "Not streaming")
        
        # Stop timing control first
        if hasattr(self, 'timing_adapter'):
            self.timing_adapter.stop_control()
            
        result = self._send_command("STOP_STREAM", timeout=10.0)
        if result and result[0]:
            self.streaming = False
            
        time.sleep(0.5)
        return result
        
    def get_status(self):
        """Request system status"""
        return self._send_command("GET_STATUS", timeout=5.0)
    
    def get_device_status(self):
        """Get comprehensive device status including filter, timing, and connection info"""
        status = {
            'connection': self.get_connection_stats(),
            'sample_tracking': self.get_sample_stats(),
            'timing_health': self.get_timestamp_health(),
            'filter': self.get_current_filter(),
            'dithering': self.get_current_dithering(),
            'streaming': self.streaming,
            'is_connected': self.is_connected
        }
        
        # Add MCU timing status if available
        try:
            mcu_timing = self._get_mcu_timing_status()
            if mcu_timing:
                status['mcu_timing'] = mcu_timing
        except Exception as e:
            status['mcu_timing'] = {'error': str(e)}
        
        return status

    def _get_mcu_timing_status(self):
        """Request timing status and return parsed dict (pps_valid, etc.)"""
        resp = self._send_command("GET_TIMING_STATUS", timeout=5.0)
        if not resp or not resp[0]:
            return None
        data = resp[1]
        status = {}
        try:
            # data like: source=...,accuracy_us=...,pps_valid=1,pps_count=...,calibration_ppm=...
            for item in data.split(','):
                if '=' in item:
                    key, value = item.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Keep both numeric and string
                    try:
                        if '.' in value:
                            status[key] = float(value)
                        else:
                            status[key] = int(value)
                    except ValueError:
                        status[key] = value
        except Exception as e:
            print(f"Error parsing TIMING status: {e}")
            return None
        return status
        
    def reset_device(self):
        """Reset the device"""
        if self.streaming:
            self.stop_streaming()
            
        result = self._send_command("RESET", timeout=15.0)
        if result and result[0]:
            self.streaming = False
        return result
        
    # Callback registration
    def register_data_callback(self, callback):
        """Register callback for sample data"""
        self.data_callback = callback
        
    def register_error_callback(self, callback):
        """Register callback for errors"""
        self.error_callback = callback
        
    def register_status_callback(self, callback):
        """Register callback for status updates"""
        self.status_callback = callback
        
    def get_connection_stats(self):
        """Get connection statistics"""
        stats_copy = dict(self.connection_stats)
        if stats_copy['connection_uptime_start']:
            stats_copy['uptime_seconds'] = time.time() - stats_copy['connection_uptime_start']
        return stats_copy
    
    def get_sample_stats(self):
        """Get sample tracking statistics including timestamp generator stats"""
        sample_stats = dict(self.sample_tracking)
        
        # Remove non-serializable objects
        if 'sample_buffer' in sample_stats:
            sample_stats['sample_buffer_length'] = len(sample_stats['sample_buffer'])
            del sample_stats['sample_buffer']
        
        # UPDATED: Add timestamp generator statistics
        sample_stats['timestamp_generator'] = self.timestamp_generator.get_stats()
        
        # Add unified timing system statistics
        if hasattr(self, 'timing_adapter'):
            sample_stats['unified_timing'] = self.timing_adapter.get_timing_info()
        
        return sample_stats
    
    def get_timestamp_health(self):
        """Get timestamp generator health assessment"""
        health_data = {
            'generator_stats': self.timestamp_generator.get_stats()
        }
        
        # Add unified timing system health data
        if hasattr(self, 'timing_adapter'):
            timing_status = self.timing_adapter.get_timing_info()
            health_data.update({
                'unified_timing_status': timing_status,
                'reference_source': timing_status.get('reference_source', 'Unknown'),
                'reference_accuracy_us': timing_status.get('reference_accuracy_us', 1000000)
            })
            
            # Add controller stats if available
            if self.timing_adapter.unified_controller:
                health_data['controller_stats'] = self.timing_adapter.unified_controller.get_stats()
        
        return health_data
        
    def close(self):
        """Close the serial connection"""
        print("Closing HostTimingSeismicAcquisition connection...")
        
        if self.streaming:
            try:
                self.stop_streaming()
                time.sleep(0.5)
            except:
                pass
            
        self.stop_receiver()
        
        with self.connection_lock:
            self.is_connected = False
            if hasattr(self, 'ser') and self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                    print("Serial port closed")
                except:
                    pass
                self.ser = None


class HostTimingManager:
    """DEPRECATED: Manages high-precision timing on the host side with advanced PLL and Kalman filtering
    This class is deprecated and replaced by UnifiedTimingManager in timing_fix.py
    It remains here for compatibility but should not be used for new code."""
    
    def __init__(self):
        self.timing_source = "Unknown"
        self.timing_accuracy_us = 0
        self.pps_available = False
        self.ntp_synced = False
        self.last_timing_check = 0
        self.timing_quality = {
            'source': 'HOST',
            'accuracy_us': 1000,  # Default 1ms accuracy
            'offset_us': 0,
            'last_update': None
        }
        
        # Advanced PLL with Kalman filter for superior accuracy
        self.pll_enabled = True
        self.pll_correction_ms = 0.0
        self.pll_last_update = 0.0
        self.pll_update_interval_s = 0.5  # Update every 500ms for faster response
        
        # Kalman filter state for robust estimation - AGGRESSIVE TUNING
        self.kalman_state = {
            'offset_ms': 0.0,      # Current offset estimate
            'drift_rate_ppm': 0.0,  # Current drift rate estimate
            'offset_variance': 25.0,     # Reduced uncertainty for faster response
            'drift_variance': 0.25,      # Reduced uncertainty for faster convergence
            'process_noise_offset': 0.1,     # Increased process noise for faster adaptation
            'process_noise_drift': 0.01,     # Increased drift noise for faster learning
            'measurement_noise': 0.5,        # Reduced measurement noise (trust measurements more)
            'last_prediction_time': 0.0
        }
        
        # STABLE rate control with smooth corrections
        self.rate_adjustment_ppm = 0.0
        self.rate_prediction_ppm = 0.0  # Predictive component
        self.rate_update_interval_s = 5.0  # Update every 5s for stability
        self._last_rate_update = 0.0
        
        # STABLE drift management with gentle corrections
        self.emergency_drift_threshold_ms = 100.0  # Emergency only for very large drift
        self.large_drift_threshold_ms = 30.0       # Large correction threshold
        self.deadband_threshold_ms = 2.0           # No correction if error < 2ms
        self.last_emergency_reset = 0.0
        
        # Conservative rate limiting for stability
        self.max_rate_change_ppm_per_update = 20.0  # Moderate rate changes
        self.correction_smoothing_factor = 0.1      # Heavy smoothing for stability
        
        # Historical data for trend analysis
        self.offset_history = deque(maxlen=100)  # Last 100 measurements
        self.drift_history = deque(maxlen=50)    # Last 50 drift estimates
        
        # Performance monitoring
        self.performance_stats = {
            'corrections_applied': 0,
            'kalman_updates': 0,
            'prediction_accuracy': 0.0,
            'rms_error_ms': 0.0,
            'max_correction_ppm': 0.0
        }
        
        # Check initial timing status
        self.update_timing_status()
    
    def update_timing_status(self):
        """Update timing status from system"""
        current_time = time.time()
        
        # Only check periodically
        if current_time - self.last_timing_check < 10:
            return
            
        self.last_timing_check = current_time
        
        # Check chrony status for precise timing
        chrony_status = self._get_chrony_status()
        if chrony_status:
            self.timing_quality.update(chrony_status)
            self.ntp_synced = True
        else:
            # Fallback to system time
            self.timing_quality.update({
                'source': 'HOST',
                'accuracy_us': 10000,  # 10ms for system time
                'offset_us': 0
            })
            self.ntp_synced = False
    
    def _get_chrony_status(self):
        """Get chrony timing status"""
        try:
            result = subprocess.run(['chronyc', 'tracking'], 
                                  capture_output=True, text=True, timeout=2)
            
            if result.returncode == 0 and result.stdout:
                status = {'source': 'NTP', 'accuracy_us': 10000}
                
                for line in result.stdout.split('\n'):
                    if 'System time' in line:
                        # Example: "System time     : 0.000003123 seconds fast of NTP"
                        parts = line.split(':', 1)[1].strip().split()
                        # Default to unsigned microseconds if parsing fails
                        try:
                            offset_value = float(parts[0])
                        except Exception:
                            offset_value = 0.0
                        unit = parts[1] if len(parts) > 1 else 'seconds'
                        is_fast = any(tok.lower() == 'fast' for tok in parts)
                        is_slow = any(tok.lower() == 'slow' for tok in parts)
                        sign = 1.0 if is_fast else (-1.0 if is_slow else 0.0)
                        # Convert to microseconds with sign
                        if unit in ['second', 'seconds', 'sec', 's']:
                            offset_us = sign * (offset_value * 1e6)
                        elif unit in ['millisecond', 'milliseconds', 'ms']:
                            offset_us = sign * (offset_value * 1e3)
                        elif unit in ['microsecond', 'microseconds', 'us', 'µs']:
                            offset_us = sign * (offset_value)
                        elif unit in ['nanosecond', 'nanoseconds', 'ns']:
                            offset_us = sign * (offset_value / 1e3)
                        else:
                            # Fallback assume seconds
                            offset_us = sign * (offset_value * 1e6)
                        # accuracy_us is magnitude; offset_us keeps sign
                        status['accuracy_us'] = abs(offset_us)
                        status['offset_us'] = offset_us
                    elif 'Reference ID' in line:
                        ref_id = line.split(':')[1].strip()
                        if 'PPS' in ref_id or 'GPS' in ref_id:
                            status['source'] = 'GPS+PPS'
                            self.pps_available = True
                        else:
                            status['source'] = 'NTP'
                            self.pps_available = False
                
                status['last_update'] = datetime.datetime.now().isoformat()
                return status
                
        except Exception as e:
            print(f"Error getting chrony status: {e}")
        
        return None
    
    def get_precise_time(self):
        """Get the most precise time available"""
        self.update_timing_status()
        
        # Return current time with best available precision
        current_time = time.time()
        
        # Apply any known corrections
        if self.timing_quality.get('offset_us', 0) != 0:
            correction = self.timing_quality['offset_us'] / 1e6
            current_time -= correction
        
        return current_time
    
    def apply_timing_correction(self, timestamp_ms):
        """Apply advanced PLL-based correction with Kalman filtering for superior accuracy"""
        try:
            if not self.pll_enabled:
                return timestamp_ms
                
            now = time.time()
            if self.pll_last_update == 0.0:
                self.pll_last_update = now
                self.kalman_state['last_prediction_time'] = now
                return timestamp_ms

            # Compute measurement error (observed offset from precise time)
            precise_now_s = self.get_precise_time()
            ts_s = timestamp_ms / 1000.0
            measured_offset_ms = (ts_s - precise_now_s) * 1000.0
            
            # Store measurement for analysis
            self.offset_history.append({
                'time': now,
                'offset_ms': measured_offset_ms,
                'timestamp': now
            })
            
            # CRITICAL: If measured offset is significantly different from Kalman estimate,
            # boost the Kalman measurement trust to converge faster
            if hasattr(self, 'kalman_state'):
                kalman_offset = self.kalman_state['offset_ms']
                offset_difference = abs(measured_offset_ms - kalman_offset)
                if offset_difference > 20.0:  # Large discrepancy
                    # Temporarily reduce measurement noise to trust the measurement more
                    original_noise = self.kalman_state['measurement_noise']
                    self.kalman_state['measurement_noise'] = original_noise * 0.1  # Trust measurement 10x more
                    print(f"📊 KALMAN BOOST: Large offset discrepancy ({offset_difference:.1f}ms), increasing measurement trust")

            # Update Kalman filter with new measurement
            dt = now - self.pll_last_update
            if dt >= self.pll_update_interval_s:
                self._update_kalman_filter(measured_offset_ms, dt, now)
                self._update_rate_control(now)
                self.pll_last_update = now

            # Apply correction based on Kalman state estimate
            estimated_offset = self.kalman_state['offset_ms']
            
            # STABLE DRIFT MANAGEMENT with deadband control
            abs_offset = abs(estimated_offset)
            
            # Deadband: No correction for small errors to prevent oscillation
            if abs_offset < self.deadband_threshold_ms:
                corrected = timestamp_ms  # No correction in deadband
                
            elif abs_offset > self.emergency_drift_threshold_ms:
                # Emergency: Only for very large drift (>100ms)
                if (now - self.last_emergency_reset) > 60.0:  # At most once per minute
                    print(f"🚨 EMERGENCY DRIFT RESET: offset={estimated_offset:+.1f}ms > {self.emergency_drift_threshold_ms}ms")
                    emergency_correction = estimated_offset * 0.5  # Gentler 50% correction
                    self.last_emergency_reset = now
                    self.performance_stats['corrections_applied'] += 1
                    corrected = timestamp_ms - emergency_correction
                    
                    # Gentle Kalman state reset
                    self.kalman_state['offset_ms'] *= 0.5  # Keep 50% for stability
                    self.kalman_state['offset_variance'] = 50.0  # Moderate uncertainty reset
                    
                    print(f"   Applied gentle emergency correction: {emergency_correction:+.1f}ms")
                else:
                    # Use graduated correction
                    graduated_correction = min(abs_offset * 0.2, 20.0) * (1 if estimated_offset > 0 else -1)
                    corrected = timestamp_ms - graduated_correction
                    
            elif abs_offset > self.large_drift_threshold_ms:
                # Large drift - graduated correction (30ms threshold)
                offset_std = math.sqrt(self.kalman_state['offset_variance'])
                max_correction = min(25.0, max(10.0, 2 * offset_std))  # Reduced limits
                limited_correction = max(-max_correction, min(max_correction, estimated_offset * 0.3))  # Only 30% correction
                corrected = timestamp_ms - limited_correction
                
                if abs(limited_correction) > 8.0:  # Only log significant corrections
                    print(f"⚡ GRADUATED CORRECTION: {limited_correction:+.1f}ms (offset: {estimated_offset:+.1f}ms)")
                
            else:
                # Normal operation - gentle adaptive correction
                offset_std = math.sqrt(self.kalman_state['offset_variance'])
                max_correction = min(15.0, max(3.0, 2 * offset_std))  # Conservative limits
                # Apply only 20% of error for smooth convergence
                gentle_correction = estimated_offset * 0.2
                limited_correction = max(-max_correction, min(max_correction, gentle_correction))
                corrected = timestamp_ms - limited_correction
            
            # Update performance statistics
            if len(self.offset_history) > 10:
                recent_errors = [abs(h['offset_ms']) for h in list(self.offset_history)[-10:]]
                self.performance_stats['rms_error_ms'] = math.sqrt(sum(e*e for e in recent_errors) / len(recent_errors))
            
            return int(corrected)
            
        except Exception as e:
            print(f"Timing correction error: {e}")
            return timestamp_ms

    def _update_kalman_filter(self, measured_offset_ms, dt, current_time):
        """Update Kalman filter with new measurement for robust state estimation"""
        try:
            # Prediction step
            predicted_drift_dt = self.kalman_state['drift_rate_ppm'] * dt / 1000.0  # Convert ppm to ms
            predicted_offset = self.kalman_state['offset_ms'] + predicted_drift_dt
            
            # Predict covariance
            predicted_offset_var = (self.kalman_state['offset_variance'] + 
                                  self.kalman_state['process_noise_offset'] * dt)
            predicted_drift_var = (self.kalman_state['drift_variance'] + 
                                 self.kalman_state['process_noise_drift'] * dt)
            
            # Update step
            innovation = measured_offset_ms - predicted_offset
            innovation_covariance = predicted_offset_var + self.kalman_state['measurement_noise']
            
            # Kalman gain
            kalman_gain_offset = predicted_offset_var / innovation_covariance
            kalman_gain_drift = 0.0  # We don't directly measure drift rate
            
            # Update state estimates
            self.kalman_state['offset_ms'] = predicted_offset + kalman_gain_offset * innovation
            
            # Update drift estimate using historical trend
            if len(self.offset_history) >= 3:
                recent_offsets = list(self.offset_history)[-3:]
                if len(recent_offsets) >= 2:
                    time_span = recent_offsets[-1]['time'] - recent_offsets[0]['time']
                    if time_span > 0:
                        offset_change = recent_offsets[-1]['offset_ms'] - recent_offsets[0]['offset_ms']
                        drift_estimate_ppm = (offset_change / time_span) * 1000.0
                        
                        # Smooth drift estimate
                        alpha = 0.1  # Smoothing factor
                        self.kalman_state['drift_rate_ppm'] = (
                            (1 - alpha) * self.kalman_state['drift_rate_ppm'] + 
                            alpha * drift_estimate_ppm
                        )
            
            # Update covariance
            self.kalman_state['offset_variance'] = (1 - kalman_gain_offset) * predicted_offset_var
            self.kalman_state['drift_variance'] = predicted_drift_var  # No direct update for drift
            
            # Store drift history
            self.drift_history.append({
                'time': current_time,
                'drift_ppm': self.kalman_state['drift_rate_ppm'],
                'offset_ms': self.kalman_state['offset_ms']
            })
            
            self.performance_stats['kalman_updates'] += 1
            
            # Restore measurement noise if it was boosted and convergence is improving
            if self.kalman_state['measurement_noise'] < 0.5:  # Was boosted
                if abs(innovation) < 10.0:  # Convergence is working
                    self.kalman_state['measurement_noise'] = min(0.5, self.kalman_state['measurement_noise'] * 1.1)
            
        except Exception as e:
            print(f"Kalman filter error: {e}")

    def _update_rate_control(self, current_time):
        """Advanced rate control with predictive compensation"""
        try:
            dt = current_time - self._last_rate_update
            if dt < self.rate_update_interval_s:
                return
                
            # Get current state estimates
            offset_ms = self.kalman_state['offset_ms']
            drift_ppm = self.kalman_state['drift_rate_ppm']
            
            # Predictive component: compensate for expected future drift
            prediction_horizon_s = 30.0  # Predict 30 seconds ahead
            predicted_future_offset = offset_ms + (drift_ppm * prediction_horizon_s / 1000.0)
            
            # SMOOTH rate adjustment for stable convergence
            abs_offset = abs(offset_ms)
            
            # Deadband for rate control - no adjustment for small offsets
            if abs_offset < self.deadband_threshold_ms:
                # In deadband - only apply gentle drift compensation
                offset_correction_ppm = 0.0
                drift_compensation_ppm = -drift_ppm * 0.5  # Gentle drift compensation
                predictive_ppm = 0.0
            else:
                # STABLE rate corrections based on error magnitude
                if abs_offset > self.large_drift_threshold_ms:
                    # Large error - moderate correction
                    offset_correction_ppm = -offset_ms * 1.5
                    drift_compensation_ppm = -drift_ppm * 2.0
                    predictive_ppm = -predicted_future_offset * 0.3
                else:
                    # Normal error - gentle correction
                    offset_correction_ppm = -offset_ms * 0.8
                    drift_compensation_ppm = -drift_ppm * 1.2
                    predictive_ppm = -predicted_future_offset * 0.2
            
            # Total rate adjustment
            total_adjustment_ppm = offset_correction_ppm + drift_compensation_ppm + predictive_ppm
            
            # Rate limiting - prevent large jumps
            current_rate = self.rate_adjustment_ppm
            max_change = self.max_rate_change_ppm_per_update
            if abs(total_adjustment_ppm - current_rate) > max_change:
                # Limit the change rate
                if total_adjustment_ppm > current_rate:
                    total_adjustment_ppm = current_rate + max_change
                else:
                    total_adjustment_ppm = current_rate - max_change
                print(f"📊 RATE LIMITED: change limited to ±{max_change}ppm/update")
            
            # Heavy smoothing for stability
            alpha = self.correction_smoothing_factor  # 0.1 - very smooth
            self.rate_adjustment_ppm = (
                (1 - alpha) * self.rate_adjustment_ppm + 
                alpha * total_adjustment_ppm
            )
            
            # Conservative limits for stability
            if self.pps_available:
                max_rate_ppm = 150.0  # Reduced for stability
            else:
                max_rate_ppm = 100.0  # Conservative without PPS
                
            self.rate_adjustment_ppm = max(-max_rate_ppm, min(max_rate_ppm, self.rate_adjustment_ppm))
            
            # Store prediction component
            self.rate_prediction_ppm = predictive_ppm
            
            # Update performance stats
            self.performance_stats['max_correction_ppm'] = max(
                self.performance_stats['max_correction_ppm'],
                abs(self.rate_adjustment_ppm)
            )
            
            self._last_rate_update = current_time
            
        except Exception as e:
            print(f"Rate control error: {e}")

    def get_rate_adjustment_ppm(self):
        """Expose current rate trim (ppm) for timestamp generator to use."""
        return self.rate_adjustment_ppm
    
    def get_advanced_timing_stats(self):
        """Get advanced timing statistics including Kalman filter state"""
        stats = {
            'kalman_state': dict(self.kalman_state),
            'performance_stats': dict(self.performance_stats),
            'rate_adjustment_ppm': self.rate_adjustment_ppm,
            'rate_prediction_ppm': self.rate_prediction_ppm,
            'offset_history_length': len(self.offset_history),
            'drift_history_length': len(self.drift_history)
        }
        
        if self.offset_history:
            recent_offsets = [h['offset_ms'] for h in list(self.offset_history)[-10:]]
            stats['recent_offset_stats'] = {
                'mean_ms': sum(recent_offsets) / len(recent_offsets),
                'std_ms': math.sqrt(sum((x - stats['recent_offset_stats']['mean_ms'])**2 
                                      for x in recent_offsets) / len(recent_offsets)) if len(recent_offsets) > 1 else 0,
                'max_abs_ms': max(abs(x) for x in recent_offsets),
                'count': len(recent_offsets)
            }
            
        if self.drift_history:
            recent_drifts = [h['drift_ppm'] for h in list(self.drift_history)[-10:]]
            stats['recent_drift_stats'] = {
                'mean_ppm': sum(recent_drifts) / len(recent_drifts),
                'std_ppm': math.sqrt(sum((x - stats['recent_drift_stats']['mean_ppm'])**2 
                                       for x in recent_drifts) / len(recent_drifts)) if len(recent_drifts) > 1 else 0,
                'max_abs_ppm': max(abs(x) for x in recent_drifts),
                'count': len(recent_drifts)
            }
            
        return stats
    
    def get_timing_info(self):
        """Get current timing information"""
        return {
            'timing_quality': self.timing_quality,
            'pps_available': self.pps_available,
            'ntp_synced': self.ntp_synced,
            'timing_source': self.timing_quality.get('source', 'Unknown')
        }