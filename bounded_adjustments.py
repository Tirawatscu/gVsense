#!/usr/bin/env python3
"""
Bounded Adjustments with Step Changes and Small Nudges (<50 ppm)
Implements conservative rate adjustment policy
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
import threading

logger = logging.getLogger(__name__)

class BoundedAdjustmentController:
    """Bounded adjustment controller for rate changes"""
    
    def __init__(self, 
                 max_adjustment_ppm: float = 50.0,
                 min_adjustment_ppm: float = 0.1,
                 adjustment_cooldown: float = 60.0,
                 max_adjustments_per_hour: int = 10):
        self.max_adjustment_ppm = max_adjustment_ppm
        self.min_adjustment_ppm = min_adjustment_ppm
        self.adjustment_cooldown = adjustment_cooldown
        self.max_adjustments_per_hour = max_adjustments_per_hour
        
        # State tracking
        self.current_rate = 100.0  # Hz
        self.target_rate = 100.0  # Hz
        self.last_adjustment_time = 0.0
        self.adjustment_history = deque(maxlen=100)
        
        # MCU status
        self.mcu_pps_valid = False
        self.mcu_timing_source = "UNKNOWN"
        self.mcu_calibration_ppm = 0.0
        self.mcu_accuracy_us = 1000.0
        
        # Adjustment policy
        self.adjustment_enabled = True
        self.emergency_mode = False
        
        # Threading
        self.lock = threading.Lock()
        
    def update_mcu_status(self, stat_data: Dict[str, Any]):
        """Update MCU status"""
        with self.lock:
            self.mcu_pps_valid = stat_data.get('pps_valid', False)
            self.mcu_timing_source = stat_data.get('timing_source', 'UNKNOWN')
            self.mcu_calibration_ppm = stat_data.get('calibration_ppm', 0.0)
            self.mcu_accuracy_us = stat_data.get('accuracy_us', 1000.0)
            
    def should_adjust_rate(self, target_rate: float) -> Tuple[bool, str]:
        """Determine if rate adjustment should be made
        
        Args:
            target_rate: Desired rate in Hz
            
        Returns:
            Tuple of (should_adjust, reason)
        """
        with self.lock:
            if not self.adjustment_enabled:
                return False, "Adjustments disabled"
                
            # Calculate rate difference in PPM
            rate_diff_ppm = abs(target_rate - self.current_rate) / self.current_rate * 1_000_000
            
            # Check if adjustment is needed
            if rate_diff_ppm < self.min_adjustment_ppm:
                return False, "Rate difference too small"
                
            # Check if adjustment is too large
            if rate_diff_ppm > self.max_adjustment_ppm:
                return False, f"Rate difference too large: {rate_diff_ppm:.1f} ppm > {self.max_adjustment_ppm} ppm"
                
            # Check cooldown period
            current_time = time.time()
            if current_time - self.last_adjustment_time < self.adjustment_cooldown:
                return False, f"Cooldown period active: {self.adjustment_cooldown - (current_time - self.last_adjustment_time):.1f}s remaining"
                
            # Check adjustment frequency
            recent_adjustments = sum(1 for adj in self.adjustment_history 
                                   if current_time - adj['timestamp'] < 3600)  # Last hour
            if recent_adjustments >= self.max_adjustments_per_hour:
                return False, f"Too many adjustments: {recent_adjustments} in last hour"
                
            # Check MCU state
            if self.mcu_pps_valid and self.mcu_timing_source == "PPS_ACTIVE":
                # PPS is active, be very conservative
                if rate_diff_ppm > 10.0:  # 10 ppm limit when PPS active
                    return False, f"PPS active, rate difference too large: {rate_diff_ppm:.1f} ppm > 10 ppm"
                    
            # Check accuracy
            if self.mcu_accuracy_us > 100.0:  # >100μs accuracy
                if rate_diff_ppm > 20.0:  # 20 ppm limit when accuracy is poor
                    return False, f"Poor accuracy ({self.mcu_accuracy_us:.1f}μs), rate difference too large: {rate_diff_ppm:.1f} ppm > 20 ppm"
                    
            return True, "Adjustment allowed"
            
    def calculate_adjustment(self, target_rate: float) -> Tuple[float, str]:
        """Calculate bounded adjustment
        
        Args:
            target_rate: Desired rate in Hz
            
        Returns:
            Tuple of (new_rate, adjustment_type)
        """
        with self.lock:
            rate_diff_ppm = (target_rate - self.current_rate) / self.current_rate * 1_000_000
            
            # Determine adjustment type
            if abs(rate_diff_ppm) <= 5.0:
                adjustment_type = "nudge"
                # Small nudge: 50% of difference
                adjustment_ppm = rate_diff_ppm * 0.5
            elif abs(rate_diff_ppm) <= 20.0:
                adjustment_type = "step"
                # Step change: 75% of difference
                adjustment_ppm = rate_diff_ppm * 0.75
            else:
                adjustment_type = "bounded"
                # Bounded change: clamp to max_adjustment_ppm
                adjustment_ppm = max(-self.max_adjustment_ppm, 
                                   min(self.max_adjustment_ppm, rate_diff_ppm))
                                   
            # Calculate new rate
            new_rate = self.current_rate * (1 + adjustment_ppm / 1_000_000)
            
            return new_rate, adjustment_type
            
    def apply_adjustment(self, new_rate: float, adjustment_type: str) -> bool:
        """Apply rate adjustment
        
        Args:
            new_rate: New rate to apply
            adjustment_type: Type of adjustment
            
        Returns:
            True if adjustment applied successfully
        """
        with self.lock:
            try:
                # Record adjustment
                current_time = time.time()
                self.adjustment_history.append({
                    'timestamp': current_time,
                    'old_rate': self.current_rate,
                    'new_rate': new_rate,
                    'adjustment_type': adjustment_type,
                    'mcu_pps_valid': self.mcu_pps_valid,
                    'mcu_timing_source': self.mcu_timing_source,
                    'mcu_accuracy_us': self.mcu_accuracy_us
                })
                
                # Update state
                self.current_rate = new_rate
                self.last_adjustment_time = current_time
                
                logger.info(f"Applied {adjustment_type} adjustment: {self.current_rate:.3f} Hz -> {new_rate:.3f} Hz")
                return True
                
            except Exception as e:
                logger.error(f"Failed to apply adjustment: {e}")
                return False
                
    def get_adjustment_statistics(self) -> Dict[str, Any]:
        """Get adjustment statistics"""
        with self.lock:
            current_time = time.time()
            
            # Calculate recent adjustments
            recent_adjustments = [adj for adj in self.adjustment_history 
                                if current_time - adj['timestamp'] < 3600]  # Last hour
            
            # Calculate adjustment types
            adjustment_types = {}
            for adj in recent_adjustments:
                adj_type = adj['adjustment_type']
                adjustment_types[adj_type] = adjustment_types.get(adj_type, 0) + 1
                
            # Calculate average adjustment
            if recent_adjustments:
                avg_adjustment = sum(abs(adj['new_rate'] - adj['old_rate']) for adj in recent_adjustments) / len(recent_adjustments)
            else:
                avg_adjustment = 0.0
                
            return {
                'current_rate': self.current_rate,
                'target_rate': self.target_rate,
                'adjustment_enabled': self.adjustment_enabled,
                'emergency_mode': self.emergency_mode,
                'mcu_pps_valid': self.mcu_pps_valid,
                'mcu_timing_source': self.mcu_timing_source,
                'mcu_accuracy_us': self.mcu_accuracy_us,
                'recent_adjustments': len(recent_adjustments),
                'adjustment_types': adjustment_types,
                'avg_adjustment': avg_adjustment,
                'last_adjustment_time': self.last_adjustment_time,
                'cooldown_remaining': max(0, self.adjustment_cooldown - (current_time - self.last_adjustment_time))
            }
            
    def enable_adjustments(self):
        """Enable rate adjustments"""
        with self.lock:
            self.adjustment_enabled = True
            logger.info("Rate adjustments enabled")
            
    def disable_adjustments(self):
        """Disable rate adjustments"""
        with self.lock:
            self.adjustment_enabled = False
            logger.info("Rate adjustments disabled")
            
    def enter_emergency_mode(self):
        """Enter emergency mode (very conservative adjustments)"""
        with self.lock:
            self.emergency_mode = True
            self.max_adjustment_ppm = 10.0  # Reduce max adjustment
            self.adjustment_cooldown = 300.0  # Increase cooldown
            logger.warning("Entered emergency mode - very conservative adjustments")
            
    def exit_emergency_mode(self):
        """Exit emergency mode"""
        with self.lock:
            self.emergency_mode = False
            self.max_adjustment_ppm = 50.0  # Restore max adjustment
            self.adjustment_cooldown = 60.0  # Restore cooldown
            logger.info("Exited emergency mode")
            
    def reset_statistics(self):
        """Reset adjustment statistics"""
        with self.lock:
            self.adjustment_history.clear()
            self.last_adjustment_time = 0.0
            self.current_rate = 100.0
            self.target_rate = 100.0

class RateController:
    """High-level rate controller"""
    
    def __init__(self, serial_interface=None):
        self.serial_interface = serial_interface
        self.adjustment_controller = BoundedAdjustmentController()
        
        # Rate monitoring
        self.rate_history = deque(maxlen=1000)
        self.last_rate_check = 0.0
        
    def update_mcu_status(self, stat_data: Dict[str, Any]):
        """Update MCU status"""
        self.adjustment_controller.update_mcu_status(stat_data)
        
    def request_rate_change(self, target_rate: float) -> bool:
        """Request rate change
        
        Args:
            target_rate: Desired rate in Hz
            
        Returns:
            True if rate change was applied
        """
        # Check if adjustment should be made
        should_adjust, reason = self.adjustment_controller.should_adjust_rate(target_rate)
        
        if not should_adjust:
            logger.info(f"Rate adjustment rejected: {reason}")
            return False
            
        # Calculate adjustment
        new_rate, adjustment_type = self.adjustment_controller.calculate_adjustment(target_rate)
        
        # Apply adjustment
        success = self.adjustment_controller.apply_adjustment(new_rate, adjustment_type)
        
        if success and self.serial_interface:
            # Send command to MCU
            command = f"SET_PRECISE_INTERVAL:{int(1_000_000 / new_rate)}"
            return self.serial_interface.send_command(command)
            
        return success
        
    def monitor_rate(self, current_rate: float):
        """Monitor current rate"""
        current_time = time.time()
        
        # Record rate
        self.rate_history.append({
            'timestamp': current_time,
            'rate': current_rate
        })
        
        # Check for rate drift
        if len(self.rate_history) >= 10:
            recent_rates = [entry['rate'] for entry in list(self.rate_history)[-10:]]
            avg_rate = sum(recent_rates) / len(recent_rates)
            rate_drift = abs(avg_rate - 100.0) / 100.0 * 1_000_000  # PPM
            
            if rate_drift > 100.0:  # >100 PPM drift
                logger.warning(f"Rate drift detected: {rate_drift:.1f} PPM")
                
    def get_controller_status(self) -> Dict[str, Any]:
        """Get controller status"""
        return self.adjustment_controller.get_adjustment_statistics()

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create rate controller
    controller = RateController()
    
    # Simulate MCU status updates
    print("Simulating MCU status updates...")
    
    # Normal operation
    controller.update_mcu_status({
        'pps_valid': True,
        'timing_source': 'PPS_ACTIVE',
        'calibration_ppm': 12.34,
        'accuracy_us': 1.0
    })
    
    # Request rate changes
    test_rates = [100.5, 101.0, 102.0, 105.0, 110.0]
    
    for rate in test_rates:
        print(f"\nRequesting rate change to {rate} Hz...")
        success = controller.request_rate_change(rate)
        print(f"Rate change success: {success}")
        
        # Check status
        status = controller.get_controller_status()
        print(f"Current rate: {status['current_rate']:.3f} Hz")
        print(f"Cooldown remaining: {status['cooldown_remaining']:.1f}s")
        
    # Check final statistics
    final_status = controller.get_controller_status()
    print(f"\nFinal status: {json.dumps(final_status, indent=2)}")
    
    print("Bounded adjustments test completed!")
