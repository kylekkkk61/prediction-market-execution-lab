#!/bin/bash
set -euo pipefail

echo "=== Polymarket Taker Bot + Auto Claim Watcher 部署開始 ==="

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/botenv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

BOT_FILE="$APP_DIR/bot.py"
CLAIM_FILE="$APP_DIR/polymarket_auto_claim.py"
ENV_FILE="$APP_DIR/.env"

TAKER_SERVICE="/etc/systemd/system/pm-taker-v2.service"
CLAIM_SERVICE="/etc/systemd/system/pm-claim-v2.service"

BOT_LOG="$APP_DIR/bot.log"
CLAIM_LOG="$APP_DIR/claim.log"

cd "$APP_DIR"

echo "[1/8] 基本檢查..."
if [ ! -f "$BOT_FILE" ]; then
  echo "❌ 找不到 $BOT_FILE"
  exit 1
fi

if [ ! -f "$CLAIM_FILE" ]; then
  echo "❌ 找不到 $CLAIM_FILE"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ 找不到 $ENV_FILE"
  exit 1
fi

echo "[2/8] 建立或更新 Python 虛擬環境..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "[3/8] 安裝/更新依賴..."
"$PIP_BIN" install --upgrade pip
"$PIP_BIN" install --upgrade \
  py-clob-client-v2 \
  websockets \
  python-dotenv \
  requests \
  certifi \
  eth-account \
  eth-abi \
  eth-utils \
  hexbytes \
  poly-eip712-structs

echo "[4/8] 建立日誌檔..."
touch "$BOT_LOG" "$CLAIM_LOG"

echo "[5/8] 寫入 pm-taker.service..."
cat > "$TAKER_SERVICE" << EOF2
[Unit]
Description=Polymarket BTC Taker Bot (V2)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN $BOT_FILE
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:$BOT_LOG
StandardError=append:$BOT_LOG

[Install]
WantedBy=multi-user.target
EOF2

echo "[6/8] 寫入 pm-claim.service（watch mode）..."
cat > "$CLAIM_SERVICE" << EOF2
[Unit]
Description=Polymarket Auto Claim Watcher (V2)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN $CLAIM_FILE watch
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:$CLAIM_LOG
StandardError=append:$CLAIM_LOG

[Install]
WantedBy=multi-user.target
EOF2

echo "[7/8] 保留 legacy 服務，不覆蓋 root 版本..."

echo "[8/8] 重新載入 systemd 並啟用服務..."
systemctl daemon-reload

systemctl enable pm-taker-v2.service
systemctl restart pm-taker-v2.service

systemctl enable pm-claim-v2.service
systemctl restart pm-claim-v2.service

echo ""
echo "=== 部署完成 ==="
echo ""
echo "服務狀態："
systemctl status pm-taker-v2.service --no-pager || true
echo ""
systemctl status pm-claim-v2.service --no-pager || true

echo ""
echo "常用指令："
echo "查看交易 bot 狀態：    systemctl status pm-taker-v2.service"
echo "查看 claim watcher：   systemctl status pm-claim-v2.service"
echo "查看 bot 日誌：         tail -f $BOT_LOG"
echo "查看 claim 日誌：       tail -f $CLAIM_LOG"
echo "重啟交易 bot：          systemctl restart pm-taker-v2.service"
echo "重啟 claim watcher：    systemctl restart pm-claim-v2.service"
echo "停止交易 bot：          systemctl stop pm-taker-v2.service"
echo "停止 claim watcher：    systemctl stop pm-claim-v2.service"
echo "手動跑一次 claim：      $PYTHON_BIN $CLAIM_FILE run-once"
