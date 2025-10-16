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
from datetime import datetime, timezone
import calendar
import datetime
import subprocess

class UnifiedTimingManager:
    """
    Single timing authority that coordinates all timing corrections
    Eliminates circular feedback loops by centralizing control
    Enhanced with MCU firmware features: PPS-locked start, calibration management, etc.
    """
    
    def __init__(self):
        # Timing reference sources
        self.reference_source = "UNKNOWN"  # GPS, NTP, or SYSTEM
        self.reference_accuracy_us = 1000000  # 1 second default
        self.last_reference_update = 0
        self.reference_check_interval = 30.0  # Check every 30 seconds for timing source changes
        
        # NEW: MCU timing state machine thresholds
        self.timing_state_machine = {
            'current_state': 'RAW',  # ACTIVE, HOLDOVER, CAL, RAW
            'state_transitions': {
                'ACTIVE': {'timeout_ms': 1500, 'accuracy_us': 1},
                'HOLDOVER': {'timeout_ms': 60000, 'accuracy_us': 10},
                'CAL': {'timeout_ms': 300000, 'accuracy_us': 100},
                'RAW': {'timeout_ms': float('inf'), 'accuracy_us': 1000000}
            },
            'last_pps_time': 0,
            'state_history': []
        }
        
        # NEW: Temperature-aware calibration
        self.temperature_calibration = {
            'enabled': False,
            'base_temp_c': 25.0,
            'temp_coefficient_ppm_per_c': 0.0,
            'current_temp_c': 25.0
        }
        
        # NEW: Smooth no-PPS degradation with EMA
        self.oscillator_calibration_ppm = 0.0
        self.calibration_ema_alpha = 0.01  # EMA smoothing factor
        self.last_calibration_update = 0
        
        # Master timing state
        self.master_offset_ms = 0.0  # Current offset from reference time
        self.master_drift_ppm = 0.0  # Current drift rate
        self.last_measurement_time = 0.0
        
        # Single Kalman filter for unified state estimation - OPTIMIZED FOR STABILITY
        self.kalman_state = {
            'offset_ms': 0.0,
            'drift_rate_ppm': 0.0,
            'offset_variance': 10.0,        # Much more conservative for stability
            'drift_variance': 0.1,           # Much more conservative for stability
            'process_noise_offset': 0.05,   # Much more conservative to prevent oscillations
            'process_noise_drift': 0.001,   # Much more conservative for smoother adaptation
            'measurement_noise': 2.0        # Much more conservative - trust measurements less
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
    
    def _get_reference_time_for_error_measurement(self):
        """Get reference time for error measurement - use MCU time when MCU timestamp mode is enabled"""
        try:
            # Check if MCU timestamp mode is enabled
            if hasattr(self, 'seismic_device') and self.seismic_device:
                if hasattr(self.seismic_device, 'timing_adapter'):
                    if hasattr(self.seismic_device.timing_adapter, 'timestamp_generator'):
                        timestamp_generator = self.seismic_device.timing_adapter.timestamp_generator
                        if getattr(timestamp_generator, 'mcu_timestamp_mode', False):
                            # MCU timestamp mode is enabled - disable error measurement to prevent drift
                            # This prevents drift between MCU timestamps and host reference time
                            print(f"🔧 DISABLING ERROR MEASUREMENT (MCU timestamp mode enabled)")
                            
                            # CRITICAL FIX: When MCU timestamp mode is enabled, we should NOT compare
                            # MCU-derived timestamps to host reference time as this causes drift.
                            # Instead, we disable error measurement entirely when MCU timestamp mode is active.
                            
                            # Return None to signal that error measurement should be skipped
                            return None
                        else:
                            # MCU timestamp mode is disabled - use standard reference time
                            return self.get_reference_time()
            
            # Fallback to standard reference time
            return self.get_reference_time()
        except Exception as e:
            print(f"Warning: Error in _get_reference_time_for_error_measurement: {e}")
            return self.get_reference_time()
            
    def _get_chrony_time(self):
        """Get chrony-corrected time with proper GPS PPS offset"""
        try:
            result = subprocess.run(['chronyc', 'tracking'],
                                  capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                # Parse chrony output to extract offset
                offset_seconds = 0.0
                for line in result.stdout.split('\n'):
                    if 'Last offset' in line:
                        # Extract offset value: "Last offset     : -0.000005699 seconds"
                        parts = line.split(':')
                        if len(parts) >= 2:
                            offset_str = parts[1].strip().split()[0]
                            try:
                                offset_seconds = float(offset_str)
                                break
                            except ValueError:
                                continue

                # Apply offset correction to get GPS-corrected time
                gps_corrected_time = time.time() + offset_seconds
                print(f"🔧 GPS TIME CORRECTION: chrony offset {offset_seconds:.9f}s applied")
                return gps_corrected_time
            else:
                print(f"🔧 CHRONYC ERROR: return code {result.returncode}")
                return time.time()
        except Exception as e:
            print(f"🔧 CHRONYC ERROR: {e}")
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
                
                # CRITICAL FIX: Proactive wraparound detection
                # Check if we're dealing with a sequence that suggests wraparound occurred
                if hasattr(self, '_last_sequence_checked'):
                    if self._last_sequence_checked > 65000 and sample_sequence < 1000:
                        print(f"🚨 PROACTIVE WRAPAROUND DETECTION: {self._last_sequence_checked} -> {sample_sequence}")
                        print(f"   Detected wraparound in timing manager - resetting state")
                        
                        # Reset timing state to prevent extreme errors
                        self.kalman_state['offset_ms'] = 0.0
                        self.kalman_state['drift_rate_ppm'] = 0.0
                        self.kalman_state['offset_variance'] = 100.0
                        self.kalman_state['drift_variance'] = 1.0
                        
                        # Clear correction history to prevent contamination
                        self.correction_history.clear()
                        
                        print(f"   Timing state reset - extreme errors prevented")
                        
                        # Also try to reset the timestamp generator if it exists
                        # This is a safety measure in case the generator is stuck
                        try:
                            if hasattr(self, '_timestamp_generator_ref'):
                                generator = self._timestamp_generator_ref()
                                if generator:
                                    generator.force_wraparound_recovery(sample_sequence)
                                    print(f"   Timestamp generator also reset")
                        except Exception as e:
                            print(f"   Warning: Could not reset timestamp generator: {e}")
                
                self._last_sequence_checked = sample_sequence
                
                # CRITICAL FIX: Use MCU-aware reference time for error measurement
                # This prevents drift between MCU timestamps and host reference time
                reference_time = self._get_reference_time_for_error_measurement()
                
                # Check if error measurement should be disabled (MCU timestamp mode)
                if reference_time is None:
                    print(f"🔧 ERROR MEASUREMENT DISABLED (MCU timestamp mode active)")
                    return {
                        'raw_error_ms': 0.0,
                        'filtered_error_ms': 0.0,
                        'drift_rate_ppm': 0.0,
                        'confidence': 1.0
                    }
                
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
                
            # Determine correction method - prefer MCU control to minimize rate chasing
            if urgency >= 3:  # Emergency only (>100ms error)
                method = "MCU"
                max_correction = min(20.0, error_ms * 0.1)  # Very gentle emergency correction
            elif urgency >= 2:  # High urgency (>50ms error)
                method = "MCU"
                max_correction = min(10.0, error_ms * 0.05)  # Minimal correction
            else:
                # Normal operation - let MCU be the PLL, minimal host intervention
                method = "MCU"
                max_correction = min(5.0, error_ms * 0.02)  # Barely any correction
                
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
    
    # NEW: MCU firmware feature methods
    
    def update_timing_state_machine(self, pps_valid: bool, pps_age_ms: float, current_temp_c: float = None):
        """Update timing state machine based on PPS status and age"""
        current_time = time.time()
        
        # Update temperature if provided
        if current_temp_c is not None:
            self.temperature_calibration['current_temp_c'] = current_temp_c
        
        # Update PPS time
        if pps_valid:
            self.timing_state_machine['last_pps_time'] = current_time
        
        # Determine new state based on PPS age
        pps_age_ms = (current_time - self.timing_state_machine['last_pps_time']) * 1000
        old_state = self.timing_state_machine['current_state']
        
        if pps_valid and pps_age_ms < self.timing_state_machine['state_transitions']['ACTIVE']['timeout_ms']:
            new_state = 'ACTIVE'
        elif pps_valid and pps_age_ms < self.timing_state_machine['state_transitions']['HOLDOVER']['timeout_ms']:
            new_state = 'HOLDOVER'
        elif pps_age_ms < self.timing_state_machine['state_transitions']['CAL']['timeout_ms']:
            new_state = 'CAL'
        else:
            new_state = 'RAW'
        
        # Update state if changed
        if new_state != old_state:
            self.timing_state_machine['current_state'] = new_state
            self.timing_state_machine['state_history'].append({
                'time': current_time,
                'from_state': old_state,
                'to_state': new_state,
                'pps_age_ms': pps_age_ms
            })
            
            # Keep only last 100 transitions
            if len(self.timing_state_machine['state_history']) > 100:
                self.timing_state_machine['state_history'] = self.timing_state_machine['state_history'][-100:]
            
            print(f"🔄 TIMING STATE CHANGE: {old_state} → {new_state} (PPS age: {pps_age_ms:.1f}ms)")
        
        return new_state
    
    def get_timing_state_info(self):
        """Get current timing state machine information"""
        current_time = time.time()
        pps_age_ms = (current_time - self.timing_state_machine['last_pps_time']) * 1000
        
        return {
            'current_state': self.timing_state_machine['current_state'],
            'pps_age_ms': pps_age_ms,
            'accuracy_us': self.timing_state_machine['state_transitions'][self.timing_state_machine['current_state']]['accuracy_us'],
            'state_history': self.timing_state_machine['state_history'][-10:],  # Last 10 transitions
            'temperature_c': self.temperature_calibration['current_temp_c'],
            'oscillator_calibration_ppm': self.oscillator_calibration_ppm
        }
    
    def update_oscillator_calibration(self, new_ppm: float, source: str = 'unknown'):
        """Update oscillator calibration with EMA smoothing"""
        current_time = time.time()
        
        # Apply EMA smoothing for smooth degradation
        if self.last_calibration_update > 0:
            alpha = self.calibration_ema_alpha
            self.oscillator_calibration_ppm = (
                (1 - alpha) * self.oscillator_calibration_ppm + 
                alpha * new_ppm
            )
        else:
            self.oscillator_calibration_ppm = new_ppm
        
        # Apply temperature compensation if enabled
        if self.temperature_calibration['enabled']:
            temp_diff = self.temperature_calibration['current_temp_c'] - self.temperature_calibration['base_temp_c']
            temp_compensation = temp_diff * self.temperature_calibration['temp_coefficient_ppm_per_c']
            self.oscillator_calibration_ppm += temp_compensation
        
        # Apply hard limits (±200 ppm)
        self.oscillator_calibration_ppm = max(-200.0, min(200.0, self.oscillator_calibration_ppm))
        
        self.last_calibration_update = current_time
        
        print(f"🔧 OSCILLATOR CALIBRATION: {new_ppm:.2f} → {self.oscillator_calibration_ppm:.2f} ppm (source: {source})")
        
        return self.oscillator_calibration_ppm
    
    def set_temperature_calibration(self, base_temp_c: float, temp_coefficient_ppm_per_c: float):
        """Configure temperature-aware calibration"""
        self.temperature_calibration['base_temp_c'] = base_temp_c
        self.temperature_calibration['temp_coefficient_ppm_per_c'] = temp_coefficient_ppm_per_c
        self.temperature_calibration['enabled'] = True
        
        print(f"🌡️  TEMPERATURE CALIBRATION: Base {base_temp_c}°C, {temp_coefficient_ppm_per_c:.3f} ppm/°C")
    
    def get_calibration_info(self):
        """Get current calibration information"""
        return {
            'oscillator_calibration_ppm': self.oscillator_calibration_ppm,
            'last_calibration_update': self.last_calibration_update,
            'temperature_calibration': dict(self.temperature_calibration),
            'calibration_ema_alpha': self.calibration_ema_alpha
        }
    
    def apply_bounded_host_nudge(self, nudge_ppm: float, pps_locked: bool = False):
        """Apply bounded host nudge with rate change rejection"""
        # Reject large changes while PPS locked
        if pps_locked and abs(nudge_ppm) > 50:
            print(f"🚫 RATE CHANGE REJECTED: {nudge_ppm:.1f} ppm > 50 ppm limit (PPS locked)")
            return False
        
        # Apply bounded adjustment
        bounded_nudge = max(-50.0, min(50.0, nudge_ppm))
        
        if abs(bounded_nudge) > 0.1:  # Only apply if significant
            self.update_oscillator_calibration(
                self.oscillator_calibration_ppm + bounded_nudge, 
                'host_nudge'
            )
            print(f"🔧 BOUNDED HOST NUDGE: {nudge_ppm:.1f} → {bounded_nudge:.1f} ppm")
            return True
        
        return False


class SimplifiedTimestampGenerator:
    """
    Simplified timestamp generator that ONLY generates timestamps
    No internal corrections - all corrections handled by UnifiedTimingManager
    Enhanced with 64-bit timestamps and MCU firmware features
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
        
        # NEW: 64-bit timestamp support to avoid wrap boundary edge cases
        self.reference_time_64 = None  # 64-bit microseconds since epoch
        self.reference_sequence = None
        self.last_sequence = None
        self.is_initialized = False
        self.lock = threading.Lock()
        
        # NEW: MCU timestamp integration
        self.mcu_timestamp_mode = False
        self.mcu_timestamp_offset_us = 0  # Offset between MCU and host timestamps
        
        # NEW: UTC timestamp policy
        self.utc_stamping_enabled = True
        self.utc_offset_seconds = 0  # UTC offset from system time
        self.last_utc_sync_time = 0  # Last UTC synchronization time
        
        # NEW: Continuous tiny phase servo
        self.phase_servo_enabled = True
        self.phase_clamp_us = 20.0  # ±20 μs/sample clamp
        self.current_phase_offset_us = 0.0
        
        # Statistics only
        self.stats = {
            'samples_processed': 0,
            'sequence_resets': 0,
            'wraparounds_detected': 0,
            'last_timestamp': None,  # Track last generated timestamp for monitoring
            'last_sequence': None,  # Track last sequence for wraparound detection
            'max_sequence_seen': 0,   # Track highest sequence seen for debugging
            'quantization_ms': quantization_ms,  # Store quantization setting
            'mcu_timestamp_mode': False,
            'phase_servo_offset_us': 0.0,
            'phase_clamp_violations': 0,
            'mcu_offset_updates': 0,  # Track number of offset updates
            'last_offset_drift_us': 0.0,  # Track last detected drift
            'mcu_timestamp_offset_us': 0  # Current offset between MCU and host time
        }
        
    def generate_timestamp(self, sequence_number, mcu_timestamp_us=None):
        """
        Generate clean timestamp based ONLY on sequence progression
        Enhanced with 64-bit timestamps and MCU timestamp integration
        No corrections applied here - purely mathematical generation
        """
        with self.lock:
            self.stats['samples_processed'] += 1
            current_time = time.time()
            
            # NEW: Use MCU timestamp if available and in MCU mode
            if self.mcu_timestamp_mode and mcu_timestamp_us is not None:
                # CRITICAL FIX: Calculate offset on first sample to align MCU and host time
                if not self.is_initialized:
                    # IMPROVED: Account for processing delay by estimating actual sample time
                    # The sample was captured at some point in the past, and we're processing it now
                    # with some delay (serial transmission + processing)
                    
                    # Use current_time as best estimate, but subtract typical processing delay
                    # Typical delay is 10-20ms for serial + processing
                    # We'll use a conservative 15ms estimate
                    estimated_processing_delay_ms = 15
                    host_time_us = int((current_time - estimated_processing_delay_ms/1000) * 1000000)
                    
                    self.mcu_timestamp_offset_us = host_time_us - mcu_timestamp_us
                    self.last_offset_update_time = current_time
                    self.stats['mcu_timestamp_offset_us'] = self.mcu_timestamp_offset_us  # Update stats
                    print(f"🔧 MCU TIMESTAMP OFFSET CALCULATED: {self.mcu_timestamp_offset_us}μs")
                    print(f"   Host time (adjusted): {host_time_us}μs, MCU time: {mcu_timestamp_us}μs")
                    print(f"   Processing delay estimate: {estimated_processing_delay_ms}ms")
                    print(f"   This offset will remain CONSTANT (both clocks are PPS-synchronized)")
                
                # IMPROVED FIX: Gentle servo to compensate for residual PPM errors
                # Both clocks are PPS-synchronized, but small PPM calibration errors can accumulate
                # We apply gentle corrections to keep timestamps aligned without oscillation
                #
                # Strategy (UPDATED after firmware fix):
                # 1. Check drift every 60 seconds 
                # 2. If drift < 100ms: NO correction (firmware handles it)
                # 3. If drift > 100ms: full recalculation (likely clock reset or major issue)
                #
                # The firmware fix now handles cumulative PPM correction properly,
                # so we only intervene for major discontinuities (>100ms)
                if hasattr(self, 'last_offset_update_time'):
                    time_since_last_update = current_time - self.last_offset_update_time
                    if time_since_last_update > 60.0:  # Check every 60 seconds
                        # Measure actual drift by comparing current timestamp alignment
                        # Subtract processing delay to get more accurate measurement
                        host_time_us = int((current_time - 0.015) * 1000000)
                        expected_offset_us = host_time_us - mcu_timestamp_us
                        offset_drift_us = expected_offset_us - self.mcu_timestamp_offset_us
                        
                        # Only update last_offset_update_time to prevent constant recalculation
                        self.last_offset_update_time = current_time
                        
                        # Calculate drift rate for diagnostics
                        drift_rate_ppm = (offset_drift_us / time_since_last_update) / 1000
                        
                        if abs(offset_drift_us) > 100000:
                            # MAJOR discontinuity (>100ms) - full recalculation
                            self.mcu_timestamp_offset_us = expected_offset_us
                            self.stats['mcu_offset_updates'] += 1
                            self.stats['last_offset_drift_us'] = offset_drift_us
                            self.stats['mcu_timestamp_offset_us'] = self.mcu_timestamp_offset_us
                            print(f"⚠️  LARGE OFFSET DISCONTINUITY: {offset_drift_us:+.0f}μs")
                            print(f"   Offset fully recalculated: {self.mcu_timestamp_offset_us}μs")
                        else:
                            # Small drift <100ms - firmware handles it via cumulative PPM correction
                            if abs(offset_drift_us) > 1000:  # >1ms
                                print(f"🔍 Offset drift: {offset_drift_us:+.0f}μs over {time_since_last_update:.0f}s ({drift_rate_ppm:+.1f} ppm) - firmware correcting")
                        
                        self.last_offset_update_time = current_time
                
                # Convert MCU timestamp to host time reference
                host_timestamp_us = mcu_timestamp_us + self.mcu_timestamp_offset_us
                timestamp_s = host_timestamp_us / 1000000.0
            else:
                timestamp_s = current_time
            
            # CRITICAL FIX: Proactive wraparound detection at the entry point
            if self.is_initialized and self.last_sequence is not None:
                if self.last_sequence > 65000 and sequence_number < 1000:
                    print(f"🚨 PROACTIVE WRAPAROUND DETECTION IN GENERATOR: {self.last_sequence} -> {sequence_number}")
                    print(f"   Forcing wraparound recovery to prevent data loss")
                    
                    # Force wraparound recovery (uses last_timestamp for continuity)
                    self.force_wraparound_recovery(sequence_number)
                    
                    # CRITICAL FIX: Calculate expected timestamp, don't use current_time
                    # Continue from last timestamp + one interval
                    if self.stats.get('last_timestamp') is not None:
                        expected_timestamp_s = self.stats['last_timestamp'] + self.expected_interval_s
                        timestamp_ms = int(expected_timestamp_s * 1000)
                    else:
                        # Fallback if no last timestamp
                        timestamp_ms = int(timestamp_s * 1000)
                    
                    quantized_timestamp_ms = round(timestamp_ms / self.quantization_ms) * self.quantization_ms
                    self.stats['last_timestamp'] = quantized_timestamp_ms / 1000.0
                    return quantized_timestamp_ms
            
            # ADDITIONAL FIX: Check for sequence 65535 -> 0 transition
            if self.is_initialized and self.last_sequence is not None:
                if self.last_sequence == 65535 and sequence_number == 0:
                    print(f"🚨 DIRECT WRAPAROUND DETECTION: {self.last_sequence} -> {sequence_number}")
                    print(f"   Detected exact 65535 -> 0 transition")
                    
                    # Force wraparound recovery (uses last_timestamp for continuity)
                    self.force_wraparound_recovery(sequence_number)
                    
                    # CRITICAL FIX: Calculate expected timestamp, don't use current_time
                    # Continue from last timestamp + one interval
                    if self.stats.get('last_timestamp') is not None:
                        expected_timestamp_s = self.stats['last_timestamp'] + self.expected_interval_s
                        timestamp_ms = int(expected_timestamp_s * 1000)
                    else:
                        # Fallback if no last timestamp
                        timestamp_ms = int(timestamp_s * 1000)
                    
                    quantized_timestamp_ms = round(timestamp_ms / self.quantization_ms) * self.quantization_ms
                    self.stats['last_timestamp'] = quantized_timestamp_ms / 1000.0
                    return quantized_timestamp_ms
            
            # Initialize on first sample with 64-bit timestamp
            if not self.is_initialized:
                self.reference_time_64 = int(timestamp_s * 1000000)  # 64-bit microseconds
                self.reference_sequence = sequence_number
                self.last_sequence = sequence_number
                self.is_initialized = True
                # Apply quantization to first sample too
                timestamp_ms = int(timestamp_s * 1000)
                quantized_timestamp_ms = round(timestamp_ms / self.quantization_ms) * self.quantization_ms
                self.stats['last_timestamp'] = quantized_timestamp_ms / 1000.0
                return quantized_timestamp_ms
            
            # SIMPLIFIED: Let MCU handle sequence validation
            if self.last_sequence is not None:
                # Calculate sequence progression (let MCU handle validation)
                sequence_diff = self._calculate_sequence_diff(
                    self.reference_sequence, sequence_number
                )
                
                # CRITICAL FIX: If sequence_diff is -1, it means wraparound was detected
                # Use current time as base to prevent massive timestamp jumps
                if sequence_diff == -1:
                    # Wraparound detected - use current time as base
                    timestamp_s = current_time
                    # Update reference time to current time
                    self.reference_time_64 = int(timestamp_s * 1000000)
                else:
                    # Generate timestamp based on pure sequence progression using 64-bit arithmetic
                    interval_us = int(self.expected_interval_s * 1000000)
                    timestamp_us_64 = self.reference_time_64 + (sequence_diff * interval_us)
                    timestamp_s = timestamp_us_64 / 1000000.0
            else:
                # First time with sequence tracking
                timestamp_s = current_time
                self.reference_time_64 = int(timestamp_s * 1000000)
            
            # NEW: Apply continuous tiny phase servo
            if self.phase_servo_enabled:
                # Calculate phase offset based on sequence progression
                expected_time_s = self.reference_time_64 / 1000000.0 + (sequence_number - self.reference_sequence) * self.expected_interval_s
                phase_error_us = (timestamp_s - expected_time_s) * 1000000
                
                # Apply phase clamp
                if abs(phase_error_us) > self.phase_clamp_us:
                    phase_error_us = max(-self.phase_clamp_us, min(self.phase_clamp_us, phase_error_us))
                    self.stats['phase_clamp_violations'] += 1
                
                # Update phase offset
                self.current_phase_offset_us = phase_error_us
                self.stats['phase_servo_offset_us'] = self.current_phase_offset_us
            
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
        ROBUST: Proper 16-bit wraparound handling for continuous operation
        Handles the critical 65535 -> 0 transition correctly
        """
        # Handle 16-bit wraparound (0-65535)
        MAX_SEQUENCE = 65536
        
        if current_seq >= ref_seq:
            # Forward progression - normal case
            diff = current_seq - ref_seq
            
            # Check for wraparound only if we're near the boundary
            if ref_seq > 60000 and current_seq < 10000:
                # Potential wraparound near 65535 boundary
                wraparound_diff = current_seq - (ref_seq + MAX_SEQUENCE)
                if abs(wraparound_diff) < abs(diff):
                    diff = wraparound_diff
                    self.stats['wraparounds_detected'] += 1
                    print(f"🔄 WRAPAROUND DETECTED: {ref_seq} -> {current_seq} (diff: {diff})")
            
            return diff
        else:
            # Backward progression - could be wraparound or reset
            # CRITICAL FIX: Properly detect wraparound at 65535 -> 0 boundary
            if ref_seq >= 65000 and current_seq <= 1000:
                # This is likely a wraparound (65535 -> 0)
                diff = current_seq - (ref_seq - MAX_SEQUENCE)
                if 0 <= diff <= 1000:  # Reasonable forward progression
                    self.stats['wraparounds_detected'] += 1
                    print(f"🔄 WRAPAROUND DETECTED: {ref_seq} -> {current_seq} (diff: {diff})")
                    print(f"   Updating reference sequence to prevent timestamp jumps")
                    
                    # CRITICAL: Update reference sequence to prevent future timestamp errors
                    self.reference_sequence = current_seq
                    self.reference_time = time.time()
                    
                    # CRITICAL FIX: Return -1 to signal wraparound detected
                    # This will trigger special handling in timestamp generation
                    return -1
            
            # Check if this is a large backward jump (likely reset)
            step_size = ref_seq - current_seq
            if step_size > 10000:  # Large backward jump - likely reset
                print(f"🚨 SEQUENCE RESET DETECTED: {ref_seq} -> {current_seq} (step: {step_size})")
                print(f"   Resetting timestamp generator state")
                
                # Reset the generator state
                self.reference_sequence = current_seq
                self.reference_time = time.time()
                self.stats['sequence_resets'] += 1
                return 0
            else:
                # Small backward step - might be timing glitch, ignore
                print(f"⚠️  SMALL BACKWARD STEP: {ref_seq} -> {current_seq} (step: {step_size})")
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
    
    def force_wraparound_recovery(self, current_sequence):
        """Force recovery from stuck sequence state (e.g., after 65535)"""
        with self.lock:
            print(f"🔧 FORCING WRAPAROUND RECOVERY")
            print(f"   Current sequence: {current_sequence}")
            print(f"   Last sequence: {self.last_sequence}")
            print(f"   Reference sequence: {self.reference_sequence}")
            
            # CRITICAL FIX: Calculate expected next timestamp, don't jump to current time
            # Continue from the last timestamp + one interval
            if self.stats.get('last_timestamp') is not None:
                # Use last timestamp and add one interval for continuity
                expected_next_time_s = self.stats['last_timestamp'] + self.expected_interval_s
                self.reference_time_64 = int(expected_next_time_s * 1000000)
                print(f"   Continuing from last_timestamp: {self.stats['last_timestamp']:.6f}s")
                print(f"   Expected next time: {expected_next_time_s:.6f}s")
            else:
                # Fallback: use current time if no last timestamp
                self.reference_time_64 = int(time.time() * 1000000)
                print(f"   No last_timestamp, using current time")
            
            # Reset to current sequence
            self.reference_sequence = current_sequence
            self.last_sequence = current_sequence
            self.is_initialized = True
            
            # Update stats
            self.stats['sequence_resets'] += 1
            self.stats['last_sequence'] = current_sequence
            self.stats['max_sequence_seen'] = max(self.stats['max_sequence_seen'], current_sequence)
            
            print(f"✅ Wraparound recovery complete - reset to sequence {current_sequence}")
    
    # NEW: MCU firmware feature methods
    
    def adjust_mcu_offset(self, adjustment_us: int):
        """Manually adjust the MCU timestamp offset by a specified amount"""
        with self.lock:
            old_offset = self.mcu_timestamp_offset_us
            self.mcu_timestamp_offset_us += adjustment_us
            self.stats['mcu_timestamp_offset_us'] = self.mcu_timestamp_offset_us
            self.stats['mcu_offset_updates'] += 1
            print(f"🔧 MCU OFFSET MANUALLY ADJUSTED")
            print(f"   Old offset: {old_offset}μs")
            print(f"   Adjustment: {adjustment_us:+d}μs")
            print(f"   New offset: {self.mcu_timestamp_offset_us}μs")
    
    def enable_mcu_timestamp_mode(self, enabled: bool = True, offset_us: int = 0):
        """Enable MCU timestamp mode with optional offset"""
        with self.lock:
            self.mcu_timestamp_mode = enabled
            self.mcu_timestamp_offset_us = offset_us
            self.stats['mcu_timestamp_mode'] = enabled
            
            if enabled:
                print(f"🔧 MCU TIMESTAMP MODE ENABLED (offset: {offset_us}μs)")
            else:
                print("🔧 MCU TIMESTAMP MODE DISABLED")
    
    def set_phase_servo(self, enabled: bool = True, clamp_us: float = 20.0):
        """Configure continuous tiny phase servo"""
        with self.lock:
            self.phase_servo_enabled = enabled
            self.phase_clamp_us = clamp_us
            
            if enabled:
                print(f"🔧 PHASE SERVO ENABLED (±{clamp_us}μs clamp)")
            else:
                print("🔧 PHASE SERVO DISABLED")
    
    def get_phase_servo_status(self):
        """Get phase servo status and statistics"""
        with self.lock:
            return {
                'enabled': self.phase_servo_enabled,
                'clamp_us': self.phase_clamp_us,
                'current_offset_us': self.current_phase_offset_us,
                'clamp_violations': self.stats['phase_clamp_violations']
            }
    
    def get_mcu_timestamp_status(self):
        """Get MCU timestamp mode status"""
        with self.lock:
            return {
                'enabled': self.mcu_timestamp_mode,
                'offset_us': self.mcu_timestamp_offset_us
            }
    
    def enable_utc_stamping(self, enabled: bool = True):
        """Enable UTC timestamp policy with MCU timestamp as primary time axis"""
        with self.lock:
            self.utc_stamping_enabled = enabled
            if enabled:
                print("🌍 UTC STAMPING POLICY ENABLED: MCU timestamp as primary time axis")
            else:
                print("🌍 UTC STAMPING POLICY DISABLED")
    
    def set_utc_offset(self, offset_seconds: float):
        """Set UTC offset from system time"""
        with self.lock:
            self.utc_offset_seconds = offset_seconds
            self.last_utc_sync_time = time.time()
            print(f"🌍 UTC OFFSET SET: {offset_seconds:.6f} seconds")
    
    def get_utc_timestamp(self, timestamp_s: float) -> datetime:
        """Convert timestamp to UTC datetime"""
        with self.lock:
            if self.utc_stamping_enabled:
                # Apply UTC offset
                utc_timestamp_s = timestamp_s + self.utc_offset_seconds
                return datetime.datetime.fromtimestamp(utc_timestamp_s, tz=timezone.utc)
            else:
                return datetime.datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
    
    def get_utc_status(self):
        """Get UTC stamping policy status"""
        with self.lock:
            # Get current UTC timestamp without nested lock
            current_time = time.time()
            if self.utc_stamping_enabled:
                utc_timestamp_s = current_time + self.utc_offset_seconds
                current_utc = datetime.datetime.fromtimestamp(utc_timestamp_s, tz=timezone.utc).isoformat()
            else:
                current_utc = datetime.datetime.fromtimestamp(current_time, tz=timezone.utc).isoformat()
            
            return {
                'enabled': self.utc_stamping_enabled,
                'offset_seconds': self.utc_offset_seconds,
                'last_sync_time': self.last_utc_sync_time,
                'current_utc': current_utc
            }


class UnifiedTimingController:
    """
    CORRECTED: Single timing controller with proper correction sign logic
    Enhanced for MCU firmware features
    """
    
    def __init__(self, seismic_device, timing_manager):
        self.seismic = seismic_device
        self.timing_manager = timing_manager
        self.running = False
        self.controller_thread = None
        self.start_time = None  # Will be set when controller starts
        
        # Control parameters - OPTIMIZED for minimal rate chasing (let MCU be PLL)
        self.measurement_interval_s = 5.0  # Measure every 5 seconds (reduced from 0.5s)
        self.target_error_ms = 2.0        # Desired steady-state absolute error (±2ms, relaxed from ±0.3ms)
        self.min_error_threshold_ms = 1.0  # Deadband to avoid chattering (±1ms, increased from ±0.1ms)
        
        # MCU control state
        self.current_mcu_interval_us = 10000.0  # 100Hz default
        self.target_mcu_interval_us = 10000.0
        
        # Host correction state
        self.host_correction_ms = 0.0
        
        # NEW: MCU firmware integration
        self.mcu_integration = {
            'enabled': False,
            'timing_source': 'UNKNOWN',
            'accuracy_us': 1000000,
            'calibration_ppm': 0.0,
            'pps_valid': False,
            'boot_id': None,
            'stream_id': None,
            'temperature_c': 25.0,
            'buffer_overflows': 0,
            'samples_skipped': 0
        }
        
        # NEW: Adaptive timing control with bounded adjustments (minimal rate chasing)
        self.adaptive_control = {
            'enabled': True,
            'target_rate': 100.0,
            'rate_tolerance_ppm': 200,  # ±200 ppm tolerance (increased from ±50 ppm)
            'last_rate_adjustment': 0,
            'adjustment_cooldown_ms': 10000,  # 10 second cooldown (increased from 1s)
            'max_adjustment_ppm': 20,  # Maximum single adjustment (reduced from 50)
            'step_changes_enabled': False,  # Disable step changes to reduce chasing
            'small_nudges_enabled': True
        }
        
        # NEW: Phase servo integration
        self.phase_servo = {
            'enabled': True,
            'clamp_us': 20.0,
            'current_offset_us': 0.0,
            'violations': 0
        }
        
        # Statistics - ENHANCED for performance monitoring
        self.stats = {
            'corrections_applied': 0,
            'mcu_adjustments': 0,
            'host_adjustments': 0,
            'measurements_taken': 0,
            'sign_corrections_applied': 0,  # Track corrections with proper sign
            'error_history': deque(maxlen=100),  # Track recent errors for analysis
            'convergence_time_s': 0.0,  # Time to reach target_error_ms
            'target_achieved': False,  # Whether ±10ms target has been reached
            'mcu_timestamp_mode': False,
            'phase_servo_active': False,
            'adaptive_adjustments': 0,
            'bounded_adjustments': 0,
            'rate_rejections': 0
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
                    
                    # SIMPLIFIED: Let MCU handle sequence validation
                    # No proactive sequence checking - MCU already validates sequences
                    
                    return sample
        except:
            pass
        return None
        
    def _apply_corrections(self, error_data, strategy):
        """Apply corrections based on unified strategy"""
        try:
            error_ms = error_data['filtered_error_ms']
            
            # SIMPLIFIED SANITY CHECK: Only prevent extremely large errors
            if abs(error_ms) > 1000:  # More than 1 second error is definitely wrong
                print(f"🚨 EXTREME ERROR: {error_ms:+.1f}ms - skipping correction")
                print(f"   This is likely a system error, not a timing issue")
                return
            
            # Log large errors for monitoring (but don't skip corrections)
            if abs(error_ms) > 100:  # Log large errors for monitoring
                print(f"⚠️  LARGE ERROR: {error_ms:+.1f}ms - applying correction")
            
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
            
            # Skip small errors
            if abs(error_ms) < self.min_error_threshold_ms:
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
        OPTIMIZED for minimal rate chasing - let MCU be the PLL
        
        CORRECT LOGIC:
        - If error_ms > 0: timestamps ahead of GPS → MCU too fast → need POSITIVE ppm to slow down
        - If error_ms < 0: timestamps behind GPS → MCU too slow → need NEGATIVE ppm to speed up
        """
        try:
            # NEW: Check cooldown to prevent excessive rate chasing
            current_time = time.time() * 1000  # Convert to ms
            time_since_last_adjustment = current_time - self.adaptive_control['last_rate_adjustment']
            
            if time_since_last_adjustment < self.adaptive_control['adjustment_cooldown_ms']:
                print(f"🛑 RATE CHASING PREVENTION: Cooldown active ({time_since_last_adjustment:.0f}ms < {self.adaptive_control['adjustment_cooldown_ms']}ms)")
                return
            
            # NEW: Only apply corrections for significant errors
            if abs(error_ms) < self.min_error_threshold_ms:
                print(f"🛑 RATE CHASING PREVENTION: Error too small ({error_ms:.3f}ms < {self.min_error_threshold_ms}ms)")
                return
            # OPTIMIZED: Minimal correction strength to let MCU be the PLL
            error_abs = abs(error_ms)
            if error_abs > 10.0:       # >10ms error: minimal correction
                correction_ppm = +error_ms * 0.5  # Very gentle correction
            elif error_abs > 5.0:      # 5-10ms: very gentle correction
                correction_ppm = +error_ms * 0.3  # Minimal correction
            else:                      # <5ms: no correction (let MCU handle)
                correction_ppm = +error_ms * 0.1  # Barely any correction
            
            # Limit correction
            max_correction = strategy['max_correction']
            correction_ppm = max(-max_correction, min(max_correction, correction_ppm))
            
            # Calculate new interval
            # Positive ppm = longer interval = slower sampling
            # Negative ppm = shorter interval = faster sampling
            correction_factor = 1.0 + (correction_ppm / 1e6)
            new_interval_us = self.current_mcu_interval_us * correction_factor
            
            # Clamp to tighter range for better stability
            new_interval_us = max(9500, min(10500, new_interval_us))
            
            # Diagnostic output
            old_rate = 1e6 / self.current_mcu_interval_us
            new_rate = 1e6 / new_interval_us
            
            print(f"CORRECTED MCU LOGIC:")
            print(f"  Error: {error_ms:+.3f}ms ({'MCU too fast' if error_ms > 0 else 'MCU too slow'})")
            print(f"  Correction: {correction_ppm:+.3f}ppm ({'slow down' if correction_ppm > 0 else 'speed up'})")
            print(f"  Rate: {old_rate:.6f}Hz → {new_rate:.6f}Hz")
            print(f"  Interval: {self.current_mcu_interval_us:.1f}μs → {new_interval_us:.1f}μs")
            
            # Send to MCU
            command = f"SET_PRECISE_INTERVAL:{int(new_interval_us)}"
            result = self.seismic._send_command(command, timeout=3.0)
            
            if result and result[0]:
                self.current_mcu_interval_us = new_interval_us
                self.stats['mcu_adjustments'] += 1
                self.stats['sign_corrections_applied'] += 1
                # Update last adjustment time to enforce cooldown
                self.adaptive_control['last_rate_adjustment'] = time.time() * 1000
                print(f"CORRECTED: MCU correction applied successfully (cooldown: {self.adaptive_control['adjustment_cooldown_ms']}ms)")
            else:
                print(f"CORRECTED: MCU correction failed: {result}")
                
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
            # OPTIMIZED host correction scaling for minimal fluctuations
            if abs(error_ms) > 3.0:      # Reduced threshold for earlier intervention
                scale = 0.3              # Reduced from 0.5 for stability
            elif abs(error_ms) > 1.0:
                scale = 0.25             # Reduced from 0.4 for stability
            else:
                scale = 0.15            # Reduced from 0.2 for stability
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
            # Reset basic stats while keeping history size
            self.stats['corrections_applied'] = 0
            self.stats['mcu_adjustments'] = 0
            self.stats['host_adjustments'] = 0
            self.stats['measurements_taken'] = 0
            self.stats['sign_corrections_applied'] = 0
            self.stats['target_achieved'] = False
            self.stats['convergence_time_s'] = 0.0
            # Clear only recent error history
            try:
                self.stats['error_history'].clear()
            except Exception:
                pass
            print("🔄 UnifiedTimingController: state reset (host correction cleared)")
        except Exception as e:
            print(f"Warning: failed to reset unified controller state: {e}")
    
    # Public setters for runtime configuration
    def set_measurement_interval(self, seconds: float):
        try:
            seconds = float(seconds)
            if 0.2 <= seconds <= 10.0:
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
        
    def get_stats(self):
        """Get controller statistics"""
        stats = dict(self.stats)
        # Convert deque to list for JSON serialization
        if 'error_history' in stats:
            stats['error_history'] = list(stats['error_history'])
        return stats


    # NEW: MCU firmware integration methods
    
    def update_mcu_status(self, status_data):
        """Update MCU status from STATUS message"""
        self.mcu_integration.update({
            'timing_source': status_data.get('timing_source', 'UNKNOWN'),
            'accuracy_us': status_data.get('accuracy_us', 1000000),
            'calibration_ppm': status_data.get('calibration_ppm', 0.0),
            'pps_valid': status_data.get('pps_valid', False),
            'boot_id': status_data.get('boot_id'),
            'stream_id': status_data.get('stream_id'),
            'temperature_c': status_data.get('temperature_c', 25.0),
            'buffer_overflows': status_data.get('buffer_overflows', 0),
            'samples_skipped': status_data.get('samples_skipped', 0)
        })
        
        # Update timing manager with MCU calibration
        if 'calibration_ppm' in status_data:
            self.timing_manager.update_oscillator_calibration(
                status_data['calibration_ppm'],
                status_data.get('temperature_c', 25.0)
            )
        
        # Update phase servo if enabled
        if self.phase_servo['enabled']:
            if hasattr(self.seismic, 'timing_adapter') and hasattr(self.seismic.timing_adapter, 'timestamp_generator'):
                self.seismic.timing_adapter.timestamp_generator.set_phase_servo(
                    enabled=True,
                    clamp_us=self.phase_servo['clamp_us']
                )
    
    def enable_mcu_timestamp_mode(self, enabled: bool = True, offset_us: int = 0):
        """Enable MCU timestamp mode"""
        self.mcu_integration['enabled'] = enabled
        self.stats['mcu_timestamp_mode'] = enabled
        
        if enabled:
            # Access timestamp generator through the seismic device's timing adapter
            if hasattr(self.seismic, 'timing_adapter') and hasattr(self.seismic.timing_adapter, 'timestamp_generator'):
                self.seismic.timing_adapter.timestamp_generator.enable_mcu_timestamp_mode(
                    enabled=True,
                    offset_us=offset_us
                )
                print(f"🔧 MCU TIMESTAMP MODE ENABLED (offset: {offset_us}μs)")
            else:
                print("🔧 MCU TIMESTAMP MODE: timing adapter not available")
        else:
            if hasattr(self.seismic, 'timing_adapter') and hasattr(self.seismic.timing_adapter, 'timestamp_generator'):
                self.seismic.timing_adapter.timestamp_generator.enable_mcu_timestamp_mode(enabled=False)
            print("🔧 MCU TIMESTAMP MODE DISABLED")
    
    def set_adaptive_control(self, enabled: bool = True, target_rate: float = 100.0):
        """Configure adaptive timing control"""
        self.adaptive_control['enabled'] = enabled
        self.adaptive_control['target_rate'] = target_rate
        
        if enabled:
            print(f"🔧 ADAPTIVE CONTROL ENABLED (target: {target_rate} Hz)")
        else:
            print("🔧 ADAPTIVE CONTROL DISABLED")
    
    def apply_bounded_adjustment(self, adjustment_ppm: float, force: bool = False):
        """Apply bounded adjustment with rate change rejection"""
        if not self.adaptive_control['enabled']:
            return False
        
        # Check cooldown period
        current_time = time.time() * 1000
        if not force and (current_time - self.adaptive_control['last_rate_adjustment']) < self.adaptive_control['adjustment_cooldown_ms']:
            return False
        
        # Rate change rejection while PPS locked
        if self.mcu_integration['pps_valid'] and abs(adjustment_ppm) > self.adaptive_control['rate_tolerance_ppm']:
            self.stats['rate_rejections'] += 1
            print(f"🚫 RATE CHANGE REJECTED: {adjustment_ppm:.2f} ppm (PPS locked, >{self.adaptive_control['rate_tolerance_ppm']} ppm)")
            return False
        
        # Apply bounded adjustment
        bounded_adjustment = max(-self.adaptive_control['max_adjustment_ppm'], 
                                min(self.adaptive_control['max_adjustment_ppm'], adjustment_ppm))
        
        if abs(bounded_adjustment) > 0.1:  # Only apply if significant
            # Convert ppm to interval adjustment
            current_interval = self.current_mcu_interval_us
            new_interval = current_interval * (1 + bounded_adjustment / 1000000.0)
            
            # Apply to MCU
            if hasattr(self.seismic, 'set_mcu_interval'):
                self.seismic.set_mcu_interval(int(new_interval))
            
            self.current_mcu_interval_us = new_interval
            self.adaptive_control['last_rate_adjustment'] = current_time
            self.stats['bounded_adjustments'] += 1
            self.stats['adaptive_adjustments'] += 1
            
            print(f"🔧 BOUNDED ADJUSTMENT APPLIED: {bounded_adjustment:.2f} ppm")
            return True
        
        return False
    
    def get_mcu_integration_status(self):
        """Get MCU integration status"""
        return {
            'mcu_integration': self.mcu_integration,
            'adaptive_control': self.adaptive_control,
            'phase_servo': self.phase_servo,
            'stats': {
                'mcu_timestamp_mode': self.stats['mcu_timestamp_mode'],
                'phase_servo_active': self.stats['phase_servo_active'],
                'adaptive_adjustments': self.stats['adaptive_adjustments'],
                'bounded_adjustments': self.stats['bounded_adjustments'],
                'rate_rejections': self.stats['rate_rejections']
            }
        }


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
        
        # CRITICAL FIX: Give UnifiedTimingManager access to seismic_device for MCU-aware error measurement
        self.unified_manager.seismic_device = seismic_device
        
        # Enable MCU firmware features by default
        self.unified_controller.enable_mcu_timestamp_mode(enabled=True)
        self.unified_controller.set_adaptive_control(enabled=True)
        
    def generate_timestamp(self, sequence, timing_manager=None, mcu_timestamp_us=None):
        """Generate timestamp (compatible with existing interface)"""
        # Generate clean timestamp with MCU timestamp support
        raw_timestamp = self.timestamp_generator.generate_timestamp(sequence, mcu_timestamp_us)
        
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
        timing_info = self.unified_manager.get_timing_info()
        
        # Add adaptive control status if available
        if self.unified_controller:
            timing_info['adaptive_control'] = self.unified_controller.adaptive_control
        
        return timing_info
    
    # NEW: MCU firmware integration methods
    
    def update_mcu_status(self, status_data):
        """Update MCU status from STATUS message"""
        if self.unified_controller:
            self.unified_controller.update_mcu_status(status_data)
    
    def enable_mcu_timestamp_mode(self, enabled: bool = True, offset_us: int = 0):
        """Enable MCU timestamp mode"""
        if self.unified_controller:
            self.unified_controller.enable_mcu_timestamp_mode(enabled, offset_us)
    
    def set_adaptive_control(self, enabled: bool = True, target_rate: float = 100.0):
        """Configure adaptive timing control"""
        if self.unified_controller:
            self.unified_controller.set_adaptive_control(enabled, target_rate)
    
    def apply_bounded_adjustment(self, adjustment_ppm: float, force: bool = False):
        """Apply bounded adjustment with rate change rejection"""
        if self.unified_controller:
            return self.unified_controller.apply_bounded_adjustment(adjustment_ppm, force)
        return False
    
    def get_mcu_integration_status(self):
        """Get MCU integration status"""
        if self.unified_controller:
            return self.unified_controller.get_mcu_integration_status()
        return {}
    
    def get_phase_servo_status(self):
        """Get phase servo status"""
        return self.timestamp_generator.get_phase_servo_status()
    
    def get_mcu_timestamp_status(self):
        """Get MCU timestamp mode status"""
        return self.timestamp_generator.get_mcu_timestamp_status()
    
    def get_timing_state_info(self):
        """Get timing state machine information"""
        return self.unified_manager.get_timing_state_info()
    
    def enable_utc_stamping(self, enabled: bool = True):
        """Enable UTC timestamp policy"""
        self.timestamp_generator.enable_utc_stamping(enabled)
    
    def set_utc_offset(self, offset_seconds: float):
        """Set UTC offset from system time"""
        self.timestamp_generator.set_utc_offset(offset_seconds)
    
    def get_utc_timestamp(self, timestamp_s: float):
        """Convert timestamp to UTC datetime"""
        return self.timestamp_generator.get_utc_timestamp(timestamp_s)
    
    def get_utc_status(self):
        """Get UTC stamping policy status"""
        return self.timestamp_generator.get_utc_status()
        
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