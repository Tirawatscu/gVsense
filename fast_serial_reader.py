#!/usr/bin/env python3
"""
Fast Serial Reader with Large Buffers and Async Parsing Queue
High-performance serial data ingestion for gVsense
"""

import serial
import threading
import queue
import time
import logging
from collections import deque
from typing import Optional, Callable, Dict, Any, List
import struct

def crc16_xmodem(data: bytes) -> int:
    """Simple CRC-16 XMODEM implementation"""
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

logger = logging.getLogger(__name__)

class FastSerialReader:
    """High-performance serial reader with async parsing"""
    
    def __init__(self, port: str, baudrate: int = 921600, 
                 buffer_size: int = 1024*1024,  # 1MB buffer
                 parse_queue_size: int = 10000):
        self.port = port
        self.baudrate = baudrate
        self.buffer_size = buffer_size
        self.parse_queue_size = parse_queue_size
        
        # Serial connection
        self.serial_port: Optional[serial.Serial] = None
        self.is_connected = False
        
        # Threading
        self.reader_thread: Optional[threading.Thread] = None
        self.parser_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Buffers and queues
        self.raw_buffer = bytearray()
        self.parse_queue = queue.Queue(maxsize=parse_queue_size)
        self.overflow_count = 0
        self.total_bytes_read = 0
        self.total_samples_parsed = 0
        
        # Performance monitoring
        self.read_rate_hz = 0.0
        self.parse_rate_hz = 0.0
        self.last_stats_time = time.time()
        self.last_bytes_read = 0
        self.last_samples_parsed = 0
        
        # Callbacks
        self.sample_callback: Optional[Callable] = None
        self.meta_callback: Optional[Callable] = None
        self.error_callback: Optional[Callable] = None
        
        # Binary framing support
        self.binary_framing_enabled = False
        self.sync_word = b'\xAA\x55\xAA\x55'  # 4-byte sync word
        self.frame_buffer = bytearray()
        self.crc_enabled = True
        
    def connect(self) -> bool:
        """Connect to serial port"""
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1,  # Non-blocking
                write_timeout=1.0,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            
            # Configure buffer sizes
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            
            self.is_connected = True
            logger.info(f"Connected to {self.port} at {self.baudrate} baud")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            self.is_connected = False
            return False
            
    def disconnect(self):
        """Disconnect from serial port"""
        self.stop()
        
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            
        self.is_connected = False
        logger.info("Disconnected from serial port")
        
    def start(self):
        """Start reader and parser threads"""
        if not self.is_connected:
            raise RuntimeError("Not connected to serial port")
            
        self.stop_event.clear()
        
        # Start reader thread
        self.reader_thread = threading.Thread(
            target=self._reader_loop, 
            name="SerialReader",
            daemon=True
        )
        self.reader_thread.start()
        
        # Start parser thread
        self.parser_thread = threading.Thread(
            target=self._parser_loop,
            name="SerialParser", 
            daemon=True
        )
        self.parser_thread.start()
        
        logger.info("Fast serial reader started")
        
    def stop(self):
        """Stop reader and parser threads"""
        self.stop_event.set()
        
        if self.reader_thread:
            self.reader_thread.join(timeout=2.0)
            
        if self.parser_thread:
            self.parser_thread.join(timeout=2.0)
            
        logger.info("Fast serial reader stopped")
        
    def _reader_loop(self):
        """High-performance serial reading loop"""
        logger.info("Serial reader thread started")
        
        while not self.stop_event.is_set():
            try:
                if not self.serial_port or not self.serial_port.is_open:
                    time.sleep(0.1)
                    continue
                    
                # Read available data
                bytes_available = self.serial_port.in_waiting
                if bytes_available > 0:
                    # Limit read size to prevent blocking
                    read_size = min(bytes_available, 8192)
                    data = self.serial_port.read(read_size)
                    
                    if data:
                        self.raw_buffer.extend(data)
                        self.total_bytes_read += len(data)
                        
                        # Trim buffer if it gets too large
                        if len(self.raw_buffer) > self.buffer_size:
                            # Keep last 50% of buffer
                            keep_size = self.buffer_size // 2
                            self.raw_buffer = self.raw_buffer[-keep_size:]
                            self.overflow_count += 1
                            
                else:
                    # No data available, small sleep
                    time.sleep(0.001)
                    
            except Exception as e:
                logger.error(f"Error in reader loop: {e}")
                if self.error_callback:
                    self.error_callback(e)
                time.sleep(0.1)
                
        logger.info("Serial reader thread stopped")
        
    def _parser_loop(self):
        """Async parsing loop"""
        logger.info("Serial parser thread started")
        
        while not self.stop_event.is_set():
            try:
                if self.binary_framing_enabled:
                    self._parse_binary_frames()
                else:
                    self._parse_text_lines()
                    
                # Update performance stats
                self._update_stats()
                
                # Small sleep to prevent CPU spinning
                time.sleep(0.001)
                
            except Exception as e:
                logger.error(f"Error in parser loop: {e}")
                if self.error_callback:
                    self.error_callback(e)
                time.sleep(0.1)
                
        logger.info("Serial parser thread stopped")
        
    def _parse_text_lines(self):
        """Parse text-based protocol (SAMPLE, STAT, etc.)"""
        if len(self.raw_buffer) == 0:
            return
            
        # Find complete lines
        while b'\n' in self.raw_buffer:
            line_end = self.raw_buffer.find(b'\n')
            line = self.raw_buffer[:line_end].decode('utf-8', errors='ignore').strip()
            self.raw_buffer = self.raw_buffer[line_end + 1:]
            
            if line:
                try:
                    # Put line in parse queue
                    if not self.parse_queue.full():
                        self.parse_queue.put_nowait(('text', line, time.time()))
                    else:
                        self.overflow_count += 1
                        
                except queue.Full:
                    self.overflow_count += 1
                    
    def _parse_binary_frames(self):
        """Parse binary frames with sync word + length + CRC"""
        if len(self.raw_buffer) < 8:  # Minimum frame size
            return
            
        # Look for sync word
        sync_pos = self.raw_buffer.find(self.sync_word)
        if sync_pos == -1:
            # No sync word found, keep last few bytes
            if len(self.raw_buffer) > len(self.sync_word):
                self.raw_buffer = self.raw_buffer[-len(self.sync_word):]
            return
            
        # Remove data before sync word
        if sync_pos > 0:
            self.raw_buffer = self.raw_buffer[sync_pos:]
            
        # Check if we have enough data for frame header
        if len(self.raw_buffer) < 8:  # sync(4) + length(2) + crc(2)
            return
            
        # Parse frame header
        sync = self.raw_buffer[:4]
        length = struct.unpack('<H', self.raw_buffer[4:6])[0]  # Little-endian
        crc = struct.unpack('<H', self.raw_buffer[6:8])[0]
        
        # Validate frame length
        if length < 8 or length > 1024:  # Sanity check
            # Invalid frame, skip one byte and try again
            self.raw_buffer = self.raw_buffer[1:]
            return
            
        # Check if we have complete frame
        if len(self.raw_buffer) < length:
            return
            
        # Extract frame data
        frame_data = self.raw_buffer[8:length-2]  # Skip sync, length, crc
        received_crc = struct.unpack('<H', self.raw_buffer[length-2:length])[0]
        
        # Verify CRC
        if self.crc_enabled:
            calculated_crc = crc16_xmodem(frame_data)
            if calculated_crc != received_crc:
                logger.warning(f"CRC mismatch: calculated={calculated_crc:04X}, received={received_crc:04X}")
                # Skip this frame
                self.raw_buffer = self.raw_buffer[length:]
                return
                
        # Valid frame, put in parse queue
        try:
            if not self.parse_queue.full():
                self.parse_queue.put_nowait(('binary', frame_data, time.time()))
            else:
                self.overflow_count += 1
                
        except queue.Full:
            self.overflow_count += 1
            
        # Remove processed frame
        self.raw_buffer = self.raw_buffer[length:]
        
    def _update_stats(self):
        """Update performance statistics"""
        current_time = time.time()
        time_diff = current_time - self.last_stats_time
        
        if time_diff >= 1.0:  # Update every second
            bytes_diff = self.total_bytes_read - self.last_bytes_read
            samples_diff = self.total_samples_parsed - self.last_samples_parsed
            
            self.read_rate_hz = bytes_diff / time_diff
            self.parse_rate_hz = samples_diff / time_diff
            
            self.last_stats_time = current_time
            self.last_bytes_read = self.total_bytes_read
            self.last_samples_parsed = self.total_samples_parsed
            
    def process_queue(self, max_items: int = 100) -> int:
        """Process items from parse queue"""
        processed = 0
        
        for _ in range(max_items):
            try:
                item_type, data, timestamp = self.parse_queue.get_nowait()
                
                if item_type == 'text':
                    self._handle_text_line(data, timestamp)
                elif item_type == 'binary':
                    self._handle_binary_frame(data, timestamp)
                    
                self.total_samples_parsed += 1
                processed += 1
                
            except queue.Empty:
                break
                
        return processed
        
    def _handle_text_line(self, line: str, timestamp: float):
        """Handle text-based protocol line"""
        if line.startswith('SAMPLE:'):
            self._parse_sample_line(line, timestamp)
        elif line.startswith('STAT:'):
            self._parse_stat_line(line, timestamp)
        elif line.startswith('SESSION:'):
            self._parse_session_line(line, timestamp)
        elif line.startswith('BOOT:'):
            self._parse_boot_line(line, timestamp)
        elif line.startswith('OFLOW:'):
            self._parse_oflow_line(line, timestamp)
        else:
            # Unknown line type
            logger.debug(f"Unknown line: {line}")
            
    def _handle_binary_frame(self, data: bytes, timestamp: float):
        """Handle binary frame data"""
        if len(data) < 8:  # Minimum sample size
            return
            
        try:
            # Parse binary sample format
            # Format: timestamp(8) + sequence(2) + channel1(4) + channel2(4) + ...
            timestamp_us = struct.unpack('<Q', data[:8])[0]  # 64-bit timestamp
            sequence = struct.unpack('<H', data[8:10])[0]  # 16-bit sequence
            
            # Parse channel data
            channels = []
            offset = 10
            while offset + 4 <= len(data):
                channel_value = struct.unpack('<i', data[offset:offset+4])[0]  # 32-bit signed
                channels.append(channel_value)
                offset += 4
                
            # Call sample callback
            if self.sample_callback:
                self.sample_callback({
                    'timestamp_us': timestamp_us,
                    'sequence': sequence,
                    'channels': channels,
                    'arrival_time': timestamp,
                    'format': 'binary'
                })
                
        except Exception as e:
            logger.error(f"Error parsing binary frame: {e}")
            
    def _parse_sample_line(self, line: str, timestamp: float):
        """Parse SAMPLE line"""
        try:
            parts = line[7:].split(',')  # Remove 'SAMPLE:' prefix
            if len(parts) >= 3:
                timestamp_us = int(parts[0])
                sequence = int(parts[1])
                channels = [int(x) for x in parts[2:]]
                
                if self.sample_callback:
                    self.sample_callback({
                        'timestamp_us': timestamp_us,
                        'sequence': sequence,
                        'channels': channels,
                        'arrival_time': timestamp,
                        'format': 'text'
                    })
                    
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing sample line: {e}")
            
    def _parse_stat_line(self, line: str, timestamp: float):
        """Parse STAT line"""
        try:
            parts = line[5:].split(',')  # Remove 'STAT:' prefix
            if len(parts) >= 10:
                stat_data = {
                    'timing_source': parts[0],
                    'accuracy_us': float(parts[1]),
                    'calibration_ppm': float(parts[2]),
                    'pps_valid': parts[3] == '1',
                    'pps_age_ms': int(parts[4]),
                    'calibration_valid': parts[5] == '1',
                    'calibration_source': parts[6],
                    'micros_wraparound_count': int(parts[7]),
                    'buffer_overflows': int(parts[8]),
                    'samples_skipped_due_to_overflow': int(parts[9]),
                    'boot_id': int(parts[10]) if len(parts) > 10 else 0,
                    'stream_id': int(parts[11]) if len(parts) > 11 else 0,
                    'adc_deadline_misses': int(parts[12]) if len(parts) > 12 else 0,
                    'timestamp': timestamp
                }
                
                if self.meta_callback:
                    self.meta_callback('STAT', stat_data)
                    
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing stat line: {e}")
            
    def _parse_session_line(self, line: str, timestamp: float):
        """Parse SESSION line"""
        try:
            parts = line[8:].split(',')  # Remove 'SESSION:' prefix
            session_data = {}
            
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    session_data[key] = value
                    
            session_data['timestamp'] = timestamp
            
            if self.meta_callback:
                self.meta_callback('SESSION', session_data)
                
        except Exception as e:
            logger.error(f"Error parsing session line: {e}")
            
    def _parse_boot_line(self, line: str, timestamp: float):
        """Parse BOOT line"""
        try:
            parts = line[5:].split(',')  # Remove 'BOOT:' prefix
            boot_data = {}
            
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    boot_data[key] = value
                    
            boot_data['timestamp'] = timestamp
            
            if self.meta_callback:
                self.meta_callback('BOOT', boot_data)
                
        except Exception as e:
            logger.error(f"Error parsing boot line: {e}")
            
    def _parse_oflow_line(self, line: str, timestamp: float):
        """Parse OFLOW line"""
        try:
            parts = line[6:].split(',')  # Remove 'OFLOW:' prefix
            oflow_data = {}
            
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    oflow_data[key] = value
                    
            oflow_data['timestamp'] = timestamp
            
            if self.meta_callback:
                self.meta_callback('OFLOW', oflow_data)
                
        except Exception as e:
            logger.error(f"Error parsing oflow line: {e}")
            
    def enable_binary_framing(self, sync_word: bytes = None, crc_enabled: bool = True):
        """Enable binary framing mode"""
        self.binary_framing_enabled = True
        if sync_word:
            self.sync_word = sync_word
        self.crc_enabled = crc_enabled
        logger.info("Binary framing enabled")
        
    def disable_binary_framing(self):
        """Disable binary framing mode"""
        self.binary_framing_enabled = False
        logger.info("Binary framing disabled")
        
    def send_command(self, command: str) -> bool:
        """Send command to MCU"""
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.write(f"{command}\n".encode())
                self.serial_port.flush()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return False
            
    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        return {
            'total_bytes_read': self.total_bytes_read,
            'total_samples_parsed': self.total_samples_parsed,
            'read_rate_hz': self.read_rate_hz,
            'parse_rate_hz': self.parse_rate_hz,
            'overflow_count': self.overflow_count,
            'buffer_size': len(self.raw_buffer),
            'queue_size': self.parse_queue.qsize(),
            'queue_maxsize': self.parse_queue.maxsize,
            'binary_framing_enabled': self.binary_framing_enabled,
            'is_connected': self.is_connected
        }

# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fast Serial Reader Test")
    parser.add_argument("--port", required=True, help="Serial port")
    parser.add_argument("--baudrate", type=int, default=921600, help="Baud rate")
    parser.add_argument("--binary", action="store_true", help="Enable binary framing")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create reader
    reader = FastSerialReader(args.port, args.baudrate)
    
    # Setup callbacks
    def sample_callback(data):
        print(f"SAMPLE: {data['timestamp_us']}, seq={data['sequence']}, channels={data['channels']}")
        
    def meta_callback(msg_type, data):
        print(f"{msg_type}: {data}")
        
    reader.sample_callback = sample_callback
    reader.meta_callback = meta_callback
    
    # Enable binary framing if requested
    if args.binary:
        reader.enable_binary_framing()
        
    try:
        # Connect and start
        if reader.connect():
            reader.start()
            
            # Main loop
            while True:
                processed = reader.process_queue()
                if processed > 0:
                    print(f"Processed {processed} items")
                    
                # Print stats every 10 seconds
                stats = reader.get_stats()
                print(f"Stats: {stats}")
                time.sleep(10)
                
    except KeyboardInterrupt:
        print("\nShutting down...")
        reader.disconnect()
