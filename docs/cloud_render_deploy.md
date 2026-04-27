# Cloud Deployment On Render

This deploys the monitoring layer only. The Nano/Pi control loop stays local.

```text
Pi control service -> CSV log -> Pi uploader -> Render API -> Render Postgres
                                                   |
                                                   v
                                           Render static dashboard
```

## Why Render For This Prototype

Render can host a Python web service, a static dashboard, and managed Postgres
from the same Git repo. It also provides HTTPS for the public service URLs.

For the free test path, Render's free Postgres is temporary. Treat it as a demo
database and expect it to expire after the free period. The Pi keeps its own
local SQLite buffer regardless.

## Prep

Use non-default secrets before deploying:

```text
DEVICE_TOKENS=pi-prototype-001:replace-with-long-random-token
DASHBOARD_TOKEN=replace-with-long-random-token
```

The Pi `.env` must use the same device token.

## Push To Git

Render deploys from a GitHub/GitLab/Bitbucket repo. Put
`irrigation_cloud_monitoring` at the repo root, or keep `render.yaml` at the
repository root if this is part of a larger repo.

## Deploy Blueprint

1. In Render, choose New > Blueprint.
2. Connect the repo containing `render.yaml`.
3. Render will create:
   - `irrigation-monitor-api`
   - `irrigation-monitor-dashboard`
   - `irrigation-monitor-db`
4. Fill secret environment variables when prompted:
   - API service: `DEVICE_TOKENS`, `DASHBOARD_TOKEN`
   - dashboard static site: `DASHBOARD_TOKEN`

## Set Dashboard API URL

After the API deploys, copy its public URL, for example:

```text
https://irrigation-monitor-api.onrender.com
```

Set this on the dashboard static site:

```text
DASHBOARD_API_BASE=https://irrigation-monitor-api.onrender.com
```

Redeploy the dashboard after setting it.

For tighter CORS later, change API `CORS_ORIGINS` from `*` to the dashboard URL:

```text
https://irrigation-monitor-dashboard.onrender.com
```

## Point The Pi To Cloud

On the Pi:

```bash
nano ~/irrigation_cloud_monitoring/pi_service/.env
```

Set:

```text
CLOUD_API_URL=https://irrigation-monitor-api.onrender.com
DEVICE_TOKEN=replace-with-long-random-token
```

Restart:

```bash
sudo systemctl restart irrigation-cloud-uploader.service
journalctl -u irrigation-cloud-uploader.service -f
```

## Validate

On the Pi:

```bash
curl https://irrigation-monitor-api.onrender.com/health
```

Expected:

```json
{"status":"ok"}
```

Then open the dashboard URL in your phone browser.

## Notes

- Pi keeps local SQLite buffering if Render or Wi-Fi is down.
- Dashboard is monitoring-only.
- Do not commit `.env` or `dashboard/config.js`.
