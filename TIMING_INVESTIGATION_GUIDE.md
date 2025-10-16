# GPS-MCU Timing Offset Investigation & Optimization Guide

**Date:** October 16, 2025  
**System:** gVsense Seismic Acquisition with GPS/PPS Timing  
**Goal:** Verify timing performance and identify optimization opportunities

## Current System Status

### ✅ Completed Fixes
1. **Sequence Wraparound** - Fixed 30ms timestamp jump at 65535→0 transition
2. **Adaptive Controller** - Auto-enables when GPS/PPS unavailable
3. **Workspace Cleanup** - Removed 44 unnecessary files (77% reduction)
4. **Firmware Updates** - Latest timing improvements deployed

## Investigation Checklist

### Phase 1: Baseline Performance Assessment (0-30 minutes)

**Run the monitoring script:**
```bash
cd /home/tsk/gVsense
python3 monitor_timing_performance.py --interval 5
```

**What to observe:**
- [ ] GPS-MCU offset (target: <1ms average, <5ms max)
- [ ] Offset variance (std deviation <0.5ms ideal)
- [ ] PPS lock status (should be stable/valid)
- [ ] Timing accuracy (target: ±1-6μs with PPS)
- [ ] Calibration PPM (typically -200 to -300 ppm)
- [ ] Systematic drift patterns

**Performance Grades:**
- **A+ (Excellent):** Max offset <1ms, std dev <0.5ms
- **A (Good):** Max offset <5ms, std dev <2ms  
- **B (Acceptable):** Max offset <10ms, std dev <5ms
- **C (Needs Attention):** Above thresholds

### Phase 2: GPS/PPS Signal Quality (30-60 minutes)

**Check PPS stability:**
```bash
# Monitor PPS signal
sudo ppstest /dev/pps0

# Check chrony tracking
watch -n 1 'chronyc tracking'

# GPS signal strength (if available)
cgps -s  # or appropriate GPS monitoring tool
```

**What to check:**
- [ ] PPS jitter (<10μs ideal)
- [ ] GPS signal strength (>4 satellites, good SNR)
- [ ] Chrony system time offset (<100μs ideal)
- [ ] Frequency error stability

**Optimization if needed:**
- Move GPS antenna for better sky view
- Check GPS antenna connections
- Verify chrony configuration (`/etc/chrony/chrony.conf`)

### Phase 3: MCU Calibration Accuracy (1-2 hours)

**Monitor calibration stability:**
```bash
# Watch MCU calibration in real-time
curl -s http://localhost:5001/api/device/status | jq '{
  timing_source,
  pps_valid,
  calibration_ppm,
  calibration_source,
  timing_accuracy_us
}'

# Check calibration history
journalctl -u gvsense.service -f | grep -i "calibration\|ppm"
```

**What to observe:**
- [ ] Calibration PPM convergence (should stabilize)
- [ ] Temperature-induced drift (<50 ppm variation)
- [ ] Calibration source (should be PPS_LIVE with GPS)

**Optimization opportunities:**
- If PPM varies >50: Consider temperature compensation
- If calibration unstable: Check PPS lock stability
- If systematic offset: Manual calibration adjustment

### Phase 4: Sequence Wraparound Verification (wait ~11 minutes)

**Monitor next wraparound:**
```bash
# Watch for sequence approaching wraparound
watch -n 1 'curl -s http://localhost:5001/api/device/status | jq .sequence'

# When sequence > 65530, monitor logs
journalctl -u gvsense.service -f | grep -i "wraparound\|65535"
```

**Check InfluxDB for clean transition:**
```flux
from(bucket: "accel")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "Test02")
  |> filter(fn: (r) => r._field == "sequence")
  |> filter(fn: (r) => r.sequence >= 65533 or r.sequence <= 3)
  |> sort(columns: ["_time"])
```

**Expected result:**
- [ ] Timestamps increment by exactly 10ms (100Hz)
- [ ] No time jump at 65535→0 transition
- [ ] Continuous sequence: ...65533, 65534, 65535, 0, 1, 2, 3...

### Phase 5: Long-term Drift Analysis (24 hours recommended)

