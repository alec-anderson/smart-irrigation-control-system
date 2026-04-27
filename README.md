# Irrigation Cloud Monitoring Starter

This starter keeps irrigation control local and treats the cloud as a monitoring,
history, and alerting layer.

Recommended path:

1. Raspberry Pi logs every telemetry/status/event record to local SQLite first.
2. A Pi sync worker uploads queued records to a cloud FastAPI endpoint in small
   idempotent batches.
3. FastAPI stores records in Postgres and exposes read-only dashboard endpoints.
4. A mobile-first static dashboard polls the API for live-ish status and history.

The cloud path is intentionally not used for safety-critical control. Later, you
can add non-critical operator commands with a separate approval path, but the
core design here is monitoring-only.

## Project Layout

```text
irrigation_cloud_monitoring/
  docs/
    architecture.md
  pi_service/
    irrigation_pi/
    schema.sql
    requirements.txt
    .env.example
  backend/
    app/
    schema.sql
    requirements.txt
    .env.example
  dashboard/
    index.html
    styles.css
    app.js
    config.example.js
  docker-compose.yml
```

## Quick Local Demo

Backend:

```powershell
cd irrigation_cloud_monitoring\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

If the `uvicorn` command is not available, run:

```powershell
python run_dev.py
```

Pi simulator, in a second terminal:

```powershell
cd irrigation_cloud_monitoring\pi_service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m irrigation_pi.main --demo
```

Dashboard:

```powershell
cd irrigation_cloud_monitoring\dashboard
copy config.example.js config.js
python -m http.server 5173
```

Open `http://localhost:5173` on a phone connected to the same network, replacing
`localhost` in `dashboard/config.js` with the backend machine IP address.

For the current mobile-friendly local demo, the dashboard config uses the host
name from the URL automatically:

```javascript
API_BASE: `http://${window.location.hostname}:8000`
```

So if the computer/Pi IP is `192.168.1.50`, open this on the phone:

```text
http://192.168.1.50:5173
```

## Switching From Demo Data To The Nano

If your existing Pi control service already reads Nano serial, do not use this
direct serial path. Use the local telemetry-file handoff in
`docs/pi_existing_control_service.md` instead.

List serial ports:

```powershell
python -m serial.tools.list_ports -v
```

Use the Arduino/Nano USB serial port, not Intel AMT/SOL or Bluetooth ports. On a
Raspberry Pi this will usually be `/dev/ttyUSB0` or `/dev/ttyACM0`.

Update `pi_service/.env`:

```text
SERIAL_PORT=COMx
SERIAL_BAUD=115200
SERIAL_PROTOCOL=nano_csv
```

Then run the Pi service without `--demo`:

```powershell
cd irrigation_cloud_monitoring\pi_service
python -m irrigation_pi.main
```

The `nano_csv` collector sends only `STATUS` requests and parses the existing
Nano `TEL,...` and `ANGLE:...` telemetry lines.

## Production Notes

- Put the Pi SQLite database on durable storage and enable WAL mode.
- Run the Pi service under `systemd` on the Raspberry Pi. See
  `docs/pi_uploader_service.md`.
- Use HTTPS for the backend.
- Rotate device tokens if a Pi image is shared.
- Use hosted Postgres/Supabase/Render/Fly/Railway for the student prototype,
  then move to a more controlled deployment only if the project grows.
- For Render deployment, see `docs/cloud_render_deploy.md`.
