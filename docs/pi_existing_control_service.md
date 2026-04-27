# Pi Setup With Existing Control Service

Use this path when the Raspberry Pi control service already talks to the Nano.
The cloud uploader must not open the Nano serial port in that case.

```text
Nano -> existing Pi control service -> existing CSV log
                                      -> cloud uploader -> SQLite -> API
```

## Preferred: Read The Existing CSV Log

Your current control service already writes `irrigation_production_nano_*.csv`
once per second. Use that as the handoff. This avoids touching the control loop.

## Configure The Cloud Uploader On The Pi

In `irrigation_cloud_monitoring/pi_service/.env`:

```text
DEVICE_ID=pi-prototype-001
TELEMETRY_SOURCE=csv
CONTROL_CSV_GLOB=/home/alec-anderson23/irrigation_production_nano_*.csv
CLOUD_API_URL=http://YOUR_BACKEND_IP:8000
DEVICE_TOKEN=dev-device-token-change-me
```

Do not set `TELEMETRY_SOURCE=serial` while the control service owns the Nano
port.

## Test One Upload

```bash
cd irrigation_cloud_monitoring/pi_service
python -m pip install -r requirements.txt
python -m irrigation_pi.main --once
```

Then open the dashboard:

```text
http://YOUR_BACKEND_IP:5173
```

## Run Continuously Later

After the one-shot test works, run:

```bash
python -m irrigation_pi.main
```

Next step after that is creating a `systemd` service for the uploader.
