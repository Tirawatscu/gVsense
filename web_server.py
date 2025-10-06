#!/usr/bin/env python3
"""
Web-based monitoring and configuration interface for Host-Managed Timing Seismic Data Acquisition
Modified to work with the new HostTimingSeismicAcquisition class
"""

from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
import threading
import time
import json
import csv
import os
import socket
from datetime import datetime
import subprocess
from collections import deque
import numpy as np

# MODIFIED: Import the new host-managed timing acquisition class
from host_timing_acquisition import HostTimingSeismicAcquisition
from data_saver import DataSaver
from adaptive_timing_controller import AdaptiveTimingController

def make_json_safe(obj):
    """Convert non-JSON-serializable objects to JSON-safe format"""
    if isinstance(obj, dict):
        return {key: make_json_safe(value) for key, value in obj.items()}
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
        try:
            return list(obj)[:10]  # Convert deque to list (first 10 items)
        except:
            return f"<{type(obj).__name__}>"
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)

# GPIO setup for MCU reset (optional, using lgpio for Raspberry Pi 5)
RESET_PIN = 12  # GPIO pin 12 for MCU reset
GPIO_AVAILABLE = False
try:
    import lgpio
    h = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_output(h, RESET_PIN)
    lgpio.gpio_write(h, RESET_PIN, 1)  # Active low reset (set HIGH initially)
    GPIO_AVAILABLE = True
    print("lgpio support enabled")
except ImportError as e:
    print("No lgpio support:", e)
    GPIO_AVAILABLE = False
except Exception as e:
    print("lgpio initialization failed:", e)
    GPIO_AVAILABLE = False

def reset_mcu():
    """Enhanced MCU reset with better timing"""
    if GPIO_AVAILABLE:
        try:
            print("Resetting MCU via lgpio...")
            lgpio.gpio_write(h, RESET_PIN, 0)  # Assert reset (active low)
            time.sleep(0.2)  # Increased hold time to 200ms
            lgpio.gpio_write(h, RESET_PIN, 1)  # Release reset
            time.sleep(3)  # Increased wait time to 3 seconds
            print("MCU reset complete")
            return True
        except Exception as e:
            print(f"Error resetting MCU via lgpio: {e}")
            return False
    else:
        # Alternative reset method: disconnect and reconnect serial
        try:
            print("Resetting MCU via serial reconnect...")
            global seismic
            if seismic:
                seismic.close()
                time.sleep(3)  # Increased wait time
                if connect_device():
                    print("MCU reset complete via serial reconnect")
                    return True
            return False
        except Exception as e:
            print(f"Error resetting MCU via serial: {e}")
            return False

def load_config(config_file='config.conf'):
    """Load configuration from file"""
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Configuration file {config_file} not found. Using defaults.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file: {e}")
        return None
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return None

def save_config(config_data, config_file='config.conf'):
    """Save configuration to file"""
    try:
        with open(config_file, 'w') as f:
            json.dump(config_data, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving configuration: {e}")
        return False

def reset_baseline_tracking():
    """Reset baseline tracking state"""
    global baseline_tracker
    baseline_tracker['means'] = [0.0, 0.0, 0.0]
    baseline_tracker['sample_count'] = 0
    baseline_tracker['enabled'] = config.get('remove_mean', False)
    print(f"Baseline tracking reset. Enabled: {baseline_tracker['enabled']}")

def convert_counts_to_g(values):
    """Convert raw ADC counts to g units"""
    return [float(val) * COUNTS_TO_G for val in values]

def update_baseline_and_apply(values):
    """Update running baseline and apply mean removal if enabled"""
    global baseline_tracker
    
    if not config.get('remove_mean', False):
        return values
    
    # Update running means using exponential moving average
    for i in range(min(len(values), 3)):
        if baseline_tracker['sample_count'] == 0:
            baseline_tracker['means'][i] = float(values[i])
        else:
            alpha = baseline_tracker['alpha']
            baseline_tracker['means'][i] = (1 - alpha) * baseline_tracker['means'][i] + alpha * float(values[i])
    
    baseline_tracker['sample_count'] += 1
    
    # Apply baseline removal
    adjusted_values = []
    for i in range(len(values)):
        if i < 3:
            adjusted_values.append(float(values[i]) - baseline_tracker['means'][i])
        else:
            adjusted_values.append(float(values[i]))
    
    return adjusted_values

# Load configuration
app_config = load_config()

app = Flask(__name__)
app.config['SECRET_KEY'] = app_config['app']['secret_key'] if app_config else 'seismic-monitoring-key'
socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    )

# Global variables
seismic = None
adaptive_controller = None  # NEW: Adaptive timing controller
data_buffer = deque(maxlen=app_config['buffer']['max_samples'] if app_config else 1000)
streaming = False
MACHINE_NAME = socket.gethostname()

# Auto-start configuration and state
auto_start_config = app_config.get('auto_start', {
    'enabled': False,
    'trigger_on_pps_lock': False,
    'pps_signal_count_threshold': 5,
    'check_interval_seconds': 5
}) if app_config else {
    'enabled': False,
    'trigger_on_pps_lock': False,
    'pps_signal_count_threshold': 5,
    'check_interval_seconds': 5
}

auto_start_state = {
    'monitoring_active': False,
    'pps_lock_count': 0,
    'auto_started': False,
    'last_check_time': 0,
    'trigger_conditions_met': False,
    # NEW: allow suspending auto-start until next reboot (in-memory only)
    'suspend_until_reboot': False
}

# Device configuration
config = app_config['device'] if app_config else {
    'adc_rate': 10,
    'gain': 3,
    'channels': 3,
    'filter_index': 3,  # Default to SINC3 filter
    'dithering': 4,     # Default to 4x oversampling
    'stream_rate': 100.0,
    'port': '/dev/ttyAMA0',
    'baudrate': 115200,
    'send_g_units': False,
    'remove_mean': False,
    'chart_display_mode': 'raw',
    'timestamp_quantization_ms': 1  # FIXED: Changed from 10ms to 1ms to prevent timestamp collisions
}

# Add new options to existing config if they don't exist
if 'filter_index' not in config:
    config['filter_index'] = 3  # Default to SINC3 filter
if 'dithering' not in config:
    config['dithering'] = 4  # Default to 4x oversampling
if 'send_g_units' not in config:
    config['send_g_units'] = False
if 'remove_mean' not in config:
    config['remove_mean'] = False
if 'chart_display_mode' not in config:
    config['chart_display_mode'] = 'raw'
if 'timestamp_quantization_ms' not in config:
    config['timestamp_quantization_ms'] = 1  # FIXED: Changed from 10ms to 1ms to prevent timestamp collisions


# Calibration constants for ±2g sensor
# Sensor: ±2g in ±3.6V, ADC: ±2.5V range
# ADC is 24-bit: 2^23 = 8,388,608 (half range for bipolar)
# Voltage per count: 2.5V / 8,388,608 = 2.98e-7 V/count
# Sensitivity: 2g / 3.6V = 0.556 g/V
# Combined: 2.98e-7 V/count × 0.556 g/V = 1.656e-7 g/count
ADC_BITS = 32
ADC_HALF_RANGE = 2**(ADC_BITS-1)  # 8,388,608
ADC_VOLTAGE_RANGE = 2.5  # ±2.5V
SENSOR_G_RANGE = 2.0  # ±2g
SENSOR_VOLTAGE_RANGE = 3.6  # ±3.6V

# Calculate conversion factor: counts to g
COUNTS_TO_VOLTS = ADC_VOLTAGE_RANGE / ADC_HALF_RANGE  # V/count
VOLTS_TO_G = SENSOR_G_RANGE / SENSOR_VOLTAGE_RANGE   # g/V
COUNTS_TO_G = COUNTS_TO_VOLTS * VOLTS_TO_G           # g/count

# Baseline tracking for mean removal
baseline_tracker = {
    'enabled': False,
    'means': [0.0, 0.0, 0.0],  # running means for x, y, z
    'sample_count': 0,
    'alpha': 0.001  # exponential moving average factor
}

# Data saving configuration
data_saver = None
saving_config = {
    'csv_enabled': app_config['data_saving']['csv']['enabled'] if app_config else False,
    'csv_directory': app_config['data_saving']['csv']['directory'] if app_config else 'data',
    'influx_enabled': app_config['data_saving']['influxdb']['enabled'] if app_config else False,
    'influx_config': app_config['data_saving']['influxdb'] if app_config else {
        'url': 'http://localhost:8086',
        'token': '',
        'org': '',
        'bucket': '',
        'measurement': 'seismic',
        'batch_size': 100,
        'tags': {},
        'fields': {},
        'building': 'Building 1',
        'floor': '',
        'sensor_id': '',
        'sensor_type': '',
        'tb_token': '',
        'tb_secret': '',
        'full_range_voltage': '',
        'full_range_value': ''
    },
    'samples_per_file': app_config['data_saving']['csv']['samples_per_file'] if app_config else 100000
}

# Ensure sensor_id is always the machine name (Device ID)
try:
    saving_config['influx_config']['sensor_id'] = MACHINE_NAME
except Exception:
    pass

# ThingsBoard sync configuration
tb_config = app_config.get('thingsboard', {})
tb_config.setdefault('enabled', False)
tb_config.setdefault('host', 'localhost')
tb_config.setdefault('port', 1883)
tb_config.setdefault('access_token', '')
tb_config.setdefault('device_name', 'SeismicDevice')
tb_config.setdefault('use_tls', False)

# Legacy CSV logging (for backward compatibility)
csv_logging = {
    'enabled': False,
    'directory': 'data',
    'current_file': None,
    'csv_writer': None,
    'file_handle': None,
    'max_file_size': 50 * 1024 * 1024,
    'samples_per_file': 100000
}

# MODIFIED: Simplified time source status for host-managed timing
time_source_status = {
    'source': 'Unknown',
    'accuracy_us': 0,
    'pps_lock': False,
    'last_update': None,
    'host_managed': True,  # NEW: Indicates this is host-managed timing
    'timing_warnings': []
}

# NEW: MCU timing status from enhanced data
mcu_timing_status = {
    'source': 'unknown',
    'accuracy_us': 1000.0,
    'timing_source_id': 3,
    'last_update': None,
    'scientific_grade': False,
    'target_grade': False
}

