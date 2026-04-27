from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"


def main() -> None:
    api_base_raw = os.environ.get("DASHBOARD_API_BASE", "").strip()
    if os.environ.get("RENDER") == "true" and not api_base_raw:
        raise SystemExit(
            "DASHBOARD_API_BASE is required for Render dashboard builds. "
            "Set it to the API service URL, for example "
            "https://irrigation-monitor-api.onrender.com"
        )

    api_base = (api_base_raw or "http://localhost:8000").rstrip("/")
    device_id = os.environ.get("DASHBOARD_DEVICE_ID", "pi-prototype-001")
    dashboard_token = os.environ.get("DASHBOARD_TOKEN", "dev-dashboard-token-change-me")
    poll_seconds = int(os.environ.get("DASHBOARD_POLL_SECONDS", "6"))

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    for filename in ("index.html", "styles.css", "app.js"):
        shutil.copy2(ROOT / filename, DIST / filename)

    config = {
        "API_BASE": api_base,
        "DEVICE_ID": device_id,
        "DASHBOARD_TOKEN": dashboard_token,
        "POLL_SECONDS": poll_seconds,
    }
    config_js = "window.DASHBOARD_CONFIG = " + json.dumps(config, indent=2) + ";\n"
    (DIST / "config.js").write_text(config_js, encoding="utf-8")
    print(f"Built dashboard in {DIST}")
    print(f"Dashboard API base: {api_base}")


if __name__ == "__main__":
    main()
