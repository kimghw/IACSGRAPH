#!/bin/bash

# MCP Mail Attachment Server with Cloudflare Tunnel
# 서버와 터널을 함께 실행하고 URL을 보기 좋게 표시

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Use environment variable or default from settings
PORT=${MCP_PORT:-8002}

echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}   📧 MCP Mail Attachment Server - Cloudflare Tunnel${NC}"
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

# Check cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo -e "${RED}❌ cloudflared가 설치되지 않았습니다.${NC}"
    echo -e "${YELLOW}설치 방법: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation${NC}"
    exit 1
fi

# Set environment
export PYTHONPATH=/home/kimghw/IACSGRAPH
export MCP_SETTINGS_PATH=${MCP_SETTINGS_PATH:-"/home/kimghw/IACSGRAPH/modules/mail_attachment/settings.json"}
cd /home/kimghw/IACSGRAPH

# Start MCP server
echo -e "${BLUE}1️⃣  MCP 서버 시작 중... (포트: ${PORT})${NC}"
python -m modules.mail_attachment.mcp_server_mail_attachment > mcp_server.log 2>&1 &
SERVER_PID=$!

# Wait for server
sleep 3

# Check if server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo -e "${RED}❌ MCP 서버 시작 실패${NC}"
    cat mcp_server.log
    exit 1
fi

echo -e "${GREEN}✅ MCP 서버 실행 중 (PID: $SERVER_PID)${NC}"
echo

# Check if tunnel is already running
# Try multiple patterns to find existing tunnel
EXISTING_TUNNEL_PID=$(pgrep -f "cloudflared.*tunnel.*${PORT}" | head -1)
if [ -z "$EXISTING_TUNNEL_PID" ]; then
    EXISTING_TUNNEL_PID=$(pgrep -f "cloudflared.*tunnel.*url.*localhost:${PORT}" | head -1)
fi
TUNNEL_URL=""
TUNNEL_PID=""
TUNNEL_CREATED=false