# Statistics
stats = {
    'samples_received': 0,
    'samples_logged': 0,
    'start_time': None,
    'current_rate': 0,
    'data_gaps': 0,
    'current_csv_file': None,
    'sequence_gaps': 0,  # NEW: Track sequence gaps
    'data_gaps': 0,
    'last_sequence': None  # NEW: Track last sequence
}

# Sliding window of recent sample timestamps (ms) for instantaneous rate calc
rate_window_ms = deque(maxlen=512)

# When we intentionally (re)start streaming, set this flag so that
# the first sample after restart does not create a giant "gap" from
# the previous session's last sequence.
expect_sequence_reset = False

def ensure_data_directory():
    """Ensure the data directory exists"""
    if not os.path.exists(csv_logging['directory']):
        os.makedirs(csv_logging['directory'])

def create_new_csv_file():
    """Create a new CSV file with timestamp"""
    global csv_logging, stats
    
    # Close current file if open
    if csv_logging['file_handle']:
        csv_logging['file_handle'].close()
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"seismic_data_{timestamp}.csv"
    filepath = os.path.join(csv_logging['directory'], filename)
    
    # Open new file and create CSV writer
    csv_logging['file_handle'] = open(filepath, 'w', newline='')
    csv_logging['csv_writer'] = csv.writer(csv_logging['file_handle'])
    
    # Write header
    header = ['timestamp', 'datetime', 'sequence', 'channel1', 'channel2', 'channel3']
    csv_logging['csv_writer'].writerow(header)
    csv_logging['file_handle'].flush()
    
    csv_logging['current_file'] = filepath
    stats['current_csv_file'] = filename
    
    print(f"Created new CSV file: {filename}")
    return filepath

def create_data_saver():
    """Create a new DataSaver instance with current configuration"""
    global data_saver, saving_config, tb_config
    
    # Close existing data saver
    if data_saver:
        data_saver.close()
    
    # Prepare CSV configuration
    csv_filename = None
    if saving_config['csv_enabled']:
        ensure_data_directory()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_filename = os.path.join(saving_config['csv_directory'], f"seismic_data_{timestamp}.csv")
    
    # Prepare InfluxDB configuration
    influx_config = None
    if saving_config['influx_enabled']:
        influx_config = dict(saving_config['influx_config'])
        if not all([influx_config.get('token'), influx_config.get('org'), influx_config.get('bucket')]):
            print("Warning: InfluxDB configuration incomplete, disabling InfluxDB")
            influx_config = None
    
    # Create data saver
    try:
        data_saver = DataSaver(
            csv_filename=csv_filename,
            influx_config=influx_config,
            thingsboard_config=tb_config if tb_config.get('enabled') else None,
            common_tags={}  # No longer needed as tags are handled in influx_config
        )
        tb_status = "ThingsBoard enabled" if tb_config.get('enabled') and data_saver and data_saver.is_thingsboard_connected() else "ThingsBoard disabled or not connected"
        print(f"Created DataSaver - CSV: {csv_filename is not None}, InfluxDB: {influx_config is not None}, {tb_status}")
    except Exception as e:
        print(f"Error creating DataSaver: {e}")
        data_saver = None

def log_data_to_csv(timestamp, sequence, values):
    """Log data sample to CSV file (legacy function)"""
    if not csv_logging['enabled']:
        return
    
    try:
        # Create new file if needed
        if not csv_logging['csv_writer'] or not csv_logging['file_handle']:
            create_new_csv_file()
        
        # Check if we need to rotate the file
        if (stats['samples_logged'] > 0 and 
            stats['samples_logged'] % csv_logging['samples_per_file'] == 0):
            create_new_csv_file()
        
        # FIXED: Remove redundant quantization - timestamps are already perfectly quantized
        # The SimplifiedTimestampGenerator provides exact configurable quantization boundaries
        if isinstance(timestamp, str) and '.' in timestamp:
            timestamp_ms = int(float(timestamp))
        else:
            timestamp_ms = int(timestamp)
        
        # Convert timestamp to datetime (no re-quantization needed)
        dt_obj = datetime.fromtimestamp(timestamp_ms / 1000.0)
        
        datetime_str = dt_obj.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Write data row
        row = [
            timestamp,
            datetime_str,
            sequence,
            values[0],
            values[1] if len(values) > 1 else 0,
            values[2] if len(values) > 2 else 0
        ]
        
        csv_logging['csv_writer'].writerow(row)
        csv_logging['file_handle'].flush()
        
        stats['samples_logged'] += 1
        
    except Exception as e:
        print(f"Error logging to CSV: {e}")

def update_timing_status():
    """Update timing status from host timing manager"""
    global time_source_status
    
    if seismic and hasattr(seismic, 'timing_manager'):
        try:
            timing_info = seismic.timing_manager.get_timing_info()
            timing_quality = timing_info.get('timing_quality', {})
            
            time_source_status.update({
                'source': timing_quality.get('source', 'Unknown'),
                'accuracy_us': timing_quality.get('accuracy_us', 0),
                'pps_lock': timing_info.get('pps_available', False),
                'last_update': datetime.now().isoformat(),
                'host_managed': True
            })
            
        except Exception as e:
            print(f"Error updating timing status: {e}")
            time_source_status.update({
                'source': 'Error',
                'accuracy_us': 0,
                'pps_lock': False,
                'last_update': datetime.now().isoformat()
            })

