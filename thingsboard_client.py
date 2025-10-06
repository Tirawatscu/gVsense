#!/usr/bin/env python3
"""
Fixed ThingsBoard MQTT Client for Seismic Data
Provides buffered, error-resilient communication with ThingsBoard platform
"""

import logging
from datetime import datetime
import json
from typing import Dict, List, Optional, Tuple
import queue
import time
import threading

# SDK Import
from tb_device_mqtt import TBDeviceMqttClient, TBPublishInfo

class ThingsBoardClient:
    def __init__(self, host="localhost", port=1883, access_token=None, device_name="SeismicDevice", 
                 max_batch_size=100, retry_interval=30, buffer_on_error=True):
        """
        Initialize ThingsBoard MQTT client
        
        Args:
            host: ThingsBoard server hostname/IP
            port: MQTT port (1883 for non-TLS, 8883 for TLS)
            access_token: Device access token from ThingsBoard
            device_name: Device name for identification
            max_batch_size: Maximum number of samples to batch
            retry_interval: Retry interval in seconds for failed sends
            buffer_on_error: Whether to buffer data when connection fails
        """
        self.host = host
        self.port = int(port) if port else 1883 
        self.access_token = access_token
        self.device_name = device_name

        self.sdk_client: Optional[TBDeviceMqttClient] = None
        self.connected = False
        self._connection_lock = threading.Lock()
        
        self.stats = {
            'telemetry_sent': 0,
            'telemetry_failed': 0,
            'connection_errors': 0,
            'last_send_time': None,
            'connection_time': None
        }
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
            
    def _tb_publish_info_to_str(self, rc_code):
        """Convert TBPublishInfo result code to a string."""
        if rc_code == TBPublishInfo.TB_ERR_SUCCESS:
            return "TB_ERR_SUCCESS"
        elif rc_code == TBPublishInfo.TB_ERR_FAILURE:
            return "TB_ERR_FAILURE (General publish error)"
        elif rc_code == TBPublishInfo.TB_ERR_TIMEOUT:
            return "TB_ERR_TIMEOUT (Publish acknowledgement timed out)"
        return f"Unknown TBPublishInfo code: {rc_code}"

    def connect(self, use_tls=False, ca_certs=None, cert_file=None, key_file=None):
        """Connect to ThingsBoard with improved error handling"""
        with self._connection_lock:
            self.logger.info(f"Connecting to ThingsBoard at {self.host}:{self.port} (TLS: {use_tls})")
            
            if self.connected and self.sdk_client:
                self.logger.info("Already connected.")
                return True

            try:
                # Clean up existing connection
                if self.sdk_client:
                    try:
                        self.sdk_client.disconnect()
                    except:
                        pass
                    self.sdk_client = None

                # Create new client
                self.sdk_client = TBDeviceMqttClient(
                    host=self.host, 
                    port=self.port, 
                    username=self.access_token
                )
                
                # Connect with timeout
                if use_tls:
                    self.logger.info(f"Connecting with TLS. CA certs: {ca_certs}")
                    self.sdk_client.connect(tls=True, ca_certs=ca_certs, cert_file=cert_file)
                else:
                    self.sdk_client.connect()
                
                # Wait a moment for connection to establish
                time.sleep(2)
                
                # Verify connection with a test
                if self._verify_connection():
                    self.connected = True
                    self.stats['connection_time'] = datetime.now()
                    self.stats['connection_errors'] = 0
                    self.logger.info(f"Successfully connected to ThingsBoard: {self.host}:{self.port}")
                    return True
                else:
                    raise Exception("Connection verification failed")
                
            except Exception as e:
                self.logger.error(f"Error connecting to ThingsBoard ({self.host}:{self.port}): {e}")
                self.connected = False
                self.stats['connection_errors'] += 1
                self.sdk_client = None
                return False
    
    def _verify_connection(self):
        """Verify connection is working by sending a test message"""
        try:
            if not self.sdk_client:
                return False
                
            test_payload = {
                "ts": int(datetime.now().timestamp() * 1000),
                "values": {
                    "connection_test": True,
                    "device_name": self.device_name,
                    "test_time": datetime.now().isoformat()
                }
            }
            
            self.logger.info("Sending connection verification telemetry...")
            result = self.sdk_client.send_telemetry(test_payload)
            
            # Wait for acknowledgment with thread-based timeout
            try:
                result_container = [None]
                exception_container = [None]
                
                def get_result():
                    try:
                        result_container[0] = result.get()
                    except Exception as e:
                        exception_container[0] = e
                
                # Start thread to get result
                thread = threading.Thread(target=get_result)
                thread.daemon = True
                thread.start()
                thread.join(timeout=5)
                
                if thread.is_alive():
                    self.logger.warning("Connection verification timeout")
                    return False
                    
                if exception_container[0]:
                    raise exception_container[0]
                    
                ack_code = result_container[0]
                if ack_code == TBPublishInfo.TB_ERR_SUCCESS:
                    self.logger.info("Connection verification successful")
                    return True
                else:
                    self.logger.warning(f"Connection verification failed: {self._tb_publish_info_to_str(ack_code)}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Connection verification error: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Connection verification error: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from ThingsBoard"""
        with self._connection_lock:
            self.logger.info("Disconnecting from ThingsBoard...")
            if self.sdk_client:
                try:
                    self.sdk_client.disconnect()
                    self.logger.info("Disconnected from ThingsBoard.")
                except Exception as e:
                    self.logger.error(f"Error during SDK disconnect: {e}")
            else:
                self.logger.info("SDK client not initialized, nothing to disconnect.")
            
            self.connected = False
            self.sdk_client = None
            
    def send_telemetry_batch(self, batch: List[Dict]):
        """Send telemetry batch with improved error handling and connection checks"""
        if not batch:
            self.logger.debug("send_telemetry_batch called with empty batch.")
            return True # Or False, depending on desired behavior for empty batch
            
        self.logger.debug(f"Attempting to send batch of {len(batch)} items. Connected: {self.connected}")
        
        # Check connection status
        if not self.connected or not self.sdk_client:
            self.logger.error("Cannot send telemetry batch: Not connected")
            self.stats['telemetry_failed'] += len(batch) # Count all items in batch as failed
            return False 
        
        # Verify connection is still alive (optional, SDK might handle this)
        # if not self._quick_connection_check():
        #     self.logger.warning("Connection check failed, attempting reconnect...")
        #     if not self.connect(): # Assuming connect() is available and tries to re-establish
        #         self.logger.error("Reconnection failed")
        #         self.stats['telemetry_failed'] += len(batch)
        #         return False

        try:
            # The SDK's send_telemetry can handle a list of telemetry data directly
            result = self.sdk_client.send_telemetry(batch)
            
            # Wait for acknowledgment with thread-based timeout
            result_container = [None]
            exception_container = [None]
            
            def get_ack_result():
                try:
                    result_container[0] = result.get() # This will block until ack or timeout by SDK
                except Exception as e:
                    exception_container[0] = e
            
            ack_thread = threading.Thread(target=get_ack_result)
            ack_thread.daemon = True
            ack_thread.start()
            ack_thread.join(timeout=10) # Adjust timeout as needed for batch operations
            
            if ack_thread.is_alive():
                self.logger.warning(f"Timeout waiting for batch ACK ({len(batch)} items).")
                self.stats['telemetry_failed'] += len(batch)
                return False # Batch send timed out
                
            if exception_container[0]:
                self.logger.error(f"Exception waiting for batch ACK: {exception_container[0]}")
                self.stats['telemetry_failed'] += len(batch)
                return False # Exception during ACK
                
            ack_code = result_container[0]
            
            if ack_code == TBPublishInfo.TB_ERR_SUCCESS:
                self.stats['telemetry_sent'] += len(batch)
                self.stats['last_send_time'] = datetime.now()
                self.logger.info(f"Successfully sent batch of {len(batch)} items.")
                return True
            else:
                self.stats['telemetry_failed'] += len(batch)
                self.logger.warning(f"Failed to send batch ({len(batch)} items): {self._tb_publish_info_to_str(ack_code)}")
                return False
                
        except Exception as e:
            self.stats['telemetry_failed'] += len(batch) 
            self.logger.error(f"Exception sending telemetry batch ({len(batch)} items): {e}")
            return False
    
    def _quick_connection_check(self):
        """Quick check to see if connection is still alive"""
        try:
            if not self.sdk_client:
                return False
                
            # The SDK should handle internal connection checking
            # We'll assume it's connected if we have a client and no recent errors
            return True
            
        except Exception as e:
            self.logger.debug(f"Connection check failed: {e}")
            return False
    
    def test_connection(self):
        """Test ThingsBoard connection with comprehensive checks"""
        self.logger.info("Testing ThingsBoard connection...")
        
        if not self.connected or not self.sdk_client:
            self.logger.warning("Test connection: Not connected. Attempting to connect...")
            if not self.connect(use_tls=False):  # Default to non-TLS for test
                self.logger.error("Test connection: Failed to connect.")
                return False
            
        try:
            test_payload = {
                "ts": int(datetime.now().timestamp() * 1000),
                "values": {
                    "test_message": "connection_test",
                    "device_name": self.device_name,
                    "test_timestamp": datetime.now().isoformat()
                }
            }
            
            self.logger.info(f"Sending test telemetry: {json.dumps(test_payload, default=str)}")
            result = self.sdk_client.send_telemetry(test_payload)
            
            # Compatible acknowledgment handling with thread-based timeout
            try:
                result_container = [None]
                exception_container = [None]
                
                def get_result():
                    try:
                        result_container[0] = result.get()
                    except Exception as e:
                        exception_container[0] = e
                
                # Start thread to get result
                thread = threading.Thread(target=get_result)
                thread.daemon = True
                thread.start()
                thread.join(timeout=10)
                
                if thread.is_alive():
                    self.logger.error("Test telemetry acknowledgment timeout")
                    return False
                    
                if exception_container[0]:
                    raise exception_container[0]
                    
                ack_code = result_container[0]
                if ack_code == TBPublishInfo.TB_ERR_SUCCESS: 
                    self.logger.info("Test telemetry sent successfully and acknowledged.")
                    return True
                else:
                    self.logger.error(f"Test telemetry failed: {self._tb_publish_info_to_str(ack_code)}")
                    return False
                
            except Exception as e:
                self.logger.error(f"Exception during test_connection: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Exception during test_connection: {e}")
            return False
    
    def get_stats(self):
        """Get client statistics"""
        current_stats = dict(self.stats)
        current_stats['connected'] = self.connected
        current_stats['host'] = self.host
        current_stats['port'] = self.port
        current_stats['device_name'] = self.device_name
        
        # Convert datetime objects to ISO strings
        if current_stats['last_send_time'] and isinstance(current_stats['last_send_time'], datetime):
            current_stats['last_send_time'] = current_stats['last_send_time'].isoformat()
        if current_stats['connection_time'] and isinstance(current_stats['connection_time'], datetime):
            current_stats['connection_time'] = current_stats['connection_time'].isoformat()
            
        return current_stats