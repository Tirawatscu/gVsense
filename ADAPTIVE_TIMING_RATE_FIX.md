# Adaptive Timing Controller - Variable Rate Support

## Problem
The adaptive timing controller was hardcoded to 100Hz, which would cause incorrect timing corrections if the system was configured to run at different sampling rates (1-1000 Hz).

## Solution
Updated the adaptive timing controller to automatically detect and use the actual configured sampling rate.

## Changes Made

### 1. `adaptive_timing_controller.py`

#### Auto-Detection of Sampling Rate
- Added optional `target_rate` parameter to `__init__()`
- Automatically detects rate from seismic device if not provided
- Falls back to 100Hz if detection fails
- Validates rate is within 1-1000 Hz range

```python
# Now accepts optional target_rate parameter
adaptive_controller = AdaptiveTimingController(
    seismic, 
    timing_manager,
    target_rate=200.0  # Optional: specify rate
)
```

#### Dynamic Rate Updates
- Added `update_target_rate()` method to change rate during operation
- Automatically recalculates timing intervals
- Applies new rate to MCU if controller is running
- Notifies unified timing controller

```python
# Change rate dynamically
adaptive_controller.update_target_rate(250.0)
```

#### Improved Logging
- Shows actual rate in initialization: `"📊 Adaptive controller initialized: 200.00 Hz (5000 µs)"`
- Displays correct rate in reset messages
- Logs rate changes with old → new values

### 2. `web_server.py`

#### Controller Initialization
Updated all 3 locations where the controller is created to pass the configured rate:

```python
adaptive_controller = CompatibilityAdaptiveTimingController(
    seismic, 
    seismic.timing_manager, 
    target_rate=config.get('stream_rate', 100.0)
)
```

#### Configuration Changes
When `stream_rate` is updated via API, the adaptive controller's target rate is automatically updated:

```python
if 'stream_rate' in new_config:
    config['stream_rate'] = new_config['stream_rate']
    if adaptive_controller:
        adaptive_controller.update_target_rate(new_config['stream_rate'])
```

## Benefits

### For GPS/PPS Operation (Current Setup)
- No functional change - adaptive controller remains dormant
- Correct rate is logged during initialization
- System ready for GPS/PPS loss scenarios

### For Non-GPS Operation (Future Scenarios)
- **Prevents incorrect corrections** at non-100Hz rates
- Works correctly from 1 Hz to 1000 Hz
- Automatically adapts to configuration changes

## Example Scenarios

### Scenario 1: 200 Hz Operation Without GPS
**Before Fix:**
- Controller expects 10,000µs (100Hz)
- MCU running at 5,000µs (200Hz)
- Controller sees 100% "drift" → incorrect corrections

**After Fix:**
- Controller expects 5,000µs (200Hz)
- MCU running at 5,000µs (200Hz)
- Correctly detects actual drift → proper corrections

### Scenario 2: 50 Hz Operation Without GPS
**Before Fix:**
- Controller expects 10,000µs (100Hz)
- MCU running at 20,000µs (50Hz)
- Controller sees -50% "drift" → incorrect corrections

**After Fix:**
- Controller expects 20,000µs (50Hz)
- MCU running at 20,000µs (50Hz)
- Correctly detects actual drift → proper corrections

### Scenario 3: Rate Change During Operation
**Before Fix:**
- Rate changes from 100Hz → 200Hz
- Controller still expects 100Hz
- Timing corrections become incorrect

**After Fix:**
- Rate changes from 100Hz → 200Hz
- Controller automatically updates to 200Hz
- Timing corrections remain accurate

## Testing Recommendations

### Test 1: Verify Auto-Detection
1. Set `stream_rate` to different values in config.conf (50, 100, 200, 500)
2. Start the system and check initialization logs
3. Should see: `"📊 Adaptive controller initialized: X.XX Hz (YYYY µs)"`

### Test 2: Verify Dynamic Updates
1. Start system with one rate (e.g., 100Hz)
2. Change `stream_rate` via web UI
3. Check logs for: `"Updated adaptive controller rate: 100.0 Hz → 200.0 Hz"`

### Test 3: Non-GPS Operation (When GPS Available)
1. Configure system to run at 200Hz
2. Check adaptive controller stats show correct target rate
3. If GPS fails, controller should maintain 200Hz baseline

### Test 4: Non-GPS Operation (Simulated)
1. Disable GPS/PPS in config
2. Set `stream_rate` to 200Hz
3. Start streaming
4. Verify adaptive controller activates with correct 200Hz target
5. Check timing quality metrics

## Backward Compatibility

- Default behavior unchanged (100Hz if not specified)
- Existing code continues to work
- Auto-detection provides seamless upgrade path
- No configuration file changes required

## API Impact

### New Optional Parameter
```python
__init__(self, seismic_acquisition, timing_manager, target_rate=None)
```

### New Method
```python
update_target_rate(self, new_rate) -> bool
```

### Updated Statistics
The `get_stats()` method now shows correct rates:
- `target_sampling_rate_hz`: Reflects actual configured rate
- `current_sampling_rate_hz`: Reflects actual MCU rate

## Files Modified

1. `/adaptive_timing_controller.py`
   - Added rate detection logic
   - Added dynamic rate update method
   - Improved logging

2. `/web_server.py`
   - Pass rate to controller during creation (3 locations)
   - Update controller rate when config changes

## Summary

The adaptive timing controller now correctly handles variable sampling rates from 1-1000 Hz, ensuring accurate timing corrections regardless of the configured rate. This fix prevents incorrect timing adjustments in non-GPS scenarios and provides a robust fallback timing system for any sampling rate configuration.
