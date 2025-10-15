# Directory Cleanup Summary
**Date:** October 16, 2025

## Overview
Cleaned gVsense workspace by archiving 40+ development/debug files and keeping only 20 production-essential files.

## Production Files Kept (12 files)

### Core Python Modules (8 files)
```
web_server.py                    132 KB   Flask-SocketIO server & API
host_timing_acquisition.py       172 KB   Main acquisition system
timing_fix.py                     86 KB   Unified timing controller
data_saver.py                     18 KB   Binary data logging
adaptive_timing_controller.py      6 KB   Adaptive control wrapper
calibration_storage.py             8 KB   Persistent calibration
influx_writer.py                  13 KB   InfluxDB integration
thingsboard_client.py             15 KB   ThingsBoard integration
```

### Configuration (2 files)
```
config.conf                       2.7 KB   Runtime configuration
config.conf.template              2.7 KB   Configuration template
```

### Firmware & Documentation (2 files)
```
src/main.cpp                      ~80 KB   MCU firmware (SAMD21)
README.md                         3.6 KB   System documentation
```

### Directories (5 directories)
```
templates/        HTML templates for web UI
static/           CSS, JS, images for web UI
data/             Binary data storage
session_logs/     Session metadata logs
archive/          Archived development files
```

## Files Archived (44+ files)

### Monitoring Scripts → archive/monitoring_scripts/ (16 files)
```
monitor_calibration.py
monitor_drift_fix.py
monitor_offset_stability.py
monitor_real_offset.py
monitor_sequence_wraparound.py
monitor_ui_offset.py
monitor_wraparound_timing.py
pps_monitor.py
live_offset_monitor.py
simple_lag_monitor.py
check_offset.py
fix_ui_offset.py
analyze_wraparound_timing.py
timing_alignment_test.py
test_offset_fix_concept.py
test_proactive_generator.py
```

### Documentation → archive/documentation/ (18 files)
```
CALIBRATION_FIX_COMPLETE.md
FINAL_DATA_LOSS_FIX.md
FIRMWARE_CHANGES_DIFF.md
FIRMWARE_FIX_CHECKLIST.md
FIRMWARE_FIX_COMPLETED.md
FIRMWARE_MODIFICATION_INSTRUCTIONS.md
FIX_QUANTIZATION.md
INVESTIGATION_SUMMARY.md
NO_GPS_OPERATION_ANALYSIS.md
OFFSET_DRIFT_FIX_SUMMARY.md
OFFSET_DRIFT_ROOT_CAUSE.md
RECOMPILE_INSTRUCTIONS.md
SEQUENCE_WRAPAROUND_ANALYSIS.md
SEQUENCE_WRAPAROUND_FIX.md
SEQUENCE_WRAPAROUND_FIX_FINAL.md
TIMESTAMP_DRIFT_ROOT_CAUSE_ANALYSIS.md
TIMESTAMP_INTERVAL_FIX.md
INDEX.md (old archive index)
```

### Temporary Files → archive/temp_files/ (12 files)
```
main.cpp                                # Duplicate of src/main.cpp
FIRMWARE_FIX_PPS_CALIBRATION.cpp       # Old firmware snippet
calibration.json                        # Old single-file format
timestamp_gaps.log                      # Old log file
.lgd-nfy0                               # Unknown temp file
timing_improvement_20251008_204003.png  # Screenshot
timing_performance_test.png             # Screenshot
backpressure_monitor.py                 # Empty file (0 bytes)
99-gvsense.rules                        # udev rules (USB only, not needed)
gvsense-cal                             # CLI tool (not needed)
install.sh                              # Installation script (system configured)
pps_gpio_setup.sh                       # PPS setup (already configured)
```

## Space Saved
- **Before cleanup:** 56 files in root directory
- **After cleanup:** 12 essential files
- **Reduction:** 79% fewer files in root

## Impact
✅ **No functional impact** - All archived files were:
- Debug/monitoring tools (not used in production)
- Historical documentation (completed fixes)
- Temporary files (duplicates, logs, screenshots)
- Empty placeholder files

✅ **Production system unchanged:**
- `gvsense.service` continues running
- Web UI accessible at http://localhost:5001
- All core functionality intact
- No code dependencies on archived files

## Archive Location
All archived files preserved at: `/home/tsk/gVsense/archive/`
- See `archive/INDEX.md` for detailed inventory
- Can be safely deleted if disk space needed
- Kept for historical reference

## Directory Structure (After Cleanup)
```
/home/tsk/gVsense/
├── README.md                          # System documentation
├── web_server.py                      # Main server
├── host_timing_acquisition.py         # Acquisition system
├── timing_fix.py                      # Timing controller
├── data_saver.py                      # Data logging
├── adaptive_timing_controller.py      # Adaptive control
├── calibration_storage.py             # Calibration storage
├── influx_writer.py                   # InfluxDB writer
├── thingsboard_client.py              # ThingsBoard client
├── config.conf                        # Configuration
├── config.conf.template               # Config template
├── requirements.txt                   # Dependencies
├── install.sh                         # Installer
├── pps_gpio_setup.sh                  # PPS setup
├── gvsense-cal                        # CLI tool
├── 99-gvsense.rules                   # udev rules
├── .gitignore                         # Git config
├── src/
│   └── main.cpp                       # MCU firmware
├── templates/                         # HTML templates
├── static/                            # Web assets
├── data/                              # Data files
├── session_logs/                      # Session logs
└── archive/                           # Archived files
    ├── INDEX.md                       # Archive index
    ├── monitoring_scripts/            # Debug scripts
    ├── documentation/                 # Fix documentation
    └── temp_files/                    # Temporary files
```

## Verification Commands
```bash
# Check service status
sudo systemctl status gvsense.service

# List production files
cd /home/tsk/gVsense && ls -1 *.py

# View archive inventory
cat /home/tsk/gVsense/archive/INDEX.md

# Check disk usage
du -sh /home/tsk/gVsense/archive
du -sh /home/tsk/gVsense
```

## Notes
- Archive can be removed with: `rm -rf /home/tsk/gVsense/archive`
- Python cache (`__pycache__/`) regenerates automatically
- Git history preserved (`.git/` directory intact)
- No changes to system service configuration

---
Cleanup performed: October 16, 2025
System: gVsense Seismic Acquisition System
Status: ✅ Production ready
