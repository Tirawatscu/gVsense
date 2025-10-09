# gVsense Migration Guide

## Overview
This guide explains how to migrate from the old system to the new integrated gVsense system with all the advanced features implemented.

## What's New

### MCU Firmware (main.cpp)
- **Single-shot scheduler** - Prevents burst catch-up, max 1 sample per loop
- **64-bit timing math** - Avoids wrap boundary edge cases
- **DRDY-driven ADC** - Throughput margin verification
- **Flow control** - Backpressure signaling with OFLOW meta messages
- **Session headers** - boot_id and stream_id for data stitching
- **PPS PLL authority** - MCU-side PPS PLL as authoritative clock source
- **Timing state machine** - ACTIVE→HOLDOVER→CAL→RAW thresholds
- **Temperature compensation** - Optional temperature-aware ppm calibration
- **Pi-side calibration** - No EEPROM writes, Pi manages calibration storage
- **Health beacons** - 1 Hz STAT line with comprehensive status
- **Bounded adjustments** - Rate change rejection (>50 ppm while PPS locked)

### Pi-Side Components
- **Fast serial reader** - High-performance serial ingestion with async parsing
- **CRC verification** - Binary frame integrity checking
- **Backpressure monitoring** - MCU buffer overflow awareness
- **UTC stamping** - MCU timestamp as primary time axis
- **Quality control** - Gap detection, quality mapping, overflow tracking
- **Data reconstruction** - Interpolating missing samples by timestamp
- **Session logging** - Comprehensive session tracking and management
- **MCU timing** - MCU-centric timing processing
- **MCU PLL controller** - Conservative rate control policy

## Migration Steps

### 1. Update MCU Firmware
```bash
# Compile and upload new main.cpp to MCU
# The new firmware includes all advanced timing features
```

### 2. Install Pi-Side Components
```bash
# Install new Python dependencies
pip install -r requirements.txt

# Install the new system
sudo ./install.sh
```

### 3. Update Web Server
The web server has been updated to use the new integrated system:
- `integrated_acquisition.py` - New unified system
- `HostTimingSeismicAcquisition` - Compatibility wrapper
- All new components are automatically integrated

### 4. Configuration
The new system uses the same configuration files:
- `config.conf` - Main configuration
- `/var/lib/gvsense/` - Calibration storage directory

## New Features Available

### Calibration Management
```bash
# List devices with calibration
gvsense-cal list

# Read calibration for device
gvsense-cal read XIAO-1234

# Set calibration
gvsense-cal set XIAO-1234 --ppm 12.34 --note "Manual calibration"

# Clear calibration
gvsense-cal clear XIAO-1234
```

### System Service
```bash
# Start the service
sudo systemctl start gvsense-agent.service

# Check status
sudo systemctl status gvsense-agent.service

# View logs
journalctl -u gvsense-agent.service -f
```

### Web Interface
The web interface now shows:
- **Advanced timing status** - PPS state, calibration, accuracy
- **Quality metrics** - Gap detection, overflow tracking
- **Session information** - boot_id, stream_id, duration
- **Calibration status** - Source, ppm, validity
- **Backpressure monitoring** - Buffer overflow awareness

## Protocol Changes

### New MCU Commands
- `SET_CAL_PPM:<value>` - Set calibration from Pi
- `CLEAR_CAL` - Clear calibration
- `GET_CAL` - Get calibration status
- `START_STREAM_PPS:<rate>,<channels>` - PPS-locked start

### New MCU Messages
- `BOOT:device=<id>,boot_id=<id>,fw=<version>` - Boot header
- `SESSION:<metadata>` - Session header
- `STAT:<comprehensive_status>` - Enhanced status line
- `OFLOW:<overflow_info>` - Overflow notification

### Enhanced Status Line
```
STAT:timing_source,accuracy_us,calibration_ppm,pps_valid,pps_age_ms,calibration_valid,calibration_source,micros_wraparound_count,buffer_overflows,samples_skipped_due_to_overflow,boot_id,stream_id,adc_deadline_misses
```

## Testing

### Test Integration
```bash
# Test the integrated system
python3 test_integration.py

# Test web server compatibility
python3 -c "from integrated_acquisition import HostTimingSeismicAcquisition; print('✓ Compatibility OK')"
```

### Test Web Server
```bash
# Start web server
python3 web_server.py

# Access web interface
# http://localhost:5000
```

## Troubleshooting

### Common Issues

1. **Serial Port Access**
   ```bash
   # Check device permissions
   ls -la /dev/ttyUSB*
   
   # Add user to dialout group
   sudo usermod -a -G dialout $USER
   ```

2. **Calibration Storage**
   ```bash
   # Check calibration directory
   ls -la /var/lib/gvsense/
   
   # Fix permissions if needed
   sudo chown -R gvsense:gvsense /var/lib/gvsense/
   ```

3. **Service Issues**
   ```bash
   # Check service status
   sudo systemctl status gvsense-agent.service
   
   # Restart service
   sudo systemctl restart gvsense-agent.service
   ```

### Logs
- **System logs**: `journalctl -u gvsense-agent.service`
- **Web server logs**: Check web server output
- **MCU logs**: Serial output from MCU

## Performance Improvements

### Before (Old System)
- Burst catch-up scheduling
- 32-bit timing math with wrap issues
- No flow control
- No quality monitoring
- No data reconstruction
- No calibration persistence

### After (New System)
- Single-shot scheduling
- 64-bit timing math
- Comprehensive flow control
- Real-time quality monitoring
- Automatic data reconstruction
- Persistent calibration management
- MCU-centric timing authority
- Conservative rate control

## Next Steps

### Optional Enhancements
1. **Binary Framing** - Add sync word + length + CRC-16/32
2. **PPS GPIO** - Wire PPS to Pi GPIO and enable pps-gpio with chrony

### Production Deployment
1. **Hardware Setup** - Connect MCU, GPS, Pi
2. **Configuration** - Set device IDs, calibration values
3. **Service Installation** - Install systemd service
4. **Monitoring** - Set up monitoring and alerting
5. **Data Pipeline** - Connect to data storage and analysis

## Support

For issues or questions:
1. Check logs for error messages
2. Verify hardware connections
3. Test with `test_integration.py`
4. Review this migration guide
5. Check the web interface for status information

The new system is backward compatible and provides significant improvements in timing accuracy, data quality, and system reliability.
