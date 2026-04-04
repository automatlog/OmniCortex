#!/bin/bash
# Installation script for bridge-relay systemd service

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/bridge-relay"
SERVICE_NAME="bridge-relay"
SERVICE_FILE="bridge-relay.service"
USER="freeswitch"
GROUP="freeswitch"

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Bridge Relay Installation Script${NC}"
echo -e "${GREEN}================================${NC}"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: Please run as root (sudo)${NC}"
    exit 1
fi

# Check if freeswitch user exists
if ! id "$USER" &>/dev/null; then
    echo -e "${YELLOW}Warning: User '$USER' does not exist${NC}"
    echo -e "${YELLOW}Creating user...${NC}"
    useradd -r -s /bin/false $USER
fi

# Create installation directory
echo -e "${GREEN}Creating installation directory...${NC}"
mkdir -p $INSTALL_DIR
mkdir -p $INSTALL_DIR/venv
mkdir -p /tmp/bridge_tts

# Copy files
echo -e "${GREEN}Copying files...${NC}"
if [ -f "../bridge_relay.py" ]; then
    cp ../bridge_relay.py $INSTALL_DIR/
else
    echo -e "${RED}Error: bridge_relay.py not found${NC}"
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo -e "${GREEN}Creating .env file...${NC}"
    cat > $INSTALL_DIR/.env << 'EOF'
# Server settings
BRIDGE_PORT=8001

# PersonaPlex connection
PERSONAPLEX_URL=ws://localhost:8998/api/chat
PERSONAPLEX_API_KEY=

# Agent configuration
AGENT_ID=
BEARER_TOKEN=
VOICE_PROMPT=NATF0.pt
TEXT_PROMPT=You are a helpful assistant.

# TTS settings
TTS_ENABLED=true
TTS_DIR=/tmp/bridge_tts
FS_CLI=/usr/local/freeswitch/bin/fs_cli

# Barge-in settings
BARGE_IN_ENABLED=false
BARGE_IN_RMS_THRESHOLD=0.012
BARGE_IN_MIN_AUDIO_SEC=0.8
BARGE_IN_MAX_AUDIO_SEC=2.5

# Debug
DEBUG=false
EOF
    echo -e "${YELLOW}Please edit $INSTALL_DIR/.env with your configuration${NC}"
fi

# Set up Python virtual environment
echo -e "${GREEN}Setting up Python virtual environment...${NC}"
python3 -m venv $INSTALL_DIR/venv

# Install dependencies
echo -e "${GREEN}Installing Python dependencies...${NC}"
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install \
    websockets \
    opuslib \
    numpy \
    edge-tts \
    aiohttp

# Set permissions
echo -e "${GREEN}Setting permissions...${NC}"
chown -R $USER:$GROUP $INSTALL_DIR
chown -R $USER:$GROUP /tmp/bridge_tts
chmod 755 $INSTALL_DIR
chmod 644 $INSTALL_DIR/bridge_relay.py
chmod 600 $INSTALL_DIR/.env

# Install systemd service
echo -e "${GREEN}Installing systemd service...${NC}"
cp $SERVICE_FILE /etc/systemd/system/

# Reload systemd
echo -e "${GREEN}Reloading systemd...${NC}"
systemctl daemon-reload

# Enable service
echo -e "${GREEN}Enabling service...${NC}"
systemctl enable $SERVICE_NAME

echo
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo
echo -e "${YELLOW}Next steps:${NC}"
echo -e "1. Edit configuration: ${GREEN}sudo nano $INSTALL_DIR/.env${NC}"
echo -e "2. Start service: ${GREEN}sudo systemctl start $SERVICE_NAME${NC}"
echo -e "3. Check status: ${GREEN}sudo systemctl status $SERVICE_NAME${NC}"
echo -e "4. View logs: ${GREEN}sudo journalctl -u $SERVICE_NAME -f${NC}"
echo
echo -e "${YELLOW}Configuration file location:${NC} $INSTALL_DIR/.env"
echo -e "${YELLOW}Service name:${NC} $SERVICE_NAME"
echo -e "${YELLOW}Installation directory:${NC} $INSTALL_DIR"
echo
