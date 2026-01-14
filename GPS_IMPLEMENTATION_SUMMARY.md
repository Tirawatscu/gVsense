# GPS Location Tracking - Implementation Summary

## 🎉 What Was Implemented

Your seismic monitoring system now has **automatic GPS location tracking** that periodically stores sensor coordinates in InfluxDB!

### Files Added

1. **`gps_reader.py`** - GPS coordinate reading module
   - Reads from gpsd (GPS daemon)
   - Auto-detects GPS availability
   - Falls back to mock GPS if hardware unavailable
   - Caches last known location

2. **`gps_updater.py`** - Periodic GPS update manager  
   - Background thread for automatic updates
   - Configurable update interval (default: 60 seconds)
   - Statistics tracking
   - Thread-safe start/stop

3. **`gps_example.py`** - Example integration code
   - Complete working example
   - Shows all features
   - Good reference for custom implementations

4. **`GPS_SETUP_GUIDE.md`** - Quick setup guide (5 minutes)
   - Step-by-step instructions
   - Configuration examples
   - Troubleshooting tips

5. **`GPS_INTEGRATION.md`** - Comprehensive documentation
   - Architecture overview
   - Query examples
   - Best practices
   - Performance analysis

6. **`test_gps.py`** - GPS testing script
   - Test before deployment
   - Verify GPS hardware
   - Test InfluxDB integration

### Files Modified

1. **`config.conf.template`** - Added GPS configuration section
   ```json
   "gps_location": {
       "enabled": true,
       "update_interval_seconds": 60,
       "method": "gpsd",
       "mock_coordinates": null
   }
   ```

2. **`web_server.py`** - Integrated GPS into main application
   - Imports GPS modules
   - Creates GPS updater when InfluxDB is enabled
   - Starts/stops GPS updater automatically
   - Cleans up GPS resources on shutdown

3. **`influx_writer.py`** - Added GPS writing capability
   - `write_gps_location()` method
   - Separate `sensor_location` measurement
   - Background buffering support
   - Optional geohash support

## 📊 How It Works

```
┌─────────────────────────┐
│   gVsense Service       │
│   (web_server.py)       │
└───────────┬─────────────┘
            │
            ├─── Creates DataSaver (with InfluxWriter)
            │
            └─── Creates GPSUpdater (if enabled)
                      │
                      │ Every 60 seconds
                      ▼
                 ┌─────────────────┐
                 │   GPS Reader    │
                 │ (gps_reader.py) │
                 └────────┬────────┘
                          │ Reads coordinates
                          ▼
                    ┌──────────┐
                    │   gpsd   │
                    │ (daemon) │
                    └─────┬────┘
                          │
                          ▼
                    ┌──────────┐
                    │ GPS      │
                    │ Hardware │
                    └──────────┘

GPS coordinates written to InfluxDB:
  Measurement: sensor_location
  Fields: latitude, longitude, altitude, satellites, accuracy
  Update rate: 1/minute (configurable)
```

## 🚀 What You Need to Do Next

### On Your Server (gVSeims02)

You've already done:
- ✅ Git pulled the new code
- ✅ Restarted the service

But GPS data won't appear until you **enable it in config.conf**:

### Step 1: Edit config.conf

```bash
cd ~/gVsense
nano config.conf
```

Add this section at the end (before the final `}`):

```json
    "gps_location": {
        "enabled": true,
        "update_interval_seconds": 60,
        "method": "gpsd",
        "mock_coordinates": null
    }
```

**⚠️ Important**: Make sure to add a comma after the previous section!

### Step 2: Restart Service

```bash
sudo systemctl restart gvsense.service
```

### Step 3: Verify GPS is Working

Watch the logs:

```bash
sudo journalctl -u gvsense.service -f
```

You should see:
```
GPS location tracking enabled (update interval: 60s)
GPS updater started (interval: 60s)
```

After ~60 seconds:
```
GPS location written: lat=XX.XXXXXX, lon=XX.XXXXXX
```

### Step 4: Check InfluxDB

Query for GPS data:

```bash
influx query 'from(bucket: "accel")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> last()'
```

You should see your sensor's coordinates!

## 🔧 Configuration Options

