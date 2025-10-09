#!/usr/bin/env python3
"""
Session Header Logging with MCU boot_id, stream_id, rate, filter, etc.
Comprehensive session tracking and logging for seismic data
"""

import time
import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path
import threading

logger = logging.getLogger(__name__)

class SessionLogger:
    """Session header logging and tracking"""
    
    def __init__(self, log_directory: str = "/var/log/gvsense/sessions"):
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        
        # Current session state
        self.current_session: Optional[Dict[str, Any]] = None
        self.session_start_time: Optional[datetime] = None
        self.session_file: Optional[Path] = None
        
        # Session statistics
        self.total_sessions = 0
        self.total_samples = 0
        self.total_duration = 0.0
        
        # Threading
        self.lock = threading.Lock()
        
    def start_session(self, session_data: Dict[str, Any]) -> bool:
        """Start a new session
        
        Args:
            session_data: Session data from MCU
            
        Returns:
            True if session started successfully
        """
        with self.lock:
            try:
                # End current session if active
                if self.current_session:
                    self.end_session()
                    
                # Create new session
                self.current_session = {
                    'session_id': self._generate_session_id(),
                    'start_time': datetime.now(timezone.utc),
                    'mcu_boot_id': session_data.get('boot_id', 0),
                    'mcu_stream_id': session_data.get('stream_id', 0),
                    'mcu_firmware_version': session_data.get('firmware_version', 'unknown'),
                    'device_id': session_data.get('device_id', 'unknown'),
                    'sample_rate': session_data.get('rate', 0),
                    'channels': session_data.get('channels', 0),
                    'filter': session_data.get('filter', 'unknown'),
                    'gain': session_data.get('gain', 0),
                    'dithering': session_data.get('dithering', False),
                    'timing_source': session_data.get('timing_source', 'unknown'),
                    'calibration_ppm': session_data.get('calibration_ppm', 0.0),
                    'calibration_source': session_data.get('calibration_source', 'unknown'),
                    'pps_valid': session_data.get('pps_valid', False),
                    'accuracy_us': session_data.get('accuracy_us', 0.0),
                    'samples': 0,
                    'gaps': 0,
                    'overflows': 0,
                    'quality_level': 'excellent',
                    'status': 'active'
                }
                
                self.session_start_time = self.current_session['start_time']
                
                # Create session log file
                self.session_file = self.log_directory / f"session_{self.current_session['session_id']}.json"
                
                # Write initial session data
                self._write_session_data()
                
                self.total_sessions += 1
                logger.info(f"Started session {self.current_session['session_id']}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to start session: {e}")
                return False
                
    def end_session(self) -> bool:
        """End current session"""
        with self.lock:
            if not self.current_session:
                return False
                
            try:
                # Update session end time
                self.current_session['end_time'] = datetime.now(timezone.utc)
                self.current_session['duration'] = (
                    self.current_session['end_time'] - self.current_session['start_time']
                ).total_seconds()
                self.current_session['status'] = 'ended'
                
                # Update statistics
                self.total_duration += self.current_session['duration']
                
                # Write final session data
                self._write_session_data()
                
                logger.info(f"Ended session {self.current_session['session_id']} "
                           f"(duration: {self.current_session['duration']:.1f}s)")
                
                # Clear current session
                self.current_session = None
                self.session_start_time = None
                self.session_file = None
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to end session: {e}")
                return False
                
    def update_session(self, update_data: Dict[str, Any]):
        """Update current session with new data"""
        with self.lock:
            if not self.current_session:
                return
                
            try:
                # Update session data
                if 'samples' in update_data:
                    self.current_session['samples'] += update_data['samples']
                    self.total_samples += update_data['samples']
                    
                if 'gaps' in update_data:
                    self.current_session['gaps'] += update_data['gaps']
                    
                if 'overflows' in update_data:
                    self.current_session['overflows'] += update_data['overflows']
                    
                if 'quality_level' in update_data:
                    self.current_session['quality_level'] = update_data['quality_level']
                    
                if 'timing_source' in update_data:
                    self.current_session['timing_source'] = update_data['timing_source']
                    
                if 'calibration_ppm' in update_data:
                    self.current_session['calibration_ppm'] = update_data['calibration_ppm']
                    
                if 'pps_valid' in update_data:
                    self.current_session['pps_valid'] = update_data['pps_valid']
                    
                if 'accuracy_us' in update_data:
                    self.current_session['accuracy_us'] = update_data['accuracy_us']
                    
                # Write updated session data
                self._write_session_data()
                
            except Exception as e:
                logger.error(f"Failed to update session: {e}")
                
    def log_sample(self, sample_data: Dict[str, Any]):
        """Log sample data to session"""
        with self.lock:
            if not self.current_session:
                return
                
            try:
                # Update sample count
                self.current_session['samples'] += 1
                self.total_samples += 1
                
                # Check for gaps
                if sample_data.get('gap_detected', False):
                    self.current_session['gaps'] += 1
                    
                # Check for overflows
                if sample_data.get('overflow_detected', False):
                    self.current_session['overflows'] += 1
                    
                # Update quality level
                quality_level = sample_data.get('quality_level', 'excellent')
                if quality_level != self.current_session['quality_level']:
                    self.current_session['quality_level'] = quality_level
                    
                # Write session data periodically
                if self.current_session['samples'] % 1000 == 0:  # Every 1000 samples
                    self._write_session_data()
                    
            except Exception as e:
                logger.error(f"Failed to log sample: {e}")
                
    def _write_session_data(self):
        """Write session data to file"""
        if not self.current_session or not self.session_file:
            return
            
        try:
            # Convert datetime objects to ISO format
            session_data = self.current_session.copy()
            if 'start_time' in session_data:
                session_data['start_time'] = session_data['start_time'].isoformat()
            if 'end_time' in session_data:
                session_data['end_time'] = session_data['end_time'].isoformat()
                
            # Write to file
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to write session data: {e}")
            
    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        timestamp = int(time.time())
        return f"{timestamp}_{self.total_sessions + 1}"
        
    def get_session_statistics(self) -> Dict[str, Any]:
        """Get session statistics"""
        with self.lock:
            current_duration = 0.0
            if self.current_session and self.session_start_time:
                current_duration = (datetime.now(timezone.utc) - self.session_start_time).total_seconds()
                
            return {
                'total_sessions': self.total_sessions,
                'total_samples': self.total_samples,
                'total_duration': self.total_duration,
                'current_session_active': self.current_session is not None,
                'current_session_duration': current_duration,
                'current_session_samples': self.current_session['samples'] if self.current_session else 0,
                'current_session_gaps': self.current_session['gaps'] if self.current_session else 0,
                'current_session_overflows': self.current_session['overflows'] if self.current_session else 0
            }
            
    def list_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List recent sessions"""
        try:
            session_files = sorted(self.log_directory.glob("session_*.json"), 
                                 key=lambda x: x.stat().st_mtime, reverse=True)
            
            sessions = []
            for session_file in session_files[:limit]:
                try:
                    with open(session_file, 'r') as f:
                        session_data = json.load(f)
                    sessions.append(session_data)
                except Exception as e:
                    logger.error(f"Failed to read session file {session_file}: {e}")
                    
            return sessions
            
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []
            
    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get summary for specific session"""
        try:
            session_file = self.log_directory / f"session_{session_id}.json"
            if not session_file.exists():
                return None
                
            with open(session_file, 'r') as f:
                session_data = json.load(f)
                
            # Calculate summary statistics
            summary = {
                'session_id': session_data.get('session_id'),
                'start_time': session_data.get('start_time'),
                'end_time': session_data.get('end_time'),
                'duration': session_data.get('duration', 0),
                'samples': session_data.get('samples', 0),
                'gaps': session_data.get('gaps', 0),
                'overflows': session_data.get('overflows', 0),
                'quality_level': session_data.get('quality_level'),
                'timing_source': session_data.get('timing_source'),
                'calibration_ppm': session_data.get('calibration_ppm'),
                'pps_valid': session_data.get('pps_valid'),
                'accuracy_us': session_data.get('accuracy_us'),
                'sample_rate': session_data.get('sample_rate'),
                'channels': session_data.get('channels'),
                'device_id': session_data.get('device_id'),
                'mcu_boot_id': session_data.get('mcu_boot_id'),
                'mcu_stream_id': session_data.get('mcu_stream_id')
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get session summary: {e}")
            return None

# Example usage
if __name__ == "__main__":
    import json
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create session logger
    logger_instance = SessionLogger("/tmp/test_sessions")
    
    # Start session
    session_data = {
        'boot_id': 123,
        'stream_id': 456,
        'firmware_version': '1.8.3',
        'device_id': 'XIAO-1234',
        'rate': 100.0,
        'channels': 2,
        'filter': 'sinc4',
        'gain': 1,
        'dithering': True,
        'timing_source': 'PPS_ACTIVE',
        'calibration_ppm': 12.34,
        'calibration_source': 'PPS_LIVE',
        'pps_valid': True,
        'accuracy_us': 1.0
    }
    
    success = logger_instance.start_session(session_data)
    print(f"Session started: {success}")
    
    # Simulate some samples
    for i in range(1000):
        sample_data = {
            'gap_detected': i % 100 == 0,  # Simulate gaps
            'overflow_detected': i % 200 == 0,  # Simulate overflows
            'quality_level': 'excellent' if i % 300 != 0 else 'good'
        }
        logger_instance.log_sample(sample_data)
        
    # Update session
    logger_instance.update_session({
        'timing_source': 'PPS_HOLDOVER',
        'calibration_ppm': 12.31,
        'pps_valid': False
    })
    
    # Check statistics
    stats = logger_instance.get_session_statistics()
    print(f"Session statistics: {json.dumps(stats, indent=2)}")
    
    # End session
    success = logger_instance.end_session()
    print(f"Session ended: {success}")
    
    # List sessions
    sessions = logger_instance.list_sessions()
    print(f"Total sessions: {len(sessions)}")
    
    if sessions:
        summary = logger_instance.get_session_summary(sessions[0]['session_id'])
        print(f"Session summary: {json.dumps(summary, indent=2)}")
        
    print("Session logging test completed!")
