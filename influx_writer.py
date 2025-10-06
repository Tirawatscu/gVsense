#!/usr/bin/env python3
"""
InfluxDB Writer for Seismic Data Acquisition
Provides buffered, error-resilient writing to InfluxDB time-series database
"""

from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
import threading
import queue
import time
import logging
from datetime import datetime

class InfluxWriter:
    def __init__(self, url, token, org, bucket, measurement="seismic", batch_size=100, tags=None, fields=None, buffer_on_error=True):
        """
        Initialize InfluxDB writer
        
        Args:
            url: InfluxDB URL (e.g., "http://localhost:8086")
            token: InfluxDB authentication token
            org: InfluxDB organization
            bucket: InfluxDB bucket name
            measurement: Measurement name for data points
            batch_size: Number of points to batch before writing
            tags: Common tags to apply to all points
            fields: Common fields to include with all points
            buffer_on_error: Whether to use background buffering
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.measurement = measurement
        self.common_tags = tags if tags else {}
        self.common_fields = fields if fields else {}
        self.buffer_on_error = buffer_on_error
        self.connected = False
        
        # Statistics
        self.stats = {
            'points_written': 0,
            'write_errors': 0,
            'connection_errors': 0,
            'last_write_time': None,
            'buffer_size': 0
        }
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Initialize client and write API
        try:
            self.client = InfluxDBClient(url=url, token=token, org=org)
            self.write_api = self.client.write_api(
                write_options=WriteOptions(
                    batch_size=batch_size,
                    flush_interval=1000,  # 1 second
                    jitter_interval=100,
                    retry_interval=5000,
                    max_retries=3
                )
            )
            self.connected = True
            self.logger.info(f"Connected to InfluxDB at {url}")
        except Exception as e:
            self.logger.error(f"Failed to connect to InfluxDB: {e}")
            self.stats['connection_errors'] += 1
            self.connected = False

        # Setup background buffering if enabled
        if self.buffer_on_error and self.connected:
            self.q = queue.Queue()
            self._stop_event = threading.Event()
            self.worker = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker.start()
            self.logger.info("Started background InfluxDB writer thread")
        else:
            self.q = None

    def test_connection(self):
        """Test InfluxDB connection"""
        try:
            if not self.connected:
                return False
            
            # Try to ping the database
            health = self.client.health()
            return health.status == "pass"
        except Exception as e:
            self.logger.error(f"InfluxDB connection test failed: {e}")
            return False

    def write_seismic_sample(self, timestamp, sequence, channel_values, tags=None, fields=None, thingsboard_status=None):
        """
        Write a seismic data sample to InfluxDB
        
        Args:
            timestamp: Unix timestamp in milliseconds (can include decimal for microseconds)
            sequence: Sample sequence number
            channel_values: List of ADC values [ch1, ch2, ch3]
            tags: Additional tags for this sample
            fields: Additional fields for this sample (e.g., calibrated g values)
            thingsboard_status: Legacy parameter (not used anymore)
        """
        if not self.connected:
            return False
            
        try:
            # FIXED: Remove redundant quantization - timestamps are already perfectly quantized
            # The SimplifiedTimestampGenerator provides exact configurable quantization boundaries
            if isinstance(timestamp, str) and '.' in timestamp:
                # Handle decimal timestamps by converting to integer
                timestamp_ms = int(float(timestamp))
            else:
                # Handle integer timestamps directly
                timestamp_ms = int(timestamp)
            
            # Convert to nanoseconds for InfluxDB (no re-quantization needed)
            ts_ns = timestamp_ms * 1_000_000  # Convert ms to ns
            
            # Debug: Verify quantization is preserved (first few samples)
            if self.stats['points_written'] < 5:
                self.logger.info(f"=== TIMESTAMP VERIFICATION DEBUG ===")
                self.logger.info(f"Original timestamp: {timestamp}")
                self.logger.info(f"Integer timestamp: {timestamp_ms}")
                # Note: Timestamp quantization is now configurable, not hardcoded to 10ms
                self.logger.info(f"Timestamp: {timestamp_ms}ms")
                self.logger.info(f"Nanoseconds: {ts_ns}")
                self.logger.info(f"=== END DEBUG ===")
            
            # Prepare fields - only core measurement data
            sample_fields = {
                'sequence': int(sequence),
                'channel1': int(channel_values[0]),
                'channel2': int(channel_values[1]) if len(channel_values) > 1 else 0,
                'channel3': int(channel_values[2]) if len(channel_values) > 2 else 0
                # Note: timing_source, thingsboard_status, location_desc removed per user request
                # Note: sample_rate removed - calculate from timestamps for accuracy
            }
            
            # Merge additional fields (like calibrated g values) if provided
            if fields:
                sample_fields.update(fields)
            
            if self.buffer_on_error:
                self.q.put((ts_ns, sample_fields, tags))
                self.stats['buffer_size'] = self.q.qsize()
            else:
                self._do_write_sample(ts_ns, sample_fields, tags)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error preparing InfluxDB sample: {e}")
            self.stats['write_errors'] += 1
            return False

    def write_sample(self, timestamp, fields, tags=None, thingsboard_status=None):
        """
        Generic method to write any sample to InfluxDB
        
        Args:
            timestamp: Unix timestamp in nanoseconds
            fields: Dictionary of field values
            tags: Dictionary of tag values
            thingsboard_status: Legacy parameter (not used anymore)
        """
        if not self.connected:
            return False
        
        # No longer adding thingsboard_status to fields
        # if 'thingsboard_status' not in fields:
        #     fields['thingsboard_status'] = str(thingsboard_status)
            
        if self.buffer_on_error:
            self.q.put((timestamp, fields, tags))
            self.stats['buffer_size'] = self.q.qsize()
        else:
            self._do_write_sample(timestamp, fields, tags)
        return True

    def _do_write_sample(self, timestamp, fields, tags=None):
        """Internal method to write sample to InfluxDB"""
        try:
            point = Point(self.measurement).time(timestamp)
            
            # Add fields (combine common fields with sample-specific fields)
            all_fields = dict(self.common_fields)
            all_fields.update(fields)
            
            # Debug: Print tags and fields being written (only for first few points)
            if self.stats['points_written'] < 5:
                self.logger.info(f"=== InfluxDB Write Debug ===")
                self.logger.info(f"Common tags: {self.common_tags}")
                self.logger.info(f"Sample tags: {tags}")
                all_tags_debug = dict(self.common_tags)
                if tags:
                    all_tags_debug.update(tags)
                self.logger.info(f"Final tags: {all_tags_debug}")
                self.logger.info(f"Common fields: {self.common_fields}")
                self.logger.info(f"Sample fields: {fields}")
                self.logger.info(f"Final fields: {list(all_fields.keys())}")
                
                # Check specific values
                if 'full_range_value' in all_tags_debug:
                    self.logger.info(f"full_range_value in TAGS = {all_tags_debug['full_range_value']} (CORRECT)")
                if 'full_range_value' in all_fields:
                    self.logger.info(f"ERROR: full_range_value in FIELDS = {all_fields['full_range_value']} (SHOULD BE TAG!)")
                
                # Check for removed fields (should not appear)
                removed_fields = ['timing_source', 'thingsboard_status', 'location_desc']
                for field in removed_fields:
                    if field in all_tags_debug:
                        self.logger.info(f"WARNING: {field} in TAGS = {all_tags_debug[field]} (SHOULD BE REMOVED!)")
                    if field in all_fields:
                        self.logger.info(f"WARNING: {field} in FIELDS = {all_fields[field]} (SHOULD BE REMOVED!)")
                        
                self.logger.info(f"Core fields only: {[k for k in all_fields.keys() if k in ['sequence', 'channel1', 'channel2', 'channel3']]}")
                self.logger.info(f"=== End Debug ===")            
            
            for k, v in all_fields.items():
                point.field(k, v)
            
            # Add tags (combine common tags with sample-specific tags)
            all_tags = dict(self.common_tags)
            if tags:
                all_tags.update(tags)
            for k, v in all_tags.items():
                point.tag(k, str(v))
            
            # Write to InfluxDB
            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            self.stats['points_written'] += 1
            self.stats['last_write_time'] = datetime.now()
            
        except Exception as e:
            self.logger.error(f"InfluxDB write failed: {e}")
            self.stats['write_errors'] += 1

    def _worker_loop(self):
        """Background worker thread for buffered writing"""
        self.logger.info("InfluxDB worker thread started")
        
        while not self._stop_event.is_set():
            try:
                # Get item from queue with timeout
                item = self.q.get(timeout=0.5)
                timestamp, fields, tags = item
                
                # Write the sample
                self._do_write_sample(timestamp, fields, tags)
                self.q.task_done()
                
                # Update buffer size stat
                self.stats['buffer_size'] = self.q.qsize()
                
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Worker thread error: {e}")

    def get_stats(self):
        """Get InfluxDB writer statistics"""
        stats = dict(self.stats)
        stats['connected'] = self.connected
        stats['connection_ok'] = self.test_connection() if self.connected else False
        
        # Convert datetime to string for JSON serialization
        if stats.get('last_write_time'):
            stats['last_write_time'] = stats['last_write_time'].isoformat()
        
        return stats

    def flush(self):
        """Flush any pending writes"""
        try:
            if self.buffer_on_error and self.q:
                self.logger.info("Flushing InfluxDB buffer...")
                self.q.join()  # Wait for all items to be processed
            
            if self.write_api:
                self.write_api.flush()  # Flush InfluxDB write API
                
            self.logger.info("InfluxDB flush completed")
        except Exception as e:
            self.logger.error(f"Error flushing InfluxDB: {e}")

    def close(self):
        """Close the InfluxDB connection and stop background threads"""
        try:
            self.logger.info("Closing InfluxDB writer...")
            
            if self.buffer_on_error and hasattr(self, '_stop_event'):
                self._stop_event.set()
                if hasattr(self, 'worker'):
                    self.worker.join(timeout=5)
                self.flush()
            
            if hasattr(self, 'write_api') and self.write_api:
                self.write_api.close()
            
            if hasattr(self, 'client') and self.client:
                self.client.close()
            
            self.connected = False
            self.logger.info("InfluxDB writer closed")
            
        except Exception as e:
            self.logger.error(f"Error closing InfluxDB writer: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 