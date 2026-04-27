create table if not exists telemetry (
  id uuid primary key,
  device_id text not null,
  recorded_at timestamptz not null,
  received_at timestamptz not null default now(),
  monotonic_ms bigint,
  source text,
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
);

create index if not exists idx_telemetry_device_recorded
  on telemetry (device_id, recorded_at desc);

create table if not exists events (
  id uuid primary key,
  device_id text not null,
  run_id uuid,
  recorded_at timestamptz not null,
  received_at timestamptz not null default now(),
  severity text not null,
  event_type text not null,
  message text not null,
  payload jsonb
);

create index if not exists idx_events_device_recorded
  on events (device_id, recorded_at desc);

create table if not exists device_status (
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
  payload jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists irrigation_runs (
  id uuid primary key,
  device_id text not null,
  run_type text not null,
  mode text,
  started_at timestamptz not null,
  ended_at timestamptz,
  start_reason text,
  end_reason text,
  total_flow_l double precision,
  summary jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists idx_runs_device_started
  on irrigation_runs (device_id, started_at desc);