### Option 1: Real GPS (Recommended)

```json
"gps_location": {
    "enabled": true,
    "update_interval_seconds": 60,
    "method": "gpsd",
    "mock_coordinates": null
}
```

Requires:
- GPS hardware connected
- gpsd running: `sudo systemctl status gpsd`

### Option 2: Mock GPS (Testing/No Hardware)

```json
"gps_location": {
    "enabled": true,
    "update_interval_seconds": 60,
    "method": "gpsd",
    "mock_coordinates": [13.7563, 100.5018, 45.2]
}
```

Replace with your actual coordinates: `[latitude, longitude, altitude]`

### Option 3: Faster Updates

For mobile sensors or testing:

```json
"update_interval_seconds": 30
```

## 📈 Data Storage

GPS data is stored separately from seismic data for efficiency:

### Seismic Data (unchanged)
- **Measurement**: `Test02` (or your configured measurement)
- **Rate**: ~100 Hz (8.6M points/day)
- **Tags**: sensor_id, building, sensor_type, etc.
- **Fields**: sequence, channel1, channel2, channel3

### GPS Location Data (new!)
- **Measurement**: `sensor_location`
- **Rate**: 1/minute (1,440 points/day)
- **Tags**: Same as seismic (sensor_id, building, etc.)
- **Fields**: 
  - `latitude` (float)
  - `longitude` (float)
  - `altitude` (float, optional)
  - `accuracy` (float, optional)
  - `satellites` (int, optional)
  - `geohash` (string, optional)

### Storage Overhead

- GPS: ~216 KB/day
- Seismic: ~150 MB/day
- **GPS overhead: 0.14%** - negligible! ✅

## 🔍 Querying GPS Data

### Latest GPS Location

```flux
from(bucket: "accel")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> filter(fn: (r) => r["sensor_id"] == "gVSeism01")
  |> last()
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
```

### GPS Location History

```flux
from(bucket: "accel")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> filter(fn: (r) => r["sensor_id"] == "gVSeism01")
  |> filter(fn: (r) => r["_field"] == "latitude" or r["_field"] == "longitude")
```

### Join Seismic with GPS

See `GPS_INTEGRATION.md` for detailed examples.

## 🐛 Troubleshooting

### Problem: Can't find GPS data in InfluxDB

**Check 1**: Is GPS enabled in config.conf?
```bash
grep -A 5 '"gps_location"' config.conf
```

**Check 2**: Are logs showing GPS updates?
```bash
sudo journalctl -u gvsense.service | grep -i gps
```

**Check 3**: Is InfluxDB enabled?
```bash
grep -A 2 '"influxdb"' config.conf
# Should show "enabled": true
```

### Problem: "GPS fix not available"

**Solution 1**: Check if gpsd is running
```bash
sudo systemctl status gpsd
gpspipe -w -n 10  # Should show GPS data
```

**Solution 2**: Use mock GPS for testing
Edit config.conf and set:
```json
"mock_coordinates": [13.7563, 100.5018, 45.2]
```

Replace with your actual coordinates!

### Problem: "GPS location tracking requires InfluxDB"

**Solution**: Enable InfluxDB in config.conf:
```json
"data_saving": {
    "influxdb": {
        "enabled": true,
        ...
    }
}
```

## 📚 Documentation Files

- **`GPS_SETUP_GUIDE.md`** - Quick 5-minute setup (start here!)
- **`GPS_INTEGRATION.md`** - Comprehensive documentation
- **`test_gps.py`** - Test script before deploying

## ✅ Next Steps

1. Edit config.conf to enable GPS
2. Restart service
3. Verify GPS data in logs
4. Query GPS data in InfluxDB
5. Set up Grafana dashboard for sensor locations
6. Create alerts for GPS signal loss

## 🎯 Benefits

✅ Track sensor location automatically  
✅ Historical location data when sensor moves  
✅ Minimal performance impact (0.14% overhead)  
✅ Same tags as seismic data for easy joining  
✅ Configurable update interval  
✅ Automatic fallback to cached location  
✅ Mock GPS support for testing  
✅ Optional geohash for spatial queries  

---

**Questions?** Check `GPS_SETUP_GUIDE.md` for quick troubleshooting!
