#!/usr/bin/env python3
"""
Compatibility wrapper for existing AdaptiveTimingController interface
Delegates actual control to UnifiedTimingController from timing_fix.py
"""

from timing_fix import UnifiedTimingController


class CompatibilityAdaptiveTimingController:
    """
    Compatibility wrapper for existing AdaptiveTimingController interface
    Delegates actual control to UnifiedTimingController
    """
    
    def __init__(self, seismic_acquisition, timing_manager):
        # Store references for compatibility
        self.seismic = seismic_acquisition
        self.timing_manager = timing_manager
        
        # Get the unified controller from the timing adapter
        if hasattr(seismic_acquisition, 'timing_adapter'):
            self.unified_controller = seismic_acquisition.timing_adapter.unified_controller
        else:
            print("Warning: Seismic device missing unified timing adapter")
            self.unified_controller = None
        
        # Compatibility properties
        self.running = False
        self.enable_corrections = True
        self.target_rate = 100.0
        self.target_interval_us = 10000
        self.current_interval_us = 10000.0
        
        # Timing parameters for compatibility
        self.measurement_interval = 10.0
        self.max_correction_ppm = 150.0
        self.kp = 1.0
        self.ki = 0.3
        self.kd = 0.2
    
    def start_controller(self):
        """Start the controller (delegates to unified system)"""
        if self.unified_controller:
            self.unified_controller.start_controller()
            self.running = True
            print("Adaptive timing controller started (unified mode)")
        else:
            print("Warning: Unified controller not available")
    
    def stop_controller(self):
        """Stop the controller"""
        if self.unified_controller:
            self.unified_controller.stop_controller()
        self.running = False
        print("Adaptive timing controller stopped (unified mode)")
    
    def set_corrections_enabled(self, enabled):
        """Enable/disable corrections"""
        self.enable_corrections = enabled
        return enabled
    
    def get_corrections_enabled(self):
        """Get correction status"""
        return self.enable_corrections
    
    def reset_to_baseline(self):
        """Reset to baseline rate"""
        try:
            if self.seismic and hasattr(self.seismic, '_send_command'):
                command = f"SET_PRECISE_INTERVAL:{self.target_interval_us}"
                result = self.seismic._send_command(command, timeout=5.0)
                
                if result and result[0]:
                    self.current_interval_us = float(self.target_interval_us)
                    print(f"Reset to baseline: {self.target_interval_us}µs (100.00Hz)")
                    return True
                else:
                    print(f"Reset failed: {result}")
                    return False
        except Exception as e:
            print(f"Reset error: {e}")
            return False
    
    def force_mcu_baseline(self):
        """Force MCU back to baseline (same as reset_to_baseline)"""
        return self.reset_to_baseline()
    
    def reset_controller_state(self):
        """Reset controller state"""
        if self.unified_controller:
            # Reset unified controller state if method exists
            if hasattr(self.unified_controller, 'reset_state'):
                self.unified_controller.reset_state()
            print("Controller state reset (unified mode)")
            return True
        return False
    
    def get_stats(self):
        """Get statistics (compatible with existing interface)"""
        base_stats = {
            'corrections_applied': 0,
            'total_drift_corrected_ppm': 0,
            'max_error_ms': 0,
            'avg_error_ms': 0,
            'controller_active_time': 0,
            'mcu_timing_quality': 'unknown',
            'pps_available': False,
            'scientific_grade_time': 0,
            'last_mcu_accuracy_us': 1000.0,
            'controller_running': self.running,
            'corrections_enabled': self.enable_corrections,
            'current_sampling_rate_hz': 1e6 / self.current_interval_us if self.current_interval_us > 0 else 0,
            'target_sampling_rate_hz': 1e6 / self.target_interval_us if self.target_interval_us > 0 else 0
        }
        
        # Add unified controller stats if available
        if self.unified_controller:
            unified_stats = self.unified_controller.get_stats()
            base_stats.update({
                'corrections_applied': unified_stats.get('corrections_applied', 0),
                'mcu_adjustments': unified_stats.get('mcu_adjustments', 0),
                'host_adjustments': unified_stats.get('host_adjustments', 0),
                'measurements_taken': unified_stats.get('measurements_taken', 0)
            })
        
        # Add timing manager stats if available
        if hasattr(self.seismic, 'timing_adapter'):
            timing_stats = self.seismic.timing_adapter.get_timing_info()
            if 'performance_metrics' in timing_stats:
                perf = timing_stats['performance_metrics']
                base_stats.update({
                    'avg_error_ms': perf.get('avg_error_ms', 0),
                    'max_error_ms': perf.get('max_error_ms', 0)
                })
        
        return base_stats
    
    def get_performance_assessment(self):
        """Get performance assessment"""
        if self.unified_controller:
            # Get performance from unified system
            timing_info = self.seismic.timing_adapter.get_timing_info()
            if 'performance_metrics' in timing_info:
                avg_error = timing_info['performance_metrics'].get('avg_error_ms', 0)
                if avg_error < 5:
                    return "excellent"
                elif avg_error < 20:
                    return "good"
                elif avg_error < 50:
                    return "fair"
                else:
                    return "poor"
        return "insufficient_data"


# Maintain backward compatibility
AdaptiveTimingController = CompatibilityAdaptiveTimingController
