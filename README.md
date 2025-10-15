# gVsense Seismic Acquisition System

High-precision seismic data acquisition system with GPS/PPS timing synchronization.

## System Architecture

### Core Components

**Web Interface & API**
- `web_server.py` - Flask-SocketIO server with real-time web UI
- `templates/` - HTML templates for web interface
- `static/` - CSS, JavaScript, and web assets

**Data Acquisition**
- `host_timing_acquisition.py` - Main acquisition system with unified timing
- `timing_fix.py` - Unified timing controller with MCU integration
- `adaptive_timing_controller.py` - Adaptive drift compensation (no-GPS mode)
- `src/main.cpp` - MCU firmware (Seeeduino XIAO SAMD21)

**Data Management**
- `data_saver.py` - Binary data logging and session management
- `calibration_storage.py` - Persistent calibration storage per device
- `data/` - Binary data files
- `session_logs/` - Session metadata and logs

**External Integrations**
- `influx_writer.py` - InfluxDB time-series database writer
- `thingsboard_client.py` - ThingsBoard IoT platform integration
- `backpressure_monitor.py` - Serial backpressure monitoring

**System Configuration**
- `config.conf` - Runtime configuration
- `config.conf.template` - Configuration template
- `99-gvsense.rules` - udev rules for device naming
- `pps_gpio_setup.sh` - PPS GPIO configuration script
- `requirements.txt` - Python dependencies

**Tools**
- `gvsense-cal` - CLI tool for calibration management
- `install.sh` - System installation script

## Timing Modes

The system supports 4-tier timing hierarchy:

1. **PPS_ACTIVE** (±1μs) - GPS PPS signal locked
2. **PPS_HOLDOVER** (±1-6μs) - GPS lost, using learned calibration
3. **INTERNAL_CAL** (±10-100μs) - Internal oscillator with stored calibration
4. **INTERNAL_RAW** (±1000μs) - Raw oscillator (adaptive control enabled)

## Quick Start

### Installation
```bash
sudo ./install.sh
```

### Start Service
```bash
sudo systemctl start gvsense.service
sudo systemctl status gvsense.service
```

### Web Interface
Open browser: `http://localhost:5001`

### CLI Calibration Tool
```bash
gvsense-cal list                              # List devices
gvsense-cal read XIAO-1234                    # Read calibration
gvsense-cal set XIAO-1234 --ppm -276.27       # Set calibration
gvsense-cal clear XIAO-1234                   # Clear calibration
```

## Configuration

Edit `config.conf` for:
- Serial device path
- Sample rate (100 Hz default)
- InfluxDB connection
- ThingsBoard connection
- Data storage paths

## Data Format

Binary format with microsecond-precision timestamps:
- 8 bytes: Unix timestamp (microseconds)
- 12 bytes: X, Y, Z acceleration (int32, little-endian)
- 100 Hz sampling rate (10ms intervals)

## Recent Improvements

### Adaptive Timing Control (Oct 2025)
- Automatically enables when GPS/PPS unavailable
- ±200 ppm tolerance monitoring
- ±20 ppm bounded adjustments
- 10-second cooldown between corrections
- Improves stability from ±1000μs to ±100μs without GPS

### Sequence Wraparound Fix (Oct 2025)
- Removed hot-path overhead from sequence counter
- Zero timing glitches at 65535→0 wraparound
- Lazy calculation: `seq_wraparounds = samples_generated >> 16`

### Persistent Calibration Storage (Oct 2025)
- Per-device calibration storage in `/var/lib/gvsense/`
- Survives reboots and firmware updates
- CLI tool for calibration management

## Archive

Historical development files moved to `archive/`:
- `archive/monitoring_scripts/` - Debug and monitoring scripts
- `archive/documentation/` - Investigation and fix documentation
- `archive/temp_files/` - Temporary files and logs

## License

Copyright © 2025 gVsense Project
