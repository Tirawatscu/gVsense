#!/bin/bash
"""
Installation script for gVsense Pi-side calibration management
"""

set -e

# Configuration
INSTALL_DIR="/opt/gvsense"
SERVICE_USER="gvsense"
SERVICE_GROUP="gvsense"
CALIBRATION_DIR="/var/lib/gvsense"

echo "Installing gVsense Pi-side calibration management..."

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

# Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "Creating service user: $SERVICE_USER"
    useradd --system --shell /bin/false --home-dir /var/lib/gvsense --create-home "$SERVICE_USER"
fi

# Create installation directory
echo "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Copy files
echo "Copying files..."
cp calibration_storage.py "$INSTALL_DIR/"
cp host_timing_acquisition.py "$INSTALL_DIR/"
cp timing_fix.py "$INSTALL_DIR/"
cp web_server.py "$INSTALL_DIR/"
cp gvsense-cal "$INSTALL_DIR/"

# Make CLI executable
chmod +x "$INSTALL_DIR/gvsense-cal"

# Create symlink for CLI
ln -sf "$INSTALL_DIR/gvsense-cal" /usr/local/bin/gvsense-cal

# Create calibration directory
echo "Creating calibration directory: $CALIBRATION_DIR"
mkdir -p "$CALIBRATION_DIR"
chown "$SERVICE_USER:$SERVICE_GROUP" "$CALIBRATION_DIR"
chmod 755 "$CALIBRATION_DIR"

# Install systemd service
echo "Installing systemd service..."
cp gvsense-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable gvsense-agent.service

# Install udev rules
echo "Installing udev rules..."
cp 99-gvsense.rules /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger

# Set permissions
echo "Setting permissions..."
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"

# Create log directory
mkdir -p /var/log/gvsense
chown "$SERVICE_USER:$SERVICE_GROUP" /var/log/gvsense

echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Connect your gVsense device"
echo "2. Check device naming: ls -la /dev/gsense-*"
echo "3. Start the service: systemctl start gvsense-agent.service"
echo "4. Check status: systemctl status gvsense-agent.service"
echo "5. View logs: journalctl -u gvsense-agent.service -f"
echo ""
echo "CLI usage:"
echo "  gvsense-cal list                    # List devices with calibration"
echo "  gvsense-cal read XIAO-1234          # Read calibration for device"
echo "  gvsense-cal set XIAO-1234 --ppm 12.34 --note 'Manual calibration'"
echo "  gvsense-cal clear XIAO-1234         # Clear calibration"
