# Irrigation Monitoring Architecture

## A. System Architecture

```text
                 local/offline-capable boundary
   -----------------------------------------------------------
   Arduino Nano                   Raspberry Pi
   ------------                   ------------
   AS5600 angle                   SPI soil moisture
   limit switches                 flow pulse counter
   pump relay state               MPU6050 vibration
   valve relay state              encoder count
   motor state telemetry          OLED/keypad UI
        |                              ^
        | serial telemetry JSON        |
        v                              |
   local control loop         logging and local dashboard node
   safety decisions stay      SQLite + upload queue + sync worker
   on Nano/Pi local code             |
   -----------------------------------------------------------
                                     |
                         HTTPS batched upload when online
                                     |
                                     v
                           FastAPI cloud ingest API
                                     |
                                     v
                              Postgres database
                                     |
                                     v
                     phone dashboard via authenticated API
```

### Data Flow

1. Sensors and Nano telemetry are sampled or received by the Pi.
2. The Pi normalizes each observation into telemetry, status, event, and run
   records with stable UUIDs.
3. The Pi writes records to SQLite first, inside a transaction.
4. The Pi adds records to `upload_queue`.
5. A sync worker sends pending queue items to the cloud API in batches.
6. The cloud API authenticates the device, inserts records idempotently, updates
   current device status, and returns accepted record IDs.
7. The phone dashboard reads current status, recent events, and historical
   telemetry from the cloud API.

### Failure Behavior When Internet Is Lost

- Local control continues because Nano/Pi control code does not call the cloud.
- Pi keeps logging to SQLite.
- New records remain in `upload_queue` with status `pending` or `retry`.
- Sync attempts use timeouts and exponential backoff.
- A local backlog alert is created if queued records exceed a configured limit.
- Dashboard may show the last cloud-seen state as stale/offline.

### Recovery Behavior When Internet Returns

- Sync worker resumes with oldest records first.
- Batches are idempotent, using device ID plus record UUID.
- Successfully accepted records are marked `uploaded`.
- Failed records keep retry metadata and do not block newer batches forever once
  they pass a max attempt threshold.
- Cloud `device_status.last_seen_at` updates when fresh records arrive.

## B. Data Model

### Timestamp Strategy

- Every record has a `device_id` and a UUID `id`.
- Use UTC timestamps in ISO 8601 format on the Pi.
- Store cloud timestamps as `timestamptz` in Postgres.
- Include `recorded_at` from the Pi and `received_at` from the cloud.
- Optional `monotonic_ms` helps diagnose Pi clock jumps after outages.

### `telemetry`

High-volume sampled measurements.

```sql
id uuid primary key,
device_id text not null,
recorded_at timestamptz not null,
received_at timestamptz,
soil_moisture_pct double precision,
flow_rate_l_min double precision,
cumulative_flow_l double precision,
angle_deg double precision,
alignment_error_deg double precision,
limit_min_active boolean,
limit_max_active boolean,
pump_on boolean,
valve_position_pct double precision,
drive_mode text,
demo_mode text,
encoder_count bigint,
vibration_rms_g double precision,
raw jsonb
```

### `events`

Alerts, operator actions, state changes, and sync warnings.

```sql
id uuid primary key,
device_id text not null,
run_id uuid,
recorded_at timestamptz not null,
received_at timestamptz,
severity text not null,
event_type text not null,
message text not null,
payload jsonb
```

### `device_status`

One current row per device.

```sql
device_id text primary key,
last_seen_at timestamptz,
last_recorded_at timestamptz,
connection_state text,
firmware_version text,
pi_app_version text,
sync_backlog_count integer,
current_run_id uuid,
current_mode text,
last_error text,
updated_at timestamptz not null
```

### `irrigation_runs`

Irrigation or demo run boundaries and summaries.

```sql
id uuid primary key,
device_id text not null,
run_type text not null,
mode text,
started_at timestamptz not null,
ended_at timestamptz,
start_reason text,
end_reason text,
total_flow_l double precision,
summary jsonb
```

### `upload_queue`

Pi-local sync state, not normally needed in the cloud database.

```sql
id integer primary key autoincrement,
entity_type text not null,
entity_id text not null,
operation text not null default 'upsert',
payload_json text not null,
status text not null default 'pending',
attempts integer not null default 0,
next_attempt_at text,
last_error text,
created_at text not null,
uploaded_at text,
unique(entity_type, entity_id, operation)
```

