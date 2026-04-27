# Pi Uploader Systemd Service

This installs the cloud uploader as a background service on the Raspberry Pi.
It does not talk to the Nano serial line. With the current setup, it reads the
existing control service CSV log, writes to local SQLite, and uploads to the API.

## Before Installing

The Pi service directory should exist:

```bash
cd ~/irrigation_cloud_monitoring/pi_service
```

The virtual environment should be installed:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The `.env` file should be configured:

```text
DEVICE_ID=pi-prototype-001
TELEMETRY_SOURCE=csv
CONTROL_CSV_GLOB=/home/alec-anderson23/irrigation_production_nano_*.csv
CLOUD_API_URL=http://YOUR_LAPTOP_IP:8000
DEVICE_TOKEN=dev-device-token-change-me
```

## Install

```bash
cd ~/irrigation_cloud_monitoring/pi_service
chmod +x scripts/install_uploader_service.sh
./scripts/install_uploader_service.sh
```

## Check Status

```bash
systemctl status irrigation-cloud-uploader.service --no-pager -l
```

Follow logs:

```bash
journalctl -u irrigation-cloud-uploader.service -f
```

Confirm local buffering exists:

```bash
sqlite3 ~/irrigation_cloud_monitoring/pi_service/data/irrigation_pi.sqlite3 \
  "select status, count(*) from upload_queue group by status;"
```

## Restart Or Stop

```bash
sudo systemctl restart irrigation-cloud-uploader.service
sudo systemctl stop irrigation-cloud-uploader.service
```

Disable autostart:

```bash
sudo systemctl disable irrigation-cloud-uploader.service
```

## Expected Behavior

- If the laptop/cloud API is reachable, records upload every sync interval.
- If the API is offline, records stay in SQLite and retry later.
- The existing `irrigation-demo.service` remains the only service using Nano
  serial.
