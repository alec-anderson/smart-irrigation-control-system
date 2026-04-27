pragma journal_mode = wal;
pragma foreign_keys = on;

create table if not exists telemetry (
  id text primary key,
  device_id text not null,
  recorded_at text not null,
  monotonic_ms integer,
  source text not null,
  soil_moisture_pct real,
  flow_rate_l_min real,
  cumulative_flow_l real,
  angle_deg real,
  alignment_error_deg real,
  limit_min_active integer,
  limit_max_active integer,
  pump_on integer,
  valve_position_pct real,
  drive_mode text,
  demo_mode text,
  encoder_count integer,
  vibration_rms_g real,
  raw_json text,
  created_at text not null,
  synced_at text,
  upload_attempts integer not null default 0
);

create index if not exists idx_telemetry_device_recorded
  on telemetry (device_id, recorded_at);

create table if not exists events (
  id text primary key,
  device_id text not null,
  run_id text,
  recorded_at text not null,
  severity text not null,
  event_type text not null,
  message text not null,
  payload_json text,
  created_at text not null,
  synced_at text,
  upload_attempts integer not null default 0
);

create index if not exists idx_events_device_recorded
  on events (device_id, recorded_at);

create table if not exists device_status (
  device_id text primary key,
  recorded_at text not null,
  connection_state text not null,
  firmware_version text,
  pi_app_version text,
  sync_backlog_count integer not null default 0,
  current_run_id text,
  current_mode text,
  last_error text,
  payload_json text,
  updated_at text not null,
  synced_at text
);

create table if not exists irrigation_runs (
  id text primary key,
  device_id text not null,
  run_type text not null,
  mode text,
  started_at text not null,
  ended_at text,
  start_reason text,
  end_reason text,
  total_flow_l real,
  summary_json text,
  created_at text not null,
  updated_at text not null,
  synced_at text,
  upload_attempts integer not null default 0
);

create index if not exists idx_runs_device_started
  on irrigation_runs (device_id, started_at);

create table if not exists upload_queue (
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
  unique (entity_type, entity_id, operation)
);

create index if not exists idx_upload_queue_status_next
  on upload_queue (status, next_attempt_at, id);
