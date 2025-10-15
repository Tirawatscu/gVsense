#!/bin/bash
# PPS GPIO Setup Script for Raspberry Pi
# This script configures PPS signal on GPIO pin 18 and sets up chrony for UTC discipline

set -e

echo "🔧 Setting up PPS GPIO and chrony configuration..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

# Check if we're on a Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "⚠️  Warning: This script is designed for Raspberry Pi"
fi

# 1. Enable PPS GPIO driver
echo "📡 Enabling PPS GPIO driver..."
if ! grep -q "pps-gpio" /boot/config.txt; then
    echo "dtoverlay=pps-gpio,gpiopin=18" >> /boot/config.txt
    echo "✅ Added PPS GPIO overlay to /boot/config.txt"
else
    echo "✅ PPS GPIO overlay already configured"
fi

# 2. Install chrony if not present
echo "⏰ Installing chrony..."
if ! command -v chrony &> /dev/null; then
    apt-get update
    apt-get install -y chrony
    echo "✅ Chrony installed"
else
    echo "✅ Chrony already installed"
fi

# 3. Configure chrony for PPS
echo "🔧 Configuring chrony for PPS..."
cat > /etc/chrony/chrony.conf << 'EOF'
# Chrony configuration for PPS synchronization
# Use local hardware clock as reference
refclock SHM 0 refid PPS precision 1e-9 offset 0.001 delay 0.000
refclock PPS /dev/pps0 refid GPS precision 1e-9 lock NMEA

# Allow chronyd to step the system clock if the offset is larger than 1 second
makestep 1.0 3

# Enable kernel synchronization
rtcsync

# Log directory
logdir /var/log/chrony

# Save drift between restarts
driftfile /var/lib/chrony/drift

# Local stratum 10 server (not synchronized)
local stratum 10

# Allow clients from local network
allow 192.168.0.0/16
allow 10.0.0.0/8
allow 172.16.0.0/12

# Serve time even if not synchronized
local
EOF

echo "✅ Chrony configured for PPS"

# 4. Create udev rule for PPS device
echo "🔌 Creating udev rule for PPS device..."
cat > /etc/udev/rules.d/99-pps.rules << 'EOF'
# PPS device rule
KERNEL=="pps[0-9]*", GROUP="dialout", MODE="0664"
EOF

echo "✅ PPS udev rule created"

# 5. Add user to dialout group for PPS access
echo "👤 Adding user to dialout group..."
if [ -n "$SUDO_USER" ]; then
    usermod -a -G dialout "$SUDO_USER"
    echo "✅ Added $SUDO_USER to dialout group"
else
    echo "⚠️  Could not determine user to add to dialout group"
fi

# 6. Enable and start chrony service
echo "🚀 Starting chrony service..."
systemctl enable chrony
systemctl restart chrony
echo "✅ Chrony service started"

# 7. Reload udev rules
echo "🔄 Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger
echo "✅ Udev rules reloaded"

# 8. Check PPS device
echo "🔍 Checking PPS device..."
sleep 2
if [ -e /dev/pps0 ]; then
    echo "✅ PPS device /dev/pps0 found"
    ls -la /dev/pps0
else
    echo "⚠️  PPS device /dev/pps0 not found - may need reboot"
fi

# 9. Check chrony status
echo "📊 Checking chrony status..."
chronyc sources -v
chronyc tracking

echo ""
echo "🎉 PPS GPIO setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Reboot the system to activate PPS GPIO overlay"
echo "2. Connect PPS signal to GPIO pin 18"
echo "3. Check PPS device: ls -la /dev/pps*"
echo "4. Monitor chrony: chronyc sources -v"
echo "5. Check PPS status: chronyc sources | grep PPS"
echo ""
echo "🔧 Manual commands:"
echo "  - Check PPS: cat /dev/pps0"
echo "  - Monitor chrony: chronyc tracking"
echo "  - Check sources: chronyc sources -v"
echo ""