**Set up continuous monitoring:**
```bash
# Run overnight monitoring (logs to file)
nohup python3 monitor_timing_performance.py --interval 10 > timing_monitor.log 2>&1 &

# Check progress
tail -f timing_monitor.log

# Analyze results next day
cat timing_monitor.log | grep "STATISTICAL ANALYSIS" -A 10
```

**What to analyze:**
- [ ] Diurnal temperature drift patterns
- [ ] Long-term offset trends
- [ ] GPS signal availability (day vs night)
- [ ] System load impact on timing

## Optimization Recommendations

### Level 1: Basic (Current Configuration)
✅ Already implemented:
- PPS-based timing synchronization
- Adaptive controller for GPS-less operation
- MCU oscillator calibration
- Sequence wraparound fixes

### Level 2: Fine-tuning (If needed)

**If offset >5ms consistently:**
```python
# Adjust MCU timestamp offset manually
# Via web UI or API:
curl -X POST http://localhost:5001/api/timing/adjust_mcu_offset \
  -H "Content-Type: application/json" \
  -d '{"adjustment_us": -5000}'  # Adjust as needed
```

**If PPM drift >50:**
- Check ambient temperature stability
- Verify GPS antenna placement
- Consider adding temperature sensor for compensation

**If PPS jitter >10μs:**
- Verify GPIO electrical connections
- Check for EMI/RFI interference
- Optimize chrony configuration

### Level 3: Advanced (Future)

**For sub-millisecond accuracy:**
1. Implement temperature compensation algorithm
2. Add phase servo fine-tuning
3. Optimize PPS GPIO interrupt latency
4. Hardware timestamp buffering in MCU

**For GPS-less operation:**
1. Implement persistent calibration storage (already coded)
2. Add TCXO or OCXO for better stability
3. Network time sync fallback (NTP)

## Key Performance Indicators (KPIs)

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| GPS-MCU Offset (avg) | <1ms | TBD | 🔍 |
| Offset Std Deviation | <0.5ms | TBD | 🔍 |
| Timing Accuracy | ±1-6μs | TBD | 🔍 |
| PPS Lock Uptime | >99% | TBD | 🔍 |
| Sequence Continuity | 100% | ✅ Fixed | ✅ |
| Calibration Stability | ±50ppm | TBD | 🔍 |

## Investigation Timeline

**Immediate (0-1 hour):**
- Run monitoring script
- Check baseline performance
- Verify PPS lock stable

**Short-term (1-4 hours):**
- Monitor calibration convergence
- Verify wraparound fix in production
- Check for any systematic offsets

**Long-term (24-48 hours):**
- Analyze drift patterns
- Temperature sensitivity test
- Long-term stability assessment

## Expected Outcomes

### Excellent Performance (Grade A+)
- Offset: <1ms average, <0.5ms std dev
- No action needed, system optimal

### Good Performance (Grade A)
- Offset: 1-5ms average, <2ms std dev
- Minor fine-tuning possible but not critical

### Acceptable Performance (Grade B)
- Offset: 5-10ms average, <5ms std dev
- Consider optimizations from Level 2

### Needs Attention (Grade C)
- Offset: >10ms or high variance
- Investigate GPS signal, PPS stability, calibration
- Apply Level 2-3 optimizations

## Monitoring Commands Summary

```bash
# Real-time performance monitoring
python3 monitor_timing_performance.py --interval 5

# PPS signal test
sudo ppstest /dev/pps0

# Chrony tracking
watch -n 1 'chronyc tracking'

# Device status
watch -n 1 'curl -s http://localhost:5001/api/device/status | jq'

# GPS alignment
curl -s http://localhost:5001/api/timing/gps_alignment | jq

# Service logs
journalctl -u gvsense.service -f

# Test GPS/PPS disable
sudo ./test_no_gps.sh disable
sudo ./test_no_gps.sh enable
```

## Next Steps

1. **Start monitoring:** Run `python3 monitor_timing_performance.py`
2. **Collect baseline:** Let it run for 30-60 minutes
3. **Analyze results:** Review performance grade and recommendations
4. **Apply optimizations:** If needed based on analysis
5. **Long-term monitoring:** Run overnight for comprehensive assessment
6. **Report findings:** Document performance KPIs and any issues

---
**Status:** Ready for investigation  
**Action:** Start monitoring script to collect baseline data
