#!/usr/bin/env python3
"""
GPS Updater for InfluxDB
Periodically updates sensor GPS location to InfluxDB
"""

import threading
import time
import logging


class GPSUpdater:
    """Periodically update GPS location to InfluxDB"""
    
    def __init__(self, influx_writer, gps_reader, interval_seconds=60):
        """
        Initialize GPS updater
        
        Args:
            influx_writer: InfluxWriter instance
            gps_reader: GPS reading function/object (should have get_location() method)
            interval_seconds: Update interval in seconds (default: 60)
        """
        self.influx_writer = influx_writer
        self.gps_reader = gps_reader
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread = None
        self.last_update = None
        self.update_count = 0
        self.error_count = 0
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
    def start(self):
        """Start periodic GPS updates"""
        if self._thread is not None and self._thread.is_alive():
            self.logger.warning("GPS updater already running")
            return
            
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"GPS updater started (interval: {self.interval}s)")
        
    def _update_loop(self):
        """Background loop to update GPS periodically"""
        while not self._stop_event.is_set():
            try:
                # Read current GPS data
                gps_data = self.gps_reader.get_location()
                
                if gps_data and gps_data.get('valid'):
                    # Write GPS location to InfluxDB
                    success = self.influx_writer.write_gps_location(
                        timestamp=int(time.time() * 1000),  # Current time in ms
                        latitude=gps_data['latitude'],
                        longitude=gps_data['longitude'],
                        altitude=gps_data.get('altitude'),
                        accuracy=gps_data.get('accuracy'),
                        satellites=gps_data.get('satellites')
                    )
                    
                    if success:
                        self.update_count += 1
                        self.last_update = time.time()
                        self.logger.debug(
                            f"GPS updated: lat={gps_data['latitude']:.6f}, "
                            f"lon={gps_data['longitude']:.6f}"
                        )
                else:
                    self.logger.warning("GPS fix not available")
                    self.error_count += 1
                    
            except Exception as e:
                self.logger.error(f"Error updating GPS: {e}")
                self.error_count += 1
            
            # Wait for next interval (or until stop event)
            self._stop_event.wait(self.interval)
    
    def stop(self):
        """Stop GPS updates"""
        if self._thread is None:
            self.logger.warning("GPS updater not running")
            return
            
        self.logger.info("Stopping GPS updater...")
        self._stop_event.set()
        
        if self._thread.is_alive():
            self._thread.join(timeout=5)
            
        self.logger.info(
            f"GPS updater stopped (updates: {self.update_count}, errors: {self.error_count})"
        )
    
    def get_stats(self):
        """Get GPS updater statistics"""
        return {
            'running': self._thread is not None and self._thread.is_alive(),
            'interval_seconds': self.interval,
            'update_count': self.update_count,
            'error_count': self.error_count,
            'last_update': self.last_update
        }
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
