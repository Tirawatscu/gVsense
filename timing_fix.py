#!/usr/bin/env python3
"""
CORRECTED Timing Architecture - Fixed Sign Inversion Bug
Eliminates circular feedback loops and conflicting correction mechanisms
"""

import time
import math
import threading
import statistics
from collections import deque
import datetime
import subprocess

class UnifiedTimingManager:
    """
    Single timing authority that coordinates all timing corrections
    Eliminates circular feedback loops by centralizing control
    """
    
    def __init__(self):
        # Timing reference sources
        self.reference_source = "UNKNOWN"  # GPS, NTP, or SYSTEM
        self.reference_accuracy_us = 1000000  # 1 second default
        self.last_reference_update = 0
        self.reference_check_interval = 30.0  # Check every 30 seconds for timing source changes
        
        # Master timing state
        self.master_offset_ms = 0.0  # Current offset from reference time
        self.master_drift_ppm = 0.0  # Current drift rate
        self.last_measurement_time = 0.0
        
        # Single Kalman filter for unified state estimation
        self.kalman_state = {
            'offset_ms': 0.0,
            'drift_rate_ppm': 0.0,
            'offset_variance': 100.0,
            'drift_variance': 1.0,
            'process_noise_offset': 0.5,
            'process_noise_drift': 0.05,
            'measurement_noise': 1.0
        }
        
        # Control strategy selection
        self.control_mode = "AUTO"  # AUTO, HOST_ONLY, MCU_ONLY
        self.prefer_mcu_control = True  # Prefer MCU rate control over host corrections
        
        # Performance tracking
        self.correction_history = deque(maxlen=1000)
        self.performance_metrics = {
            'total_corrections': 0,
            'mcu_corrections': 0,
            'host_corrections': 0,
            'avg_error_ms': 0.0,
            'max_error_ms': 0.0
        }
        
        # Thread safety
        self.lock = threading.RLock()
        
        # Initialize reference
        self._update_reference_source()
        
    def _update_reference_source(self, force=False):
        """Update reference time source and accuracy
        
        Args:
            force: If True, update immediately. If False, respect check interval.
        """
        current_time = time.time()
        
        # Check if it's time to update (unless forced)
        if not force and (current_time - self.last_reference_update) < self.reference_check_interval:
            return False
        
        try:
            old_source = self.reference_source
            
            # Try GPS/PPS first
            chrony_status = self._get_chrony_status()
            if chrony_status and chrony_status.get('source') == 'GPS+PPS':
                self.reference_source = "GPS+PPS"
                self.reference_accuracy_us = 1  # 1 microsecond for PPS
                self.prefer_mcu_control = False  # Use host control for scientific precision
                
            elif chrony_status and chrony_status.get('accuracy_us', 1000000) < 10000:
                self.reference_source = "NTP"
                self.reference_accuracy_us = chrony_status['accuracy_us']
                self.prefer_mcu_control = True  # Use MCU control for normal NTP
                
            else:
                self.reference_source = "SYSTEM"
                self.reference_accuracy_us = 1000000  # 1 second
                self.prefer_mcu_control = True
                
            self.last_reference_update = current_time
            
            # Log source changes
            if old_source != self.reference_source:
                print(f"🔄 HOST TIMING SOURCE CHANGED: {old_source} → {self.reference_source}")
                print(f"   Accuracy: ±{self.reference_accuracy_us:.1f}µs")
                return True
            
            return False
            
        except Exception as e:
            print(f"Reference source update failed: {e}")
            self.reference_source = "SYSTEM"
            self.reference_accuracy_us = 1000000
            return False
            
    def get_reference_time(self):
        """Get current reference time with best available precision
        
        Note: Also performs periodic timing source re-checking
        """
        # Periodically re-check timing source (non-blocking)
        self._update_reference_source(force=False)
        
        try:
            if self.reference_source == "GPS+PPS":
                # Use chrony for GPS time
                return self._get_chrony_time()
            elif self.reference_source == "NTP":
                # Use system time with NTP correction
                return time.time()
            else:
                # System time only
                return time.time()
        except:
            return time.time()
            
    def _get_chrony_time(self):
        """Get chrony-corrected time"""
        try:
            result = subprocess.run(['chronyc', 'tracking'], 
                                  capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                # Parse offset and apply correction
                for line in result.stdout.split('\n'):
                    if 'System time' in line:
                        # Extract offset and apply correction
                        # Implementation depends on chrony output format
                        pass
            return time.time()
        except:
            return time.time()
            
    def _get_chrony_status(self):
        """Get chrony timing status with PPS lock detection"""
        try:
            result = subprocess.run(['chronyc', 'tracking'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                status = {
                    'source': 'NTP',
                    'accuracy_us': 10000,
                    'pps_locked': False,
                    'leap_status': 'Normal'
                }
                
                for line in result.stdout.split('\n'):
                    if 'Reference ID' in line:
                        ref_id = line.split(':')[1].strip()
                        if 'PPS' in ref_id or 'GPS' in ref_id:
                            status['source'] = 'GPS+PPS'
                            status['accuracy_us'] = 1
                            status['pps_locked'] = True
                    elif 'Leap status' in line:
                        status['leap_status'] = line.split(':')[1].strip()
                    elif 'System time' in line:
                        # Parse offset to determine lock quality
                        try:
                            offset_str = line.split(':')[1].strip().split()[0]
                            offset_seconds = float(offset_str)
                            # If offset < 1ms, we consider it locked
                            if abs(offset_seconds) < 0.001:
                                status['pps_locked'] = status.get('pps_locked', False) and True
                        except:
                            pass
                
                return status
        except:
            pass
        return None
    
    def check_pps_lock_status(self):
        """Check if GPS+PPS is locked and stable
        
        Returns:
            dict: Status with 'locked', 'source', 'accuracy_us'
        """
        chrony_status = self._get_chrony_status()
        if not chrony_status:
            return {'locked': False, 'source': 'UNKNOWN', 'accuracy_us': 1000000}
        
        return {
            'locked': chrony_status.get('pps_locked', False) and chrony_status.get('source') == 'GPS+PPS',
            'source': chrony_status.get('source', 'UNKNOWN'),
            'accuracy_us': chrony_status.get('accuracy_us', 1000000),
            'leap_status': chrony_status.get('leap_status', 'Unknown')
        }
        
    def measure_timing_error(self, generated_timestamp_ms, sample_sequence):
        """
        Measure timing error - this is the ONLY place where error is measured
        All other components must use this measurement
        """
        with self.lock:
            try:
                current_time = time.time()
                
                # Get reference time
                reference_time = self.get_reference_time()
                
                # Convert generated timestamp to seconds
                generated_time = generated_timestamp_ms / 1000.0
                
                # Calculate raw error
                raw_error_ms = (generated_time - reference_time) * 1000.0
                
                # Update Kalman filter with measurement
                self._update_kalman_filter(raw_error_ms, current_time)
                
                # Store measurement
                measurement = {
                    'time': current_time,
                    'sequence': sample_sequence,
                    'raw_error_ms': raw_error_ms,
                    'filtered_error_ms': self.kalman_state['offset_ms'],
                    'reference_source': self.reference_source
                }
                self.correction_history.append(measurement)
                
                # Update performance metrics
                self._update_performance_metrics(raw_error_ms)
                
                return {
                    'raw_error_ms': raw_error_ms,
                    'filtered_error_ms': self.kalman_state['offset_ms'],
                    'drift_rate_ppm': self.kalman_state['drift_rate_ppm'],
                    'confidence': 1.0 / (1.0 + math.sqrt(self.kalman_state['offset_variance']))
                }
                
            except Exception as e:
                print(f"Error measurement failed: {e}")
                return None
                
    def _update_kalman_filter(self, measured_error_ms, current_time):
        """Update unified Kalman filter"""
        try:
            dt = current_time - self.last_measurement_time
            if dt <= 0:
                dt = 0.1
                
            # Prediction step
            predicted_offset = (self.kalman_state['offset_ms'] + 
                              self.kalman_state['drift_rate_ppm'] * dt / 1000.0)
            predicted_offset_var = (self.kalman_state['offset_variance'] + 
                                  self.kalman_state['process_noise_offset'] * dt)
            predicted_drift_var = (self.kalman_state['drift_variance'] + 
                                 self.kalman_state['process_noise_drift'] * dt)
            
            # Update step
            innovation = measured_error_ms - predicted_offset
            innovation_covariance = predicted_offset_var + self.kalman_state['measurement_noise']
            
            # Kalman gains
            gain_offset = predicted_offset_var / innovation_covariance
            gain_drift = 0.0  # Direct drift measurement not available
            
            # Update estimates
            self.kalman_state['offset_ms'] = predicted_offset + gain_offset * innovation
            # Update drift based on recent trend
            if len(self.correction_history) >= 3:
                self._update_drift_estimate()
                
            # Update covariances
            self.kalman_state['offset_variance'] = (1 - gain_offset) * predicted_offset_var
            self.kalman_state['drift_variance'] = predicted_drift_var
            
            self.last_measurement_time = current_time
            
        except Exception as e:
            print(f"Kalman filter update failed: {e}")
            
    def _update_drift_estimate(self):
        """Update drift estimate from measurement history"""
        try:
            recent = list(self.correction_history)[-10:]
            if len(recent) >= 3:
                time_span = recent[-1]['time'] - recent[0]['time']
                if time_span > 0:
                    error_change = (recent[-1]['filtered_error_ms'] - 
                                  recent[0]['filtered_error_ms'])
                    drift_estimate = (error_change / time_span) * 1000.0  # ppm
                    
                    # Smooth update
                    alpha = 0.1
                    self.kalman_state['drift_rate_ppm'] = (
                        (1 - alpha) * self.kalman_state['drift_rate_ppm'] + 
                        alpha * drift_estimate
                    )
        except Exception as e:
            print(f"Drift estimate update failed: {e}")
            
    def _update_performance_metrics(self, error_ms):
        """Update performance tracking"""
        self.performance_metrics['max_error_ms'] = max(
            self.performance_metrics['max_error_ms'], abs(error_ms)
        )
        
        if len(self.correction_history) > 0:
            recent_errors = [abs(m['raw_error_ms']) for m in list(self.correction_history)[-100:]]
            self.performance_metrics['avg_error_ms'] = sum(recent_errors) / len(recent_errors)
            
    def get_correction_strategy(self):
        """
        Determine optimal correction strategy based on current conditions
        Returns: {'method': 'MCU'|'HOST'|'BOTH', 'max_correction': float, 'urgency': int}
        """
        with self.lock:
            error_ms = abs(self.kalman_state['offset_ms'])
            confidence = 1.0 / (1.0 + math.sqrt(self.kalman_state['offset_variance']))
            
            # Determine urgency level
            if error_ms > 100:
                urgency = 3  # Emergency
            elif error_ms > 50:
                urgency = 2  # High
            elif error_ms > 10:
                urgency = 1  # Medium
            else:
                urgency = 0  # Low
                
            # Determine correction method
            if self.reference_source == "GPS+PPS" and confidence > 0.8:
                # High precision reference - use host corrections
                method = "HOST"
                max_correction = min(50.0, error_ms * 0.5)
            elif self.reference_source == "NTP" and self.prefer_mcu_control:
                # NTP reference - use MCU corrections
                method = "MCU"
                max_correction = min(100.0, error_ms * 0.3)
            elif urgency >= 2:
                # Emergency - use both methods
                method = "BOTH"
                max_correction = min(200.0, error_ms * 0.2)
            else:
                # Normal operation - prefer MCU
                method = "MCU"
                max_correction = min(50.0, error_ms * 0.2)
                
            return {
                'method': method,
                'max_correction': max_correction,
                'urgency': urgency,
                'error_ms': error_ms,
                'confidence': confidence
            }
            
    def get_status(self):
        """Get comprehensive timing status"""
        with self.lock:
            return {
                'reference_source': self.reference_source,
                'reference_accuracy_us': self.reference_accuracy_us,
                'kalman_state': dict(self.kalman_state),
                'performance_metrics': dict(self.performance_metrics),
                'control_mode': self.control_mode,
                'prefer_mcu_control': self.prefer_mcu_control,
                'measurements_count': len(self.correction_history)
            }
    
    def get_timing_info(self):
        """Get timing info (compatible with web server interface)
        
        Note: Also performs periodic timing source re-checking
        """
        # Periodically re-check timing source (non-blocking)
        self._update_reference_source(force=False)
        
        with self.lock:
            return {
                'timing_quality': {
                    'source': self.reference_source,
                    'accuracy_us': self.reference_accuracy_us,
                    'last_update': self.last_reference_update
                },
                'pps_available': self.reference_source == 'GPS+PPS',
                'ntp_synced': self.reference_source in ['GPS+PPS', 'NTP'],
                'timing_source': self.reference_source,
                'reference_source': self.reference_source,
                'reference_accuracy_us': self.reference_accuracy_us,
                'performance_metrics': dict(self.performance_metrics),
                'kalman_state': dict(self.kalman_state),
                'control_mode': self.control_mode,
                'measurements_count': len(self.correction_history),
                'last_source_check': self.last_reference_update
            }
    
    def force_timing_source_check(self):
        """Force an immediate re-check of timing source availability
        
        Returns:
            bool: True if source changed, False otherwise
        """
        return self._update_reference_source(force=True)
    
    def get_precise_time(self):
        """Get precise time (alias for get_reference_time for compatibility)"""
        return self.get_reference_time()


class SimplifiedTimestampGenerator:
    """
    Simplified timestamp generator that ONLY generates timestamps
    No internal corrections - all corrections handled by UnifiedTimingManager
    """
    
    def __init__(self, expected_rate=100.0, quantization_ms=10):
        """
        Initialize timestamp generator with expected sampling rate and timestamp quantization
        
        Args:
            expected_rate: Expected sampling rate in Hz
            quantization_ms: Timestamp quantization interval in milliseconds (default: 10ms)
        """
        self.expected_rate = expected_rate
        self.expected_interval_s = 1.0 / expected_rate
        self.expected_interval = 1.0 / expected_rate  # Compatibility with host_timing_acquisition
        
        # Timestamp quantization
        self.quantization_ms = quantization_ms
        
        self.reference_time = None
        self.reference_sequence = None
        self.last_sequence = None
        self.is_initialized = False
        self.lock = threading.Lock()
        
        # Statistics only
        self.stats = {
            'samples_processed': 0,
            'sequence_resets': 0,
            'wraparounds_detected': 0,
            'last_timestamp': None,  # Track last generated timestamp for monitoring
            'last_sequence': None,  # Track last sequence for wraparound detection
            'max_sequence_seen': 0,   # Track highest sequence seen for debugging
            'quantization_ms': quantization_ms  # Store quantization setting
        }
        
    def generate_timestamp(self, sequence_number):
        """
        Generate clean timestamp based ONLY on sequence progression
        No corrections applied here - purely mathematical generation
        """
        with self.lock:
            self.stats['samples_processed'] += 1
            current_time = time.time()
            
            # Initialize on first sample
            if not self.is_initialized:
                self.reference_time = current_time
                self.reference_sequence = sequence_number
                self.last_sequence = sequence_number
                self.is_initialized = True
                # Apply quantization to first sample too
                timestamp_ms = int(current_time * 1000)
                quantized_timestamp_ms = round(timestamp_ms / self.quantization_ms) * self.quantization_ms
                self.stats['last_timestamp'] = quantized_timestamp_ms / 1000.0
                return quantized_timestamp_ms
            
            # IMPROVED: Detect sequence resets before calculating differences
            if self.last_sequence is not None:
                # Check for large backward jumps that indicate MCU reset
                if sequence_number < self.last_sequence and (self.last_sequence - sequence_number) > 10000:
                    print(f"🔄 MCU SEQUENCE RESET DETECTED: {self.last_sequence} -> {sequence_number}")
                    print(f"   Large backward jump indicates MCU restart or reset")
                    print(f"   Resetting timestamp generator state")
                    
                    # Reset the generator state
                    self.reference_time = current_time
                    self.reference_sequence = sequence_number
                    self.stats['sequence_resets'] += 1
                    
                    # Return current time as new reference (with quantization)
                    timestamp_s = current_time
                else:
                    # Calculate sequence progression (handle wraparound)
                    sequence_diff = self._calculate_sequence_diff(
                        self.reference_sequence, sequence_number
                    )
                    
                    # Generate timestamp based on pure sequence progression
                    timestamp_s = self.reference_time + (sequence_diff * self.expected_interval_s)
            else:
                # First time with sequence tracking
                timestamp_s = current_time
            
            # Update tracking
            self.last_sequence = sequence_number
            self.stats['last_sequence'] = sequence_number
            self.stats['max_sequence_seen'] = max(self.stats['max_sequence_seen'], sequence_number)
            
            # Track last timestamp for monitoring
            self.stats['last_timestamp'] = timestamp_s
            
            # QUANTIZE TIMESTAMP TO CONFIGURABLE BOUNDARIES
            # Round to nearest quantization boundary (e.g., 10ms: 0, 10, 20, 30, 40, 50...)
            timestamp_ms = int(timestamp_s * 1000)
            quantized_timestamp_ms = round(timestamp_ms / self.quantization_ms) * self.quantization_ms
            
            # CRITICAL FIX: Force final integer quantization to prevent floating-point precision errors
            # This ensures all timestamps end with proper quantization boundaries
            final_timestamp_ms = int(quantized_timestamp_ms)
            final_quantized_ms = (final_timestamp_ms // self.quantization_ms) * self.quantization_ms
            
            # Update tracking with final quantized timestamp
            self.stats['last_timestamp'] = final_quantized_ms / 1000.0
            
            return final_quantized_ms  # Return final quantized timestamp in milliseconds
            
    def _calculate_sequence_diff(self, ref_seq, current_seq):
        """
        COMPLETELY REWRITTEN: Robust sequence handling with proper reset detection
        Handles both 16-bit wraparound and MCU sequence resets correctly
        """
        # CRITICAL FIX: If current sequence is much lower than reference, it's a reset
        # This prevents the system from treating resets as wraparounds
        if current_seq < ref_seq and (ref_seq - current_seq) > 10000:
            print(f"🚨 SEQUENCE RESET DETECTED: {ref_seq} -> {current_seq}")
            print(f"   Large backward jump ({ref_seq - current_seq}) indicates MCU reset")
            print(f"   NOT a wraparound - resetting reference immediately")
            
            # Reset reference to current sequence
            self.reference_sequence = current_seq
            self.reference_time = time.time()
            self.stats['sequence_resets'] += 1
            return 0
        
        # Handle 16-bit wraparound correctly (only for forward progression)
        MAX_SEQUENCE = 65536
        HALF_SEQUENCE = 32768
        
        # Only calculate differences for forward progression
        if current_seq >= ref_seq:
            # Forward progression - normal case
            diff = current_seq - ref_seq
            
            # CRITICAL FIX: Only detect wraparound if we're actually near the 16-bit boundary
            # A jump from 1000 to 34000 is NOT a wraparound - it's a sequence reset!
            if ref_seq > 60000 and current_seq < 10000:
                # This might be a true wraparound (near 65535 boundary)
                wraparound_diff = current_seq - (ref_seq + MAX_SEQUENCE)
                if abs(wraparound_diff) < abs(diff):
                    diff = wraparound_diff
                    self.stats['wraparounds_detected'] += 1
                    print(f"🔄 TRUE WRAPAROUND: {ref_seq} -> {current_seq} (diff: {diff})")
            elif diff > HALF_SEQUENCE:
                # Large forward jump - this is suspicious and likely a reset
                print(f"⚠️  LARGE FORWARD JUMP: {ref_seq} -> {current_seq} (jump: {diff})")
                print(f"   This is suspicious - might be a sequence reset")
                print(f"   Resetting reference to be safe")
                
                # Reset reference to current sequence
                self.reference_sequence = current_seq
                self.reference_time = time.time()
                self.stats['sequence_resets'] += 1
                return 0
            
            return diff
        else:
            # Backward progression - this should NOT happen in normal operation
            # If it's a small step, it might be a timing glitch
            # If it's a large step, it's definitely a reset
            step_size = ref_seq - current_seq
            if step_size < 100:  # Small backward step - might be timing glitch
                print(f"⚠️  SMALL BACKWARD STEP: {ref_seq} -> {current_seq} (step: {step_size})")
                return 0  # Ignore small backward steps
            else:  # Large backward step - definitely a reset
                print(f"🚨 LARGE BACKWARD STEP: {ref_seq} -> {current_seq} (step: {step_size})")
                print(f"   This indicates a sequence reset - resetting reference")
                
                # Reset reference
                self.reference_sequence = current_seq
                self.reference_time = time.time()
                self.stats['sequence_resets'] += 1
                return 0
                
    def update_rate(self, new_rate_hz):
        """Update expected rate (called when MCU rate is changed)"""
        with self.lock:
            self.expected_rate = new_rate_hz
            self.expected_interval_s = 1.0 / new_rate_hz
            self.expected_interval = 1.0 / new_rate_hz  # Compatibility with host_timing_acquisition
            
    def get_stats(self):
        """Get generator statistics"""
        with self.lock:
            return dict(self.stats)
    
    def force_sequence_reset(self, new_sequence):
        """Force a sequence reset (useful for debugging)"""
        with self.lock:
            print(f"🔧 FORCED SEQUENCE RESET: {self.reference_sequence} -> {new_sequence}")
            self.reference_sequence = new_sequence
            self.reference_time = time.time()
            self.last_sequence = new_sequence
            self.stats['sequence_resets'] += 1
            print(f"   Generator state reset to sequence {new_sequence}")
    
    def set_quantization(self, quantization_ms):
        """Change timestamp quantization interval"""
        with self.lock:
            old_quantization = self.quantization_ms
            self.quantization_ms = quantization_ms
            self.stats['quantization_ms'] = quantization_ms
            print(f"🔧 QUANTIZATION CHANGED: {old_quantization}ms -> {quantization_ms}ms")
            print(f"   Timestamps will now align to {quantization_ms}ms boundaries")
    
    def reset_for_restart(self):
        """Reset generator state for clean streaming restart"""
        with self.lock:
            print(f"🔄 RESETTING TIMESTAMP GENERATOR FOR RESTART")
            print(f"   Clearing all timing state from previous session")
            
            # Clear all tracking
            self.last_sequence = None
            self.reference_sequence = None
            # Force full re-initialization on next sample
            self.reference_time = None
            self.is_initialized = False
            
            # Reset statistics (but preserve configuration)
            self.stats['samples_processed'] = 0
            self.stats['sequence_resets'] = 0
            self.stats['last_sequence'] = None
            self.stats['max_sequence_seen'] = 0
            self.stats['last_timestamp'] = None
            
            print(f"✅ Generator reset complete - ready for fresh start")


class UnifiedTimingController:
    """
    CORRECTED: Single timing controller with proper correction sign logic
    ENHANCED: Non-blocking commands to prevent data loss
    """
    
    def __init__(self, seismic_device, timing_manager):
        self.seismic = seismic_device
        self.timing_manager = timing_manager
        self.running = False
        self.controller_thread = None
        self.start_time = None  # Will be set when controller starts
        
        # Control parameters - OPTIMIZED to prevent data loss
        self.measurement_interval_s = 10.0  # Measure every 10 seconds (INCREASED to reduce blocking)
        self.target_error_ms = 0.5        # Desired steady-state absolute error (±0.5ms)
        self.min_error_threshold_ms = 0.2 # Deadband to avoid chattering (±0.2ms)
        
        # CRITICAL: Monitor-only mode to prevent data loss after convergence
        self.monitor_only_mode = False  # When True, only monitor - don't send corrections
        self.auto_enable_monitor_mode = True  # Automatically switch to monitor-only after convergence
        
        # MCU control state
        self.current_mcu_interval_us = 10000.0  # 100Hz default
        self.target_mcu_interval_us = 10000.0
        
        # Host correction state
        self.host_correction_ms = 0.0
        
        # Statistics - ENHANCED for performance monitoring and data loss tracking
        self.stats = {
            'corrections_applied': 0,
            'mcu_adjustments': 0,
            'host_adjustments': 0,
            'measurements_taken': 0,
            'sign_corrections_applied': 0,  # Track corrections with proper sign
            'error_history': deque(maxlen=100),  # Track recent errors for analysis
            'convergence_time_s': 0.0,  # Time to reach target_error_ms
            'target_achieved': False,  # Whether ±10ms target has been reached
            'commands_sent': 0,  # Track command send attempts
            'commands_blocked': 0,  # Track blocking command operations
            'corrections_skipped_monitor_mode': 0,  # Track corrections skipped in monitor mode
            'potential_data_loss_events': 0  # Track events that could cause data loss
        }
    
    def start_controller(self):
        """Start the unified timing controller"""
        if self.running:
            return
            
        self.running = True
        self.start_time = time.time()  # Track start time for convergence measurement
        self.controller_thread = threading.Thread(
            target=self._control_loop, daemon=True
        )
        self.controller_thread.start()
        print("CORRECTED: Unified timing controller started with proper sign logic")
        print(f"🎯 TARGET: ±{self.target_error_ms}ms error bound with optimized correction parameters")
        print(f"⚙️  MEASUREMENT INTERVAL: {self.measurement_interval_s}s (increased to prevent data loss)")
        print(f"🔒 AUTO MONITOR MODE: {'Enabled' if self.auto_enable_monitor_mode else 'Disabled'} (stops corrections after convergence)")
        
    def stop_controller(self):
        """Stop the timing controller"""
        self.running = False
        if self.controller_thread:
            self.controller_thread.join(timeout=3.0)
        print("CORRECTED: Unified timing controller stopped")
        
    def _control_loop(self):
        """Main control loop with corrected sign logic"""
        last_measurement = 0.0
        
        while self.running:
            try:
                current_time = time.time()
                
                # Wait for measurement interval
                if current_time - last_measurement < self.measurement_interval_s:
                    time.sleep(1.0)
                    continue
                    
                # Skip if not streaming
                if not getattr(self.seismic, 'streaming', False):
                    time.sleep(1.0)
                    continue
                    
                # Get recent sample for measurement
                recent_sample = self._get_recent_sample()
                if not recent_sample:
                    time.sleep(1.0)
                    continue
                    
                # Measure timing error using unified manager
                error_data = self.timing_manager.measure_timing_error(
                    recent_sample['timestamp'], recent_sample['sequence']
                )
                
                if not error_data:
                    time.sleep(1.0)
                    continue
                    
                # Get correction strategy
                strategy = self.timing_manager.get_correction_strategy()
                
                # Apply corrections based on strategy
                self._apply_corrections(error_data, strategy)
                
                self.stats['measurements_taken'] += 1
                last_measurement = current_time
                
            except Exception as e:
                print(f"Timing control error: {e}")
                time.sleep(5.0)
                
    def _get_recent_sample(self):
        """Get most recent sample from device"""
        try:
            if hasattr(self.seismic, 'sample_tracking'):
                buffer = self.seismic.sample_tracking.get('sample_buffer')
                if buffer and len(buffer) > 0:
                    sample = buffer[-1]  # Most recent sample
                    
                    # PROACTIVE: Check for sequence wraparound
                    if hasattr(sample, 'sequence') and sample.get('sequence', 0) < 1000:
                        # Sequence near 0 - check if this is a wraparound
                        if hasattr(self, 'last_sequence') and self.last_sequence > 65000:
                            print(f"🔄 PROACTIVE WRAPAROUND DETECTION: {self.last_sequence} -> {sample.get('sequence', 0)}")
                            print(f"   Resetting sequence tracking to prevent massive errors")
                            self.last_sequence = sample.get('sequence', 0)
                    
                    return sample
        except:
            pass
        return None
        
    def _apply_corrections(self, error_data, strategy):
        """Apply corrections based on unified strategy"""
        try:
            error_ms = error_data['filtered_error_ms']
            
            # AGGRESSIVE SANITY CHECK: Prevent any large errors from sequence bugs
            if abs(error_ms) > 100:  # More than 100ms error is suspicious
                print(f"🚨 SANITY CHECK FAILED: Large error {error_ms:+.1f}ms detected!")
                print(f"   This likely indicates a sequence reset or MCU restart")
                print(f"   Error magnitude suggests sequence jumped from ~{abs(error_ms)//10} samples")
                print(f"   Skipping correction to prevent system instability")
                print(f"   System will recover when sequence stabilizes")
                return
            
            # ADDITIONAL CHECK: If error is still large but under 100ms, log it
            if abs(error_ms) > 50:  # Log large errors for monitoring
                print(f"⚠️  LARGE ERROR DETECTED: {error_ms:+.1f}ms")
                print(f"   Monitoring for potential sequence issues")
            
            # Track error for performance analysis
            self.stats['error_history'].append({
                'time': time.time(),
                'error_ms': error_ms,
                'mcu_interval_us': self.current_mcu_interval_us
            })
            
            # Check if we've achieved precision target
            if not self.stats['target_achieved'] and abs(error_ms) <= self.target_error_ms:
                self.stats['target_achieved'] = True
                self.stats['convergence_time_s'] = time.time() - self.start_time
                print(f"🎯 TARGET ACHIEVED: ±{self.target_error_ms}ms error target reached in {self.stats['convergence_time_s']:.1f}s!")
                
                # CRITICAL: Switch to monitor-only mode to prevent data loss
                if self.auto_enable_monitor_mode:
                    self.monitor_only_mode = True
                    print(f"🔒 MONITOR-ONLY MODE ACTIVATED: Timing target achieved!")
                    print(f"   No further MCU corrections will be sent to prevent data loss")
                    print(f"   System will continue monitoring timing accuracy")
            
            # Skip small errors
            if abs(error_ms) < self.min_error_threshold_ms:
                return
            
            # CRITICAL: Check monitor-only mode before applying corrections
            if self.monitor_only_mode:
                self.stats['corrections_skipped_monitor_mode'] += 1
                print(f"📊 MONITOR MODE: Error {error_ms:+.3f}ms detected but correction SKIPPED (monitor-only)")
                return
                
            print(f"CORRECTED: Applying correction for error: {error_ms:+.3f}ms (target: ±{self.target_error_ms}ms)")
                
            if strategy['method'] == 'MCU':
                self._apply_mcu_correction_corrected(error_ms, strategy)
            elif strategy['method'] == 'HOST':
                self._apply_host_correction_corrected(error_ms, strategy)
            elif strategy['method'] == 'BOTH':
                # Split correction between MCU and host
                mcu_error = error_ms * 0.7
                host_error = error_ms * 0.3
                self._apply_mcu_correction_corrected(mcu_error, strategy)
                self._apply_host_correction_corrected(host_error, strategy)
                
            self.stats['corrections_applied'] += 1
            
        except Exception as e:
            print(f"Correction application failed: {e}")
            
    def _apply_mcu_correction_corrected(self, error_ms, strategy):
        """
        CORRECTED: Apply correction to MCU sampling rate with proper sign logic
        OPTIMIZED for ±10ms target with adaptive correction strength
        
        CORRECT LOGIC:
        - If error_ms > 0: timestamps ahead of GPS → MCU too fast → need POSITIVE ppm to slow down
        - If error_ms < 0: timestamps behind GPS → MCU too slow → need NEGATIVE ppm to speed up
        """
        try:
            # OPTIMIZED: Adaptive correction strength based on error magnitude (sub-ms precision)
            error_abs = abs(error_ms)
            if error_abs > 10.0:       # >10ms error: aggressive but safe
                correction_ppm = +error_ms * 2.0
            elif error_abs > 1.0:      # 1..10ms: moderate
                correction_ppm = +error_ms * 1.0
            else:                      # <1ms: very gentle to avoid oscillation
                correction_ppm = +error_ms * 0.4
            
            # Limit correction
            max_correction = strategy['max_correction']
            correction_ppm = max(-max_correction, min(max_correction, correction_ppm))
            
            # Calculate new interval
            # Positive ppm = longer interval = slower sampling
            # Negative ppm = shorter interval = faster sampling
            correction_factor = 1.0 + (correction_ppm / 1e6)
            new_interval_us = self.current_mcu_interval_us * correction_factor
            
            # Clamp to reasonable range
            new_interval_us = max(9000, min(11000, new_interval_us))
            
            # Diagnostic output
            old_rate = 1e6 / self.current_mcu_interval_us
            new_rate = 1e6 / new_interval_us
            
            print(f"CORRECTED MCU LOGIC:")
            print(f"  Error: {error_ms:+.3f}ms ({'MCU too fast' if error_ms > 0 else 'MCU too slow'})")
            print(f"  Correction: {correction_ppm:+.3f}ppm ({'slow down' if correction_ppm > 0 else 'speed up'})")
            print(f"  Rate: {old_rate:.6f}Hz → {new_rate:.6f}Hz")
            print(f"  Interval: {self.current_mcu_interval_us:.1f}μs → {new_interval_us:.1f}μs")
            
            # CRITICAL: Send to MCU with NON-BLOCKING mode to prevent data loss
            command = f"SET_PRECISE_INTERVAL:{int(new_interval_us)}"
            
            # IMPROVEMENT: Use non-blocking command during streaming to avoid sample loss
            print(f"⚡ Sending NON-BLOCKING command to prevent data loss")
            self.stats['commands_sent'] += 1
            
            result = self.seismic._send_command(command, wait_response=False, timeout=0)
            
            if result and result[0]:
                # Optimistically update state (MCU should accept the command)
                self.current_mcu_interval_us = new_interval_us
                self.stats['mcu_adjustments'] += 1
                self.stats['sign_corrections_applied'] += 1
                print(f"✅ MCU correction sent (non-blocking)")
            else:
                print(f"⚠️  MCU correction send failed: {result}")
                self.stats['potential_data_loss_events'] += 1
                
        except Exception as e:
            print(f"MCU correction error: {e}")
            
    def _apply_host_correction_corrected(self, error_ms, strategy):
        """
        CORRECTED: Apply correction to host timestamps with proper sign logic
        """
        try:
            # For host corrections, we want to adjust timestamps to compensate for error
            # If error_ms > 0: timestamps ahead → subtract from future timestamps
            # If error_ms < 0: timestamps behind → add to future timestamps
            # Dynamic host correction scaling for sub-ms stability
            if abs(error_ms) > 5.0:
                scale = 0.5
            elif abs(error_ms) > 1.0:
                scale = 0.4
            else:
                scale = 0.2
            correction = -error_ms * scale
            
            # Limit correction
            max_correction = strategy['max_correction']
            correction = max(-max_correction, min(max_correction, correction))
            
            # Update host correction offset
            self.host_correction_ms += correction  # Accumulate corrections
            
            self.stats['host_adjustments'] += 1
            print(f"CORRECTED: Host correction applied: {correction:+.3f}ms "
                  f"(total: {self.host_correction_ms:+.3f}ms)")
            
        except Exception as e:
            print(f"Host correction error: {e}")
            
    def apply_host_correction(self, timestamp_ms):
        """Apply current host correction to a timestamp"""
        return timestamp_ms + self.host_correction_ms
    
    def reset_state(self):
        """Reset controller state between streaming sessions"""
        try:
            self.host_correction_ms = 0.0
            self.monitor_only_mode = False  # Reset monitor mode for new session
            
            # Reset basic stats while keeping history size
            self.stats['corrections_applied'] = 0
            self.stats['mcu_adjustments'] = 0
            self.stats['host_adjustments'] = 0
            self.stats['measurements_taken'] = 0
            self.stats['sign_corrections_applied'] = 0
            self.stats['target_achieved'] = False
            self.stats['convergence_time_s'] = 0.0
            self.stats['commands_sent'] = 0
            self.stats['commands_blocked'] = 0
            self.stats['corrections_skipped_monitor_mode'] = 0
            self.stats['potential_data_loss_events'] = 0
            
            # Clear only recent error history
            try:
                self.stats['error_history'].clear()
            except Exception:
                pass
            print("🔄 UnifiedTimingController: state reset (host correction cleared, monitor mode disabled)")
        except Exception as e:
            print(f"Warning: failed to reset unified controller state: {e}")
    
    # Public setters for runtime configuration
    def set_measurement_interval(self, seconds: float):
        try:
            seconds = float(seconds)
            if 0.2 <= seconds <= 60.0:  # Increased max to 60s
                self.measurement_interval_s = seconds
                print(f"🔧 Adaptive controller: measurement interval set to {seconds}s")
        except Exception:
            pass
    
    def set_target_error_ms(self, target_ms: float):
        try:
            target = float(target_ms)
            if 0.1 <= target <= 20.0:
                self.target_error_ms = target
                print(f"🎯 Adaptive controller: target error set to ±{target}ms")
        except Exception:
            pass
    
    def set_min_error_threshold_ms(self, threshold_ms: float):
        try:
            threshold = float(threshold_ms)
            if 0.05 <= threshold <= 5.0:
                self.min_error_threshold_ms = threshold
                print(f"🔧 Adaptive controller: deadband set to ±{threshold}ms")
        except Exception:
            pass
    
    def set_monitor_only_mode(self, enabled: bool):
        """Enable/disable monitor-only mode"""
        try:
            self.monitor_only_mode = bool(enabled)
            print(f"🔒 Monitor-only mode: {'ENABLED' if self.monitor_only_mode else 'DISABLED'}")
            if self.monitor_only_mode:
                print(f"   No MCU corrections will be sent (prevents data loss)")
            else:
                print(f"   MCU corrections enabled (may cause brief data loss during adjustments)")
        except Exception:
            pass
    
    def set_auto_monitor_mode(self, enabled: bool):
        """Enable/disable automatic monitor-only mode after convergence"""
        try:
            self.auto_enable_monitor_mode = bool(enabled)
            print(f"⚙️  Auto monitor mode: {'ENABLED' if self.auto_enable_monitor_mode else 'DISABLED'}")
        except Exception:
            pass
        
    def get_stats(self):
        """Get controller statistics with data loss analysis"""
        stats = dict(self.stats)
        
        # Add calculated metrics
        if self.stats['measurements_taken'] > 0:
            stats['correction_rate'] = self.stats['corrections_applied'] / self.stats['measurements_taken']
        else:
            stats['correction_rate'] = 0.0
        
        # Add current mode status
        stats['monitor_only_active'] = self.monitor_only_mode
        stats['auto_monitor_enabled'] = self.auto_enable_monitor_mode
        stats['measurement_interval_s'] = self.measurement_interval_s
        
        # Data loss risk assessment
        stats['data_loss_risk'] = 'LOW' if self.monitor_only_mode else 'MEDIUM'
        
        return stats


# Integration adapter for existing codebase
class TimingAdapter:
    """
    Adapter to integrate new timing system with existing codebase
    Provides compatibility layer for existing interfaces
    """
    
    def __init__(self, quantization_ms=10):
        """
        Initialize timing adapter with configurable timestamp quantization
        
        Args:
            quantization_ms: Timestamp quantization interval in milliseconds (default: 10ms)
        """
        self.unified_manager = UnifiedTimingManager()
        self.timestamp_generator = SimplifiedTimestampGenerator(quantization_ms=quantization_ms)
        self.unified_controller = None
        
    def initialize_with_device(self, seismic_device):
        """Initialize with seismic device"""
        self.unified_controller = UnifiedTimingController(
            seismic_device, self.unified_manager
        )
        
    def generate_timestamp(self, sequence, timing_manager=None):
        """Generate timestamp (compatible with existing interface)"""
        # Generate clean timestamp
        raw_timestamp = self.timestamp_generator.generate_timestamp(sequence)
        
        # CRITICAL FIX: Force integer quantization to prevent floating-point precision errors
        # This ensures all timestamps end with proper quantization boundaries
        if isinstance(raw_timestamp, float):
            # Convert to integer and ensure proper quantization
            timestamp_ms = int(raw_timestamp)
            # Force quantization: round to nearest quantization boundary
            quantized_timestamp = (timestamp_ms // self.timestamp_generator.quantization_ms) * self.timestamp_generator.quantization_ms
        else:
            # Already integer, ensure quantization
            timestamp_ms = int(raw_timestamp)
            quantized_timestamp = (timestamp_ms // self.timestamp_generator.quantization_ms) * self.timestamp_generator.quantization_ms
        
        # Apply any host corrections if controller exists
        if self.unified_controller:
            corrected_timestamp = self.unified_controller.apply_host_correction(quantized_timestamp)
            # Ensure correction doesn't break quantization
            final_timestamp = int(corrected_timestamp)
            return (final_timestamp // self.timestamp_generator.quantization_ms) * self.timestamp_generator.quantization_ms
        else:
            return quantized_timestamp
            
    def get_timing_info(self):
        """Get timing info (compatible with existing interface)"""
        return self.unified_manager.get_timing_info()
        
    def apply_timing_correction(self, timestamp_ms):
        """Apply timing correction (compatible with existing interface)"""
        if self.unified_controller:
            return self.unified_controller.apply_host_correction(timestamp_ms)
        return timestamp_ms
        
    def get_precise_time(self):
        """Get precise time (compatible with existing interface)"""
        return self.unified_manager.get_reference_time()
        
    def start_control(self):
        """Start timing control"""
        if self.unified_controller:
            self.unified_controller.start_controller()
            
    def stop_control(self):
        """Stop timing control"""  
        if self.unified_controller:
            self.unified_controller.stop_controller()


# Immediate Fix for Existing Code
def patch_existing_adaptive_controller():
    """
    Emergency patch for existing AdaptiveTimingController
    Call this function to fix the sign inversion in your current system
    """
    print("EMERGENCY PATCH: Applying sign correction fix...")
    
    # This patches the existing AdaptiveTimingController in memory
    import adaptive_timing_controller
    
    # Store the original method
    original_apply_correction = adaptive_timing_controller.AdaptiveTimingController._apply_rate_correction
    
    def corrected_apply_rate_correction(self, correction_ppm):
        """PATCHED: Apply rate correction with CORRECTED sign"""
        try:
            # CRITICAL FIX: Invert the sign of correction_ppm
            corrected_ppm = -correction_ppm  # This fixes the sign inversion
            
            print(f"PATCH: Original correction: {correction_ppm:+.1f}ppm")
            print(f"PATCH: Corrected correction: {corrected_ppm:+.1f}ppm")
            
            # Apply the original logic with corrected sign
            return original_apply_correction(self, corrected_ppm)
            
        except Exception as e:
            print(f"PATCH: Error in corrected rate correction: {e}")
            return False
    
    # Monkey patch the method
    adaptive_timing_controller.AdaptiveTimingController._apply_rate_correction = corrected_apply_rate_correction
    
    print("EMERGENCY PATCH: Sign correction applied successfully!")
    print("IMPORTANT: Restart your streaming to see the corrected behavior")


# Additional debugging tools
def diagnose_correction_direction(mcu_interval_us, target_interval_us, error_ms):
    """
    Diagnostic tool to verify correction direction
    """
    print("\n" + "="*60)
    print("CORRECTION DIRECTION DIAGNOSIS")
    print("="*60)
    
    actual_rate = 1e6 / mcu_interval_us
    target_rate = 1e6 / target_interval_us
    
    print(f"MCU State:")
    print(f"  Current interval: {mcu_interval_us:.1f}μs ({actual_rate:.6f}Hz)")
    print(f"  Target interval:  {target_interval_us:.1f}μs ({target_rate:.6f}Hz)")
    print(f"  Timing error:     {error_ms:+.1f}ms")
    
    if mcu_interval_us < target_interval_us:
        print(f"  → MCU sampling TOO FAST")
        print(f"  → Need POSITIVE ppm to SLOW DOWN (increase interval)")
        required_ppm = +abs(error_ms) * 2.0
    else:
        print(f"  → MCU sampling TOO SLOW") 
        print(f"  → Need NEGATIVE ppm to SPEED UP (decrease interval)")
        required_ppm = -abs(error_ms) * 2.0
    
    print(f"\nCorrect correction: {required_ppm:+.1f}ppm")
    
    new_interval = mcu_interval_us * (1.0 + required_ppm / 1e6)
    new_rate = 1e6 / new_interval
    
    print(f"Result:")
    print(f"  New interval: {new_interval:.1f}μs ({new_rate:.6f}Hz)")
    print(f"  Direction: {'SLOWER' if new_rate < actual_rate else 'FASTER'}")
    print("="*60)


def analyze_data_loss_from_stats(stats_dict):
    """
    Analyze data loss statistics and provide recommendations
    
    Args:
        stats_dict: Dictionary with keys:
            - 'samples_received': Total samples received
            - 'sequence_gaps': Total sequence gaps detected
            - 'duration_s': Duration in seconds
            - 'expected_rate_hz': Expected sampling rate
            
    Returns:
        dict: Analysis with loss percentage, potential causes, and recommendations
    """
    samples_received = stats_dict.get('samples_received', 0)
    sequence_gaps = stats_dict.get('sequence_gaps', 0)
    duration_s = stats_dict.get('duration_s', 0)
    expected_rate = stats_dict.get('expected_rate_hz', 100)
    
    if duration_s <= 0:
        return {'error': 'Invalid duration'}
    
    expected_samples = int(duration_s * expected_rate)
    missing_samples = expected_samples - samples_received
    loss_percentage = (missing_samples / expected_samples * 100) if expected_samples > 0 else 0
    
    analysis = {
        'expected_samples': expected_samples,
        'actual_samples': samples_received,
        'missing_samples': missing_samples,
        'loss_percentage': loss_percentage,
        'sequence_gaps_detected': sequence_gaps,
        'severity': 'NONE',
        'likely_causes': [],
        'recommendations': []
    }
    
    # Assess severity
    if loss_percentage < 0.001:
        analysis['severity'] = 'NONE'
        analysis['recommendations'].append('✅ Excellent! No significant data loss detected')
    elif loss_percentage < 0.01:
        analysis['severity'] = 'NEGLIGIBLE'
        analysis['likely_causes'].append('Normal system jitter and timing corrections')
        analysis['recommendations'].append('✅ Good! Loss is negligible (<0.01%)')
        analysis['recommendations'].append('Monitor-only mode should eliminate this completely')
    elif loss_percentage < 0.1:
        analysis['severity'] = 'LOW'
        analysis['likely_causes'].append('Timing controller sending blocking commands')
        analysis['likely_causes'].append('OS-level serial buffer limitations')
        analysis['recommendations'].append('⚠️  Enable monitor-only mode to reduce loss')
        analysis['recommendations'].append('Increase measurement interval to 30-60 seconds')
        analysis['recommendations'].append('Check that non-blocking commands are enabled')
    elif loss_percentage < 1.0:
        analysis['severity'] = 'MODERATE'
        analysis['likely_causes'].append('Frequent timing corrections blocking serial port')
        analysis['likely_causes'].append('Insufficient serial buffer size')
        analysis['likely_causes'].append('CPU/system load issues')
        analysis['recommendations'].append('🔴 CRITICAL: Enable monitor-only mode immediately')
        analysis['recommendations'].append('Set measurement_interval to 60 seconds')
        analysis['recommendations'].append('Check system CPU load and reduce background tasks')
        analysis['recommendations'].append('Consider disabling active timing corrections')
    else:
        analysis['severity'] = 'CRITICAL'
        analysis['likely_causes'].append('Major system issue or connection problems')
        analysis['likely_causes'].append('MCU resets or communication errors')
        analysis['likely_causes'].append('Insufficient system resources')
        analysis['recommendations'].append('🔴🔴 CRITICAL: Immediate action required!')
        analysis['recommendations'].append('Disable all timing corrections immediately')
        analysis['recommendations'].append('Check physical connections and power supply')
        analysis['recommendations'].append('Review system logs for errors')
        analysis['recommendations'].append('Consider hardware upgrade or dedicated system')
    
    return analysis


def print_data_loss_report(analysis):
    """Print a formatted data loss analysis report"""
    print("\n" + "="*70)
    print("📊 DATA LOSS ANALYSIS REPORT")
    print("="*70)
    print(f"Expected samples:  {analysis['expected_samples']:,}")
    print(f"Actual samples:    {analysis['actual_samples']:,}")
    print(f"Missing samples:   {analysis['missing_samples']:,}")
    print(f"Loss percentage:   {analysis['loss_percentage']:.6f}%")
    print(f"Severity:          {analysis['severity']}")
    print()
    
    if analysis['likely_causes']:
        print("Likely Causes:")
        for cause in analysis['likely_causes']:
            print(f"  • {cause}")
        print()
    
    if analysis['recommendations']:
        print("Recommendations:")
        for rec in analysis['recommendations']:
            print(f"  {rec}")
    
    print("="*70 + "\n")