def on_data(timestamp, sequence, values, timing_info=None):
    """Handle incoming data from seismic acquisition with enhanced timing info"""
    global stats, data_buffer, expect_sequence_reset
    
    # Update statistics
    stats['samples_received'] += 1
    if stats['start_time'] is None:
        stats['start_time'] = time.time()
    
    # MODIFIED: Track sequence gaps for host-managed timing with restart-awareness
    if stats['last_sequence'] is not None:
        expected_sequence = (stats['last_sequence'] + 1) % 65536  # 16-bit sequences
        if sequence != expected_sequence:
            # If we just restarted/realigned, suppress the first gap
            if expect_sequence_reset:
                print("INFO: Suppressing initial sequence gap after restart/realign")
                expect_sequence_reset = False
            else:
                # Calculate gap (handle wraparound)
                if sequence >= stats['last_sequence']:
                    gap = sequence - stats['last_sequence'] - 1
                else:
                    gap = (65536 - stats['last_sequence']) + sequence - 1
                stats['sequence_gaps'] += gap
                stats['data_gaps'] += 1
                print(f"Sequence gap detected: expected {expected_sequence}, got {sequence} (gap: {gap})")
    
    stats['last_sequence'] = sequence
    
    # Calculate current rate using a robust sliding window over recent timestamps (ms)
    try:
        # timestamp is ms per HostTimingSeismicAcquisition
        rate_window_ms.append(timestamp)
        # Use last N timestamps to compute instantaneous rate
        if len(rate_window_ms) >= 10:
            t0 = rate_window_ms[0]
            t1 = rate_window_ms[-1]
            if t1 > t0:
                num_samples = len(rate_window_ms) - 1
                duration_s = (t1 - t0) / 1000.0
                inst_rate = num_samples / duration_s if duration_s > 0 else 0.0
                # Exponential smoothing to stabilize UI
                prev = stats.get('current_rate', 0) or 0
                alpha = 0.2  # smoothing factor
                stats['current_rate'] = alpha * inst_rate + (1 - alpha) * prev
        else:
            # Fallback to coarse average at startup
            elapsed = time.time() - stats['start_time']
            if elapsed > 0:
                stats['current_rate'] = stats['samples_received'] / elapsed
    except Exception:
        # Never break data path due to rate calc
        elapsed = time.time() - stats['start_time']
        if elapsed > 0:
            stats['current_rate'] = stats['samples_received'] / elapsed
    
    # Enhanced: Add timing information with numeric codes
    # Timing source codes: 0=NTP, 1=GPS, 2=GPS+PPS
    def get_timing_source_code(source_name):
        if not source_name:
            return 0  # Default to NTP
        source_lower = source_name.lower()
        if 'pps' in source_lower and 'gps' in source_lower:
            return 2  # GPS+PPS
        elif 'gps' in source_lower:
            return 1  # GPS
        else:
            return 0  # NTP or other
    
    # Update global MCU timing status for monitoring (no longer saved to InfluxDB)
    global mcu_timing_status
    if timing_info:
        mcu_timing_status = {
            'source': timing_info.get('source_name', 'unknown'),
            'accuracy_us': timing_info.get('accuracy_us', 0),
            'timing_source_id': timing_info.get('timing_source', 3),
            'last_update': datetime.now().isoformat(),
            'scientific_grade': timing_info.get('accuracy_us', 1000) < 10,
            'target_grade': timing_info.get('accuracy_us', 1000) <= 100
        }
    
    # Apply baseline removal if enabled (do this first!)
    processed_values = update_baseline_and_apply(values)
    
    # Save using DataSaver with calibrated values if enabled
    if data_saver:
        sample_fields = {}
        if config.get('send_g_units', False):
            calibrated_values = convert_counts_to_g(processed_values)
            sample_fields = {
                'Value_x': calibrated_values[1] if len(calibrated_values) > 1 else 0.0,  # Channel 1 -> X
                'Value_y': calibrated_values[2] if len(calibrated_values) > 2 else 0.0,  # Channel 2 -> Y  
                'Value_z': calibrated_values[0] if len(calibrated_values) > 0 else 0.0   # Channel 0 -> Z
            }
        data_saver.save_seismic_sample(timestamp, sequence, processed_values, None, sample_fields)
    
    # Log to CSV (legacy method for backward compatibility)
    log_data_to_csv(timestamp, sequence, values)
    
    # Prepare sample data structure
    sample = {
        'timestamp': timestamp,
        'sequence': sequence,
        'values': processed_values,  # Use processed values (baseline removed if enabled)
        'raw_values': values,  # Keep original values
        'time_str': datetime.fromtimestamp(timestamp/1000.0).strftime('%H:%M:%S.%f')[:-3],
        'timing_info': timing_info  # Include MCU timing info
    }
    
    # Add calibrated values if g units are enabled
    if config.get('send_g_units', False):
        calibrated_values = convert_counts_to_g(processed_values)
        sample['Value_x'] = calibrated_values[1] if len(calibrated_values) > 1 else 0.0  # Channel 1 -> X
        sample['Value_y'] = calibrated_values[2] if len(calibrated_values) > 2 else 0.0  # Channel 2 -> Y  
        sample['Value_z'] = calibrated_values[0] if len(calibrated_values) > 0 else 0.0  # Channel 0 -> Z
        sample['calibrated_values'] = calibrated_values
    
    # Add chart display values based on mode
    chart_mode = config.get('chart_display_mode', 'raw')
    if chart_mode == 'calibrated' and config.get('send_g_units', False):
        sample['chart_values'] = convert_counts_to_g(processed_values)
    else:
        sample['chart_values'] = processed_values
    
    data_buffer.append(sample)
    
    # Emit to websocket clients with enhanced data
    socketio.emit('new_data', sample)

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """Get current system status with host-managed timing information"""
    update_timing_status()
    
    device_status = {'connected': False, 'status': 'Not connected'}
    if seismic:
        try:
            if seismic.is_connected:
                device_status = {'connected': True, 'status': 'Connected'}
                if streaming:
                    device_status['status'] = 'Streaming'
        except Exception as e:
            print(f"Error checking device status: {e}")
            device_status = {'connected': False, 'status': 'Error: ' + str(e)}
    
    data_saver_stats = {}
    tb_web_status = {
        'configured': bool(tb_config.get('access_token')),
        'connection_status': 'Disabled',
        'buffer_size': 0,
        'sender_active': False,
        'items_queued_total': 0,
        'items_sent_total': 0,
        'items_failed_total': 0
    }

    if not tb_config.get('enabled', False):
        tb_web_status['connection_status'] = 'Disabled'
    elif data_saver:
        data_saver_stats = data_saver.get_stats()
        tb_client_status_ds = data_saver_stats.get('thingsboard_client_status', {})

        if not tb_client_status_ds.get('connected', False):
            tb_web_status['connection_status'] = 'Disconnected'
            if tb_client_status_ds.get('connection_errors', 0) > 0:
                tb_web_status['connection_status'] = 'Error (Connection)'
        elif not data_saver_stats.get('tb_sender_alive', False):
            tb_web_status['connection_status'] = 'Error (Sender Thread Down)'
        else:
            tb_web_status['connection_status'] = 'Connected & Sending'
            if data_saver_stats.get('tb_buffer_size', 0) > 0:
                tb_web_status['connection_status'] = 'Connected & Buffering'
                
        tb_web_status['buffer_size'] = data_saver_stats.get('tb_buffer_size', 0)
        tb_web_status['sender_active'] = data_saver_stats.get('tb_sender_alive', False)
        tb_web_status['items_queued_total'] = data_saver_stats.get('thingsboard_queued', 0)
        tb_web_status['items_sent_total'] = data_saver_stats.get('thingsboard_sent_items', 0)
        tb_web_status['items_failed_total'] = data_saver_stats.get('thingsboard_failed_items', 0)
    else:
        tb_web_status['connection_status'] = 'Error (DataSaver not initialized)'

    # MODIFIED: Add host timing information (JSON-safe)
    host_timing_info = {}
    if seismic and hasattr(seismic, 'timing_manager'):
        try:
            raw_timing_info = seismic.timing_manager.get_timing_info()
            host_timing_info = make_json_safe(raw_timing_info)
        except Exception as e:
            print(f"Error getting host timing info: {e}")
            host_timing_info = {'error': str(e)}

    # MODIFIED: Add sample tracking stats (JSON-safe)
    sample_tracking_stats = {}
    if seismic and hasattr(seismic, 'get_sample_stats'):
        try:
            raw_stats = seismic.get_sample_stats()
            sample_tracking_stats = make_json_safe(raw_stats)
        except Exception as e:
            print(f"Error getting sample stats: {e}")
    
    # NEW: Add timestamp quantization information
    timestamp_quantization_info = {}
    if seismic and hasattr(seismic, 'timing_adapter') and hasattr(seismic.timing_adapter, 'timestamp_generator'):
        try:
            quantization_ms = seismic.timing_adapter.timestamp_generator.quantization_ms
            timestamp_quantization_info = {
                'quantization_ms': quantization_ms,
                'description': f'Timestamps quantized to {quantization_ms}ms boundaries',
                'config_quantization_ms': config.get('timestamp_quantization_ms', 10)
            }
        except Exception as e:
            print(f"Error getting quantization info: {e}")
            timestamp_quantization_info = {'error': str(e)}

    # NEW: Add adaptive controller status
    adaptive_status = {}
    if adaptive_controller:
        try:
            adaptive_status = {
                'enabled': True,
                'running': adaptive_controller.running,
                'performance': adaptive_controller.get_performance_assessment(),
                'stats': make_json_safe(adaptive_controller.get_stats()),
                'measurement_interval': adaptive_controller.measurement_interval
            }
        except Exception as e:
            print(f"Error getting adaptive controller status: {e}")
            adaptive_status = {'enabled': False, 'error': str(e)}
    else:
        adaptive_status = {'enabled': False, 'status': 'not_initialized'}

    # Get auto-start status
    pps_lock_status = {'locked': False, 'source': 'UNKNOWN', 'accuracy_us': 1000000}
    if seismic and hasattr(seismic, 'timing_manager'):
        try:
            pps_lock_status = seismic.timing_manager.check_pps_lock_status()
        except:
            pass
    
    auto_start_status = {
        'enabled': auto_start_config.get('enabled', False),
        'trigger_on_pps_lock': auto_start_config.get('trigger_on_pps_lock', False),
        'pps_signal_count': auto_start_state['pps_lock_count'],
        'threshold': auto_start_config.get('pps_signal_count_threshold', 5),
        'auto_started': auto_start_state['auto_started'],
        'conditions_met': auto_start_state['trigger_conditions_met'],
        'suspend_until_reboot': auto_start_state.get('suspend_until_reboot', False),
        'pps_lock_status': pps_lock_status
    }
    
    return jsonify({
        'device': device_status,
        'time_source': time_source_status,
        'host_timing': host_timing_info,  # NEW: Host timing information
        'mcu_timing': mcu_timing_status,  # NEW: MCU timing information
        'config': config,
        'stats': stats,
        'streaming': streaming,
        'streaming_allowed': True,  # Always allowed in host-managed timing
        'streaming_reason': 'Host manages timing',
        'device_id': MACHINE_NAME,
        'csv_logging': {
            'enabled': csv_logging['enabled'],
            'current_file': stats.get('current_csv_file'),
            'samples_logged': stats['samples_logged']
        },
        'data_saver': data_saver_stats,
        'saving_config': saving_config,
        'sample_tracking': sample_tracking_stats,  # NEW: Sample tracking stats (JSON-safe)
        'timestamp_quantization': timestamp_quantization_info,  # NEW: Timestamp quantization info
        'adaptive_timing': adaptive_status,  # NEW: Adaptive timing controller status
        'auto_start': auto_start_status,  # NEW: Auto-start trigger status
        'thingsboard': {
            'enabled': tb_config.get('enabled', False),
            'config': tb_config,
            'status': tb_web_status,
            'has_access_token': bool(tb_config.get('access_token'))
        },
        'filter': {  # NEW: Filter information (like other device settings)
            'index': config.get('filter_index', 3),
            'name': ['SINC1', 'SINC2', 'SINC3', 'SINC4', 'FIR'][config.get('filter_index', 3) - 1]
        }
    })

@app.route('/api/server_time')
def get_server_time():
    """Return the device server's current time and precise time if available"""
    now_s = time.time()
    precise_s = None
    source = None
    accuracy_us = None
    if seismic and hasattr(seismic, 'timing_manager') and seismic.timing_manager:
        try:
            precise_val = seismic.timing_manager.get_precise_time()
            if precise_val:
                precise_s = precise_val
            tinfo = seismic.timing_manager.get_timing_info()
            tq = tinfo.get('timing_quality', {}) if isinstance(tinfo, dict) else {}
            source = tq.get('source')
            accuracy_us = tq.get('accuracy_us')
        except Exception:
            pass
    resp = {
        'server_time_ms': int(now_s * 1000),
        'server_time_iso': datetime.fromtimestamp(now_s).isoformat()
    }
    if precise_s is not None:
        resp['precise_time_ms'] = int(precise_s * 1000)
    if source is not None:
        resp['source'] = source
    if accuracy_us is not None:
        resp['accuracy_us'] = accuracy_us
    return jsonify(resp)

