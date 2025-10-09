#!/usr/bin/env python3
"""
MCU PLL Controller: Stop chasing rate - only set targets sparingly, let MCU be the PLL
Implements conservative rate control policy
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from collections import deque
import threading

logger = logging.getLogger(__name__)

class MCUPLLController:
    """MCU PLL controller with conservative rate management"""
    
    def __init__(self, 
                 target_rate: float = 100.0,
                 rate_tolerance_ppm: float = 100.0,
                 max_rate_changes_per_hour: int = 3,
                 rate_change_cooldown: float = 300.0):  # 5 minutes
        self.target_rate = target_rate
        self.rate_tolerance_ppm = rate_tolerance_ppm
        self.max_rate_changes_per_hour = max_rate_changes_per_hour
        self.rate_change_cooldown = rate_change_cooldown
        
        # State tracking
        self.current_rate = target_rate
        self.last_rate_change_time = 0.0
        self.rate_change_history = deque(maxlen=100)
        
        # MCU status
        self.mcu_pps_valid = False
        self.mcu_timing_source = "UNKNOWN"
        self.mcu_calibration_ppm = 0.0
        self.mcu_accuracy_us = 1000.0
        
        # Rate monitoring
        self.rate_history = deque(maxlen=1000)
        self.rate_stability_window = 600.0  # 10 minutes
        self.rate_stability_threshold_ppm = 50.0
        
        # Control policy
        self.rate_chasing_enabled = False
        self.mcu_pll_authority = True
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
            
    def update_rate_measurement(self, measured_rate: float):
        """Update rate measurement from MCU"""
        with self.lock:
            current_time = time.time()
            
            # Record rate measurement
            self.rate_history.append({
                'timestamp': current_time,
                'rate': measured_rate
            })
            
            # Update current rate
            self.current_rate = measured_rate
            
    def should_change_rate(self, new_target_rate: float) -> Tuple[bool, str]:
        """Determine if rate change should be made
        
        Args:
            new_target_rate: New target rate in Hz
            
        Returns:
            Tuple of (should_change, reason)
        """
        with self.lock:
            if not self.mcu_pll_authority:
                return False, "MCU PLL authority disabled"
                
            # Calculate rate difference in PPM
            rate_diff_ppm = abs(new_target_rate - self.current_rate) / self.current_rate * 1_000_000
            
            # Check if change is needed
            if rate_diff_ppm < self.rate_tolerance_ppm:
                return False, f"Rate difference too small: {rate_diff_ppm:.1f} ppm < {self.rate_tolerance_ppm} ppm"
                
            # Check cooldown period
            current_time = time.time()
            if current_time - self.last_rate_change_time < self.rate_change_cooldown:
                remaining = self.rate_change_cooldown - (current_time - self.last_rate_change_time)
                return False, f"Rate change cooldown active: {remaining:.1f}s remaining"
                
            # Check rate change frequency
            recent_changes = sum(1 for change in self.rate_change_history 
                               if current_time - change['timestamp'] < 3600)  # Last hour
            if recent_changes >= self.max_rate_changes_per_hour:
                return False, f"Too many rate changes: {recent_changes} in last hour"
                
            # Check MCU state
            if self.mcu_pps_valid and self.mcu_timing_source == "PPS_ACTIVE":
                # PPS is active, be very conservative
                if rate_diff_ppm > 50.0:  # 50 ppm limit when PPS active
                    return False, f"PPS active, rate difference too large: {rate_diff_ppm:.1f} ppm > 50 ppm"
                    
            # Check rate stability
            if not self._is_rate_stable():
                return False, "Rate not stable, waiting for stability"
                
            return True, "Rate change allowed"
            
    def _is_rate_stable(self) -> bool:
        """Check if current rate is stable"""
        if len(self.rate_history) < 10:
            return False
            
        current_time = time.time()
        recent_rates = [entry['rate'] for entry in self.rate_history 
                       if current_time - entry['timestamp'] < self.rate_stability_window]
        
        if len(recent_rates) < 5:
            return False
            
        # Calculate rate stability
        avg_rate = sum(recent_rates) / len(recent_rates)
        max_deviation = max(abs(rate - avg_rate) for rate in recent_rates)
        max_deviation_ppm = max_deviation / avg_rate * 1_000_000
        
        return max_deviation_ppm <= self.rate_stability_threshold_ppm
        
    def change_rate(self, new_target_rate: float) -> bool:
        """Change target rate
        
        Args:
            new_target_rate: New target rate in Hz
            
        Returns:
            True if rate change was applied
        """
        with self.lock:
            # Check if change should be made
            should_change, reason = self.should_change_rate(new_target_rate)
            
            if not should_change:
                logger.info(f"Rate change rejected: {reason}")
                return False
                
            # Record rate change
            current_time = time.time()
            self.rate_change_history.append({
                'timestamp': current_time,
                'old_target': self.target_rate,
                'new_target': new_target_rate,
                'mcu_pps_valid': self.mcu_pps_valid,
                'mcu_timing_source': self.mcu_timing_source,
                'mcu_accuracy_us': self.mcu_accuracy_us
            })
            
            # Update target rate
            self.target_rate = new_target_rate
            self.last_rate_change_time = current_time
            
            logger.info(f"Rate target changed: {self.current_rate:.3f} Hz -> {new_target_rate:.3f} Hz")
            return True
            
    def get_rate_status(self) -> Dict[str, Any]:
        """Get rate status"""
        with self.lock:
            current_time = time.time()
            
            # Calculate rate statistics
            if self.rate_history:
                recent_rates = [entry['rate'] for entry in self.rate_history 
                               if current_time - entry['timestamp'] < 60]  # Last minute
                
                if recent_rates:
                    avg_rate = sum(recent_rates) / len(recent_rates)
                    min_rate = min(recent_rates)
                    max_rate = max(recent_rates)
                    rate_std = self._calculate_std(recent_rates)
                else:
                    avg_rate = self.current_rate
                    min_rate = self.current_rate
                    max_rate = self.current_rate
                    rate_std = 0.0
            else:
                avg_rate = self.current_rate
                min_rate = self.current_rate
                max_rate = self.current_rate
                rate_std = 0.0
                
            # Calculate rate change statistics
            recent_changes = [change for change in self.rate_change_history 
                            if current_time - change['timestamp'] < 3600]  # Last hour
            
            return {
                'target_rate': self.target_rate,
                'current_rate': self.current_rate,
                'avg_rate': avg_rate,
                'min_rate': min_rate,
                'max_rate': max_rate,
                'rate_std': rate_std,
                'rate_stable': self._is_rate_stable(),
                'mcu_pps_valid': self.mcu_pps_valid,
                'mcu_timing_source': self.mcu_timing_source,
                'mcu_accuracy_us': self.mcu_accuracy_us,
                'rate_chasing_enabled': self.rate_chasing_enabled,
                'mcu_pll_authority': self.mcu_pll_authority,
                'emergency_mode': self.emergency_mode,
                'recent_rate_changes': len(recent_changes),
                'last_rate_change_time': self.last_rate_change_time,
                'cooldown_remaining': max(0, self.rate_change_cooldown - (current_time - self.last_rate_change_time))
            }
            
    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0.0
            
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
        
    def enable_rate_chasing(self):
        """Enable rate chasing (not recommended)"""
        with self.lock:
            self.rate_chasing_enabled = True
            logger.warning("Rate chasing enabled - this may cause instability")
            
    def disable_rate_chasing(self):
        """Disable rate chasing (recommended)"""
        with self.lock:
            self.rate_chasing_enabled = False
            logger.info("Rate chasing disabled - MCU PLL is authoritative")
            
    def set_mcu_pll_authority(self, authority: bool):
        """Set MCU PLL authority"""
        with self.lock:
            self.mcu_pll_authority = authority
            if authority:
                logger.info("MCU PLL set as authoritative")
            else:
                logger.warning("MCU PLL authority disabled")
                
    def enter_emergency_mode(self):
        """Enter emergency mode (very conservative)"""
        with self.lock:
            self.emergency_mode = True
            self.rate_tolerance_ppm = 200.0  # Increase tolerance
            self.max_rate_changes_per_hour = 1  # Reduce changes
            self.rate_change_cooldown = 600.0  # Increase cooldown
            logger.warning("Entered emergency mode - very conservative rate control")
            
    def exit_emergency_mode(self):
        """Exit emergency mode"""
        with self.lock:
            self.emergency_mode = False
            self.rate_tolerance_ppm = 100.0  # Restore tolerance
            self.max_rate_changes_per_hour = 3  # Restore changes
            self.rate_change_cooldown = 300.0  # Restore cooldown
            logger.info("Exited emergency mode")
            
    def reset_statistics(self):
        """Reset rate control statistics"""
        with self.lock:
            self.rate_history.clear()
            self.rate_change_history.clear()
            self.last_rate_change_time = 0.0
            self.current_rate = self.target_rate

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create MCU PLL controller
    controller = MCUPLLController(target_rate=100.0)
    
    # Simulate MCU status updates
    print("Simulating MCU PLL control...")
    
    # Normal operation
    controller.update_mcu_status({
        'pps_valid': True,
        'timing_source': 'PPS_ACTIVE',
        'calibration_ppm': 12.34,
        'accuracy_us': 1.0
    })
    
    # Simulate rate measurements
    for i in range(100):
        measured_rate = 100.0 + (i % 10) * 0.01  # Small variations
        controller.update_rate_measurement(measured_rate)
        
    # Test rate changes
    test_rates = [100.5, 101.0, 102.0]
    
    for rate in test_rates:
        print(f"\nRequesting rate change to {rate} Hz...")
        success = controller.change_rate(rate)
        print(f"Rate change success: {success}")
        
        # Check status
        status = controller.get_rate_status()
        print(f"Current rate: {status['current_rate']:.3f} Hz")
        print(f"Rate stable: {status['rate_stable']}")
        print(f"Cooldown remaining: {status['cooldown_remaining']:.1f}s")
        
    # Check final status
    final_status = controller.get_rate_status()
    print(f"\nFinal status: {json.dumps(final_status, indent=2)}")
    
    print("MCU PLL control test completed!")
