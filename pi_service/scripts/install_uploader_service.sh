#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-irrigation-cloud-uploader.service}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_USER="${IRRIGATION_RUN_USER:-$(id -un)}"
RUN_GROUP="${IRRIGATION_RUN_GROUP:-$(id -gn)}"
PYTHON_BIN="${PI_SERVICE_DIR}/.venv/bin/python"
ENV_FILE="${PI_SERVICE_DIR}/.env"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}."
  echo "Create it first with: cp .env.example .env"
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing virtualenv Python at ${PYTHON_BIN}."
  echo "Create it first:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  python -m pip install -r requirements.txt"
  exit 1
fi

mkdir -p "${PI_SERVICE_DIR}/data"

sudo tee "${UNIT_PATH}" >/dev/null <<UNIT
[Unit]
Description=Irrigation Cloud Uploader
After=network-online.target irrigation-demo.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PI_SERVICE_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PYTHON_BIN} -m irrigation_pi.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

echo "Installed and started ${SERVICE_NAME}"
echo "Check status with:"
echo "  systemctl status ${SERVICE_NAME} --no-pager -l"
echo "Follow logs with:"
echo "  journalctl -u ${SERVICE_NAME} -f"