## C. Cloud And Dashboard Recommendation

Ranked for this project:

1. FastAPI + Postgres + static mobile dashboard
   - Best match for Python preference and the assumed architecture.
   - Clear device-auth boundary.
   - Easy to run locally, host cheaply, and migrate later.
   - Slightly more setup than Firebase/Supabase-only.

2. Supabase Postgres + Auth + optional FastAPI ingest
   - Strong choice if you want hosted Postgres, Auth, and dashboard auth quickly.
   - Free tier can be enough for a prototype, but keep device write keys out of
     browser code.
   - Recommended later upgrade: use Supabase for Postgres/Auth while keeping the
     FastAPI ingest service.

3. Firebase Firestore + Firebase Hosting/Auth
   - Fastest phone dashboard if you already know Firebase.
   - Less natural for relational run/event/telemetry queries.
   - Cost is read/write driven, so chart-heavy dashboards need care.

Not recommended as the first build: MQTT broker + dashboard. MQTT is useful for
live IoT streaming, but it adds another moving part. Add MQTT later only if you
need lower-latency streaming or multiple subscribers.

Recommended path: FastAPI + Postgres + static responsive dashboard. For a cheap
prototype, host Postgres as managed Postgres or Supabase, host FastAPI on a small
PaaS/container service, and host the dashboard as static files.

## D. Implementation Plan

### Phase 1: Local Logging On Pi

- Create SQLite schema.
- Wrap all inserts in a small storage module.
- Add telemetry, event, run, status insert functions.
- Feed it with demo telemetry first, then serial JSON from the Nano, then real
  Pi sensor adapters.
- Verify that logging continues with Wi-Fi disabled.

Build first.

### Phase 2: Sync Service

- Add `upload_queue` on every local insert.
- Implement batch upload with timeouts.
- Mark accepted records uploaded.
- Retry failed batches with backoff.
- Add backlog alert when the queue grows too large.

Build second.

### Phase 3: Cloud API And Database

- Implement `/v1/ingest/batch`.
- Authenticate devices with `X-Device-ID` and `X-Device-Token`.
- Insert records idempotently by UUID.
- Add read-only dashboard endpoints protected by bearer token.
- Deploy with HTTPS.

Build third.

### Phase 4: Cellphone Dashboard

- Mobile-first status cards.
- Current values for soil, flow, angle, switches, pump, valve, mode, and last
  seen state.
- Recent alerts/events.
- Simple history charts.
- Poll every 5-10 seconds.

Build fourth.

### Phase 5: Alerts/Notifications

- Start with visible dashboard alerts.
- Add email/SMS/push later for device offline, zero flow, vibration, limit hits,
  bad soil readings, and sync backlog.
- Avoid alert actions that change motor/water state.

Can wait until the end-to-end demo is working.

## F. Dashboard Features

Minimum dashboard cards:

- Current soil moisture.
- Current flow rate and cumulative flow.
- Current angle/alignment error.
- Limit switch status.
- Pump state.
- Valve estimated position.
- Drive/demo mode status.
- Recent alerts/events.
- Historical soil, flow, angle, and vibration charts.
- Connection and last-seen status.

## G. Practical Alerts

- Device offline: no cloud upload for more than 2-5 minutes.
- Unexpected zero flow while irrigating: pump on but flow near zero for N seconds.
- Repeated limit hits: limit switch trips repeatedly during a short window.
- Excessive vibration: MPU6050 RMS over configured threshold.
- Abnormal soil readings: impossible value, stuck value, or sudden jump.
- Failed cloud sync backlog: queue length above threshold or oldest pending item
  older than threshold.
- Sensor unavailable: missing SPI/MPU/serial values for repeated samples.

## H. Development Priorities This Week

1. Run the backend locally and confirm `/health` works.
2. Run the Pi demo collector and confirm SQLite records appear.
3. Confirm Pi demo records upload to backend.
4. Open the dashboard from a phone on the same network.
5. Replace demo collector fields with serial JSON from the Nano.
6. Add one real Pi sensor at a time, starting with flow and soil moisture.
7. Add the zero-flow and offline alerts after data is flowing end to end.

Defer these until after the demo:

- True real-time streaming.
- SMS/push notifications.
- Cloud-originated control commands.
- Complex user roles.
- Pressure-dependent logic.
