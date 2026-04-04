#!/bin/bash
# Quick Start Script for ICICI Bank Voice AI
# Connects FreeSWITCH to RunPod PersonaPlex instance

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}ICICI Bank Voice AI - Quick Start${NC}"
echo -e "${GREEN}========================================${NC}"
echo

# Check if running in correct directory
if [ ! -f "bridge_relay.py" ]; then
    echo -e "${RED}Error: bridge_relay.py not found${NC}"
    echo -e "${YELLOW}Please run this script from the project root directory${NC}"
    exit 1
fi

# Step 1: Copy ICICI Bank configuration
echo -e "${GREEN}Step 1: Setting up configuration...${NC}"
if [ -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env already exists${NC}"
    read -p "Overwrite with ICICI Bank config? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp .env.icici_bank .env
        echo -e "${GREEN}✓ Configuration updated${NC}"
    else
        echo -e "${YELLOW}Keeping existing .env${NC}"
    fi
else
    cp .env.icici_bank .env
    echo -e "${GREEN}✓ Configuration created${NC}"
fi

# Step 2: Get RunPod URL
echo
echo -e "${GREEN}Step 2: Configure RunPod endpoint...${NC}"
echo -e "${YELLOW}Current URL in .env:${NC}"
grep "PERSONAPLEX_URL=" .env | cut -d'=' -f2

echo
read -p "Do you want to update the RunPod URL? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Enter your RunPod endpoint URL:${NC}"
    echo -e "${YELLOW}Format: wss://[POD_ID]-8998.proxy.runpod.net/api/chat${NC}"
    read -p "URL: " runpod_url
    
    # Update .env file
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|PERSONAPLEX_URL=.*|PERSONAPLEX_URL=$runpod_url|" .env
    else
        # Linux
        sed -i "s|PERSONAPLEX_URL=.*|PERSONAPLEX_URL=$runpod_url|" .env
    fi
    echo -e "${GREEN}✓ RunPod URL updated${NC}"
fi

# Step 3: Check Python dependencies
echo
echo -e "${GREEN}Step 3: Checking Python dependencies...${NC}"
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q --upgrade pip
pip install -q websockets opuslib numpy edge-tts aiohttp

echo -e "${GREEN}✓ Dependencies installed${NC}"

# Step 4: Test configuration
echo
echo -e "${GREEN}Step 4: Testing configuration...${NC}"
echo -e "${YELLOW}Configuration summary:${NC}"
echo "  Bridge Port: $(grep BRIDGE_PORT .env | cut -d'=' -f2)"
echo "  PersonaPlex: $(grep PERSONAPLEX_URL .env | cut -d'=' -f2)"
echo "  Voice: $(grep VOICE_PROMPT .env | cut -d'=' -f2)"
echo "  Agent: Priya Sharma (ICICI Bank)"

# Step 5: Start bridge
echo
echo -e "${GREEN}Step 5: Starting bridge relay...${NC}"
read -p "Start bridge_relay.py now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Starting bridge relay...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo
    python3 bridge_relay.py
else
    echo
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Setup Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    echo -e "${YELLOW}To start the bridge manually:${NC}"
    echo -e "  source venv/bin/activate"
    echo -e "  python3 bridge_relay.py"
    echo
    echo -e "${YELLOW}To install as systemd service:${NC}"
    echo -e "  cd systemd"
    echo -e "  sudo bash install.sh"
    echo
    echo -e "${YELLOW}To configure FreeSWITCH:${NC}"
    echo -e "  sudo cp freeswitch/icici_bank_dialplan.xml \\"
    echo -e "      /usr/local/freeswitch/conf/dialplan/default/"
    echo -e "  fs_cli -x 'reloadxml'"
    echo
    echo -e "${YELLOW}Test by calling extension: 1800${NC}"
    echo
fi
