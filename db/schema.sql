-- Asset Intelligence Copilot: SQLite schema.
--
-- Three layers:
--   1. Source records   loaded from the dataset folders by db/load.py. Never edited by
--                       the copilot. A reload replaces them (per well) and leaves layer 2.
--   2. Runtime knowledge written by the copilot: corrections, user rules, shared notes,
--                       private conversations. Survives reloads.
--   3. Views            join 1 + 2 and apply the rules: effective readings, producing flag,
--                       real spills, latest status per well.
--
-- Enumerations that come from the dataset (roles, event types, ...) are not CHECKed, so an
-- unexpected value in the test dataset loads and gets reported instead of failing the load.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- Settings
-- ============================================================================

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- "today" is a setting, not a constant: the docs say both 16 and 17 Oct 2026.
INSERT OR IGNORE INTO settings (key, value) VALUES ('today', '2026-10-16');

CREATE TABLE IF NOT EXISTS load_runs (
    run_id     INTEGER PRIMARY KEY,
    loaded_at  TEXT NOT NULL,
    data_dir   TEXT NOT NULL,
    counts     TEXT NOT NULL,          -- JSON {table: rows}
    warnings   TEXT NOT NULL           -- JSON [string]
);

-- ============================================================================
-- Layer 1: source records
-- ============================================================================

-- fleet/areas.json -> teams[]
CREATE TABLE IF NOT EXISTS teams (
    team_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    lead_user_id  TEXT
);

-- fleet/users.json
CREATE TABLE IF NOT EXISTS users (
    user_id  TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    role     TEXT NOT NULL,            -- production_supervisor, field_operator, field_inspector, ...
    team_id  TEXT REFERENCES teams(team_id)
);

-- fleet/areas.json -> areas[]
CREATE TABLE IF NOT EXISTS areas (
    area_id     TEXT PRIMARY KEY,      -- e.g. NE-07
    name        TEXT NOT NULL,         -- e.g. Northeast Block 7 (answers use this)
    team_id     TEXT REFERENCES teams(team_id),
    center_lat  REAL,
    center_lon  REAL
);