@app.route('/api/timing/status')
def get_unified_timing_status():
    """Get unified timing system status"""
    if not seismic or not hasattr(seismic, 'timing_adapter'):
        return jsonify({'status': 'error', 'message': 'Unified timing not available'}), 400
    
    try:
        timing_info = seismic.timing_adapter.get_timing_info()
        
        # Add generator stats
        generator_stats = seismic.timestamp_generator.get_stats()
        
        # Add controller stats if available
        controller_stats = {}
        if adaptive_controller and hasattr(adaptive_controller, 'unified_controller'):
            controller_stats = adaptive_controller.get_stats()
        
        # Compute timestamp health for UI (last sample vs now and precise host time)
        timestamp_health = {}
        try:
            if seismic and hasattr(seismic, 'timestamp_generator'):
                gen_stats = seismic.timestamp_generator.get_stats()
                last_ts = gen_stats.get('last_timestamp')  # seconds float
                if last_ts:
                    now_s = time.time()
                    timestamp_health['last_timestamp'] = int(last_ts * 1000)
                    timestamp_health['offset_ms'] = int((last_ts - now_s) * 1000)
                    if hasattr(seismic, 'timing_manager') and seismic.timing_manager:
                        precise_now = seismic.timing_manager.get_precise_time()
                        timestamp_health['offset_precise_ms'] = int((last_ts - precise_now) * 1000)
        except Exception as e:
            timestamp_health = {'error': str(e)}
        
        return jsonify({
            'unified_timing': timing_info,
            'timestamp_generator': generator_stats,
            'controller': controller_stats,
            'timestamp_health': timestamp_health,  # NEW: Include timestamp health data
            'system_health': _assess_timing_health(timing_info)
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

def _assess_timing_health(timing_info):
    """Assess overall timing system health"""
    health = {
        'overall_status': 'unknown',
        'reference_quality': 'unknown',
        'stability': 'unknown',
        'recommendations': []
    }
    
    try:
        # Check reference source
        ref_source = timing_info.get('reference_source', 'UNKNOWN')
        ref_accuracy = timing_info.get('reference_accuracy_us', 1000000)
        
        if ref_source == 'GPS+PPS' and ref_accuracy <= 10:
            health['reference_quality'] = 'excellent'
        elif ref_source == 'NTP' and ref_accuracy <= 10000:
            health['reference_quality'] = 'good'
        elif ref_accuracy <= 100000:
            health['reference_quality'] = 'fair'
        else:
            health['reference_quality'] = 'poor'
            health['recommendations'].append('Improve time synchronization (NTP/GPS)')
        
        # Check performance metrics
        if 'performance_metrics' in timing_info:
            perf = timing_info['performance_metrics']
            avg_error = perf.get('avg_error_ms', 0)
            
            if avg_error <= 5:
                health['stability'] = 'excellent'
            elif avg_error <= 20:
                health['stability'] = 'good'
            elif avg_error <= 50:
                health['stability'] = 'fair'
            else:
                health['stability'] = 'poor'
                health['recommendations'].append('Check system load and timing configuration')
        
        # Overall assessment
        if (health['reference_quality'] in ['excellent', 'good'] and 
            health['stability'] in ['excellent', 'good']):
            health['overall_status'] = 'healthy'
        elif (health['reference_quality'] in ['good', 'fair'] and 
              health['stability'] in ['good', 'fair']):
            health['overall_status'] = 'acceptable'
        else:
            health['overall_status'] = 'needs_attention'
            
    except Exception as e:
        health['error'] = str(e)
        
    return health

# MODIFIED: Simplified timing config endpoints (no complex PPS management)
@app.route('/api/timing/config', methods=['GET', 'POST'])
def handle_timing_config():
    """Get or update host timing configuration"""
    if request.method == 'POST':
        new_config = request.json
        
        # Update host timing manager if available
        if seismic and hasattr(seismic, 'timing_manager'):
            # This would be extended based on HostTimingManager capabilities
            pass
        
        return jsonify({'status': 'ok', 'message': 'Host timing is automatically managed'})
    
    return jsonify({
        'host_managed': True,
        'automatic': True,
        'source': time_source_status.get('source', 'Unknown'),
        'accuracy_us': time_source_status.get('accuracy_us', 0)
    })

@app.route('/api/timing/check_source', methods=['POST'])
def force_timing_source_check():
    """Force an immediate check of timing source (GPS/PPS) availability"""
    if not seismic or not hasattr(seismic, 'timing_manager'):
        return jsonify({
            'status': 'error',
            'message': 'Timing manager not available'
        }), 400
    
    try:
        # Force immediate timing source check
        changed = False
        if hasattr(seismic.timing_manager, 'force_timing_source_check'):
            changed = seismic.timing_manager.force_timing_source_check()
        elif hasattr(seismic.timing_manager, '_update_reference_source'):
            changed = seismic.timing_manager._update_reference_source(force=True)
        
        # Get updated status
        update_timing_status()
        
        return jsonify({
            'status': 'ok',
            'changed': changed,
            'current_source': time_source_status.get('source', 'Unknown'),
            'accuracy_us': time_source_status.get('accuracy_us', 0),
            'message': 'Timing source checked' + (' and updated' if changed else ' (no change)')
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Failed to check timing source: {str(e)}'
        }), 500

@app.route('/api/timing/quantization', methods=['GET', 'POST'])
def handle_timestamp_quantization():
    """Get or update timestamp quantization configuration"""
    if not seismic or not hasattr(seismic, 'timing_adapter'):
        return jsonify({'status': 'error', 'message': 'Timing system not available'}), 400
    
    if request.method == 'POST':
        try:
            config_data = request.json
            quantization_ms = int(config_data.get('quantization_ms', 10))
            
            # Validate quantization value
            if 1 <= quantization_ms <= 1000:
                # Update the timestamp generator
                seismic.timing_adapter.timestamp_generator.set_quantization(quantization_ms)
                
                # Update the web server config
                config['timestamp_quantization_ms'] = quantization_ms
                
                # Save to configuration file
                if app_config:
                    app_config['device']['timestamp_quantization_ms'] = quantization_ms
                    save_config(app_config)
                
                return jsonify({
                    'status': 'success', 
                    'message': f'Timestamp quantization updated to {quantization_ms}ms',
                    'quantization_ms': quantization_ms
                })
            else:
                return jsonify({
                    'status': 'error', 
                    'message': 'Quantization must be between 1ms and 1000ms'
                }), 400
                
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    # GET request - return current quantization
    try:
        current_quantization = seismic.timing_adapter.timestamp_generator.quantization_ms
        return jsonify({
            'quantization_ms': current_quantization,
            'config_quantization_ms': config.get('timestamp_quantization_ms', 10),
            'description': f'Timestamps are quantized to {current_quantization}ms boundaries'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Keep existing InfluxDB and ThingsBoard config endpoints unchanged
@app.route('/api/influx/config', methods=['GET', 'POST'])
def handle_influx_config():
    """Get or update InfluxDB configuration"""
    global saving_config, data_saver
    
    if request.method == 'POST':
        new_config = request.json
        
        # Update InfluxDB configuration
        if 'enabled' in new_config:
            saving_config['influx_enabled'] = bool(new_config['enabled'])
        
        if 'url' in new_config:
            saving_config['influx_config']['url'] = new_config['url']
        
        if 'token' in new_config:
            saving_config['influx_config']['token'] = new_config['token']
        
        if 'org' in new_config:
            saving_config['influx_config']['org'] = new_config['org']
        
        if 'bucket' in new_config:
            saving_config['influx_config']['bucket'] = new_config['bucket']
        
        if 'measurement' in new_config:
            saving_config['influx_config']['measurement'] = new_config['measurement']
        
        # Handle individual tag and field configuration
        # Tags (for indexing/filtering)
        tags = {}
        if 'building' in new_config and new_config['building']:
            tags['building'] = new_config['building']
        if 'floor' in new_config and new_config['floor']:
            tags['floor'] = new_config['floor']
        if 'sensor_id' in new_config and new_config['sensor_id']:
            tags['sensor_id'] = new_config['sensor_id']
        if 'sensor_type' in new_config and new_config['sensor_type']:
            tags['sensor_type'] = new_config['sensor_type']
        if 'tb_token' in new_config and new_config['tb_token']:
            tags['tb_token'] = new_config['tb_token']
        if 'tb_secret' in new_config and new_config['tb_secret']:
            tags['tb_secret'] = new_config['tb_secret']
        # Only include calibration tags if they have meaningful values
        if 'full_range_voltage' in new_config and new_config['full_range_voltage']:
            try:
                voltage_value = float(new_config['full_range_voltage'])
                if voltage_value > 0:  # Only add if > 0
                    tags['full_range_voltage'] = str(voltage_value)
            except (ValueError, TypeError):
                pass  # Skip invalid values
        if 'full_range_value' in new_config and new_config['full_range_value']:
            try:
                adc_value = float(new_config['full_range_value'])
                if adc_value > 0:  # Only add if > 0
                    tags['full_range_value'] = str(adc_value)
            except (ValueError, TypeError):
                pass  # Skip invalid values
        
        saving_config['influx_config']['tags'] = tags
        
        # Fields (for data storage) - now empty, only measurement data will be added
        fields = {}
        
        saving_config['influx_config']['fields'] = fields
        
        # Store individual field values for form population
        saving_config['influx_config']['building'] = new_config.get('building', '')
        saving_config['influx_config']['floor'] = new_config.get('floor', '')
        # Enforce sensor_id = MACHINE_NAME (Device ID)
        saving_config['influx_config']['sensor_id'] = MACHINE_NAME
        saving_config['influx_config']['sensor_type'] = new_config.get('sensor_type', '')
        saving_config['influx_config']['tb_token'] = new_config.get('tb_token', '')
        saving_config['influx_config']['tb_secret'] = new_config.get('tb_secret', '')
        saving_config['influx_config']['full_range_voltage'] = new_config.get('full_range_voltage', '')
        saving_config['influx_config']['full_range_value'] = new_config.get('full_range_value', '')
        
        # Save updated configuration to file
        if app_config:
            app_config['data_saving']['influxdb'] = saving_config['influx_config']
            app_config['data_saving']['influxdb']['enabled'] = saving_config['influx_enabled']
            save_config(app_config)
        
        # If streaming or data_saver exists, recreate data saver with new config
        if streaming or data_saver:
            create_data_saver()
        
        return jsonify({'status': 'ok', 'config': saving_config['influx_config']})
    
    return jsonify(saving_config['influx_config'])

# REMOVED: Separate filter endpoint - now handled through main /api/config endpoint
# Filters work exactly like ADC rate, gain, and channels - simple and straightforward

@app.route('/api/influx/test', methods=['POST'])
def test_influx_connection():
    """Test InfluxDB connection"""
    try:
        from influx_writer import InfluxWriter
        
        config_data = saving_config['influx_config']
        test_writer = InfluxWriter(
            url=config_data['url'],
            token=config_data['token'],
            org=config_data['org'],
            bucket=config_data['bucket'],
            measurement='test',
            tags=config_data.get('tags', {}),
            fields=config_data.get('fields', {}),
            buffer_on_error=False
        )
        
        connected = test_writer.test_connection()
        test_writer.close()
        
        return jsonify({
            'connected': connected,
            'status': 'success' if connected else 'failed'
        })
        
    except Exception as e:
        return jsonify({
            'connected': False,
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/thingsboard/config', methods=['GET', 'POST'])
def handle_thingsboard_config():
    """Get or update ThingsBoard configuration"""
    global tb_config, data_saver
    
    if request.method == 'POST':
        new_config = request.json
        
        # Update ThingsBoard configuration
        if 'enabled' in new_config:
            tb_config['enabled'] = bool(new_config['enabled'])
        
        if 'host' in new_config:
            tb_config['host'] = new_config['host']
        
        if 'port' in new_config:
            tb_config['port'] = int(new_config['port'])
        
        if 'access_token' in new_config:
            tb_config['access_token'] = new_config['access_token']
        
        if 'device_name' in new_config:
            tb_config['device_name'] = new_config['device_name']
        
        if 'use_tls' in new_config:
            tb_config['use_tls'] = bool(new_config['use_tls'])
        
        # Save updated configuration to file
        if app_config:
            app_config['thingsboard'] = tb_config
            save_config(app_config)

        # Recreate DataSaver if it exists or if streaming to apply new TB settings
        if streaming or data_saver:
            create_data_saver()
        
        return jsonify({'status': 'ok', 'config': tb_config})
    
    return jsonify(tb_config)

@app.route('/api/thingsboard/test', methods=['POST'])
def test_thingsboard_connection():
    """Test ThingsBoard connection"""
    try:
        from thingsboard_client import ThingsBoardClient
        
        test_client = ThingsBoardClient(
            host=tb_config['host'],
            port=tb_config['port'],
            access_token=tb_config['access_token'],
            device_name=tb_config['device_name'],
            buffer_on_error=False
        )
        
        connected = test_client.connect(use_tls=tb_config['use_tls'])
        test_passed = False
        
        if connected:
            test_passed = test_client.test_connection()
            test_client.disconnect()
            
            return jsonify({
                'connected': connected,
                'test_passed': test_passed,
                'status': 'success' if test_passed else 'connected_but_test_failed'
            })
        else:
            return jsonify({
                'connected': False,
                'test_passed': False,
                'status': 'connection_failed',
                'message': 'Failed to connect to ThingsBoard MQTT broker'
            })
        
    except Exception as e:
        return jsonify({
            'connected': False,
            'test_passed': False,
            'status': 'error',
            'message': str(e)
        }), 500

# Keep existing CSV endpoints unchanged
@app.route('/api/csv/toggle', methods=['POST'])
def toggle_csv_logging():
    """Toggle CSV logging on/off"""
    csv_logging['enabled'] = not csv_logging['enabled']
    
    if not csv_logging['enabled'] and csv_logging['file_handle']:
        csv_logging['file_handle'].close()
        csv_logging['file_handle'] = None
        csv_logging['csv_writer'] = None
    
    return jsonify({
        'enabled': csv_logging['enabled'],
        'status': 'enabled' if csv_logging['enabled'] else 'disabled'
    })

@app.route('/api/disconnect', methods=['POST'])
def disconnect_device():
    """Disconnect from the seismic device"""
    global seismic, streaming
    
    try:
        if streaming:
            stop_stream()
        
        if seismic:
            seismic.close()
            seismic = None
        
        return jsonify({'status': 'disconnected'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/stream/stop', methods=['POST'])
def stop_stream():
    """Stop data streaming (manual or auto-started)"""
    global streaming, data_saver, adaptive_controller, auto_start_state
    
    if not seismic:
        return jsonify({'status': 'error', 'message': 'Device not connected'}), 400
    
    try:
        was_auto_started = auto_start_state['auto_started']
        
        seismic.stop_streaming()
        streaming = False
        
        # Reset auto-start state
        auto_start_state['auto_started'] = False
        auto_start_state['pps_lock_count'] = 0
        auto_start_state['trigger_conditions_met'] = False
        
        # Stop adaptive controller
        if adaptive_controller:
            adaptive_controller.stop_controller()
        
        # Close current CSV file
        if csv_logging['file_handle']:
            csv_logging['file_handle'].close()
            csv_logging['file_handle'] = None
            csv_logging['csv_writer'] = None
        
        # Close data saver
        if data_saver:
            data_saver.close()
            data_saver = None
        
        return jsonify({
            'status': 'stopped',
            'was_auto_started': was_auto_started,
            'message': 'Streaming stopped (auto-start will re-trigger if enabled)' if was_auto_started else 'Streaming stopped'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/data/recent')
def get_recent_data():
    """Get recent data samples"""
    samples = list(data_buffer)[-100:]  # Last 100 samples
    return jsonify(samples)

@socketio.on('connect')
def handle_connect():
    """Handle websocket connection"""
    print('Client connected')
    emit('connected', {'data': 'Connected to host-managed timing seismic monitoring server'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle websocket disconnection"""
    print('Client disconnected')

def cleanup_resources():
    """Cleanup resources on shutdown"""
    global data_saver
    
    if csv_logging['file_handle']:
        csv_logging['file_handle'].close()
    
    if data_saver:
        data_saver.close()
    
    # Cleanup lgpio if available
    if GPIO_AVAILABLE:
        try:
            lgpio.gpiochip_close(h)
        except Exception as e:
            print(f"Error during lgpio cleanup: {e}")

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Get or update configuration"""
    global config, seismic
    
    if request.method == 'POST':
        new_config = request.json
        
        # Reset MCU before applying new configuration
        if seismic and not streaming:
            if not reset_mcu():
                return jsonify({'status': 'error', 'message': 'Failed to reset MCU'}), 500
            
            # Reconnect after reset
            if not connect_device():
                return jsonify({'status': 'error', 'message': 'Failed to reconnect after reset'}), 500
        
        # Validate configuration
        if 'adc_rate' in new_config:
            if 1 <= new_config['adc_rate'] <= 16:
                config['adc_rate'] = new_config['adc_rate']
                if seismic and not streaming:
                    seismic.set_adc_rate(config['adc_rate'])
        
        if 'gain' in new_config:
            if 1 <= new_config['gain'] <= 6:
                config['gain'] = new_config['gain']
                if seismic and not streaming:
                    seismic.set_gain(config['gain'])
        
        if 'channels' in new_config:
            if 1 <= new_config['channels'] <= 3:
                config['channels'] = new_config['channels']
                if seismic and not streaming:
                    seismic.set_channels(config['channels'])
        
        if 'filter_index' in new_config:
            if 1 <= new_config['filter_index'] <= 5:
                config['filter_index'] = new_config['filter_index']
                if seismic and not streaming:
                    seismic.set_filter(config['filter_index'])
        
        if 'dithering' in new_config:
            if new_config['dithering'] in [0, 2, 3, 4]:
                config['dithering'] = new_config['dithering']
                if seismic:
                    try:
                        if streaming:
                            # Try on-the-fly first (if MCU supports)
                            try:
                                seismic.set_dithering(config['dithering'])
                                print("Applied dithering while streaming")
                            except Exception:
                                # Fallback: brief stop/apply/resume
                                prev_rate = config.get('stream_rate', 100.0)
                                try:
                                    seismic.stop_streaming()
                                except Exception:
                                    pass
                                time.sleep(0.2)
                                seismic.set_dithering(config['dithering'])
                                time.sleep(0.2)
                                # Hint downstream to suppress initial gap
                                global expect_sequence_reset
                                expect_sequence_reset = True
                                start_result = seismic.start_streaming(prev_rate)
                                if not (start_result and start_result[0]):
                                    print("Warning: Failed to resume streaming after dithering change")
                        else:
                            seismic.set_dithering(config['dithering'])
                    except Exception as e:
                        print(f"Warning: Could not apply dithering: {e}")
        
        if 'stream_rate' in new_config:
            if 1 <= new_config['stream_rate'] <= 1000:
                config['stream_rate'] = new_config['stream_rate']
        
        if 'send_g_units' in new_config:
            config['send_g_units'] = bool(new_config['send_g_units'])
        
        if 'remove_mean' in new_config:
            config['remove_mean'] = bool(new_config['remove_mean'])
            # Reset baseline tracking when this option changes
            reset_baseline_tracking()
        
        if 'chart_display_mode' in new_config:
            if new_config['chart_display_mode'] in ['raw', 'calibrated']:
                config['chart_display_mode'] = new_config['chart_display_mode']
        
        if 'timestamp_quantization_ms' in new_config:
            quantization = int(new_config['timestamp_quantization_ms'])
            if 1 <= quantization <= 1000:  # Allow 1ms to 1000ms quantization
                config['timestamp_quantization_ms'] = quantization
                # Update the timing system if connected
                if seismic and hasattr(seismic, 'timing_adapter'):
                    try:
                        seismic.timing_adapter.timestamp_generator.set_quantization(quantization)
                        print(f"🔧 Timestamp quantization updated to {quantization}ms")
                    except Exception as e:
                        print(f"Warning: Could not update quantization: {e}")
        
        # Save updated configuration to file
        if app_config:
            app_config['device'] = config
            save_config(app_config)
        
        return jsonify({'status': 'ok', 'config': config})
    
    return jsonify(config)

@app.route('/api/stream/start', methods=['POST'])
def start_stream():
    """Modified start stream for unified timing (manual start)"""
    global streaming, stats, adaptive_controller, auto_start_state, expect_sequence_reset, rate_window_ms
    
    if not seismic or not seismic.is_connected:
        return jsonify({'status': 'error', 'message': 'Device not connected'}), 400
    
    try:
        # Get desired rate
        desired_rate = config['stream_rate']
        
        # CRITICAL FIX: Reset timing state before starting
        # This prevents offset time issues when restarting streaming
        expect_sequence_reset = True  # Suppress sequence gap detection on first sample
        rate_window_ms.clear()  # Clear timestamp tracking window
        
        # Reset timestamp generator and controller to clear any stale timing offsets
        if hasattr(seismic, 'timestamp_generator'):
            try:
                # Call the new reset method to clear all timing state
                if hasattr(seismic.timestamp_generator, 'reset_for_restart'):
                    seismic.timestamp_generator.reset_for_restart()
                else:
                    print("⚠️  Warning: reset_for_restart method not found, using basic reset")
                    seismic.timestamp_generator.last_sequence = None
                    seismic.timestamp_generator.reference_sequence = None
            except Exception as e:
                print(f"Warning: Could not reset timestamp generator: {e}")
        # Reset unified controller host correction if present
        try:
            if hasattr(seismic, 'timing_adapter') and seismic.timing_adapter and hasattr(seismic.timing_adapter, 'unified_controller'):
                controller = seismic.timing_adapter.unified_controller
                if controller and hasattr(controller, 'reset_state'):
                    controller.reset_state()
        except Exception as e:
            print(f"Warning: Could not reset unified controller state: {e}")
        
        # Start streaming (timing system handles synchronization automatically)
        result = seismic.start_streaming(desired_rate)
        if result and result[0]:
            streaming = True
            stats['samples_received'] = 0
            stats['samples_logged'] = 0
            stats['sequence_gaps'] = 0
            stats['data_gaps'] = 0
            stats['last_sequence'] = None
            stats['start_time'] = time.time()
            
            # Reset auto-start state (manual start takes precedence)
            auto_start_state['auto_started'] = False
            auto_start_state['pps_lock_count'] = 0
            auto_start_state['trigger_conditions_met'] = False
            
            # Create new data saver for this session
            create_data_saver()
            
            # Create new CSV file for legacy support
            if csv_logging['enabled']:
                create_new_csv_file()
            
            # Create compatibility adaptive controller
            global adaptive_controller
            if not adaptive_controller:
                from adaptive_timing_controller import CompatibilityAdaptiveTimingController
                adaptive_controller = CompatibilityAdaptiveTimingController(
                    seismic, seismic.timing_manager
                )
            
            # Start timing control
            adaptive_controller.start_controller()
            
            return jsonify({
                'status': 'streaming',
                'timing_source': 'unified_timing_system',
                'message': 'Streaming started manually',
                'start_type': 'manual'
            })
        else:
            return jsonify({'status': 'error', 'message': result[1] if result else 'Failed to start streaming'}), 500
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

def connect_device():
    """MODIFIED: Connect device using new HostTimingSeismicAcquisition class"""
    global seismic
    
    try:
        if seismic:
            seismic.close()
            time.sleep(1)
        
        # MODIFIED: Use the new HostTimingSeismicAcquisition class with configurable quantization
        quantization_ms = config.get('timestamp_quantization_ms', 10)
        seismic = HostTimingSeismicAcquisition(config['port'], baudrate=config['baudrate'])
        
        # Set the quantization for the timing system
        if hasattr(seismic, 'timing_adapter') and hasattr(seismic.timing_adapter, 'timestamp_generator'):
            try:
                seismic.timing_adapter.timestamp_generator.set_quantization(quantization_ms)
                print(f"🔧 Timestamp quantization set to {quantization_ms}ms")
            except Exception as e:
                print(f"Warning: Could not set quantization: {e}")
        seismic.register_data_callback(on_data)
        
        # MODIFIED: Add status callback for the new class
        def on_status_update(status):
            print(f"Device status update: {status}")
        
        seismic.register_status_callback(on_status_update)
        seismic.start_receiver()
        
        # Wait for connection to stabilize
        print("Waiting for connection to stabilize...")
        time.sleep(3)
        
        # Initialize device settings
        time.sleep(1)
        
        try:
            seismic.set_adc_rate(config['adc_rate'])
            time.sleep(0.5)
            seismic.set_gain(config['gain'])
            time.sleep(0.5)
            seismic.set_channels(config['channels'])
            time.sleep(0.5)
            # Apply dithering/oversampling from config on connect
            try:
                if 'dithering' in config:
                    seismic.set_dithering(config['dithering'])
                    print(f"\ud83d\udd27 Dithering set to {config['dithering']}x on connect")
                    time.sleep(0.3)
            except Exception as e:
                print(f"Warning: Could not set dithering on connect: {e}")
            
            # Sync filter setting if available in config
            if app_config and 'device' in app_config and 'filter_index' in app_config['device']:
                try:
                    filter_index = app_config['device']['filter_index']
                    if 1 <= filter_index <= 5:
                        seismic.set_filter(filter_index)
                        print(f"🔧 Filter synchronized to index {filter_index}")
                        time.sleep(0.5)
                except Exception as e:
                    print(f"Warning: Could not sync filter setting: {e}")
        except Exception as e:
            print(f"Warning: Error setting device configuration: {e}")
        
        print(f"Connected to device on {config['port']} with unified timing system")
        return True
        
    except Exception as e:
        print(f"Error connecting to device: {e}")
        if seismic:
            try:
                seismic.close()
            except:
                pass
            seismic = None
        return False

def check_auto_start_trigger():
    """Check if auto-start conditions are met and trigger streaming if needed"""
    global auto_start_config, auto_start_state, seismic, streaming, stats, data_saver, adaptive_controller, csv_logging
    
    # Skip if auto-start not enabled or already started
    if not auto_start_config.get('enabled', False):
        return
    # Skip if suspended until reboot
    if auto_start_state.get('suspend_until_reboot', False):
        return
    
    if not auto_start_config.get('trigger_on_pps_lock', False):
        return
    
    if auto_start_state['auto_started']:
        return  # Already auto-started
    
    if streaming:
        return  # Already streaming (manual start)
    
    current_time = time.time()
    check_interval = auto_start_config.get('check_interval_seconds', 5)
    
    # Rate limit checks
    if current_time - auto_start_state['last_check_time'] < check_interval:
        return
    
    auto_start_state['last_check_time'] = current_time
    
    # Check PPS lock status
    if seismic and hasattr(seismic, 'timing_manager'):
        try:
            pps_status = seismic.timing_manager.check_pps_lock_status()
            
            if pps_status['locked']:
                auto_start_state['pps_lock_count'] += 1
                threshold = auto_start_config.get('pps_signal_count_threshold', 5)
                
                print(f"🔒 PPS LOCK DETECTED: Count {auto_start_state['pps_lock_count']}/{threshold}")
                
                # Check if threshold is met
                if auto_start_state['pps_lock_count'] >= threshold:
                    if not auto_start_state['trigger_conditions_met']:
                        auto_start_state['trigger_conditions_met'] = True
                        print(f"✅ AUTO-START TRIGGER CONDITIONS MET!")
                        print(f"   GPS+PPS locked with {auto_start_state['pps_lock_count']} consecutive signals")
                        print(f"   Initiating automatic streaming...")
                        
                        # Trigger auto-start
                        try:
                            # CRITICAL FIX: Reset timing state before auto-starting
                            # This prevents offset time issues when auto-starting streaming
                            global expect_sequence_reset, rate_window_ms
                            expect_sequence_reset = True  # Suppress sequence gap detection on first sample
                            rate_window_ms.clear()  # Clear timestamp tracking window
                            
                            # Reset timestamp generator and controller to clear any stale timing offsets
                            if hasattr(seismic, 'timestamp_generator'):
                                try:
                                    # Call the new reset method to clear all timing state
                                    if hasattr(seismic.timestamp_generator, 'reset_for_restart'):
                                        seismic.timestamp_generator.reset_for_restart()
                                        print("✅ Timing state reset for clean auto-start")
                                    else:
                                        print("⚠️  Warning: reset_for_restart method not found")
                                except Exception as e:
                                    print(f"Warning: Could not reset timestamp generator: {e}")
                            # Reset unified controller host correction if present
                            try:
                                if hasattr(seismic, 'timing_adapter') and seismic.timing_adapter and hasattr(seismic.timing_adapter, 'unified_controller'):
                                    controller = seismic.timing_adapter.unified_controller
                                    if controller and hasattr(controller, 'reset_state'):
                                        controller.reset_state()
                            except Exception as e:
                                print(f"Warning: Could not reset unified controller state: {e}")
                            
                            result = seismic.start_streaming(config['stream_rate'])
                            if result and result[0]:
                                auto_start_state['auto_started'] = True
                                streaming = True
                                stats['samples_received'] = 0
                                stats['samples_logged'] = 0
                                stats['sequence_gaps'] = 0
                                stats['data_gaps'] = 0
                                stats['last_sequence'] = None
                                stats['start_time'] = time.time()
                                
                                # Create new data saver for this session
                                create_data_saver()
                                
                                # Create new CSV file for legacy support
                                if csv_logging['enabled']:
                                    create_new_csv_file()
                                
                                # Create adaptive controller
                                if not adaptive_controller:
                                    from adaptive_timing_controller import CompatibilityAdaptiveTimingController
                                    adaptive_controller = CompatibilityAdaptiveTimingController(
                                        seismic, seismic.timing_manager
                                    )
                                
                                # Start timing control
                                adaptive_controller.start_controller()
                                
                                print(f"🚀 AUTO-START SUCCESSFUL: Streaming initiated by PPS lock trigger")
                                
                                # Emit notification to UI
                                socketio.emit('auto_start_triggered', {
                                    'message': 'Streaming auto-started on GPS+PPS lock',
                                    'pps_lock_count': auto_start_state['pps_lock_count'],
                                    'timestamp': current_time
                                })
                            else:
                                print(f"❌ AUTO-START FAILED: {result[1] if result else 'Unknown error'}")
                        except Exception as e:
                            print(f"❌ AUTO-START ERROR: {e}")
            else:
                # PPS not locked, reset counter
                if auto_start_state['pps_lock_count'] > 0:
                    print(f"⚠️  PPS lock lost, resetting counter (was {auto_start_state['pps_lock_count']})")
                auto_start_state['pps_lock_count'] = 0
                auto_start_state['trigger_conditions_met'] = False
                
        except Exception as e:
            print(f"Error checking auto-start trigger: {e}")

def background_monitor():
    """Enhanced background monitoring for unified timing system"""
    global adaptive_controller, config, seismic, streaming, data_saver, tb_config, time_source_status, mcu_timing_status, stats, csv_logging, saving_config
    
    last_connection_check = 0
    connection_check_interval = 10
    
    while True:
        try:
            current_time = time.time()
            
            # Basic connection health monitoring
            if current_time - last_connection_check > connection_check_interval:
                if seismic and streaming:
                    if not seismic.is_connected:
                        print("Warning: Lost connection to device during streaming")
                
                last_connection_check = current_time
            
            # Check auto-start trigger conditions
            check_auto_start_trigger()
            
            # Update timing status from host timing manager
            update_timing_status()
            
            # Emit unified timing status
            if seismic and hasattr(seismic, 'timing_adapter'):
                try:
                    timing_status = seismic.timing_adapter.get_timing_info()
                    socketio.emit('unified_timing_status', timing_status)
                except Exception as e:
                    print(f"Error emitting unified timing status: {e}")
            
            # Get device status
            device_status = {'connected': False, 'status': 'Not connected'}
            if seismic:
                try:
                    if seismic.is_connected:
                        device_status = {'connected': True, 'status': 'Connected'}
                        if streaming:
                            device_status['status'] = 'Streaming'
                except Exception as e:
                    print(f"Error checking device status: {e}")
                    device_status = {'connected': False, 'status': 'Error: ' + str(e)}
            
            # Get data saver stats
            data_saver_stats = {}
            tb_web_status = {
                'configured': bool(tb_config.get('access_token')),
                'connection_status': 'Disabled',
                'buffer_size': 0,
                'sender_active': False,
                'items_queued_total': 0,
                'items_sent_total': 0,
                'items_failed_total': 0
            }

            if data_saver:
                data_saver_stats = data_saver.get_stats()
                # ... (ThingsBoard status logic remains the same)
            
            # Get host timing info (JSON-safe)
            host_timing_info = {}
            if seismic and hasattr(seismic, 'timing_manager'):
                try:
                    raw_timing_info = seismic.timing_manager.get_timing_info()
                    host_timing_info = make_json_safe(raw_timing_info)
                except Exception as e:
                    print(f"Error getting host timing info: {e}")
                    host_timing_info = {'error': str(e)}
            
            # Get sample tracking stats (JSON-safe)
            sample_tracking_stats = {}
            if seismic and hasattr(seismic, 'get_sample_stats'):
                try:
                    raw_stats = seismic.get_sample_stats()
                    sample_tracking_stats = make_json_safe(raw_stats)
                except Exception as e:
                    print(f"Error getting sample stats: {e}")
            
            # Get timestamp quantization information
            timestamp_quantization_info = {}
            if seismic and hasattr(seismic, 'timing_adapter') and hasattr(seismic.timing_adapter, 'timestamp_generator'):
                try:
                    quantization_ms = seismic.timing_adapter.timestamp_generator.quantization_ms
                    timestamp_quantization_info = {
                        'quantization_ms': quantization_ms,
                        'description': f'Timestamps quantized to {quantization_ms}ms boundaries',
                        'config_quantization_ms': config.get('timestamp_quantization_ms', 10)
                    }
                except Exception as e:
                    print(f"Error getting quantization info: {e}")
                    timestamp_quantization_info = {'error': str(e)}
            
            # Note: PPS realignment is now handled automatically by the unified timing system
            # Unified timing system handles PPS alignment automatically
            pass

            # Compute timestamp health for UI (last sample vs now and precise host time)
            timestamp_health = {}
            try:
                if seismic and hasattr(seismic, 'timestamp_generator'):
                    gen_stats = seismic.timestamp_generator.get_stats()
                    last_ts = gen_stats.get('last_timestamp')  # seconds float
                    if last_ts:
                        now_s = time.time()
                        timestamp_health['last_timestamp'] = int(last_ts * 1000)
                        timestamp_health['offset_ms'] = int((last_ts - now_s) * 1000)
                        if hasattr(seismic, 'timing_manager') and seismic.timing_manager:
                            precise_now = seismic.timing_manager.get_precise_time()
                            timestamp_health['offset_precise_ms'] = int((last_ts - precise_now) * 1000)
            except Exception as e:
                timestamp_health = {'error': str(e)}

            # Emit status update
            socketio.emit('status_update', {
                'device': device_status,
                'time_source': time_source_status,
                'host_timing': host_timing_info,
                'mcu_timing': mcu_timing_status,  # NEW: MCU timing status
                'stats': stats,
                'streaming': streaming,
                'streaming_allowed': True,  # Always allowed with host timing
                'streaming_reason': 'Host manages timing automatically',
                'csv_logging': {
                    'enabled': csv_logging['enabled'],
                    'current_file': stats.get('current_csv_file'),
                    'samples_logged': stats['samples_logged']
                },
                'data_saver': data_saver_stats,
                'saving_config': saving_config,
                'sample_tracking': sample_tracking_stats,
                'timestamp_quantization': timestamp_quantization_info,  # NEW: Timestamp quantization info
                'timestamp_health': timestamp_health,
                'thingsboard': {
                    'enabled': tb_config.get('enabled', False),
                    'config': tb_config,
                    'status': tb_web_status,
                    'has_access_token': bool(tb_config.get('access_token'))
                }
            })
            
            time.sleep(1)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(5)

@app.route('/api/timing/diagnostics')
def get_timing_diagnostics():
    """Get comprehensive timing diagnostics"""
    diagnostics = {
        'timestamp_generator': {},
        'timing_health': {},
        'recent_samples': [],
        'performance_metrics': {}
    }
    
    if seismic and hasattr(seismic, 'timestamp_generator'):
        try:
            # Get timestamp generator statistics
            diagnostics['timestamp_generator'] = make_json_safe(seismic.timestamp_generator.get_stats())
            
            # Get health assessment
            with seismic.timestamp_generator.lock:
                health = {
                    'status': 'unknown',
                    'issues': [],
                    'recommendations': []
                }
                
                if not seismic.timestamp_generator.is_initialized:
                    health['status'] = 'not_initialized'
                else:
                    # Check for issues
                    issues = []
                    stats = seismic.timestamp_generator.stats
                    
                    if stats['resets_performed'] > 5:
                        issues.append('frequent_resets')
                    
                    if abs(seismic.timestamp_generator.current_drift_rate) > 100:
                        issues.append('high_drift')
                    
                    if len(seismic.timestamp_generator.recent_intervals) > 5:
                        try:
                            import statistics
                            avg_interval = statistics.mean(seismic.timestamp_generator.recent_intervals)
                            if abs(avg_interval - seismic.timestamp_generator.expected_interval) > 0.001:
                                issues.append('rate_mismatch')
                        except:
                            pass
                    
                    if stats['outliers_rejected'] > stats['samples_processed'] * 0.1:
                        issues.append('high_outlier_rate')
                    
                    # Determine overall status
                    if not issues:
                        health['status'] = 'excellent'
                    elif len(issues) == 1 and 'high_drift' not in issues:
                        health['status'] = 'good'
                    elif len(issues) <= 2:
                        health['status'] = 'fair'
                    else:
                        health['status'] = 'poor'
                    
                    health['issues'] = issues
                    
                    # Generate recommendations
                    if 'frequent_resets' in issues:
                        health['recommendations'].append('Check sequence number stability and system timing')
                    if 'high_drift' in issues:
                        health['recommendations'].append('Verify system clock stability and NTP synchronization')
                    if 'rate_mismatch' in issues:
                        health['recommendations'].append('Check MCU sampling rate configuration')
                    if 'high_outlier_rate' in issues:
                        health['recommendations'].append('Check serial communication stability')
                
                diagnostics['timing_health'] = health
            
            # Get recent sample info from buffer
            if hasattr(seismic, 'sample_tracking') and seismic.sample_tracking.get('sample_buffer'):
                recent_samples = []
                buffer = seismic.sample_tracking['sample_buffer']
                
                # Get last 10 samples
                for sample in list(buffer)[-10:]:
                    sample_info = {
                        'sequence': sample.get('sequence'),
                        'timestamp': sample.get('timestamp'),
                        'arrival_time': sample.get('arrival_time'),
                        'datetime_str': datetime.fromtimestamp(sample.get('timestamp', 0)/1000.0).strftime('%H:%M:%S.%f')[:-3] if sample.get('timestamp') else 'N/A'
                    }
                    recent_samples.append(sample_info)
                
                diagnostics['recent_samples'] = recent_samples
            
            # Performance metrics
            if seismic.timestamp_generator.is_initialized:
                uptime = time.time() - (seismic.timestamp_generator.reference_system_time or time.time())
                samples_processed = seismic.timestamp_generator.stats['samples_processed']
                processing_rate = samples_processed / uptime if uptime > 0 else 0
                
                diagnostics['performance_metrics'] = {
                    'uptime_seconds': uptime,
                    'samples_processed': samples_processed,
                    'processing_rate_hz': processing_rate,
                    'drift_rate_ppm': seismic.timestamp_generator.current_drift_rate,
                    'consecutive_good_samples': seismic.timestamp_generator.consecutive_good_samples,
                    'anomaly_rate_percent': (
                        (seismic.timestamp_generator.stats['resets_performed'] + 
                         seismic.timestamp_generator.stats['outliers_rejected']) / 
                        max(samples_processed, 1) * 100
                    )
                }
        
        except Exception as e:
            diagnostics['error'] = str(e)
            print(f"Error getting timing diagnostics: {e}")
    else:
        diagnostics['error'] = 'Timestamp generator not available'
    
    return jsonify(diagnostics)

@app.route('/api/timing/reset', methods=['POST'])
def reset_timestamp_generator():
    """Reset the timestamp generator"""
    if seismic and hasattr(seismic, 'timestamp_generator'):
        try:
            seismic.timestamp_generator.reset()
            return jsonify({'status': 'success', 'message': 'Timestamp generator reset'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Timestamp generator not available'}), 400

@app.route('/api/timing/config', methods=['GET', 'POST'])
def handle_timestamp_config():
    """Get or update timestamp generator configuration"""
    if not seismic or not hasattr(seismic, 'timestamp_generator'):
        return jsonify({'status': 'error', 'message': 'Timestamp generator not available'}), 400
    
    if request.method == 'POST':
        try:
            config_data = request.json
            
            # Update configuration
            if 'expected_rate' in config_data:
                rate = float(config_data['expected_rate'])
                if 1 <= rate <= 1000:
                    seismic.timestamp_generator.expected_rate = rate
                    seismic.timestamp_generator.expected_interval = 1.0 / rate
            
            if 'sequence_gap_threshold' in config_data:
                threshold = int(config_data['sequence_gap_threshold'])
                if 1 <= threshold <= 100:
                    seismic.timestamp_generator.sequence_gap_threshold = threshold
            
            if 'outlier_threshold' in config_data:
                threshold = float(config_data['outlier_threshold'])
                if 0.001 <= threshold <= 1.0:
                    seismic.timestamp_generator.outlier_threshold = threshold
            
            return jsonify({'status': 'success', 'message': 'Configuration updated'})
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    # GET request - return current configuration
    try:
        config = {
            'expected_rate': seismic.timestamp_generator.expected_rate,
            'expected_interval': seismic.timestamp_generator.expected_interval,
            'sequence_gap_threshold': seismic.timestamp_generator.sequence_gap_threshold,
            'outlier_threshold': seismic.timestamp_generator.outlier_threshold,
            'time_jump_threshold': seismic.timestamp_generator.time_jump_threshold,
            'max_drift_ppm': seismic.timestamp_generator.max_drift_ppm
        }
        return jsonify(config)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Add this to your background_monitor function to emit timing updates
def emit_timing_diagnostics():
    """Emit timing diagnostics via websocket"""
    if seismic and hasattr(seismic, 'timestamp_generator'):
        try:
            # Get key metrics
            stats = seismic.timestamp_generator.get_stats()
            
            # Create summary for websocket
            timing_summary = {
                'samples_processed': stats.get('samples_processed', 0),
                'resets_performed': stats.get('resets_performed', 0),
                'outliers_rejected': stats.get('outliers_rejected', 0),
                'drift_rate_ppm': stats.get('current_drift_rate_ppm', 0),
                'consecutive_good_samples': stats.get('consecutive_good_samples', 0),
                'average_interval': stats.get('average_interval', 0),
                'is_initialized': stats.get('is_initialized', False)
            }
            
            # Emit to connected clients
            socketio.emit('timing_diagnostics', timing_summary)
            
        except Exception as e:
            print(f"Error emitting timing diagnostics: {e}")

@app.route('/api/adaptive/status')
def get_adaptive_status():
    """Get adaptive timing controller status"""
    if not adaptive_controller:
        return jsonify({
            'enabled': False,
            'status': 'not_initialized',
            'message': 'Adaptive controller not created'
        })
    
    stats = adaptive_controller.get_stats()
    performance = adaptive_controller.get_performance_assessment()
    
    return jsonify({
        'enabled': True,
        'status': performance,
        'running': adaptive_controller.running,
        'stats': stats,
        'controller_active': adaptive_controller.running,
        'measurement_interval_s': adaptive_controller.measurement_interval,
        'max_correction_ppm': adaptive_controller.max_correction_ppm
    })

@app.route('/api/adaptive/config', methods=['GET', 'POST'])
def handle_adaptive_config():
    """Get or update adaptive controller configuration"""
    if not adaptive_controller:
        return jsonify({'status': 'error', 'message': 'Adaptive controller not available'}), 400
    
    if request.method == 'POST':
        config_data = request.json
        
        try:
            # Update configuration parameters
            if 'measurement_interval' in config_data:
                interval = float(config_data['measurement_interval'])
                if 10 <= interval <= 300:  # 10 seconds to 5 minutes
                    adaptive_controller.measurement_interval = interval
            
            if 'max_correction_ppm' in config_data:
                max_corr = float(config_data['max_correction_ppm'])
                if 1 <= max_corr <= 1000:  # 1 to 1000 ppm
                    adaptive_controller.max_correction_ppm = max_corr
            
            if 'kp' in config_data:
                kp = float(config_data['kp'])
                if 0.1 <= kp <= 2.0:
                    adaptive_controller.kp = kp
            
            if 'ki' in config_data:
                ki = float(config_data['ki'])
                if 0.0 <= ki <= 1.0:
                    adaptive_controller.ki = ki
            
            if 'kd' in config_data:
                kd = float(config_data['kd'])
                if 0.0 <= kd <= 1.0:
                    adaptive_controller.kd = kd
            
            return jsonify({'status': 'success', 'message': 'Configuration updated'})
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    # GET request - return current configuration
    return jsonify({
        'measurement_interval': adaptive_controller.measurement_interval,
        'max_correction_ppm': adaptive_controller.max_correction_ppm,
        'kp': adaptive_controller.kp,
        'ki': adaptive_controller.ki,
        'kd': adaptive_controller.kd,
        'target_rate': adaptive_controller.target_rate,
        'target_interval_us': adaptive_controller.target_interval_us
    })

@app.route('/api/adaptive/enable', methods=['POST'])
def enable_adaptive_control():
    """Enable/disable adaptive timing control"""
    global adaptive_controller
    
    if not seismic:
        return jsonify({'status': 'error', 'message': 'Device not connected'}), 400
    
    enable = request.json.get('enable', True)
    
    try:
        if enable:
            if not adaptive_controller:
                adaptive_controller = AdaptiveTimingController(seismic, seismic.timing_manager)
            
            # ENSURE CORRECTIONS ARE ENABLED
            adaptive_controller.set_corrections_enabled(True)
            
            if streaming and not adaptive_controller.running:
                adaptive_controller.start_controller()
                return jsonify({'status': 'enabled', 'message': 'Adaptive control enabled with corrections'})
            elif not streaming:
                return jsonify({'status': 'ready', 'message': 'Adaptive control ready (will start with streaming)'})
            else:
                return jsonify({'status': 'already_enabled', 'message': 'Adaptive control already running'})
        else:
            if adaptive_controller and adaptive_controller.running:
                adaptive_controller.stop_controller()
                return jsonify({'status': 'disabled', 'message': 'Adaptive control disabled'})
            else:
                return jsonify({'status': 'already_disabled', 'message': 'Adaptive control not running'})
                
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/adaptive/reset', methods=['POST'])
def reset_adaptive_controller():
    """Reset adaptive controller to baseline"""
    if not adaptive_controller:
        return jsonify({'status': 'error', 'message': 'Adaptive controller not available'}), 400
    
    try:
        success = adaptive_controller.reset_to_baseline()
        if success:
            return jsonify({
                'status': 'success', 
                'message': 'Adaptive controller reset to baseline (100.00Hz)',
                'current_interval_us': adaptive_controller.current_interval_us,
                'target_interval_us': adaptive_controller.target_interval_us
            })
        else:
            return jsonify({'status': 'error', 'message': 'Failed to reset to baseline'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/adaptive/force_baseline', methods=['POST'])
def force_mcu_baseline():
    """Force MCU back to exact baseline rate (emergency correction)"""
    if not adaptive_controller:
        return jsonify({'status': 'error', 'message': 'Adaptive controller not available'}), 400
    
    try:
        success = adaptive_controller.force_mcu_baseline()
        if success:
            return jsonify({
                'status': 'success', 
                'message': 'MCU forced back to baseline (100.00Hz)',
                'current_interval_us': adaptive_controller.current_interval_us,
                'target_interval_us': adaptive_controller.target_interval_us
            })
        else:
            return jsonify({'status': 'error', 'message': 'Failed to force MCU baseline'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/adaptive/interval_status')
def get_interval_status():
    """Get current MCU sampling interval status"""
    if not adaptive_controller:
        return jsonify({'status': 'error', 'message': 'Adaptive controller not available'}), 400
    
    try:
        current_rate = 1e6 / adaptive_controller.current_interval_us
        target_rate = 1e6 / adaptive_controller.target_interval_us
        deviation_ppm = ((adaptive_controller.current_interval_us - adaptive_controller.target_interval_us) / adaptive_controller.target_interval_us) * 1e6
        
        return jsonify({
            'current_interval_us': adaptive_controller.current_interval_us,
            'target_interval_us': adaptive_controller.target_interval_us,
            'current_rate_hz': round(current_rate, 6),
            'target_rate_hz': round(target_rate, 6),
            'deviation_ppm': round(deviation_ppm, 2),
            'is_at_baseline': abs(deviation_ppm) < 1.0
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Auto-start configuration endpoints
@app.route('/api/auto_start/config', methods=['GET', 'POST'])
def handle_auto_start_config():
    """Get or update auto-start configuration"""
    global auto_start_config, app_config
    
    if request.method == 'POST':
        new_config = request.json
        
        # Update configuration
        if 'enabled' in new_config:
            auto_start_config['enabled'] = bool(new_config['enabled'])
        
        if 'trigger_on_pps_lock' in new_config:
            auto_start_config['trigger_on_pps_lock'] = bool(new_config['trigger_on_pps_lock'])
        
        if 'pps_signal_count_threshold' in new_config:
            threshold = int(new_config['pps_signal_count_threshold'])
            if 1 <= threshold <= 20:
                auto_start_config['pps_signal_count_threshold'] = threshold
        
        if 'check_interval_seconds' in new_config:
            interval = int(new_config['check_interval_seconds'])
            if 1 <= interval <= 60:
                auto_start_config['check_interval_seconds'] = interval
        
        # Save to config file
        if app_config:
            app_config['auto_start'] = auto_start_config
            save_config(app_config)
        
        # Determine if reboot is needed
        reboot_needed = new_config.get('enabled', False) or new_config.get('trigger_on_pps_lock', False)
        
        return jsonify({
            'status': 'ok',
            'config': auto_start_config,
            'reboot_needed': reboot_needed,
            'message': 'Auto-start configuration updated. Reboot required for changes to take effect.' if reboot_needed else 'Configuration updated'
        })
    
    return jsonify(auto_start_config)

# NEW: suspend auto-start until reboot (not persisted)
@app.route('/api/auto_start/suspend_until_reboot', methods=['POST'])
def suspend_auto_start_until_reboot():
    global auto_start_state
    try:
        body = request.json or {}
        suspend = bool(body.get('suspend', True))
        auto_start_state['suspend_until_reboot'] = suspend
        return jsonify({
            'status': 'ok',
            'suspend_until_reboot': auto_start_state['suspend_until_reboot']
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/auto_start/status')
def get_auto_start_status():
    """Get current auto-start monitoring status"""
    global auto_start_config, auto_start_state, seismic
    
    pps_lock_status = {'locked': False, 'source': 'UNKNOWN', 'accuracy_us': 1000000}
    if seismic and hasattr(seismic, 'timing_manager'):
        try:
            pps_lock_status = seismic.timing_manager.check_pps_lock_status()
        except:
            pass
    
    return jsonify({
        'config': auto_start_config,
        'state': auto_start_state,
        'pps_lock_status': pps_lock_status,
        'streaming': streaming,
        'conditions_met': auto_start_state['trigger_conditions_met']
    })

@app.route('/api/system/reboot', methods=['POST'])
def reboot_system():
    """Reboot the system (requires sudo privileges)"""
    try:
        import subprocess
        print("🔄 SYSTEM REBOOT REQUESTED")
        print("   Initiating system reboot in 5 seconds...")
        
        # Schedule reboot in 5 seconds to allow response to be sent
        subprocess.Popen(['sudo', 'shutdown', '-r', '+0.08'])  # ~5 seconds
        
        return jsonify({
            'status': 'ok',
            'message': 'System will reboot in 5 seconds'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Failed to reboot: {str(e)}'
        }), 500

if __name__ == '__main__':
    # Ensure data directory exists
    ensure_data_directory()
    
    # Start background monitoring thread
    monitor_thread = threading.Thread(target=background_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    try:
        # Connect to device automatically
        if not connect_device():
            print("Warning: Failed to connect to device automatically")
        
        # Run the web server
        print("Starting Host-Managed Timing Seismic Monitoring Web Server...")
        print(f"Timing: Host-managed (automatic PPS/NTP/system selection)")
        print(f"Configuration loaded from: {os.path.abspath('config.conf')}")
        print(f"CSV files will be saved to: {os.path.abspath(saving_config['csv_directory'])}")
        
        host = app_config['app']['host'] if app_config else '0.0.0.0'
        port = app_config['app']['port'] if app_config else 5000
        debug = app_config['app']['debug'] if app_config else False
        
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    finally:
        cleanup_resources()