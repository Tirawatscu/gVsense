#!/bin/bash
# Test script for disabling PPS/GPS temporarily
# Usage: sudo ./test_no_gps.sh [disable|enable|status]

set -e

case "$1" in
    disable)
        echo "🔴 DISABLING PPS/GPS for testing..."
        echo ""
        
        # Show current state
        echo "📊 BEFORE:"
        echo -n "  PPS device: "
        ls /dev/pps* 2>/dev/null || echo "Not found"
        echo -n "  Chrony: "
        systemctl is-active chrony 2>/dev/null || echo "inactive"
        echo ""
        
        # Disable PPS kernel module
        echo "⏸️  Removing PPS kernel modules..."
        rmmod pps_gpio 2>/dev/null || echo "  (pps_gpio already removed)"
        rmmod pps_core 2>/dev/null || echo "  (pps_core already removed)"
        
        # Stop chrony
        echo "⏸️  Stopping chrony..."
        systemctl stop chrony
        
        # Verify
        echo ""
        echo "📊 AFTER:"
        echo -n "  PPS device: "
        ls /dev/pps* 2>/dev/null || echo "Not found ✅"
        echo -n "  Chrony: "
        systemctl is-active chrony 2>/dev/null || echo "inactive ✅"
        
        echo ""
        echo "✅ PPS/GPS disabled. Testing no-GPS mode..."
        echo ""
        
        # Wait for gVsense to detect change
        sleep 2
        
        # Check gVsense timing status
        echo "📡 gVsense timing status:"
        if command -v curl &> /dev/null; then
            curl -s http://localhost:5001/api/device/status 2>/dev/null | \
                jq -r '"  timing_source: " + (.timing_source // "unknown") + 
                       "\n  pps_valid: " + (.pps_valid | tostring) + 
                       "\n  timing_accuracy_us: " + (.timing_accuracy_us | tostring) + 
                       "\n  calibration_source: " + (.calibration_source // "unknown")' || \
                echo "  (Could not query gVsense API)"
        else
            echo "  (curl not available)"
        fi
        
        echo ""
        echo "🧪 System now running in no-GPS mode"
        echo "   Adaptive controller should be ENABLED"
        echo "   To re-enable: sudo ./test_no_gps.sh enable"
        ;;
        
    enable)
        echo "🟢 RE-ENABLING PPS/GPS..."
        echo ""
        
        # Re-load PPS kernel module
        echo "▶️  Loading PPS kernel modules..."
        modprobe pps_core
        modprobe pps_gpio
        
        # Restart chrony
        echo "▶️  Starting chrony..."
        systemctl start chrony
        
        # Wait for initialization
        sleep 2
        
        # Verify
        echo ""
        echo "📊 STATUS:"
        echo -n "  PPS device: "
        ls -la /dev/pps* 2>/dev/null || echo "Not found ❌"
        echo -n "  Chrony: "
        systemctl is-active chrony 2>/dev/null || echo "inactive ❌"
        
        echo ""
        echo "✅ PPS/GPS re-enabled"
        echo "   Wait ~30 seconds for PPS lock to stabilize"
        echo "   gVsense will switch to PPS_ACTIVE mode"
        ;;
        
    status)
        echo "📊 CURRENT PPS/GPS STATUS"
        echo ""
        
        echo "Hardware:"
        echo -n "  PPS device: "
        if ls /dev/pps* &>/dev/null; then
            ls -la /dev/pps* | awk '{print $NF " ✅"}'
        else
            echo "Not found ❌ (disabled)"
        fi
        
        echo -n "  Chrony: "
        if systemctl is-active chrony &>/dev/null; then
            echo "active ✅"
        else
            echo "inactive ❌ (disabled)"
        fi
        
        echo ""
        echo "Kernel modules:"
        echo -n "  pps_core: "
        lsmod | grep -q pps_core && echo "loaded ✅" || echo "not loaded ❌"
        echo -n "  pps_gpio: "
        lsmod | grep -q pps_gpio && echo "loaded ✅" || echo "not loaded ❌"
        
        echo ""
        echo "gVsense timing:"
        if command -v curl &> /dev/null && systemctl is-active gvsense.service &>/dev/null; then
            curl -s http://localhost:5001/api/device/status 2>/dev/null | \
                jq -r '"  timing_source: " + (.timing_source // "unknown") + 
                       "\n  pps_valid: " + (.pps_valid | tostring) + 
                       "\n  timing_accuracy_us: " + (.timing_accuracy_us | tostring) + 
                       "\n  calibration_ppm: " + (.calibration_ppm | tostring) + 
                       "\n  calibration_source: " + (.calibration_source // "unknown")' || \
                echo "  (Could not query gVsense API)"
        else
            echo "  (gVsense service not running)"
        fi
        ;;
        
    *)
        echo "Usage: sudo $0 [disable|enable|status]"
        echo ""
        echo "Commands:"
        echo "  disable  - Temporarily disable PPS/GPS for testing"
        echo "  enable   - Re-enable PPS/GPS"
        echo "  status   - Show current PPS/GPS status"
        echo ""
        echo "Examples:"
        echo "  sudo $0 disable    # Test no-GPS mode"
        echo "  sudo $0 status     # Check current state"
        echo "  sudo $0 enable     # Restore PPS/GPS"
        exit 1
        ;;
esac