-- assets/WELL-XXXX/metadata.json
CREATE TABLE IF NOT EXISTS wells (
    asset_id                TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    asset_category          TEXT,
    well_type               TEXT NOT NULL,      -- selects the manual: fleet/well-types/<well_type>.md
    area_id                 TEXT REFERENCES areas(area_id),
    team_id                 TEXT REFERENCES teams(team_id),
    in_charge_user_id       TEXT REFERENCES users(user_id),
    lat                     REAL,
    lon                     REAL,
    installed_on            TEXT,
    recorded_status         TEXT,               -- active | down. CAN BE OUT OF DATE; inspections are the truth.
    last_inspection_id      TEXT,
    last_inspected_at       TEXT,
    last_inspector_user_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_wells_area ON wells(area_id);
CREATE INDEX IF NOT EXISTS idx_wells_type ON wells(well_type);

-- metadata.json -> equipment[]
CREATE TABLE IF NOT EXISTS equipment (
    equipment_id  TEXT PRIMARY KEY,
    asset_id      TEXT NOT NULL REFERENCES wells(asset_id),
    kind          TEXT NOT NULL,        -- wellhead, pump_jack, rod_string, downhole_pump, flowline, separator
    model         TEXT
);
CREATE INDEX IF NOT EXISTS idx_equipment_asset ON equipment(asset_id);

-- assets/WELL-XXXX/inspections.jsonl (raw, as recorded)
CREATE TABLE IF NOT EXISTS inspections (
    inspection_id         TEXT PRIMARY KEY,
    asset_id              TEXT NOT NULL REFERENCES wells(asset_id),
    inspected_at          TEXT NOT NULL,      -- ISO 8601 UTC; also the spill discovery time
    inspected_date        TEXT GENERATED ALWAYS AS (substr(inspected_at, 1, 10)) VIRTUAL,
    inspector_user_id     TEXT REFERENCES users(user_id),
    method                TEXT,               -- drone | manual
    ambient_temp_c        REAL,
    wellhead_temp_c       REAL,
    temp_delta_c          REAL GENERATED ALWAYS AS (wellhead_temp_c - ambient_temp_c) VIRTUAL,
    spill_detected        INTEGER NOT NULL,   -- 0/1, AI detection before any correction
    spill_area_pct        REAL,
    spill_est_volume_bbl  REAL,               -- AI estimate from images
    evidence_images       TEXT,               -- JSON array of paths (files not supplied)
    notes                 TEXT                -- inspector remark, e.g. "Pump jack not moving."
);
CREATE INDEX IF NOT EXISTS idx_inspections_asset_time ON inspections(asset_id, inspected_at);
CREATE INDEX IF NOT EXISTS idx_inspections_time ON inspections(inspected_at);

-- assets/WELL-XXXX/maintenance.jsonl
CREATE TABLE IF NOT EXISTS maintenance (
    maintenance_id              TEXT PRIMARY KEY,
    asset_id                    TEXT NOT NULL REFERENCES wells(asset_id),
    started_at                  TEXT NOT NULL,   -- a repair belongs to a period by this date
    completed_at                TEXT,            -- planned end if still in progress; can be after today
    maintenance_type            TEXT NOT NULL,   -- scheduled | corrective
    equipment_kind              TEXT,
    issue                       TEXT,
    action_taken                TEXT,
    technician_user_id          TEXT REFERENCES users(user_id),
    contractor                  TEXT,
    downtime_hours              INTEGER,         -- length of this job. NOT well downtime.
    cost_labor_usd              REAL,
    cost_parts_usd              REAL,
    cost_total_usd              REAL,
    triggered_by_inspection_id  TEXT REFERENCES inspections(inspection_id),
    report_file                 TEXT             -- path relative to the well folder; names vary
);
CREATE INDEX IF NOT EXISTS idx_maintenance_asset_start ON maintenance(asset_id, started_at);
CREATE INDEX IF NOT EXISTS idx_maintenance_trigger ON maintenance(triggered_by_inspection_id);

-- assets/WELL-XXXX/maintenance-reports/*.md (one per corrective repair)
CREATE TABLE IF NOT EXISTS maintenance_reports (
    maintenance_id     TEXT PRIMARY KEY REFERENCES maintenance(maintenance_id),
    asset_id           TEXT NOT NULL REFERENCES wells(asset_id),
    file_path          TEXT NOT NULL,     -- relative to the dataset root, for citations
    title              TEXT,
    body_md            TEXT NOT NULL,
    containment_hours  REAL               -- parsed from "contained about N hours"; only in reports
);

-- Report split at its "## " headings. Heading sets vary (e.g. "Waste", "Work done so far").
CREATE TABLE IF NOT EXISTS report_sections (
    maintenance_id  TEXT NOT NULL REFERENCES maintenance_reports(maintenance_id),
    ord             INTEGER NOT NULL,
    heading         TEXT NOT NULL,
    body            TEXT NOT NULL,
    PRIMARY KEY (maintenance_id, ord)
);

-- Rows of the report's "Compliance check" table, as the report states them.
CREATE TABLE IF NOT EXISTS report_compliance (
    maintenance_id  TEXT NOT NULL REFERENCES maintenance_reports(maintenance_id),
    protocol        TEXT NOT NULL,        -- SR-02, WS-05, "Manual §10", "HSE notice", ...
    result          TEXT NOT NULL,        -- Met | Not met | In progress | Action required | ...
    detail          TEXT,
    PRIMARY KEY (maintenance_id, protocol)
);
CREATE INDEX IF NOT EXISTS idx_report_compliance_protocol ON report_compliance(protocol, result);

-- assets/WELL-XXXX/regulatory-events.jsonl
CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id               TEXT PRIMARY KEY,
    asset_id               TEXT NOT NULL REFERENCES wells(asset_id),
    date                   TEXT NOT NULL,
    agency                 TEXT,
    event_type             TEXT NOT NULL,   -- spill_report_filed, notice_of_violation, site_inspection, nov_response_filed
    protocol_id            TEXT,
    related_inspection_id  TEXT REFERENCES inspections(inspection_id),
    detail                 TEXT,
    hours_to_report        REAL,
    fine_usd               REAL,
    status                 TEXT             -- open | closed
);
CREATE INDEX IF NOT EXISTS idx_regulatory_asset ON regulatory_events(asset_id, date);
CREATE INDEX IF NOT EXISTS idx_regulatory_inspection ON regulatory_events(related_inspection_id);

-- fleet/well-types/*.md and fleet/sops/*.md
CREATE TABLE IF NOT EXISTS documents (
    doc_id     TEXT PRIMARY KEY,     -- file stem: T200, spill-response-sop, ...
    kind       TEXT NOT NULL,        -- well_manual | sop
    well_type  TEXT,                 -- set for well manuals
    file_path  TEXT NOT NULL,
    title      TEXT,
    body_md    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_sections (
    doc_id        TEXT NOT NULL REFERENCES documents(doc_id),
    ord           INTEGER NOT NULL,
    level         INTEGER NOT NULL,
    heading       TEXT NOT NULL,
    section_path  TEXT NOT NULL,     -- "9. Engineering limits > 9.3 Production temperature rule"
    body          TEXT NOT NULL,
    PRIMARY KEY (doc_id, ord)
);

-- ============================================================================
-- Layer 1 + 2: tables shared by the dataset and the copilot (column `source`)
-- ============================================================================

-- Human notes: assets/WELL-XXXX/context.jsonl (source = 'dataset') plus facts that users
-- tell the copilot (source = 'copilot'). This is the SHARED knowledge about a well: every
-- user sees every note.
CREATE TABLE IF NOT EXISTS notes (
    note_id         TEXT PRIMARY KEY,
    source          TEXT NOT NULL CHECK (source IN ('dataset', 'copilot')),
    asset_id        TEXT NOT NULL REFERENCES wells(asset_id),
    created_at      TEXT NOT NULL,
    author_user_id  TEXT REFERENCES users(user_id),
    note_type       TEXT NOT NULL,   -- dataset: operator_feedback | operator_note | correction
    inspection_id   TEXT,            -- dataset: only on 'correction' notes
    text            TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,            -- NULL = open-ended
    -- For copilot notes that state a fact about the well ("WELL-0175 is running fine").
    -- 'unconfirmed' when it disagrees with the data; the copilot keeps it and says so.
    claim_status    TEXT CHECK (claim_status IN ('consistent', 'unconfirmed', 'confirmed', 'retracted')),
    conversation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_notes_asset ON notes(asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notes_inspection ON notes(inspection_id);

-- Record-level overrides. One row = one field of one record, with full provenance.
-- The original value stays in the source table; views apply the latest active row.
--   source = 'dataset': a context.jsonl correction note (cancels a spill detection)
--   source = 'copilot': user feedback on raw data ("reading was 41.0 °C") or on the
--                       AI analysis ("spill was 5.4 bbl, not 4.5")
CREATE TABLE IF NOT EXISTS corrections (
    correction_id     TEXT PRIMARY KEY,
    source            TEXT NOT NULL CHECK (source IN ('dataset', 'copilot')),
    kind              TEXT NOT NULL CHECK (kind IN ('raw_data', 'ai_analysis')),
    target_table      TEXT NOT NULL CHECK (target_table IN ('inspections', 'maintenance', 'wells')),
    target_id         TEXT NOT NULL,          -- inspection_id / maintenance_id / asset_id
    asset_id          TEXT NOT NULL REFERENCES wells(asset_id),
    field             TEXT NOT NULL,          -- e.g. wellhead_temp_c, spill_detected, spill_est_volume_bbl
    original_value    NUMERIC,
    corrected_value   NUMERIC,
    author_user_id    TEXT REFERENCES users(user_id),
    reason            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retracted', 'superseded')),
    note_id           TEXT REFERENCES notes(note_id),   -- dataset correction note it came from
    conversation_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_corrections_target ON corrections(target_table, target_id, field, status);

-- Thresholds and deadlines. source = 'document' rows are parsed from the manuals and SOPs
-- by the loader (with the section they came from). source = 'user' rows are feedback
-- such as "for all T350 wells, RCA after 2 repairs".
-- Scope: asset_id set -> one well; else well_type set -> one type; else -> all wells.
CREATE TABLE IF NOT EXISTS rules (
    rule_id          INTEGER PRIMARY KEY,
    rule_key         TEXT NOT NULL,       -- production_min_delta_c, rca_corrective_count, ...
    well_type        TEXT,
    asset_id         TEXT REFERENCES wells(asset_id),
    value            REAL NOT NULL,
    unit             TEXT,
    source           TEXT NOT NULL CHECK (source IN ('document', 'user')),
    doc_id           TEXT,                -- document rules: where it came from
    section_path     TEXT,
    protocol_id      TEXT,                -- SR-01, RC-04, ... when the rule is a protocol row
    source_text      TEXT,                -- the sentence or table row, for citations
    author_user_id   TEXT REFERENCES users(user_id),
    reason           TEXT,
    created_at       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retracted', 'superseded')),
    conversation_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_rules_key ON rules(rule_key, status);

-- ============================================================================
-- Layer 2: private memory (per user)
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id  TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(user_id),
    started_at       TEXT NOT NULL,
    title            TEXT,
    summary          TEXT              -- short summary for recall in later chats
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, started_at);

CREATE TABLE IF NOT EXISTS messages (
    message_id       INTEGER PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(conversation_id),
    created_at       TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content          TEXT NOT NULL,
    payload          TEXT              -- JSON: tool calls, visual spec, citations
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, message_id);

-- Entities an answer was about, so "the three wells we discussed yesterday" resolves by
-- (user, time) without reading old transcripts. Always filtered by the asking user.
CREATE TABLE IF NOT EXISTS conversation_entities (
    conversation_id  TEXT NOT NULL REFERENCES conversations(conversation_id),
    message_id       INTEGER REFERENCES messages(message_id),
    entity_type      TEXT NOT NULL,    -- well | area | inspection | maintenance | event
    entity_id        TEXT NOT NULL,
    rank             INTEGER,          -- order in the answer (e.g. top-3 list)
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_entities ON conversation_entities(conversation_id, entity_type);

-- ============================================================================
-- Full-text search over every text source
-- ============================================================================

-- kind: report_section | doc_section | note | inspection_note
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    kind UNINDEXED,
    ref_id UNINDEXED,        -- maintenance_id / doc_id / note_id / inspection_id
    asset_id UNINDEXED,
    heading,
    body,
    tokenize = 'porter unicode61'
);

-- ============================================================================
-- Layer 3: views
-- ============================================================================

-- One effective value per (well, rule_key).
-- Precedence: user rules over document rules; then the narrower scope (well > type > all);
-- then the newest.
DROP VIEW IF EXISTS well_rules;
CREATE VIEW well_rules AS
SELECT asset_id, rule_key, value, unit, rule_id, source, scope, doc_id, section_path,
       protocol_id, author_user_id
FROM (
    SELECT w.asset_id, r.rule_key, r.value, r.unit, r.rule_id, r.source,
           CASE WHEN r.asset_id IS NOT NULL THEN 'well'
                WHEN r.well_type IS NOT NULL THEN 'well_type'
                ELSE 'all' END AS scope,
           r.doc_id, r.section_path, r.protocol_id, r.author_user_id,
           ROW_NUMBER() OVER (
               PARTITION BY w.asset_id, r.rule_key
               ORDER BY (r.source = 'user') DESC,
                        (r.asset_id IS NOT NULL) DESC,
                        (r.well_type IS NOT NULL) DESC,
                        r.created_at DESC, r.rule_id DESC
           ) AS rn
    FROM wells w
    JOIN rules r
      ON r.status = 'active'
     AND (r.asset_id = w.asset_id
          OR (r.asset_id IS NULL AND (r.well_type = w.well_type OR r.well_type IS NULL)))
)
WHERE rn = 1;

-- Latest active correction per (record, field).
DROP VIEW IF EXISTS corrections_current;
CREATE VIEW corrections_current AS
SELECT *
FROM (
    SELECT c.*,
           ROW_NUMBER() OVER (
               PARTITION BY c.target_table, c.target_id, c.field
               ORDER BY c.created_at DESC, c.correction_id DESC
           ) AS rn
    FROM corrections c
    WHERE c.status = 'active'
)
WHERE rn = 1;

-- Inspections with corrections applied and the producing rule evaluated.
-- raw_* columns keep the recorded values; the plain names are the effective values.
DROP VIEW IF EXISTS inspections_effective;
CREATE VIEW inspections_effective AS
WITH cc AS (SELECT * FROM corrections_current WHERE target_table = 'inspections'),
     thr AS (SELECT asset_id, value, rule_id FROM well_rules WHERE rule_key = 'production_min_delta_c'),
     dpi AS (SELECT asset_id, value FROM well_rules WHERE rule_key = 'downtime_days_per_inspection')
SELECT
    i.inspection_id, i.asset_id, w.well_type, w.area_id,
    i.inspected_at, i.inspected_date, i.inspector_user_id, i.method, i.notes,
    i.ambient_temp_c       AS raw_ambient_temp_c,
    i.wellhead_temp_c      AS raw_wellhead_temp_c,
    i.spill_detected       AS raw_spill_detected,
    i.spill_est_volume_bbl AS raw_spill_est_volume_bbl,
    i.spill_area_pct       AS raw_spill_area_pct,
    COALESCE(c_amb.corrected_value, i.ambient_temp_c)        AS ambient_temp_c,
    COALESCE(c_wh.corrected_value,  i.wellhead_temp_c)       AS wellhead_temp_c,
    COALESCE(c_wh.corrected_value,  i.wellhead_temp_c)
      - COALESCE(c_amb.corrected_value, i.ambient_temp_c)    AS temp_delta_c,
    thr.value                                                AS producing_threshold_c,
    thr.rule_id                                              AS producing_rule_id,
    (COALESCE(c_wh.corrected_value, i.wellhead_temp_c)
      - COALESCE(c_amb.corrected_value, i.ambient_temp_c)) >= thr.value AS is_producing,
    CASE WHEN (COALESCE(c_wh.corrected_value, i.wellhead_temp_c)
               - COALESCE(c_amb.corrected_value, i.ambient_temp_c)) >= thr.value
         THEN 0 ELSE dpi.value END                           AS downtime_days,
    COALESCE(c_sd.corrected_value,  i.spill_detected)        AS spill_detected,
    COALESCE(c_vol.corrected_value, i.spill_est_volume_bbl)  AS spill_volume_bbl,
    COALESCE(c_area.corrected_value, i.spill_area_pct)       AS spill_area_pct,
    -- IDs of the corrections that changed this row, for citations
    NULLIF(trim(
        COALESCE(c_amb.correction_id || ' ', '') || COALESCE(c_wh.correction_id || ' ', '') ||
        COALESCE(c_sd.correction_id || ' ', '')  || COALESCE(c_vol.correction_id || ' ', '') ||
        COALESCE(c_area.correction_id, '')), '')             AS correction_ids
FROM inspections i
JOIN wells w ON w.asset_id = i.asset_id
LEFT JOIN thr ON thr.asset_id = i.asset_id
LEFT JOIN dpi ON dpi.asset_id = i.asset_id
LEFT JOIN cc c_amb  ON c_amb.target_id  = i.inspection_id AND c_amb.field  = 'ambient_temp_c'
LEFT JOIN cc c_wh   ON c_wh.target_id   = i.inspection_id AND c_wh.field   = 'wellhead_temp_c'
LEFT JOIN cc c_sd   ON c_sd.target_id   = i.inspection_id AND c_sd.field   = 'spill_detected'
LEFT JOIN cc c_vol  ON c_vol.target_id  = i.inspection_id AND c_vol.field  = 'spill_est_volume_bbl'
LEFT JOIN cc c_area ON c_area.target_id = i.inspection_id AND c_area.field = 'spill_area_pct';

-- Real spills only (after corrections), classed by the Spill Response SOP thresholds,
-- with the repair, report and containment time linked.
DROP VIEW IF EXISTS spills;
CREATE VIEW spills AS
WITH r AS (
    SELECT asset_id,
           MAX(CASE WHEN rule_key = 'spill_moderate_min_bbl'   THEN value END) AS moderate_min,
           MAX(CASE WHEN rule_key = 'spill_reportable_min_bbl' THEN value END) AS reportable_min,
           MAX(CASE WHEN rule_key = 'spill_major_min_bbl'      THEN value END) AS major_min
    FROM well_rules GROUP BY asset_id
)
SELECT
    e.inspection_id, e.asset_id, e.well_type, e.area_id, e.inspected_at, e.inspected_date,
    e.spill_volume_bbl, e.raw_spill_est_volume_bbl, e.spill_area_pct, e.notes, e.correction_ids,
    CASE WHEN e.spill_volume_bbl >= r.major_min      THEN 'major'
         WHEN e.spill_volume_bbl >= r.reportable_min THEN 'reportable'
         WHEN e.spill_volume_bbl >= r.moderate_min   THEN 'moderate'
         ELSE 'minor' END                                   AS spill_class,
    e.spill_volume_bbl >= r.reportable_min                  AS is_reportable,
    m.maintenance_id, mr.file_path AS report_path, mr.containment_hours
FROM inspections_effective e
JOIN r ON r.asset_id = e.asset_id
LEFT JOIN maintenance m ON m.triggered_by_inspection_id = e.inspection_id
LEFT JOIN maintenance_reports mr ON mr.maintenance_id = m.maintenance_id
WHERE e.spill_detected = 1;

-- "Right now" = each well's latest inspection.
DROP VIEW IF EXISTS well_status_now;
CREATE VIEW well_status_now AS
SELECT
    w.asset_id, w.name, w.well_type, w.area_id, a.name AS area_name, w.lat, w.lon,
    w.recorded_status,
    e.inspection_id, e.inspected_at, e.inspector_user_id, e.method,
    e.ambient_temp_c, e.wellhead_temp_c, e.temp_delta_c, e.producing_threshold_c,
    e.is_producing, e.notes AS inspection_notes, e.correction_ids,
    (CASE WHEN e.is_producing THEN 'active' ELSE 'down' END) <> w.recorded_status AS recorded_status_stale
FROM wells w
JOIN areas a ON a.area_id = w.area_id
JOIN inspections_effective e
  ON e.inspection_id = (SELECT i.inspection_id FROM inspections i
                        WHERE i.asset_id = w.asset_id
                        ORDER BY i.inspected_at DESC LIMIT 1);