if [ ! -z "$EXISTING_TUNNEL_PID" ]; then
    echo -e "${GREEN}✅ 기존 Cloudflare 터널 발견 (PID: $EXISTING_TUNNEL_PID)${NC}"
    echo -e "${YELLOW}   기존 터널 URL 찾는 중...${NC}"
    
    # Try to find existing tunnel URL from process output or logs
    TUNNEL_URL=$(ps aux | grep "cloudflared" | grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' | head -1)
    
    # Try various log file locations
    if [ -z "$TUNNEL_URL" ]; then
        # Check port-specific log file first
        if [ -f "tunnel_output_${PORT}.log" ]; then
            TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' tunnel_output_${PORT}.log | tail -1)
        fi
        
        # Check parent directory for port-specific log
        if [ -z "$TUNNEL_URL" ] && [ -f "../tunnel_output_${PORT}.log" ]; then
            TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' ../tunnel_output_${PORT}.log | tail -1)
        fi
        
        # Check project root for port-specific log
        if [ -z "$TUNNEL_URL" ] && [ -f "/home/kimghw/IACSGRAPH/tunnel_output_${PORT}.log" ]; then
            TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' /home/kimghw/IACSGRAPH/tunnel_output_${PORT}.log | tail -1)
        fi
        
        # Fallback to generic tunnel_output.log
        if [ -z "$TUNNEL_URL" ] && [ -f "tunnel_output.log" ]; then
            TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' tunnel_output.log | tail -1)
        fi
    fi
    
    if [ ! -z "$TUNNEL_URL" ]; then
        echo -e "${GREEN}✅ 기존 터널 URL: ${YELLOW}$TUNNEL_URL${NC}"
        TUNNEL_PID=$EXISTING_TUNNEL_PID
    else
        echo -e "${YELLOW}⚠️  기존 터널 URL을 찾을 수 없어 새 터널을 생성합니다.${NC}"
        kill $EXISTING_TUNNEL_PID 2>/dev/null
    fi
fi

# Create new tunnel if needed
if [ -z "$TUNNEL_URL" ]; then
    echo -e "${BLUE}2️⃣  Cloudflare 터널 생성 중...${NC}"
    TUNNEL_LOG="/home/kimghw/IACSGRAPH/tunnel_output_${PORT}.log"
    # Use stdbuf to disable buffering
    stdbuf -oL -eL cloudflared tunnel --url http://localhost:${PORT} 2>&1 | tee $TUNNEL_LOG &
    TUNNEL_PID=$!
    TUNNEL_CREATED=true

    # Wait for tunnel URL
    echo -e "${YELLOW}   터널 URL 대기 중...${NC}"
    COUNTER=0

    while [ $COUNTER -lt 30 ]; do
        if [ -f $TUNNEL_LOG ]; then
            URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' $TUNNEL_LOG | head -1)
            if [ ! -z "$URL" ]; then
                TUNNEL_URL=$URL
                break
            fi
        fi
        sleep 1
        COUNTER=$((COUNTER + 1))
        echo -n "."
    done
fi

echo
echo

if [ -z "$TUNNEL_URL" ]; then
    echo -e "${RED}❌ 터널 URL을 찾을 수 없습니다${NC}"
    cat $TUNNEL_LOG
    kill $SERVER_PID 2>/dev/null
    kill $TUNNEL_PID 2>/dev/null
    exit 1
fi

# Display success info
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}✨ 서버가 성공적으로 시작되었습니다!${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo -e "${CYAN}📍 접속 정보:${NC}"
echo -e "${BOLD}   🌐 Public URL: ${YELLOW}$TUNNEL_URL${NC}"
echo -e "${BOLD}   🏠 Local URL:  ${BLUE}http://localhost:${PORT}${NC}"
echo
echo -e "${CYAN}🔍 테스트 URL:${NC}"
echo -e "   Health: ${YELLOW}${TUNNEL_URL}/health${NC}"
echo -e "   Info:   ${YELLOW}${TUNNEL_URL}/info${NC}"
echo
echo -e "${CYAN}🤖 Claude.ai 설정:${NC}"
echo -e "   1. Claude.ai에서 MCP 서버 추가"
echo -e "   2. URL에 ${YELLOW}$TUNNEL_URL${NC} 입력"
echo -e "   3. 연결 확인 후 사용"
echo
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${RED}종료하려면 Ctrl+C를 누르세요${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Cleanup function
cleanup() {
    echo
    echo -e "${YELLOW}🛑 종료 중...${NC}"
    
    # Only kill tunnel if we created it
    if [ "$TUNNEL_CREATED" = true ] && [ ! -z "$TUNNEL_PID" ]; then
        kill $TUNNEL_PID 2>/dev/null && echo -e "${BLUE}   ✓ 터널 종료${NC}"
    else
        echo -e "${BLUE}   ℹ️  터널 유지 (기존 터널 사용)${NC}"
    fi
    
    kill $SERVER_PID 2>/dev/null && echo -e "${BLUE}   ✓ 서버 종료${NC}"
    rm -f mcp_server.log 2>/dev/null
    
    # Only remove tunnel log if we created the tunnel
    if [ "$TUNNEL_CREATED" = true ]; then
        rm -f $TUNNEL_LOG 2>/dev/null
    fi
    
    echo -e "${GREEN}✅ 정상 종료되었습니다${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Keep running - monitor only server if using existing tunnel
if [ "$TUNNEL_CREATED" = true ]; then
    # Monitor both server and tunnel
    while kill -0 $SERVER_PID 2>/dev/null && kill -0 $TUNNEL_PID 2>/dev/null; do
        sleep 1
    done
else
    # Monitor only server (tunnel runs independently)
    while kill -0 $SERVER_PID 2>/dev/null; do
        sleep 1
    done
fi