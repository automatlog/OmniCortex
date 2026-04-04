#!/bin/bash
# start_bridge_stack.sh
# Starts the complete bridge stack (bridge_in, brain_orchestrator, bridge_out)
# on the same server as FreeSWITCH

set -e

# Configuration
PERSONAPLEX_WS="wss://lhoac81oebncui-8998.proxy.runpod.net/api/chat"
VOICE_PROMPT="NATF0.pt"
TEXT_PROMPT="You work for ICICI Bank and your name is Priya Sharma. You are a helpful and professional customer service representative specializing in personal accounts and loan products. You are currently assisting a customer who holds a personal savings account with a current balance of Rs 50,000. Your role is to help the customer with account balance, recent transactions, and loan products including personal loans, home loans, car loans, and education loans. Mention that ICICI Bank offers competitive personal loan rates starting from 10.5% per annum with flexible EMI options and instant approval for eligible customers. Always verify the customer's identity using registered mobile number and date of birth before sharing account details."

# Ports
ORCH_PORT=8101
BRIDGE_IN_PORT=8001
BRIDGE_OUT_PORT=8002

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
PID_DIR="${SCRIPT_DIR}/pids"

# Create directories
mkdir -p "$LOG_DIR" "$PID_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if process is running
is_running() {
    local pid_file="$1"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Stop all components
stop_all() {
    log_info "Stopping all bridge components..."
    
    for component in brain_orchestrator bridge_in bridge_out; do
        local pid_file="$PID_DIR/${component}.pid"
        if is_running "$pid_file"; then
            local pid=$(cat "$pid_file")
            log_info "Stopping $component (PID: $pid)"
            kill "$pid" 2>/dev/null || true
            sleep 1
            if ps -p "$pid" > /dev/null 2>&1; then
                log_warn "Force killing $component"
                kill -9 "$pid" 2>/dev/null || true
            fi
            rm -f "$pid_file"
        fi
    done
    
    log_info "All components stopped"
}

# Start brain orchestrator
start_orchestrator() {
    local pid_file="$PID_DIR/brain_orchestrator.pid"
    local log_file="$LOG_DIR/brain_orchestrator.log"
    
    if is_running "$pid_file"; then
        log_warn "brain_orchestrator already running"
        return 0
    fi
    
    log_info "Starting brain_orchestrator on port $ORCH_PORT..."
    
    python3 "$SCRIPT_DIR/brain_orchestrator.py" \
        --host 0.0.0.0 \
        --port "$ORCH_PORT" \
        --omnicortex-voice-ws "$PERSONAPLEX_WS" \
        --default-voice-prompt "$VOICE_PROMPT" \
        --fs-sample-rate 8000 \
        --moshi-sample-rate 24000 \
        --fs-input-codec pcmu \
        --inbound-mode pcm16 \
        --outbound-mode pcm16 \
        --barge-in-enabled \
        --silence-pump-enabled \
        > "$log_file" 2>&1 &
    
    local pid=$!
    echo "$pid" > "$pid_file"
    sleep 2
    
    if is_running "$pid_file"; then
        log_info "brain_orchestrator started (PID: $pid)"
        return 0
    else
        log_error "brain_orchestrator failed to start"
        cat "$log_file"
        return 1
    fi
}

# Start bridge_in
start_bridge_in() {
    local pid_file="$PID_DIR/bridge_in.pid"
    local log_file="$LOG_DIR/bridge_in.log"
    
    if is_running "$pid_file"; then
        log_warn "bridge_in already running"
        return 0
    fi
    
    log_info "Starting bridge_in on port $BRIDGE_IN_PORT..."
    
    python3 "$SCRIPT_DIR/bridge_in.py" \
        --host 0.0.0.0 \
        --port "$BRIDGE_IN_PORT" \
        --endpoint /freeswitch \
        --orchestrator-ingest-ws "ws://127.0.0.1:$ORCH_PORT/ingest" \
        --fs-input-codec pcmu \
        > "$log_file" 2>&1 &
    
    local pid=$!
    echo "$pid" > "$pid_file"
    sleep 2
    
    if is_running "$pid_file"; then
        log_info "bridge_in started (PID: $pid)"
        return 0
    else
        log_error "bridge_in failed to start"
        cat "$log_file"
        return 1
    fi
}

# Start bridge_out
start_bridge_out() {
    local pid_file="$PID_DIR/bridge_out.pid"
    local log_file="$LOG_DIR/bridge_out.log"
    
    if is_running "$pid_file"; then
        log_warn "bridge_out already running"
        return 0
    fi
    
    log_info "Starting bridge_out on port $BRIDGE_OUT_PORT..."
    
    python3 "$SCRIPT_DIR/bridge_out.py" \
        --host 0.0.0.0 \
        --port "$BRIDGE_OUT_PORT" \
        --endpoint /speak \
        --orchestrator-egress-ws "ws://127.0.0.1:$ORCH_PORT/egress" \
        --source-sample-rate 8000 \
        --output-sample-rate 8000 \
        --tts-enabled \
        --http-write-silence \
        > "$log_file" 2>&1 &
    
    local pid=$!
    echo "$pid" > "$pid_file"
    sleep 2
    
    if is_running "$pid_file"; then
        log_info "bridge_out started (PID: $pid)"
        return 0
    else
        log_error "bridge_out failed to start"
        cat "$log_file"
        return 1
    fi
}

# Show status
show_status() {
    log_info "Bridge Stack Status:"
    echo ""
    
    for component in brain_orchestrator bridge_in bridge_out; do
        local pid_file="$PID_DIR/${component}.pid"
        if is_running "$pid_file"; then
            local pid=$(cat "$pid_file")
            echo -e "  ${GREEN}✓${NC} $component (PID: $pid)"
        else
            echo -e "  ${RED}✗${NC} $component (not running)"
        fi
    done
    
    echo ""
    log_info "Logs: $LOG_DIR"
    log_info "PIDs: $PID_DIR"
}

# Show logs
show_logs() {
    local component="$1"
    local log_file="$LOG_DIR/${component}.log"
    
    if [ -f "$log_file" ]; then
        tail -f "$log_file"
    else
        log_error "Log file not found: $log_file"
        exit 1
    fi
}

# Main
case "${1:-start}" in
    start)
        log_info "Starting bridge stack..."
        start_orchestrator || exit 1
        start_bridge_in || exit 1
        start_bridge_out || exit 1
        echo ""
        show_status
        echo ""
        log_info "Bridge stack started successfully!"
        log_info "FreeSWITCH should connect to:"
        log_info "  - Inbound:  ws://127.0.0.1:$BRIDGE_IN_PORT/freeswitch?call_uuid=\${uuid}"
        log_info "  - Outbound: http://127.0.0.1:$BRIDGE_OUT_PORT/stream/\${uuid}.raw"
        ;;
    
    stop)
        stop_all
        ;;
    
    restart)
        stop_all
        sleep 2
        "$0" start
        ;;
    
    status)
        show_status
        ;;
    
    logs)
        if [ -z "$2" ]; then
            log_error "Usage: $0 logs <component>"
            log_info "Components: brain_orchestrator, bridge_in, bridge_out"
            exit 1
        fi
        show_logs "$2"
        ;;
    
    *)
        echo "Usage: $0 {start|stop|restart|status|logs <component>}"
        exit 1
        ;;
esac
