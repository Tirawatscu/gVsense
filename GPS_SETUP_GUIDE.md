# GPS Location Tracking - Setup Guide

## Quick Start (Get GPS Working in 5 Minutes!)

### Step 1: Update Your config.conf

SSH to your server and edit `config.conf`:

```bash
cd ~/gVsense
nano config.conf
```

Add this section at the end (before the closing `}`):

```json
    "gps_location": {
        "enabled": true,
        "update_interval_seconds": 60,
        "method": "gpsd",
        "mock_coordinates": null
    }
```

**Important**: Make sure the previous section ends with a comma!

### Step 2: Check if gpsd is Running

```bash
# Check gpsd status
sudo systemctl status gpsd

# If not running, start it
sudo systemctl start gpsd
sudo systemctl enable gpsd

# Test GPS is working
gpspipe -w -n 10
```

You should see JSON output with GPS data. Look for "TPV" messages with lat/lon.

### Step 3: Restart Your Service

```bash
sudo systemctl restart gvsense.service
```

### Step 4: Verify GPS Data in InfluxDB

Check logs first:

```bash
sudo journalctl -u gvsense.service -f
```

You should see:
```
GPS location tracking enabled (update interval: 60s)
GPS updater started (interval: 60s)
```

Then after 1 minute, you should see:
```
GPS location written: lat=13.756300, lon=100.501800
```

### Step 5: Query InfluxDB for GPS Data

```bash
influx query 'from(bucket: "accel")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> limit(n: 10)'
```

You should see your sensor's latitude and longitude!

## Configuration Options

### Option 1: Use Real GPS (Recommended)

```json
"gps_location": {
    "enabled": true,
    "update_interval_seconds": 60,
    "method": "gpsd",
    "mock_coordinates": null
}
```

### Option 2: Use Mock GPS (Testing)

If you don't have GPS hardware or want to test:

```json
"gps_location": {
    "enabled": true,
    "update_interval_seconds": 60,
    "method": "gpsd",
    "mock_coordinates": [13.7563, 100.5018, 45.2]
}
```

Replace with your actual coordinates: `[latitude, longitude, altitude]`

### Option 3: Different Update Intervals

For faster updates (every 30 seconds):

```json
"update_interval_seconds": 30
```

For slower updates (every 5 minutes):

```json
"update_interval_seconds": 300
```

## Troubleshooting

### Problem: "GPS location tracking requires InfluxDB to be enabled"

**Solution**: Make sure InfluxDB is enabled in your config:

```json
"data_saving": {
    "influxdb": {
        "enabled": true,
        ...
    }
}
```

### Problem: "gpspipe not found"

**Solution**: Install gpsd:

```bash
sudo apt-get update
sudo apt-get install gpsd gpsd-clients
```

### Problem: "GPS fix not available"

**Check 1**: Is GPS antenna connected?

```bash
# Check GPS device
ls -l /dev/ttyACM0  # or /dev/ttyAMA0 or /dev/ttyUSB0

# Check if GPS is getting data
cat /dev/ttyACM0    # You should see NMEA sentences
```

**Check 2**: Is gpsd configured correctly?

```bash
# Edit gpsd config
sudo nano /etc/default/gpsd

# Should have:
DEVICES="/dev/ttyACM0"  # or your GPS device
GPSD_OPTIONS="-n"
```

Then restart:

```bash
sudo systemctl restart gpsd
```

**Check 3**: Test GPS directly:

```bash
# Try cgps (visual GPS monitor)
cgps -s

# Or gpsmon
gpsmon
```

### Problem: No GPS data in InfluxDB

**Check logs**:

```bash
# Watch service logs
sudo journalctl -u gvsense.service -f

# Look for:
# - "GPS location tracking enabled"
# - "GPS updater started"
# - "GPS location written"
# - "GPS fix not available" (problem!)
```

**Test GPS manually**:

```bash
cd ~/gVsense
python3 -c "
from gps_reader import create_gps_reader
gps = create_gps_reader()
print(gps.get_location())
"
```

Should output: `{'valid': True, 'latitude': ..., 'longitude': ...}`

### Problem: Using last known GPS location

This is **normal** if GPS temporarily loses signal. The system will:
1. Try to get fresh GPS fix
2. If failed, use last known location (cached)
3. Log warning: "Using last known GPS location"

## Viewing GPS Data

### Grafana Dashboard

Create a new panel with this query:

```flux
from(bucket: "accel")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> filter(fn: (r) => r["_field"] == "latitude" or r["_field"] == "longitude")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
```

### Command Line

```bash
# Most recent location
influx query 'from(bucket: "accel")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> last()
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'

# Location history (last 24 hours)
influx query 'from(bucket: "accel")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "sensor_location")
  |> filter(fn: (r) => r["sensor_id"] == "gVSeism01")'
```

## Data Schema

GPS data is stored in a separate measurement:

**Measurement**: `sensor_location`

**Tags** (same as seismic data):
- `sensor_id`: e.g., "gVSeism01"
- `building`: e.g., "Building 1"
- `sensor_type`: e.g., "Geophone"
- etc.

**Fields**:
- `latitude` (float): Latitude in decimal degrees
- `longitude` (float): Longitude in decimal degrees
- `altitude` (float): Altitude in meters (if available)
- `accuracy` (float): GPS accuracy in meters (if available)
- `satellites` (int): Number of satellites (if available)
- `geohash` (string): Geohash for spatial queries (if pygeohash installed)

**Timestamp**: Same nanosecond precision as seismic data

## Advanced: Install Geohash Support

For spatial queries (find sensors near a location):

```bash
pip3 install pygeohash
sudo systemctl restart gvsense.service
```

The system will automatically add a `geohash` field to GPS data.

## Performance Impact

With default settings (60-second interval):
- **GPS writes**: 1,440 points/day
- **Seismic writes**: ~8.6M points/day (at 100 Hz)
- **GPS overhead**: 0.017%
- **Storage**: ~216 KB/day for GPS data

Negligible performance impact! ✅

## Next Steps

1. ✅ Configure GPS in config.conf
2. ✅ Restart service
3. ✅ Verify GPS data in logs
4. ✅ Query GPS data in InfluxDB
5. Set up Grafana dashboard to visualize sensor locations
6. Create alerts for GPS signal loss
7. Join GPS with seismic data for location-aware analysis

## Need Help?

Check the detailed documentation in `GPS_INTEGRATION.md`
