#!/usr/bin/env python3
"""
Multi-format Data Saver for Seismic Data Acquisition
Sends data to ThingsBoard first (buffered, batched), then saves to CSV files and/or InfluxDB
"""

import csv
import os
from datetime import datetime
from influx_writer import InfluxWriter
from thingsboard_client import ThingsBoardClient
import json
import queue
import threading
import time

class DataSaver:
    def __init__(self, csv_filename=None, influx_config=None, thingsboard_config=None, csv_fields=None, common_tags=None):
        """
        Initialize data saver with CSV, InfluxDB, and/or ThingsBoard support
        
        Args:
            csv_filename: Path to CSV file (None to disable CSV)
            influx_config: Dict with InfluxDB config (None to disable InfluxDB)
            thingsboard_config: Dict with ThingsBoard config (None to disable ThingsBoard)
            csv_fields: List of CSV field names
            common_tags: Common tags to apply to InfluxDB points
        """
        self.csv_filename = csv_filename
        self.csv_fields = csv_fields or ['timestamp', 'datetime', 'sequence', 'channel1', 'channel2', 'channel3', 'thingsboard_status']
        self.common_tags = common_tags or {}
        
        # Initialize CSV
        if csv_filename:
            self._init_csv()
        
        # Initialize InfluxDB
        self.influx_writer = None
        if influx_config:
            self._init_influxdb(influx_config)
        
        # Initialize ThingsBoard Client and Buffered Sender
        self.tb_client = None
        self.tb_buffer = None
        self.tb_sender_thread = None
        self._tb_stop_event = None
        self.tb_send_interval = 1.0 # Default 1 second

        if thingsboard_config and thingsboard_config.get('enabled', False):
            self._init_thingsboard(thingsboard_config)
            if self.tb_client and self.tb_client.connected:
                self.tb_buffer = queue.Queue()
                self._tb_stop_event = threading.Event()
                # Get send interval from config or use default
                self.tb_send_interval = float(thingsboard_config.get('send_interval_sec', 1.0))
                self.tb_sender_thread = threading.Thread(target=self._thingsboard_sender_loop, daemon=True)
                self.tb_sender_thread.start()
                print(f"ThingsBoard buffered sender started with {self.tb_send_interval}s interval.")
        
        # Statistics
        self.stats = {
            'csv_samples': 0,
            'influx_samples': 0,
            'thingsboard_queued': 0,
            'thingsboard_sent_batches': 0,
            'thingsboard_failed_batches': 0,
            'thingsboard_sent_items': 0,
            'thingsboard_failed_items': 0,
            'csv_errors': 0,
            'influx_errors': 0,
            'start_time': datetime.now(),
            'tb_buffer_size': 0
        }

    def _init_csv(self):
        """Initialize CSV file with headers"""
        try:
            directory = os.path.dirname(self.csv_filename)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            if not os.path.isfile(self.csv_filename):
                with open(self.csv_filename, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=self.csv_fields)
                    writer.writeheader()
                print(f"Created CSV file: {self.csv_filename}")
        except Exception as e:
            print(f"Error initializing CSV: {e}")

    def _init_influxdb(self, config):
        """Initialize InfluxDB writer"""
        try:
            self.influx_writer = InfluxWriter(
                url=config.get('url', 'http://localhost:8086'),
                token=config.get('token'),
                org=config.get('org'),
                bucket=config.get('bucket'),
                measurement=config.get('measurement', 'seismic'),
                batch_size=config.get('batch_size', 100),
                tags=config.get('tags', {}),
                fields=config.get('fields', {}),
                buffer_on_error=config.get('buffer_on_error', True)
            )
            
            if self.influx_writer.test_connection():
                print(f"InfluxDB connected: {config.get('url')}")
            else:
                print(f"InfluxDB connection failed: {config.get('url')}")
                
        except Exception as e:
            print(f"Error initializing InfluxDB: {e}")
            self.influx_writer = None

    def _init_thingsboard(self, config):
        """Initialize ThingsBoard client"""
        try:
            self.tb_client = ThingsBoardClient(
                host=config.get('host', 'localhost'),
                port=config.get('port', 1883),
                access_token=config.get('access_token'),
                device_name=config.get('device_name', 'SeismicDevice')
            )
            use_tls = config.get('use_tls', False)
            if self.tb_client.connect(use_tls=use_tls):
                print(f"ThingsBoard connected: {config.get('host')}")
            else:
                print(f"ThingsBoard connection failed: {config.get('host')}")
                self.tb_client = None
        except Exception as e:
            print(f"Error initializing ThingsBoard client: {e}")
            self.tb_client = None

    def _thingsboard_sender_loop(self):
        """Periodically sends data from tb_buffer to ThingsBoard"""
        while not self._tb_stop_event.is_set():
            time.sleep(self.tb_send_interval) # Wait for the send interval
            
            current_batch = []
            while not self.tb_buffer.empty():
                try:
                    # Get up to N items or whatever is in the queue
                    # For simplicity, getting all for now. Can be limited.
                    item = self.tb_buffer.get_nowait()
                    current_batch.append(item)
                    self.tb_buffer.task_done() 
                except queue.Empty:
                    break # Should not happen if checked tb_buffer.empty()
            
            self.stats['tb_buffer_size'] = self.tb_buffer.qsize() # Update buffer size stat

            if current_batch:
                if self.tb_client and self.tb_client.connected:
                    print(f"ThingsBoard Sender: Attempting to send batch of {len(current_batch)} items.")
                    if self.tb_client.send_telemetry_batch(current_batch):
                        self.stats['thingsboard_sent_batches'] += 1
                        self.stats['thingsboard_sent_items'] += len(current_batch)
                        print(f"ThingsBoard Sender: Successfully sent batch of {len(current_batch)} items.")
                    else:
                        self.stats['thingsboard_failed_batches'] += 1
                        self.stats['thingsboard_failed_items'] += len(current_batch)
                        # Optionally, re-queue failed batch items if sophisticated retry is needed here
                        # For now, they are just marked as failed.
                        print(f"ThingsBoard Sender: Failed to send batch of {len(current_batch)} items.")
                else:
                    self.stats['thingsboard_failed_batches'] += 1
                    self.stats['thingsboard_failed_items'] += len(current_batch)
                    print(f"ThingsBoard Sender: Client not connected. Failed to send batch of {len(current_batch)} items.")
                    # Re-queue if not connected and retry later? Or handle in tb_client.connect
                    # For now, items are lost if client is disconnected during this send attempt.

    def save_seismic_sample(self, timestamp, sequence, channel_values, sample_tags=None, sample_fields=None):
        """
        Queue for ThingsBoard, then save a seismic data sample to other configured outputs.
        
        Args:
            timestamp: Unix timestamp in milliseconds (can include decimal)
            sequence: Sample sequence number
            channel_values: List of ADC values [ch1, ch2, ch3]
            sample_tags: Additional tags for this sample
            sample_fields: Additional fields for this sample
        """
        thingsboard_status = "tb_disabled" # Default if TB not configured/enabled
        
        # FIXED: Remove redundant quantization - timestamps are already perfectly quantized
        # The SimplifiedTimestampGenerator provides exact configurable quantization boundaries
        if isinstance(timestamp, str) and '.' in timestamp:
            timestamp_ms = int(float(timestamp))
        else:
            timestamp_ms = int(timestamp)
        
        # Convert timestamp to datetime (no re-quantization needed)
        dt_obj = datetime.fromtimestamp(timestamp_ms / 1000.0)
        ts_ms = timestamp_ms
        
        datetime_str = dt_obj.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # 1. Queue for ThingsBoard if enabled and client connected
        if self.tb_client and self.tb_buffer is not None: # Check tb_buffer for sender thread
            telemetry_values = {
                "count_z": float(channel_values[0]),
                "count_x": float(channel_values[1]) if len(channel_values) > 1 else 0.0,
                "count_y": float(channel_values[2]) if len(channel_values) > 2 else 0.0
            }
            
            # Add calibrated g values if provided
            if sample_fields and 'Value_x' in sample_fields:
                telemetry_values.update({
                    "Value_x": sample_fields['Value_x'],
                    "Value_y": sample_fields['Value_y'],
                    "Value_z": sample_fields['Value_z']
                })
            
            telemetry_item = {
                "ts": ts_ms,
                "values": telemetry_values
            }
            try:
                self.tb_buffer.put_nowait(telemetry_item)
                self.stats['thingsboard_queued'] += 1
                thingsboard_status = "queued"
            except queue.Full:
                thingsboard_status = "tb_buffer_full"
                self.stats['thingsboard_failed_items'] +=1 # Consider this a failure to queue
                print("Warning: ThingsBoard buffer is full. Sample not queued.")
        elif self.tb_client and self.tb_buffer is None: # Client configured but sender thread didn't start (e.g. not connected initially)
             thingsboard_status = "tb_sender_not_ready"
        
        self.stats['tb_buffer_size'] = self.tb_buffer.qsize() if self.tb_buffer else 0


        # Prepare sample for CSV/InfluxDB with the current TB status
        sample_for_csv_influx = {
            'timestamp': timestamp,
            'datetime': datetime_str,
            'sequence': sequence,
            'channel1': channel_values[0],
            'channel2': channel_values[1] if len(channel_values) > 1 else 0,
            'channel3': channel_values[2] if len(channel_values) > 2 else 0,
            'thingsboard_status': thingsboard_status 
        }

        # 2. Save to CSV
        if self.csv_filename:
            if self._save_csv(sample_for_csv_influx):
                self.stats['csv_samples'] += 1
            else:
                self.stats['csv_errors'] += 1
        
        # 3. Save to InfluxDB (no thingsboard_status saved anymore)
        if self.influx_writer:
            if self.influx_writer.write_seismic_sample(timestamp, sequence, channel_values, sample_tags, sample_fields):
                self.stats['influx_samples'] += 1
            else:
                self.stats['influx_errors'] += 1
        
        # This method no longer directly returns send success, as TB send is async
        return True # Indicates sample was processed by DataSaver

    def save(self, sample, tags=None, fields=None):
        """
        Generic save method. Send to ThingsBoard then save.
        Assumes 'sample' dict contains 'timestamp', 'sequence', 'channel1', etc.
        """
        timestamp = sample.get('timestamp')
        sequence = sample.get('sequence')
        # Construct channel_values from sample if they exist
        channel_values = [
            sample.get('channel1', 0),
            sample.get('channel2', 0),
            sample.get('channel3', 0)
        ]

        if timestamp is None or sequence is None:
            print("Error: 'timestamp' and 'sequence' are required in sample for generic save.")
            return False
            
        return self.save_seismic_sample(timestamp, sequence, channel_values, sample_tags=tags, sample_fields=fields)

    def _save_csv(self, sample):
        """Save sample to CSV file"""
        try:
            complete_sample = {field: sample.get(field) for field in self.csv_fields}

            with open(self.csv_filename, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.csv_fields)
                if f.tell() == 0:
                    writer.writeheader()
                writer.writerow(complete_sample)
            return True
        except Exception as e:
            print(f"CSV save error: {e}")
            return False

    def get_stats(self):
        """Get saving statistics"""
        stats_copy = dict(self.stats)
        
        if stats_copy.get('start_time') and isinstance(stats_copy['start_time'], datetime):
            stats_copy['start_time'] = stats_copy['start_time'].isoformat()
        
        if self.influx_writer:
            stats_copy['influx_status'] = self.influx_writer.get_stats()
        else:
            stats_copy['influx_status'] = {'connected': False, 'points_written': 0, 'write_errors': 0}

        # Update with direct TB client stats and buffer stats
        tb_client_stats = {}
        if self.tb_client:
            tb_client_stats = self.tb_client.get_stats()
        
        stats_copy['thingsboard_client_status'] = tb_client_stats
        stats_copy['tb_buffer_size'] = self.tb_buffer.qsize() if self.tb_buffer else 0
        stats_copy['tb_sender_alive'] = self.tb_sender_thread.is_alive() if self.tb_sender_thread else False
        
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
        if elapsed > 0:
            stats_copy['csv_rate'] = self.stats['csv_samples'] / elapsed
            stats_copy['influx_rate'] = self.stats['influx_samples'] / elapsed
            stats_copy['thingsboard_queue_rate'] = self.stats['thingsboard_queued'] / elapsed
            stats_copy['thingsboard_send_rate_items'] = self.stats['thingsboard_sent_items'] / elapsed
        else:
            stats_copy['csv_rate'] = 0
            stats_copy['influx_rate'] = 0
            stats_copy['thingsboard_queue_rate'] = 0
            stats_copy['thingsboard_send_rate_items'] = 0
        
        return stats_copy

    def is_influx_connected(self):
        """Check if InfluxDB is connected"""
        return self.influx_writer and self.influx_writer.connected

    def is_csv_enabled(self):
        """Check if CSV saving is enabled"""
        return bool(self.csv_filename)

    def is_thingsboard_connected(self):
        """Check if ThingsBoard is connected"""
        return self.tb_client and self.tb_client.connected

    def flush(self):
        """Flush any pending writes"""
        if self.influx_writer:
            self.influx_writer.flush()
        # For ThingsBoard, the sender loop handles periodic sending.
        # A manual flush could optionally try to send the current tb_buffer contents immediately.
        # For now, relying on the periodic sender or close().

    def close(self):
        """Close all connections and stop worker threads"""
        print("Closing DataSaver...")
        if self._tb_stop_event:
            print("Stopping ThingsBoard sender thread...")
            self._tb_stop_event.set()
        if self.tb_sender_thread:
            self.tb_sender_thread.join(timeout=self.tb_send_interval + 1) # Wait for one more cycle + buffer
            if self.tb_sender_thread.is_alive():
                print("Warning: ThingsBoard sender thread did not terminate cleanly.")
            else:
                print("ThingsBoard sender thread stopped.")
        
        # Process any remaining items in tb_buffer after attempting to stop the thread
        # This ensures data queued right before close might still be sent if connection is up
        if self.tb_buffer and not self.tb_buffer.empty():
            print(f"Processing remaining {self.tb_buffer.qsize()} items in ThingsBoard buffer before closing...")
            # Call the sender logic one last time manually
            # This is a simplified version, a more robust one might check connection etc.
            final_batch = []
            while not self.tb_buffer.empty():
                try:
                    final_batch.append(self.tb_buffer.get_nowait())
                    self.tb_buffer.task_done()
                except queue.Empty:
                    break
            if final_batch and self.tb_client and self.tb_client.connected:
                print(f"Sending final batch of {len(final_batch)} items to ThingsBoard...")
                if self.tb_client.send_telemetry_batch(final_batch):
                    self.stats['thingsboard_sent_batches'] += 1
                    self.stats['thingsboard_sent_items'] += len(final_batch)
                    print("Final ThingsBoard batch sent successfully.")
                else:
                    self.stats['thingsboard_failed_batches'] += 1
                    self.stats['thingsboard_failed_items'] += len(final_batch)
                    print("Failed to send final ThingsBoard batch.")
            elif final_batch:
                print("ThingsBoard client not connected, could not send final batch.")

        if self.tb_client:
            self.tb_client.disconnect()
            self.tb_client = None
            print("ThingsBoard client disconnected.")

        if self.influx_writer:
            self.influx_writer.close()
            self.influx_writer = None
            print("InfluxDB writer closed.")
        print("DataSaver closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 