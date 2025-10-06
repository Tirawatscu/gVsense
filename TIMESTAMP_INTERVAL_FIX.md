# Timestamp Interval Fix

## 🔍 Problem

gVs002 was showing **20ms intervals** in InfluxDB even though sampling rate was set to **100Hz** (which should be 10ms intervals).

## 📊 Root Cause

The timestamp generator's `expected_rate` was not being updated properly, causing it to use the wrong interval for timestamp calculation.

**What was happening:**
1. MCU correctly sends samples at 100Hz (every 10ms)
2. Timestamp generator thinks rate is 50Hz (uses 20ms interval)
3. Each sequence number increment → +20ms timestamp instead of +10ms
4. Result: InfluxDB shows 20ms intervals instead of 10ms

## ✅ The Fix

Added explicit rate synchronization in `web_server.py` at stream start:

```python
# CRITICAL: Update timestamp generator rate to match streaming rate
if hasattr(seismic, 'timing_adapter') and hasattr(seismic.timing_adapter, 'timestamp_generator'):
    try:
        actual_rate = config.get('stream_rate', 100.0)
        seismic.timing_adapter.timestamp_generator.update_rate(actual_rate)
        print(f"✅ Timestamp generator rate set to {actual_rate}Hz (interval: {1000/actual_rate}ms)")
    except Exception as e:
        print(f"⚠️  Warning: Could not update timestamp generator rate: {e}")
```

**Location**: Line 1445-1452 in `web_server.py`

## 🚀 How to Verify

After restarting:

1. **Check console output** when starting stream:
   ```
   ✅ Timestamp generator rate set to 100.0Hz (interval: 10.0ms)
   ```

2. **Check InfluxDB intervals**:
   - Should show: **10ms** intervals (not 20ms)
   - Sample timestamps: 1000, 1010, 1020, 1030... (for 100Hz)

3. **Verify in Python console** (optional):
   ```python
   # Check rate
   seismic.timing_adapter.timestamp_generator.expected_rate
   # Should show: 100.0
   
   # Check interval
   seismic.timing_adapter.timestamp_generator.expected_interval_s
   # Should show: 0.01 (10ms)
   ```

## 📈 Expected Results

### Before Fix
- Configured: 100Hz
- InfluxDB intervals: **20ms** ❌
- Implied rate: 50Hz (wrong!)

### After Fix
- Configured: 100Hz  
- InfluxDB intervals: **10ms** ✅
- Actual rate: 100Hz (correct!)

## 🔬 Technical Details

The timestamp generator uses:
```python
timestamp = reference_time + (sequence_diff * expected_interval_s)
```

Where:
- `expected_interval_s = 1.0 / expected_rate`

If `expected_rate` is wrong, all timestamps are wrong!

Example with wrong rate:
- expected_rate = 50Hz (wrong)
- expected_interval_s = 0.02s = 20ms
- sequence 0 → timestamp 0ms
- sequence 1 → timestamp 20ms ❌ (should be 10ms)
- sequence 2 → timestamp 40ms ❌ (should be 20ms)

With correct rate:
- expected_rate = 100Hz (correct)
- expected_interval_s = 0.01s = 10ms
- sequence 0 → timestamp 0ms
- sequence 1 → timestamp 10ms ✅
- sequence 2 → timestamp 20ms ✅

## 💡 Summary

**Problem**: Timestamp generator using wrong rate → wrong intervals
**Fix**: Explicitly set rate when starting stream
**Result**: Correct 10ms intervals at 100Hz

The fix is already applied in `web_server.py`. Just restart your application and verify the intervals are correct!

---

*Fix Applied*: October 6, 2025  
*Status*: ✅ Ready for Testing

