# Final questions: full answers (web UI threads)

## Q1 turn 1 — Michael Turner (U-201)
_Thread: 01a149c5-b68b-7c60-8a5d-6d85fdb9fc67_

> All our wells feed one reservoir. Map the reservoir pressure across the field from the pressure data.

The data has no measurement for reservoir pressure. I cannot create a reservoir pressure map because pressure is not a recorded field in the inspection or well data.

The closest proxy available is wellhead temperature, which is recorded during inspections and can be mapped by area to show thermal trends across the field. Would you like me to show a map of wellhead temperatures instead?

<details><summary>Tool calls and citations</summary>

- `data_coverage({"topic": "reservoir pressure"})`

</details>

_Check: passed — verified against the tool results: nothing to check_

## Q2 turn 1 — Robert Hayes (U-301)
_Thread: 01a149c5-b68b-7c60-8a5d-6d70d7cae0d1_

> Which well produced the most oil in 2026?

The data has no recorded oil volumes or production rates. As a proxy, I have identified the well with the most producing days (uptime) during 2026 (from 2026-01-01 to 2026-12-31).

**Top Well by Uptime Proxy (2026):**
*   **Well ID:** WELL-0212
*   **Area:** Southeast Block 31
*   **Type:** T500
*   **Producing Days:** 371 (based on 53 producing inspections)
*   **Mean Temperature Delta:** 36.6 °C above air

*Note: This ranking is based on weekly inspections multiplied by 7 days and does not represent actual barrels of oil produced (Source: producing_days r_92c9).*

**Visual: table** — Top Producing Well (by Uptime Proxy) in 2026  
fields: `{"columns": ["asset_id", "area", "inspections", "mean_delta_c", "producing_days", "well_type"]}`

| asset_id | area | inspections | mean_delta_c | producing_days | well_type |
|---|---|---|---|---|---|
| WELL-0212 | Southeast Block 31 | 53 | 36.6 | 371 | T500 |

<details><summary>Tool calls and citations</summary>

- `data_coverage({"topic": "oil volume"})`
- `producing_days({"end": "2026-12-31", "start": "2026-01-01", "top_n": 1})`
- `show_visual({"fields": {"asset_id": "asset_id", "area": "area", "inspections": "inspections", "mean_delta_c": "mean_delta_c", "producing_days": "producing_days", "well_type": "well_type"}, "source": "r_92c9", "title": "Top Producing Well (by Uptime Proxy) in 2026", "type": "table"})`

Citations: WELL-0212

</details>

_Check: failed — not verified: 1 problem(s) (1 ids, 6 numbers checked)_

## Q3 turn 1 — Laura Simmons (U-401)
_Thread: 01a149c5-b68b-7c60-8a5d-6da2919b946a_

> Since 1 Nov 2026, every time an operator note reports gas at a well, did we get someone out to that well in time under our operating procedures? List every report and whether the response met the deadline.

Since 1 November 2026, there have been 26 gas reports. Of these, 17 met the response deadline and 9 missed it.

The response deadline is 24 hours for reports before 1 January 2027, and 12 hours for reports on or after 1 January 2027 (per Operations SOP rev 2, §OPS-1).

### Gas Reports Summary (2026-11-01 to 2027-01-15)

| Well ID | Reported At | Deadline (h) | Response Time (h) | Result | Note ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| WELL-0163 | 2026-11-03 20:55 | 24 | 251.1 | **Missed** | CTX-0163-002 |
| WELL-0149 | 2026-11-06 18:20 | 24 | 13.7 | Met | CTX-0149-004 |
| WELL-0165 | 2026-11-13 20:35 | 24 | 11.4 | Met | CTX-0165-001 |
| WELL-0341 | 2026-11-19 07:40 | 24 | 677.8 | **Missed** | CTX-0341-002 |
| WELL-0091 | 2026-11-27 22:25 | 24 | 9.6 | Met | CTX-0091-001 |
| WELL-0423 | 2026-12-03 05:25 | 24 | 3.8 | Met | CTX-0423-002 |
| WELL-0059 | 2026-12-03 06:10 | 24 | 6.1 | Met | CTX-0059-002 |
| WELL-0332 | 2026-12-03 12:10 | 24 | N/A | **Missed** | CTX-0332-004 |
| WELL-0401 | 2026-12-05 13:50 | 24 | 138.2 | **Missed** | CTX-0401-002 |
| WELL-0189 | 2026-12-10 12:35 | 24 | 19.4 | Met | CTX-0189-003 |
| WELL-0403 | 2026-12-10 21:15 | 24 | 10.8 | Met | CTX-0403-004 |
| WELL-0244 | 2026-12-11 05:25 | 24 | 2.6 | Met | CTX-0244-002 |
| WELL-0040 | 2026-12-12 01:55 | 24 | 6.1 | Met | CTX-0040-002 |
| WELL-0228 | 2026-12-16 19:50 | 24 | 16.9 | Met | CTX-0228-004 |
| WELL-0052 | 2026-12-18 06:45 | 24 | N/A | **Missed** | CTX-0052-003 |
| WELL-0370 | 2026-12-21 12:45 | 24 | 19.2 | Met | CTX-0370-005 |
| WELL-0362 | 2026-12-24 00:15 | 24 | 31.8 | **Missed** | CTX-0362-002 |
| WELL-0161 | 2026-12-25 15:45 | 24 | 475.2 | **Missed** | CTX-0161-006 |
| WELL-0135 | 2026-12-27 03:50 | 24 | 4.2 | Met | CTX-0135-009 |
| WELL-0324 | 2027-01-01 22:40 | 12 | 9.3 | Met | CTX-0324-001 |
| WELL-0330 | 2027-01-02 21:40 | 12 | 10.3 | Met | CTX-0330-003 |
| WELL-0599 | 2027-01-06 17:20 | 12 | 16.4 | **Missed** | CTX-0599-003 |
| WELL-0516 | 2027-01-06 21:15 | 12 | 15.0 | **Missed** | CTX-0516-002 |
| WELL-0425 | 2027-01-07 05:20 | 12 | 3.7 | Met | CTX-0425-006 |
| WELL-0465 | 2027-01-08 23:35 | 12 | 8.4 | Met | CTX-0465-005 |
| WELL-0137 | 2027-01-10 23:30 | 12 | 8.5 | Met | CTX-0137-004 |

**Visual: table** — Gas Reports and Response Compliance (Since 2026-11-01)  
fields: `{"columns": ["asset_id", "deadline_hours", "hours_to_response", "note_id", "reported_at", "result"]}`

| asset_id | deadline_hours | hours_to_response | note_id | reported_at | result |
|---|---|---|---|---|---|
| WELL-0163 | 24 | 251.1 | CTX-0163-002 | 2026-11-03 20:55 UTC | Missed |
| WELL-0149 | 24 | 13.7 | CTX-0149-004 | 2026-11-06 18:20 UTC | Met |
| WELL-0165 | 24 | 11.4 | CTX-0165-001 | 2026-11-13 20:35 UTC | Met |
| WELL-0341 | 24 | 677.8 | CTX-0341-002 | 2026-11-19 07:40 UTC | Missed |
| WELL-0091 | 24 | 9.6 | CTX-0091-001 | 2026-11-27 22:25 UTC | Met |
| WELL-0423 | 24 | 3.8 | CTX-0423-002 | 2026-12-03 05:25 UTC | Met |
| WELL-0059 | 24 | 6.1 | CTX-0059-002 | 2026-12-03 06:10 UTC | Met |
| WELL-0332 | 24 |  | CTX-0332-004 | 2026-12-03 12:10 UTC | Missed |
| WELL-0401 | 24 | 138.2 | CTX-0401-002 | 2026-12-05 13:50 UTC | Missed |
| WELL-0189 | 24 | 19.4 | CTX-0189-003 | 2026-12-10 12:35 UTC | Met |
| WELL-0403 | 24 | 10.8 | CTX-0403-004 | 2026-12-10 21:15 UTC | Met |
| WELL-0244 | 24 | 2.6 | CTX-0244-002 | 2026-12-11 05:25 UTC | Met |
| WELL-0040 | 24 | 6.1 | CTX-0040-002 | 2026-12-12 01:55 UTC | Met |
| WELL-0228 | 24 | 16.9 | CTX-0228-004 | 2026-12-16 19:50 UTC | Met |
| WELL-0052 | 24 |  | CTX-0052-003 | 2026-12-18 06:45 UTC | Missed |
| WELL-0370 | 24 | 19.2 | CTX-0370-005 | 2026-12-21 12:45 UTC | Met |
| WELL-0362 | 24 | 31.8 | CTX-0362-002 | 2026-12-24 00:15 UTC | Missed |
| WELL-0161 | 24 | 475.2 | CTX-0161-006 | 2026-12-25 15:45 UTC | Missed |
| WELL-0135 | 24 | 4.2 | CTX-0135-009 | 2026-12-27 03:50 UTC | Met |
| WELL-0324 | 12 | 9.3 | CTX-0324-001 | 2027-01-01 22:40 UTC | Met |
| WELL-0330 | 12 | 10.3 | CTX-0330-003 | 2027-01-02 21:40 UTC | Met |
| WELL-0599 | 12 | 16.4 | CTX-0599-003 | 2027-01-06 17:20 UTC | Missed |
| WELL-0516 | 12 | 15.0 | CTX-0516-002 | 2027-01-06 21:15 UTC | Missed |
| WELL-0425 | 12 | 3.7 | CTX-0425-006 | 2027-01-07 05:20 UTC | Met |
| WELL-0465 | 12 | 8.4 | CTX-0465-005 | 2027-01-08 23:35 UTC | Met |
| WELL-0137 | 12 | 8.5 | CTX-0137-004 | 2027-01-10 23:30 UTC | Met |

<details><summary>Tool calls and citations</summary>

- `gas_reports({"start": "2026-11-01"})`
- `show_visual({"fields": {"asset_id": "asset_id", "deadline_hours": "deadline_hours", "hours_to_response": "hours_to_response", "note_id": "note_id", "reported_at": "reported_at", "result": "result"}, "source": "r_d118", "title": "Gas Reports and Response Compliance (Since 2026-11-01)", "type": "table"})`

Citations: operations-sop-rev2 §OPS-1 Gas odor response, MNT-0163-019, CTX-0163-002, MNT-0149-029, CTX-0149-004, MNT-0165-031, CTX-0165-001, INS-0341-0109, CTX-0341-002, MNT-0091-019, CTX-0091-001, INS-0423-0213, CTX-0423-002, INS-0059-0213, CTX-0059-002, CTX-0332-004, MNT-0401-033, CTX-0401-002, MNT-0189-037, CTX-0189-003, MNT-0403-024, CTX-0403-004, MNT-0244-026, CTX-0244-002, MNT-0040-029, CTX-0040-002, INS-0228-0144, CTX-0228-004, CTX-0052-003, MNT-0370-028, CTX-0370-005, MNT-0362-030, CTX-0362-002, INS-0161-0168, CTX-0161-006, MNT-0135-034, CTX-0135-009, MNT-0324-036, CTX-0324-001, MNT-0330-030, CTX-0330-003, INS-0599-0196, CTX-0599-003, INS-0516-0215, CTX-0516-002, INS-0425-0218, CTX-0425-006, MNT-0465-031, CTX-0465-005, MNT-0137-032, CTX-0137-004

</details>

_Check: failed — not verified: 1 problem(s) (52 ids, 87 numbers checked)_

## Q4 turn 1 — Chris Dalton (U-402)
_Thread: 01a149c5-b68b-7c60-8a5d-6d9ca34d154d_

> Across all areas, which temporary flowline bypasses are in place right now, and is each one allowed? Also list any bypass, past or present, that stayed in after its approval ran out or was never approved at all.

There are currently 3 temporary flowline bypasses in place:

| Well ID | Area | Bypass In | Bypass Out | Status | MOC ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| WELL-0248 | Southeast Block 31 | 2026-11-05 | still in | Allowed | MOC-2026-031 |
| WELL-0249 | Southeast Block 31 | 2026-11-25 | still in | Expired | MOC-2026-036 |
| WELL-0405 | Northwest Block 12 | 2026-12-20 | still in | Not approved | N/A |

The following bypasses are recorded as having stayed in after their approval expired or were never approved:

| Well ID | Area | Bypass In | Bypass Out | Status | MOC ID |
| :--- | :--- | :--- | :--- | :--- | :--- |
| WELL-0087 | Southwest Block 24 | 2026-12-02 | 2027-01-06 | Expired | MOC-2026-036 |
| WELL-0158 | Northeast Block 8 | 2026-11-20 | 2026-12-28 | Expired | MOC-2026-036 |
| WELL-0249 | Southeast Block 31 | 2026-11-25 | still in | Expired | MOC-2026-036 |
| WELL-0405 | Northwest Block 12 | 2026-12-20 | still in | Not approved | N/A |
| WELL-0561 | Southeast Block 32 | 2026-12-08 | 2026-12-19 | Not approved | N/A |

**Visual: table** — Current and Past Flowline Bypasses  
fields: `{"columns": ["asset_id", "area", "bypass_in", "bypass_out", "status", "moc_id"]}`

| asset_id | area | bypass_in | bypass_out | status | moc_id |
|---|---|---|---|---|---|
| WELL-0013 | Southwest Block 23 | 2026-11-10 | 2027-01-08 | Allowed | MOC-2026-031 |
| WELL-0062 | Southwest Block 24 | 2026-11-02 | 2026-11-27 | Allowed | MOC-2026-031 |
| WELL-0087 | Southwest Block 24 | 2026-12-02 | 2027-01-06 | Expired | MOC-2026-036 |
| WELL-0158 | Northeast Block 8 | 2026-11-20 | 2026-12-28 | Expired | MOC-2026-036 |
| WELL-0248 | Southeast Block 31 | 2026-11-05 | still in | Allowed | MOC-2026-031 |
| WELL-0249 | Southeast Block 31 | 2026-11-25 | still in | Expired | MOC-2026-036 |
| WELL-0284 | Southwest Block 24 | 2026-11-12 | 2026-12-10 | Allowed | MOC-2026-036 |
| WELL-0356 | Northwest Block 12 | 2026-11-18 | 2026-12-05 | Allowed | MOC-2026-036 |
| WELL-0405 | Northwest Block 12 | 2026-12-20 | still in | Not approved |  |
| WELL-0461 | Southeast Block 32 | 2026-11-14 | 2026-12-12 | Allowed | MOC-2026-036 |
| WELL-0476 | Southeast Block 32 | 2026-10-22 | 2026-11-18 | Allowed | MOC-2026-031 |
| WELL-0561 | Southeast Block 32 | 2026-12-08 | 2026-12-19 | Not approved |  |

<details><summary>Tool calls and citations</summary>

- `bypasses({})`
- `show_visual({"fields": {"{\"asset_id\"": "\"asset_id\"", "\"area\"": "\"area\"", "\"bypass_in\"": "\"bypass_in\"", "\"bypass_out\"": "\"bypass_out\"", "\"moc_id\"": "\"moc_id\"", "\"status\"": "\"status\""}, "source": "r_034f", "title": "Current and Past Flowline Bypasses", "type": "table"})`
- `show_visual({"fields": {"columns": ["asset_id", "area", "bypass_in", "bypass_out", "status", "moc_id"]}, "source": "r_034f", "title": "Current and Past Flowline Bypasses", "type": "table"})`

Citations: operations-sop-rev2 §OPS-2 Temporary bypass, MOC-2026-031, MOC-2026-044, CTX-0013-002, CTX-0013-005, CTX-0062-002, CTX-0062-005, MOC-2026-036, CTX-0087-001, CTX-0087-004, CTX-0158-003, CTX-0158-005, CTX-0248-002, CTX-0249-002, CTX-0284-002, CTX-0284-003, CTX-0356-002, CTX-0356-003, CTX-0405-003, CTX-0461-002, CTX-0461-003, CTX-0476-002, CTX-0476-003, CTX-0561-004, CTX-0561-005

</details>

_Check: passed — verified against the tool results: 6 ids, 15 numbers_

## Q5 turn 1 — Michael Turner (U-201)
_Thread: 01a149c5-de25-77e3-959f-d78ab8e8e354_

> The State Oil & Gas Commission wrote to us in November 2026 about spills. Which of our spills does the letter cover, and on which ones are we not compliant? Show me a table.

The State Oil & Gas Commission letter covers reportable spills (≥ 5 bbl) in Northeast Block 7 and Northeast Block 8 discovered since 2026-06-01. 

There are **6 spills** covered by the letter, and we are **not compliant on 3** of them because the clean-up reports did not include the required statement: "Soil samples sent to the lab." (Note: field soil readings/TPH results do not satisfy this requirement).

### Non-Compliant Spills
| Well ID | Area | Inspection Date | Volume (bbl) | Reason for Non-Compliance |
| :--- | :--- | :--- | :--- | :--- |
| WELL-0123 | NE-07 | 2026-09-24 | 6.0 | clean-up report has no "Soil samples sent to the lab." (INS-0123-0093) |
| WELL-0182 | NE-08 | 2026-12-03 | 5.2 | clean-up report has no "Soil samples sent to the lab." (INS-0182-0208) |
| WELL-0262 | NE-08 | 2027-01-07 | 6.1 | clean-up report has no "Soil samples sent to the lab." (INS-0262-0218) |

### All Covered Spills
| Well ID | Area | Inspection Date | Volume (bbl) | Compliant |
| :--- | :--- | :--- | :--- | :--- |
| WELL-0123 | NE-07 | 2026-09-24 | 6.0 | No |
| WELL-0277 | NE-07 | 2026-10-01 | 6.2 | Yes |
| WELL-0119 | NE-07 | 2026-11-05 | 6.0 | Yes |
| WELL-0168 | NE-08 | 2026-06-11 | 5.6 | Yes |
| WELL-0182 | NE-08 | 2026-12-03 | 5.2 | No |
| WELL-0262 | NE-08 | 2027-01-07 | 6.1 | No |

**Visual: table** — Spills Covered by State Commission Letter (NE-07)  
fields: `{"columns": ["asset_id", "compliant", "inspected_date", "reason", "volume_bbl"]}`

| asset_id | compliant | inspected_date | reason | volume_bbl |
|---|---|---|---|---|
| WELL-0123 | No | 2026-09-24 | clean-up report has no "Soil samples sent to the lab."; only field soil readings (TPH on site), which do not count | 6.0 |
| WELL-0277 | Yes | 2026-10-01 | clean-up report says "Soil samples sent to the lab." | 6.2 |
| WELL-0119 | Yes | 2026-11-05 | clean-up report says "Soil samples sent to the lab." | 6.0 |

**Visual: table** — Spills Covered by State Commission Letter (NE-08)  
fields: `{"columns": ["asset_id", "compliant", "inspected_date", "reason", "volume_bbl"]}`

| asset_id | compliant | inspected_date | reason | volume_bbl |
|---|---|---|---|---|
| WELL-0168 | Yes | 2026-06-11 | clean-up report says "Soil samples sent to the lab." | 5.6 |
| WELL-0182 | No | 2026-12-03 | clean-up report has no "Soil samples sent to the lab."; only field soil readings (TPH on site), which do not count | 5.2 |
| WELL-0262 | No | 2027-01-07 | clean-up report has no "Soil samples sent to the lab."; only field soil readings (TPH on site), which do not count | 6.1 |

<details><summary>Tool calls and citations</summary>

- `regulator_letter_spills({"area": "Northeast Block 7"})`
- `regulator_letter_spills({"area": "Northeast Block 8"})`
- `show_visual({"fields": {"asset_id": "asset_id", "compliant": "compliant", "inspected_date": "inspected_date", "reason": "reason", "volume_bbl": "volume_bbl"}, "source": "r_c314", "title": "Spills Covered by State Commission Letter (NE-07)", "type": "table"})`
- `show_visual({"fields": {"asset_id": "asset_id", "compliant": "compliant", "inspected_date": "inspected_date", "reason": "reason", "volume_bbl": "volume_bbl"}, "source": "r_c6bb", "title": "Spills Covered by State Commission Letter (NE-08)", "type": "table"})`

Citations: regulator-letter-2026-11-20 §Letter from the State Oil & Gas Commission, spill-response-sop §3. Spill classes, spill-response-sop §7. False positives, MNT-0123-014, INS-0123-0093, MNT-0277-031, INS-0277-0205, MNT-0119-029, INS-0119-0209, MNT-0168-024, INS-0168-0190, MNT-0182-028, INS-0182-0208, MNT-0262-029, INS-0262-0218

</details>

_Check: passed — verified against the tool results: 9 ids, 9 numbers_

## Q6 turn 1 — Nathan Pierce (U-601)
_Thread: 01a149c6-5578-7282-be22-eb0bd10a130a_

> Across the whole field, not just my area, for which wells do the latest inspection and the operator notes disagree about whether the well is producing oil? For each one, what is its real status right now, and why?

There are 12 wells across the field where the latest inspection and the latest operator note disagree on production status. Per Operations SOP OPS-3, the most recent record (either the inspection or the note) determines the current status.

| Well ID | Current Status | Reason for Status | Evidence (Inspection vs. Note) |
| :--- | :--- | :--- | :--- |
| **WELL-0323** | Not producing oil | The shut-in note is newer than the inspection (r_a336). | Inspection (INS-0323-0219) showed producing; Note (CTX-0323-002) reported shut in due to a stuffing box leak. |
| **WELL-0330** | Not producing oil | The inspection is newer than the restart note (r_a336). | Note (CTX-0330-002) reported a restart; Inspection (INS-0330-0213) showed not producing. |
| **WELL-0355** | Not producing oil | The shut-in note is newer than the inspection (r_a336). | Inspection (INS-0355-0213) showed producing; Note (CTX-0355-004) reported shut in due to a stuffing box leak. |
| **WELL-0422** | Not producing oil | The shut-in note is newer than the inspection (r_a336). | Inspection (INS-0422-0215) showed producing; Note (CTX-0422-003) reported shut in due to a high pressure alarm. |
| **WELL-0479** | Not producing oil | The shut-in note is newer than the inspection (r_a336). | Inspection (INS-0479-0213) showed producing; Note (CTX-0479-004) reported shut in due to a stuffing box leak. |
| **WELL-0481** | Not producing oil | The shut-in note is newer than the inspection (r_a336). | Inspection (INS-0481-0220) showed producing; Note (CTX-0481-006) reported shut in due to a high pressure alarm. |
| **WELL-0010** | Not producing oil | The inspection is newer than the restart note (r_a336). | Note (CTX-0010-004) reported a restart; Inspection (INS-0010-0219) showed not producing. |
| **WELL-0026** | Producing oil (unconfirmed) | The restart note is newer than the inspection (r_a336). | Inspection (INS-0026-0216) showed not producing; Note (CTX-0026-001) reported a restart. |
| **WELL-0032** | Producing oil (unconfirmed) | The restart note is newer than the inspection (r_a336). | Inspection (INS-0032-0219) showed not producing; Note (CTX-0032-006) reported a restart. |
| **WELL-0033** | Producing oil (unconfirmed) | The restart note is newer than the inspection (r_a336). | Inspection (INS-0033-0222) showed not producing; Note (CTX-0033-003) reported a restart. |
| **WELL-0044** | Not producing oil | The shut-in note is newer than the inspection (r_a336). | Inspection (INS-0044-0218) showed producing; Note (CTX-0044-008) reported shut in due to a suspected flowline leak. |
| **WELL-0046** | Producing oil (unconfirmed) | The restart note is newer than the inspection (r_a336). | Inspection (INS-0046-0220) showed not producing; Note (CTX-0046-004) reported a restart. |

**Visual: table** — Wells with Conflicting Production Status (Inspection vs. Operator Note)  
fields: `{"columns": ["asset_id", "inspection_id", "note_id", "note_text", "status_now", "why"]}`

| asset_id | inspection_id | note_id | note_text | status_now | why |
|---|---|---|---|---|---|
| WELL-0323 | INS-0323-0219 | CTX-0323-002 | Shut-in WELL-0323 after the pumper reported a stuffing box leak. | Not producing oil | The shut in note (2027-01-14 19:20) is newer than the inspection (2027-01-14 14:45), so it decides (OPS-3). |
| WELL-0330 | INS-0330-0213 | CTX-0330-002 | WELL-0330 put back on production after the repair crew finished. | Not producing oil | The inspection (2027-01-14 07:15) is newer than the restarted note (2026-12-19 06:00), so the inspection decides (OPS-3). |
| WELL-0355 | INS-0355-0213 | CTX-0355-004 | Found WELL-0355 leaking at the stuffing box, shut the well in. | Not producing oil | The shut in note (2027-01-14 19:05) is newer than the inspection (2027-01-14 15:15), so it decides (OPS-3). |
| WELL-0422 | INS-0422-0215 | CTX-0422-003 | Shut in WELL-0422 for the night, high pressure alarm on the separator. | Not producing oil | The shut in note (2027-01-14 21:35) is newer than the inspection (2027-01-14 15:15), so it decides (OPS-3). |
| WELL-0479 | INS-0479-0213 | CTX-0479-004 | Found WELL-0479 leaking at the stuffing box, shut the well in. | Not producing oil | The shut in note (2027-01-14 15:35) is newer than the inspection (2027-01-14 11:45), so it decides (OPS-3). |
| WELL-0481 | INS-0481-0220 | CTX-0481-006 | Shut in WELL-0481 for the night, high pressure alarm on the separator. | Not producing oil | The shut in note (2027-01-14 18:50) is newer than the inspection (2027-01-14 14:30), so it decides (OPS-3). |
| WELL-0010 | INS-0010-0219 | CTX-0010-004 | Restarted WELL-0010 after the crew cleared the lockout. | Not producing oil | The inspection (2027-01-14 14:00) is newer than the restarted note (2027-01-09 04:00), so the inspection decides (OPS-3). |
| WELL-0026 | INS-0026-0216 | CTX-0026-001 | WELL-0026 put back on production after the repair crew finished. | Producing oil (unconfirmed) | The restarted note (2027-01-15 10:25) is newer than the inspection (2027-01-14 12:15), so it decides (OPS-3). Unconfirmed until an inspection shows the well producing. |
| WELL-0032 | INS-0032-0219 | CTX-0032-006 | Brought WELL-0032 back online after the pump change. | Producing oil (unconfirmed) | The restarted note (2027-01-15 10:25) is newer than the inspection (2027-01-14 08:30), so it decides (OPS-3). Unconfirmed until an inspection shows the well producing. |
| WELL-0033 | INS-0033-0222 | CTX-0033-003 | Restarted WELL-0033, unit running smooth. | Producing oil (unconfirmed) | The restarted note (2027-01-15 10:25) is newer than the inspection (2027-01-14 14:45), so it decides (OPS-3). Unconfirmed until an inspection shows the well producing. |
| WELL-0044 | INS-0044-0218 | CTX-0044-008 | Shut in WELL-0044 at the wellhead, flowline leak suspected. | Not producing oil | The shut in note (2027-01-14 13:05) is newer than the inspection (2027-01-14 07:30), so it decides (OPS-3). |
| WELL-0046 | INS-0046-0220 | CTX-0046-004 | WELL-0046 put back on production after the repair crew finished. | Producing oil (unconfirmed) | The restarted note (2027-01-15 10:25) is newer than the inspection (2027-01-14 13:00), so it decides (OPS-3). Unconfirmed until an inspection shows the well producing. |

<details><summary>Tool calls and citations</summary>

- `status_conflicts({})`
- `show_visual({"fields": {"asset_id": "asset_id", "inspection_id": "inspection_id", "note_id": "note_id", "note_text": "note_text", "status_now": "status_now", "why": "why"}, "source": "r_a336", "title": "Wells with Conflicting Production Status (Inspection vs. Operator Note)", "type": "table"})`

Citations: operations-sop-rev2 §OPS-3 Status evidence precedence, WELL-0323, INS-0323-0219, CTX-0323-002, WELL-0330, INS-0330-0213, CTX-0330-002, WELL-0355, INS-0355-0213, CTX-0355-004, WELL-0422, INS-0422-0215, CTX-0422-003, WELL-0479, INS-0479-0213, CTX-0479-004, WELL-0481, INS-0481-0220, CTX-0481-006, WELL-0010, INS-0010-0219, CTX-0010-004, WELL-0026, INS-0026-0216, CTX-0026-001, WELL-0032, INS-0032-0219, CTX-0032-006, WELL-0033, INS-0033-0222, CTX-0033-003, WELL-0044, INS-0044-0218, CTX-0044-008, WELL-0046, INS-0046-0220, CTX-0046-004

</details>

_Check: passed — verified against the tool results: 36 ids_

## Q7 turn 1 — Robert Hayes (U-301)
_Thread: 01a149c6-6095-7610-abf9-5094fe9603fc_

> Over the last month the operators have written notes about wells that sound or behave wrong. Which of those wells haven't had a repair since? Rank the 10 most likely to need a repair in the next 90 days, other than a spill clean-up, and quote the notes as evidence.

Based on operator notes from the last month (2026-12-16 to 2027-01-15), here are the 10 wells most likely to need a repair in the next 90 days, ranked by their risk score.

| Rank | Well ID | Area | Well Type | Score | Evidence (Operator Notes) | Last Repair (ID, Date, Type, Issue) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | WELL-0336 | NW-12 | T500 | 11.5 | "amps hunting on the drive panel" (CTX-0336-003, 2026-12-24); "drive tripping on underload" (CTX-0336-004, 2027-01-07); "amps hunting on the drive panel" (CTX-0336-005, 2027-01-14) | MNT-0336-029 (2026-11-22, scheduled, wellhead valve service) |
| 2 | WELL-0344 | NW-12 | T500 | 10.0 | "amps hunting between 38 and 44 A" (CTX-0344-002, 2026-12-21); "amps hunting between 38 and 44 A" (CTX-0344-003, 2026-12-24); "drive tripping on and off overnight" (CTX-0344-004, 2027-01-04) | MNT-0344-035 (2026-12-01, scheduled, wellhead valve service) |
| 3 | WELL-0401 | NW-12 | T500 | 9.5 | "amps hunting on the drive panel" (CTX-0401-003, 2026-12-18); "amps hunting on the drive panel" (CTX-0401-004, 2027-01-14) | MNT-0401-033 (2026-12-11, scheduled, wellhead valve service) |
| 4 | WELL-0498 | SE-32 | T500 | 9.5 | "drive tripping on and off overnight" (CTX-0498-004, 2027-01-09); "drive tripping on underload" (CTX-0498-005, 2027-01-11); "drive tripping on underload" (CTX-0498-006, 2027-01-12) | MNT-0498-031 (2027-01-03, corrective, separator level controller fault) |
| 5 | WELL-0263 | SW-23 | T350 | 8.0 | "Heard fluid pound" (CTX-0263-004, 2027-01-11); "Rod squeal at stuffing box" (CTX-0263-005, 2027-01-14) | MNT-0263-035 (2027-01-09, corrective, flowline corrosion pinhole leak) |
| 6 | WELL-0175 | NE-08 | T200 | 7.5 | "Heard fluid pound" (CTX-0175-003, 2026-12-17); "Rod squeal at stuffing box" (CTX-0175-006, 2026-12-21); "tagging bottom on the downstroke" (CTX-0175-007, 2026-12-26) | MNT-0175-035 (2026-11-28, scheduled, wellhead valve service) |
| 7 | WELL-0182 | NE-08 | T200 | 7.5 | "Pumper reports rattling at pump jack" (CTX-0182-005, 2026-12-27); "tagging bottom on the downstroke" (CTX-0182-007, 2026-12-30); "Heard fluid pound" (CTX-0182-008, 2027-01-05) | MNT-0182-029 (2026-12-26, corrective, walking beam bearing wear) |
| 8 | WELL-0197 | NE-08 | T200 | 7.5 | "Pumper reports rattling at pump jack" (CTX-0197-002, 2027-01-04); "Heard fluid pound" (CTX-0197-003, 2027-01-08); "Heard fluid pound" (CTX-0197-004, 2027-01-12) | MNT-0197-029 (2027-01-01, corrective, sucker rod parted) |
| 9 | WELL-0219 | SE-31 | T500 | 7.5 | "drive tripping on underload" (CTX-0219-006, 2027-01-05); "amps hunting between 38 and 44 A" (CTX-0219-007, 2027-01-13) | MNT-0219-022 (2026-11-24, scheduled, wellhead valve service) |
| 10 | WELL-0005 | SW-23 | T350 | 7.0 | "Heard fluid pound" (CTX-0005-004, 2026-12-24); "tagging bottom on the downstroke" (CTX-0005-005, 2026-12-30); "Rod squeal at stuffing box" (CTX-0005-006, 2027-01-08) | MNT-0005-035 (2026-12-14, scheduled, lubrication and belt inspection) |

***Note:** The risk scores are a judgement based on the severity of the reported symptoms and historical repair frequency.*

<details><summary>Tool calls and citations</summary>

- `operator_concerns({"end": "2027-01-15", "start": "2026-12-16", "top_n": 10})`

Citations: WELL-0336, CTX-0336-003, CTX-0336-004, CTX-0336-005, MNT-0336-029, WELL-0344, CTX-0344-002, CTX-0344-003, CTX-0344-004, MNT-0344-035, WELL-0401, CTX-0401-003, CTX-0401-004, MNT-0401-033, WELL-0498, CTX-0498-004, CTX-0498-005, CTX-0498-006, MNT-0498-031, WELL-0263, CTX-0263-004, CTX-0263-005, MNT-0263-035, WELL-0175, CTX-0175-003, CTX-0175-006, CTX-0175-007, MNT-0175-035, WELL-0182, CTX-0182-005, CTX-0182-007, CTX-0182-008, MNT-0182-029, WELL-0197, CTX-0197-002, CTX-0197-003, CTX-0197-004, MNT-0197-029, WELL-0219, CTX-0219-006, CTX-0219-007, MNT-0219-022, WELL-0005, CTX-0005-004, CTX-0005-005, CTX-0005-006, MNT-0005-035

</details>

_Check: passed — verified against the tool results: 47 ids, 21 numbers_

## Q7 turn 2 — Robert Hayes (U-301)
_Thread: 01a149c6-6095-7610-abf9-5094fe9603fc_

> Which three would you send a crew to first this week, and why?

I would prioritize sending a crew to **WELL-0336**, **WELL-0344**, and **WELL-0401** first.

All three are high-risk T500 wells in the Northwest Block 12 area with very high risk scores (9.5 to 11.5) due to a combination of critical factors:

*   **WELL-0336 (Score 11.5):** This is the highest priority. It is showing active, repeated symptoms of "amps hunting" and "drive tripping" (CTX-0336-003, CTX-0336-004, CTX-0336-005). Additionally, it is showing a falling wellhead-to-air temperature difference, which the T500 manual (§5) identifies as an early warning sign requiring an ESP drive and insulation check.
*   **WELL-0344 (Score 10.0):** This well has a high score driven by repeated "amps hunting" and "drive tripping" (CTX-0344-002, CTX-0344-003, CTX-0344-004) and a significant history of 5 corrective repairs in the last 12 months.
*   **WELL-0401 (Score 9.5):** Similar to the others, it is experiencing repeated "amps hunting" (CTX-0401-003, CTX-0401-004) and is also showing the T500-specific falling temperature warning sign, indicating potential ESP drive or insulation issues.

_Check: passed — verified against the tool results: 11 ids, 5 numbers_

## Q8 turn 1 — Nathan Pierce (U-601)
_Thread: 01a149c6-8116-7672-a9f5-38a98c5f4fde_

> WELL-0333's recalled pump was swapped out yesterday. The work order isn't in the system yet. Please count it as replaced from now on.

I have recorded your note for WELL-0333 (NOTE-0333-001), stating that the recalled pump was swapped out on 2027-01-14. I will treat this as a replacement in our discussions, though the official work order is not yet in the system.

As of now, the following wells in Northwest Block 12 still have recalled Highline RP-175 pumps (from lots LOT-2409-A, LOT-2409-C, or LOT-2410-B) in the ground, and are past the 31 Dec 2026 replacement deadline:

| Well ID | Pump Model | Lot | Status | User Reports |
| :--- | :--- | :--- | :--- | :--- |
| WELL-0305 | Highline RP-175 | LOT-2409-A | Overdue | |
| WELL-0333 | Highline RP-175 | LOT-2409-A | Overdue | Swapped out 2027-01-14 (reported by Nathan Pierce on 2027-01-15) |
| WELL-0426 | Highline RP-175 | LOT-2409-C | Overdue | |
| WELL-0428 | Highline RP-175 | LOT-2410-B | Overdue | |

(Data from `recalled_pumps` result r_60fa)

<details><summary>Tool calls and citations</summary>

- `add_note({"asset_id": "WELL-0333", "text": "recalled pump was swapped out yesterday (2027-01-14). Work order not yet in system."})`
- `recalled_pumps({"area": "NW-12", "include_replaced": true})`

Citations: NOTE-0333-001, INS-0333-0219, supplier-recall-notice-2026-12-01 §What is recalled, MNT-0302-031, WELL-0302, MNT-0302-030, INS-0302-0217, WELL-0305, MNT-0305-032, INS-0305-0216, WELL-0333, MNT-0333-024, MNT-0340-038, WELL-0340, MNT-0340-031, INS-0340-0218, MNT-0345-039, WELL-0345, MNT-0345-036, INS-0345-0217, MNT-0398-025, WELL-0398, MNT-0398-018, INS-0398-0220, WELL-0426, MNT-0426-030, INS-0426-0222, MNT-0427-025, WELL-0427, MNT-0427-020, INS-0427-0220, WELL-0428, MNT-0428-022, INS-0428-0218

</details>

_Check: passed — verified against the tool results: 5 ids, 14 numbers, 1 notes_

## Q8 turn 2 — Nathan Pierce (U-601)
_Thread: 01a149c6-8116-7672-a9f5-38a98c5f4fde_

> Also, just for me: whenever you list wells, sort them by area and then by well ID, and show costs in thousands of dollars.

I've saved that preference for you. From now on, whenever I list wells, I will sort them by area and then by well ID, and I will show all costs in thousands of dollars.

<details><summary>Tool calls and citations</summary>

- `set_preference({"preference": "Whenever you list wells, sort them by area and then by well ID; show costs in thousands of dollars."})`

</details>

_Check: passed — verified against the tool results: nothing to check_

## Q8 turn 3 — Robert Hayes (U-301)
_Thread: 01a149c7-aef3-7c11-90ca-a0a0b50cbcb5_

> Which recalled pumps are still in the ground right now?

There are 9 recalled Highline RP-175 pumps still in the ground. All of these are past their 2026-12-31 replacement deadline.

| Well ID | Area | Install Job | Installed On | Lot | Pump Model | Serial | Status Now |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| WELL-0156 | Northeast Block 8 | MNT-0156-027 | 2026-06-27 | LOT-2409-A | Highline RP-175 | SN-952958 | Producing oil |
| WELL-0160 | Northeast Block 8 | MNT-0160-028 | 2026-07-18 | LOT-2409-C | Highline RP-175 | SN-429965 | Not producing oil |
| WELL-0305 | Northwest Block 12 | MNT-0305-032 | 2026-10-16 | LOT-2409-A | Highline RP-175 | SN-978137 | Producing oil |
| WELL-0333 | Northwest Block 12 | MNT-0333-024 | 2026-05-09 | LOT-2409-A | Highline RP-175 | SN-507591 | Producing oil* |
| WELL-0426 | Northwest Block 12 | MNT-0426-030 | 2026-06-19 | LOT-2409-C | Highline RP-175 | SN-880271 | Producing oil |
| WELL-0428 | Northwest Block 12 | MNT-0428-022 | 2026-03-07 | LOT-2410-B | Highline RP-175 | SN-708611 | Producing oil |
| WELL-0577 | Southeast Block 32 | MNT-0577-028 | 2026-07-31 | LOT-2409-A | Highline RP-175 | SN-757468 | Producing oil |
| WELL-0031 | Southwest Block 23 | MNT-0031-027 | 2026-04-24 | LOT-2409-A | Highline RP-175 | SN-664877 | Producing oil |
| WELL-0263 | Southwest Block 23 | MNT-0263-033 | 2026-10-16 | LOT-2410-B | Highline RP-175 | SN-187332 | Not producing oil |

*\*Note: Nathan Pierce reported on 2027-01-15 that the recalled pump for WELL-0333 was swapped out yesterday (2027-01-14), but the work order is not yet in the system. This is unconfirmed.*

**Source:** supplier-recall-notice-2026-12-01 §What is recalled.

**Visual: table** — Recalled Pumps Still in Ground  
fields: `{"columns": ["asset_id", "area", "install_job", "installed_on", "lot", "pump_model", "serial", "status_now"]}`

| asset_id | area | install_job | installed_on | lot | pump_model | serial | status_now |
|---|---|---|---|---|---|---|---|
| WELL-0156 | Northeast Block 8 | MNT-0156-027 | 2026-06-27 | LOT-2409-A | Highline RP-175 | SN-952958 | Producing oil |
| WELL-0160 | Northeast Block 8 | MNT-0160-028 | 2026-07-18 | LOT-2409-C | Highline RP-175 | SN-429965 | Not producing oil |
| WELL-0305 | Northwest Block 12 | MNT-0305-032 | 2026-10-16 | LOT-2409-A | Highline RP-175 | SN-978137 | Producing oil |
| WELL-0333 | Northwest Block 12 | MNT-0333-024 | 2026-05-09 | LOT-2409-A | Highline RP-175 | SN-507591 | Producing oil |
| WELL-0426 | Northwest Block 12 | MNT-0426-030 | 2026-06-19 | LOT-2409-C | Highline RP-175 | SN-880271 | Producing oil |
| WELL-0428 | Northwest Block 12 | MNT-0428-022 | 2026-03-07 | LOT-2410-B | Highline RP-175 | SN-708611 | Producing oil |
| WELL-0577 | Southeast Block 32 | MNT-0577-028 | 2026-07-31 | LOT-2409-A | Highline RP-175 | SN-757468 | Producing oil |
| WELL-0031 | Southwest Block 23 | MNT-0031-027 | 2026-04-24 | LOT-2409-A | Highline RP-175 | SN-664877 | Producing oil |
| WELL-0263 | Southwest Block 23 | MNT-0263-033 | 2026-10-16 | LOT-2410-B | Highline RP-175 | SN-187332 | Not producing oil |

<details><summary>Tool calls and citations</summary>

- `recalled_pumps({"include_replaced": false})`
- `show_visual({"fields": {"asset_id": "asset_id", "area": "area", "install_job": "install_job", "installed_on": "installed_on", "lot": "lot", "pump_model": "pump_model", "serial": "serial", "status_now": "status_now"}, "source": "r_e689", "title": "Recalled Pumps Still in Ground", "type": "table"})`

Citations: supplier-recall-notice-2026-12-01 §What is recalled, WELL-0156, MNT-0156-027, INS-0156-0217, WELL-0160, MNT-0160-028, INS-0160-0217, WELL-0305, MNT-0305-032, INS-0305-0216, WELL-0333, MNT-0333-024, INS-0333-0219, NOTE-0333-001, WELL-0426, MNT-0426-030, INS-0426-0222, WELL-0428, MNT-0428-022, INS-0428-0218, WELL-0577, MNT-0577-028, INS-0577-0211, WELL-0031, MNT-0031-027, INS-0031-0215, WELL-0263, MNT-0263-033, INS-0263-0219

</details>

_Check: passed — verified against the tool results: 18 ids, 31 numbers_

## Q8 turn 4 — Olivia Grant (U-501)
_Thread: 01a149c7-e19c-7840-8b66-7907dee5168f_

> Nathan told me the recalled pump on WELL-0577 was swapped as well. Take it off the recall list.

I have recorded your note about WELL-0577 (NOTE-0577-001), but I cannot remove it from the recall list yet.

Because this is a second-hand claim (you mentioned Nathan told you), I have marked it as unconfirmed. To officially clear the well from the recall list, I need a recorded work order or maintenance report showing the new pump installation.

| Well ID | Status | Note |
| :--- | :--- | :--- |
| **WELL-0577** | **On Recall List** | Reported by Olivia Grant on 2027-01-15: "Nathan said the recalled pump was swapped." (Unconfirmed) |

**Why it stays on the list:**
The system requires a formal maintenance record to verify a replacement. Currently, the latest recorded maintenance for WELL-0577 is a scheduled lubrication and belt inspection (MNT-0577-033) from 2026-12-07. Once the work order for the pump swap is entered into the system, the well will be automatically removed from the list.

<details><summary>Tool calls and citations</summary>

- `add_note({"asset_id": "WELL-0577", "text": "Nathan said the recalled pump was swapped."})`
- `recalled_pumps({"asset_ids": ["WELL-0577"], "include_replaced": true})`

Citations: NOTE-0577-001, INS-0577-0211, CTX-0577-001, CTX-0577-002, supplier-recall-notice-2026-12-01 §What is recalled, WELL-0156, MNT-0156-027, INS-0156-0217, WELL-0160, MNT-0160-028, INS-0160-0217, MNT-0302-031, WELL-0302, MNT-0302-030, INS-0302-0217, WELL-0305, MNT-0305-032, INS-0305-0216, WELL-0333, MNT-0333-024, INS-0333-0219, NOTE-0333-001, MNT-0340-038, WELL-0340, MNT-0340-031, INS-0340-0218, MNT-0345-039, WELL-0345, MNT-0345-036, INS-0345-0217, MNT-0398-025, WELL-0398, MNT-0398-018, INS-0398-0220, WELL-0426, MNT-0426-030, INS-0426-0222, MNT-0427-025, WELL-0427, MNT-0427-020, INS-0427-0220, WELL-0428, MNT-0428-022, INS-0428-0218, MNT-0460-035, WELL-0460, MNT-0460-029, INS-0460-0217, MNT-0475-034, WELL-0475, MNT-0475-030, INS-0475-0219, MNT-0517-030, WELL-0517, MNT-0517-021, INS-0517-0197, WELL-0577, MNT-0577-028, MNT-0595-031, WELL-0595, MNT-0595-028, INS-0595-0217, WELL-0031, MNT-0031-027, INS-0031-0215, WELL-0263, MNT-0263-033, INS-0263-0219

</details>

_Check: passed — verified against the tool results: 3 ids, 1 notes_

## Q8 turn 5 — Nathan Pierce (U-601)
_Thread: 01a149c7-fae0-7201-abbd-730c8cd37420_

> Show me the recalled pumps that are still in the ground in my area, and what it cost to install each one.

There are 4 recalled Highline RP-175 pumps still in the ground in Northwest Block 12. All of these are currently overdue for replacement (deadline was 2026-12-31).

| Well ID | Install Cost ($k) | Pump Model | Serial |
| :--- | :--- | :--- | :--- |
| WELL-0305 | 24.5 | Highline RP-175 | SN-978137 |
| WELL-0333 | 15.4 | Highline RP-175 | SN-507591 |
| WELL-0426 | 24.0 | Highline RP-175 | SN-880271 |
| WELL-0428 | 27.1 | Highline RP-175 | SN-708611 |

**Note on WELL-0333:** You reported that this pump was swapped out yesterday (2027-01-14), but the work order is not yet in the system (NOTE-0333-001).

**Visual: table** — Recalled Pumps in NW-12  
fields: `{"columns": ["asset_id", "install_cost_k_usd", "pump_model", "serial"]}`

| asset_id | install_cost_k_usd | pump_model | serial |
|---|---|---|---|
| WELL-0305 | 24.5 | Highline RP-175 | SN-978137 |
| WELL-0333 | 15.4 | Highline RP-175 | SN-507591 |
| WELL-0426 | 24.0 | Highline RP-175 | SN-880271 |
| WELL-0428 | 27.1 | Highline RP-175 | SN-708611 |

<details><summary>Tool calls and citations</summary>

- `recalled_pumps({"area": "Northwest Block 12 (NW-12)"})`
- `recalled_pumps({"area": "NW-12"})`
- `show_visual({"fields": {"asset_id": "asset_id", "install_cost_k_usd": "install_cost_k_usd", "pump_model": "pump_model", "serial": "serial"}, "source": "r_0ae7", "title": "Recalled Pumps in NW-12", "type": "table"})`

Citations: supplier-recall-notice-2026-12-01 §What is recalled, WELL-0305, MNT-0305-032, INS-0305-0216, WELL-0333, MNT-0333-024, INS-0333-0219, NOTE-0333-001, WELL-0426, MNT-0426-030, INS-0426-0222, WELL-0428, MNT-0428-022, INS-0428-0218

</details>

_Check: passed — verified against the tool results: 5 ids, 13 numbers_

## Q9 turn 1 — Robert Hayes (U-301)
_Thread: 01a149c8-16f9-7bb2-9b8a-5e6d596ec851_

> How many recalled pumps are still in the ground, and in which areas?

There are **9** recalled Highline RP-175 pumps still in the ground. All are currently overdue for replacement (deadline was 2026-12-31).

The distribution by area is as follows:

| Area | Count | Wells |
| :--- | :--- | :--- |
| **Northwest Block 12** | 4 | WELL-0305, WELL-0333, WELL-0426, WELL-0428 |
| **Northeast Block 8** | 2 | WELL-0156, WELL-0160 |
| **Southwest Block 23** | 2 | WELL-0031, WELL-0263 |
| **Southeast Block 32** | 1 | WELL-0577 |

**Important Notes:**
* **WELL-0333:** Nathan Pierce reported on 2027-01-15 that the recalled pump was swapped out yesterday (2027-01-14), but the work order is not yet in the system.
* **WELL-0577:** Olivia Grant reported on 2027-01-15 that Nathan Pierce said the pump was swapped, but this is unconfirmed as there is no corresponding record for this well. I have kept it on the list; please provide the work order to confirm.

**Visual: bar_chart** — Recalled Pumps in Ground by Area  
fields: `{"category": "area", "value": "install_cost_usd"}`

| area | install_cost_usd |
|---|---|
| Northeast Block 8 | 23398.0 |
| Northeast Block 8 | 33086.0 |
| Northwest Block 12 | 24528.0 |
| Northwest Block 12 | 15440.0 |
| Northwest Block 12 | 24044.0 |
| Northwest Block 12 | 27074.0 |
| Southeast Block 32 | 25500.0 |
| Southwest Block 23 | 19625.0 |
| Southwest Block 23 | 17254.0 |

<details><summary>Tool calls and citations</summary>

- `recalled_pumps({"include_replaced": false})`
- `show_visual({"fields": {"area": ["area"], "asset_id": ["asset_id"]}, "source": "r_b226", "title": "Recalled Pumps in Ground by Area", "type": "bar_chart"})`

Citations: supplier-recall-notice-2026-12-01 §What is recalled, WELL-0156, MNT-0156-027, INS-0156-0217, WELL-0160, MNT-0160-028, INS-0160-0217, WELL-0305, MNT-0305-032, INS-0305-0216, WELL-0333, MNT-0333-024, INS-0333-0219, NOTE-0333-001, WELL-0426, MNT-0426-030, INS-0426-0222, WELL-0428, MNT-0428-022, INS-0428-0218, WELL-0577, MNT-0577-028, INS-0577-0211, NOTE-0577-001, WELL-0031, MNT-0031-027, INS-0031-0215, WELL-0263, MNT-0263-033, INS-0263-0219

</details>

_Check: passed — verified against the tool results: 9 ids, 3 numbers_

## Q9 turn 2 — Robert Hayes (U-301)
_Thread: 01a149c8-16f9-7bb2-9b8a-5e6d596ec851_

> Different topic. Who leads Northwest Production, and how many wells does that team run?

Northwest Production is led by **Nathan Pierce** (U-601) and runs **150 wells**.

**Visual: table** — Northwest Production Team Summary  
fields: `{"columns": ["area", "lead", "plugged", "team", "wells_run"]}`

| area | lead | plugged | team | wells_run |
|---|---|---|---|---|
| Northwest Block 12 | Nathan Pierce | 0 | Northwest Production | 150 |
| All areas | Nathan Pierce | 0 | Northwest Production | 150 |

<details><summary>Tool calls and citations</summary>

- `team_summary({"team": "Northwest Production"})`
- `show_visual({"fields": {"area": ["area"], "lead": ["lead"], "plugged": ["plugged"], "team": ["team"], "wells_run": ["wells_run"]}, "source": "r_7ba3", "title": "Northwest Production Team Summary", "type": "table"})`

Citations: TEAM-NW, U-601

</details>

_Check: passed — verified against the tool results: 1 ids, 1 numbers_

## Q9 turn 3 — Robert Hayes (U-301)
_Thread: 01a149c8-16f9-7bb2-9b8a-5e6d596ec851_

> What does our operations SOP say about cold weather? Name one well that missed the check in December.

According to the Operations SOP (rev 2, §OPS-5), during the freeze protection period (1 Dec – 28 Feb), any inspection that records an ambient temperature of **-5 °C or below** on a well that is producing oil requires a maintenance job. This job must have an issue containing "**Heat trace check**" and must start within **7 days** of the inspection.

One well that missed this check in December is **WELL-0310** (inspected on 2026-12-17 with an ambient temperature of -6.0 °C; ID: INS-0310-0213).

<details><summary>Tool calls and citations</summary>

- `search_docs({"query": "cold weather heat trace check"})`
- `freeze_checks({"end": "2026-12-31", "missed_only": true, "start": "2026-12-01"})`

Citations: operations-sop-rev2 §OPS-5 Freeze protection (1 Dec – 28 Feb), T200 §7. Common failure modes, T500 §3. Production temperature rule, T200 §3. Normal operation, T200 §6. Lubrication schedule, CTX-0002-001, CTX-0003-001, CTX-0005-001, CTX-0007-001, CTX-0012-001, MNT-0421-032, INS-0421-0216, INS-0310-0213, MNT-0325-030, INS-0325-0215, INS-0354-0215, MNT-0445-026, INS-0445-0213, MNT-0468-020, INS-0468-0154, INS-0486-0219, MNT-0547-028, INS-0547-0214, INS-0531-0217

</details>

_Check: passed — verified against the tool results: 2 ids, 2 numbers_

## Q9 turn 4 — Robert Hayes (U-301)
_Thread: 01a149c8-16f9-7bb2-9b8a-5e6d596ec851_

> An operator reported a gas smell at WELL-0332 on 3 Dec. What was the H2S reading?

There was no H2S reading taken for the gas odor reported at WELL-0332 on 2026-12-03 (ID: CTX-0332-004) because there was no field response following the report (ID: none).

<details><summary>Tool calls and citations</summary>

- `gas_reports({"asset_id": "WELL-0332", "start": "2026-12-01"})`

Citations: operations-sop-rev2 §OPS-1 Gas odor response, CTX-0332-004

</details>

_Check: passed — verified against the tool results: 2 ids_

## Q9 turn 5 — Robert Hayes (U-301)
_Thread: 01a149c8-16f9-7bb2-9b8a-5e6d596ec851_

> Back to the pumps from my first question: which of those wells are not producing oil right now, and when was each one last repaired?

Of the recalled pumps still in the ground, the following wells are not currently producing oil:

| Well ID | Last Repair Date |
| :--- | :--- |
| **WELL-0160** | 2027-01-15 (MNT-0160-032) |
| **WELL-0263** | 2027-01-09 (MNT-0263-035) |

<details><summary>Tool calls and citations</summary>

- `recall_conversations({"query": "recalled pumps"})`
- `well_status({"asset_ids": ["WELL-0156", "WELL-0160", "WELL-0305", "WELL-0333", "WELL-0426", "WELL-0428", "WELL-0577", "WELL-0031", "WELL-0263"], "not_producing_only": true})`
- `well_records({"asset_id": "WELL-0160", "end": "2027-01-15", "sections": ["repairs"], "start": "2020-01-01"})`
- `well_records({"asset_id": "WELL-0263", "end": "2027-01-15", "sections": ["repairs"], "start": "2020-01-01"})`

Citations: INS-0160-0217, MNT-0160-032, CTX-0160-002, INS-0263-0219, MNT-0263-035, CTX-0263-001, CTX-0263-002, CTX-0263-003, CTX-0263-004, CTX-0263-005, T200 § 9. Engineering limits > 9.3 Production temperature rule, T350 § 3. Production temperature rule, MNT-0160-001, MNT-0160-002, MNT-0160-003, MNT-0160-004, MNT-0160-005, MNT-0160-006, MNT-0160-007, MNT-0160-008, MNT-0160-009, MNT-0160-010, MNT-0160-011, MNT-0160-012, MNT-0160-013, MNT-0160-014, MNT-0160-015, MNT-0160-016, MNT-0160-017, MNT-0160-018, MNT-0160-019, MNT-0160-020, MNT-0160-021, MNT-0160-022, MNT-0160-023, MNT-0160-024, MNT-0160-025, MNT-0160-026, MNT-0160-027, MNT-0160-028, MNT-0160-029, MNT-0160-030, MNT-0160-031, REG-0160-001, REG-0160-002, REG-0160-003, CTX-0160-001, INS-0160-0025, spill-response-sop §4. Protocols, INS-0160-0052, regulatory-compliance-sop §2. Protocols, T200 §10. Maintenance escalation, MNT-0263-001, MNT-0263-002, MNT-0263-003, MNT-0263-004, MNT-0263-005, MNT-0263-006, MNT-0263-007, MNT-0263-008, MNT-0263-009, MNT-0263-010, MNT-0263-011, MNT-0263-012, MNT-0263-013, MNT-0263-014, MNT-0263-015, MNT-0263-016, MNT-0263-017, MNT-0263-018, MNT-0263-019, MNT-0263-020, MNT-0263-021, MNT-0263-022, MNT-0263-023, MNT-0263-024, MNT-0263-025, MNT-0263-026, MNT-0263-027, MNT-0263-028

</details>

_Check: passed — verified against the tool results: 4 ids, 1 lists, 1 notes_

## Q9 turn 6 — Robert Hayes (U-301)
_Thread: 01a149c8-16f9-7bb2-9b8a-5e6d596ec851_

> Of all the wells we've talked about today, which one would you deal with first, and why?

Based on the data we have discussed, I would prioritize **WELL-0160** first.

While both WELL-0160 and WELL-0263 are currently not producing and contain recalled pumps, **WELL-0160** presents a more immediate operational risk for the following reasons:

1.  **Active Mechanical Issue:** It has an open corrective repair (MNT-0160-032) for "Walking beam bearing wear" that is currently in progress.
2.  **Recent Status Change:** Its non-producing status was confirmed by a drone inspection as recently as 2027-01-14, and the inspection noted the "Wellhead cold to touch," which can be a precursor to further mechanical or freeze-related issues.
3.  **Recalled Pump Urgency:** It contains a Highline RP-175 from lot LOT-2409-C, which is overdue for replacement.

**WELL-0263** is also a high priority due to a very recent corrective repair for a "Flowline corrosion pinhole leak" (MNT-0263-035) on 2027-01-09, but the mechanical stability of WELL-0160's pump jack makes it the more pressing concern for immediate maintenance attention.

_Check: passed — verified against the tool results: 4 ids, 2 numbers_

## Q10 turn 1 — Michael Turner (U-201)
_Thread: 01a149c6-a67f-7953-b7fc-b2f3a62536ae_

> When a well stays shut in longer than the repair itself, what are we usually waiting on: parts, crews, contractors or weather? Break it down by area for jobs started in 2026, with the typical number of extra days, and tell me if any area stands out.

For jobs started in 2026, the most common reason wells stayed shut in longer than the repair itself was waiting on **contractors** (32.6% of all waiting jobs), followed by **crews** (26.9%) and **weather** (22.0%).

The breakdown by area is as follows:

| Area | Top Reason | Share (%) | Typical Extra Days |
| :--- | :--- | :--- | :--- |
| **Northeast Block 7** | Contractors | 31.2% | 9.0 |
| **Northeast Block 8** | Crews | 31.2% | 9.0 |
| **Northwest Block 12** | Crews | 31.6% | 9.0 |
| **Southeast Block 31** | Contractors | 42.5% | 14.0 |
| **Southeast Block 32** | Contractors | 32.4% | 9.0 |
| **Southwest Block 23** | Contractors | 29.2% | 9.0 |
| **Southwest Block 24** | Contractors | 40.9% | 9.0 |

### Standout Areas
*   **Southeast Block 31** stands out significantly for contractor delays. Contractors account for **42.5%** of its waiting jobs (compared to the 32.6% field average), and the typical delay is **14.0 days**, much higher than the field-wide typical of 9.0 days (ID: r_e3b4).
*   **Northeast Block 7** also shows a notable delay when waiting on **parts**, with a typical extra time of **15.0 days** (compared to the 9.0-day field average) (ID: r_e3b4).

**Visual: stacked_bar_chart** — Waiting Reasons by Area (Jobs Started in 2026)  
fields: `{"category": "reason", "value": "share_pct", "series": "area"}`

| reason | area | share_pct |
|---|---|---|
| parts | Northeast Block 7 | 23.4 |
| crews | Northeast Block 7 | 21.9 |
| contractors | Northeast Block 7 | 31.2 |
| weather | Northeast Block 7 | 23.4 |
| parts | Northeast Block 8 | 16.2 |
| crews | Northeast Block 8 | 31.2 |
| contractors | Northeast Block 8 | 30.0 |
| weather | Northeast Block 8 | 22.5 |
| parts | Northwest Block 12 | 17.0 |
| crews | Northwest Block 12 | 31.6 |
| contractors | Northwest Block 12 | 30.4 |
| weather | Northwest Block 12 | 21.1 |
| parts | Southeast Block 31 | 15.0 |
| crews | Southeast Block 31 | 22.5 |
| contractors | Southeast Block 31 | 42.5 |
| weather | Southeast Block 31 | 20.0 |
| parts | Southeast Block 32 | 18.7 |
| crews | Southeast Block 32 | 26.6 |
| contractors | Southeast Block 32 | 32.4 |
| weather | Southeast Block 32 | 22.3 |
| parts | Southwest Block 23 | 22.2 |
| crews | Southwest Block 23 | 26.4 |
| contractors | Southwest Block 23 | 29.2 |
| weather | Southwest Block 23 | 22.2 |
| parts | Southwest Block 24 | 18.2 |
| crews | Southwest Block 24 | 18.2 |
| contractors | Southwest Block 24 | 40.9 |
| weather | Southwest Block 24 | 22.7 |
| parts | All areas | 18.5 |
| crews | All areas | 26.9 |
| contractors | All areas | 32.6 |
| weather | All areas | 22.0 |

<details><summary>Tool calls and citations</summary>

- `waiting_reasons({"end": "2026-12-31", "start": "2026-01-01"})`
- `show_visual({"fields": {"category": "reason", "share_pct": "share_pct", "typical_extra_days": "typical_extra_days"}, "source": "r_e3b4", "title": "Waiting Reasons by Area (Jobs Started in 2026)", "type": "stacked_bar_chart"})`

Citations: MNT-0001-028, MNT-0001-033, MNT-0002-018, MNT-0002-020, MNT-0004-021, MNT-0004-026, MNT-0005-031, MNT-0006-023, MNT-0006-025, MNT-0006-026, MNT-0007-031, MNT-0009-026, MNT-0010-024, MNT-0010-027, MNT-0012-029, MNT-0013-034, MNT-0013-037, MNT-0013-038, MNT-0014-015, MNT-0015-030, MNT-0015-032, MNT-0015-036, MNT-0018-028, MNT-0019-026, MNT-0019-032, MNT-0020-030, MNT-0020-034, MNT-0021-027, MNT-0021-032, MNT-0023-030, MNT-0025-030, MNT-0025-032, MNT-0025-035, MNT-0026-031, MNT-0028-028, MNT-0030-028, MNT-0031-026, MNT-0031-027, MNT-0031-028, MNT-0032-021, MNT-0033-022, MNT-0033-024, MNT-0033-026, MNT-0033-030, MNT-0033-031, MNT-0035-027, MNT-0036-022, MNT-0039-024, MNT-0040-025, MNT-0041-031

</details>

_Check: passed — verified against the tool results: 29 numbers_

## Q11 turn 1 — Olivia Grant (U-501)
_Thread: 01a149c6-d8aa-7f71-b28e-d77924778ece_

> Which region of the field consistently runs hotter?

The **Southeast** region consistently runs the hottest, with the highest mean temperature above ambient in every month from January 2026 through January 2027 (Record ID: r_c85d).

However, the data indicates this is primarily due to the well mix rather than geography. When comparing wells of the same type, the temperature differences between regions are minimal (less than 0.9 °C). The Southeast appears hotter because it has a significantly higher share of T500 (ESP) wells, which run hotter by design (T500 manual §3).

**Regional Comparison (Mean °C above air):**
| Region | Mean ΔC (Jan 2026 – Jan 2027) | T500 Share (Avg) |
| :--- | :--- | :--- |
| **Southeast** | **30.7 °C** | **~32%** |
| **Northwest** | 29.7 °C | ~23% |
| **Southwest** | 28.2 °C | ~3% |
| **Northeast** | 28.2 °C | ~2% |

**Visual: heatmap** — Mean Wellhead Temperature Above Ambient by Region and Month  
fields: `{"x": "month", "value": "mean_delta_c", "y": "group"}`

| month | group | mean_delta_c |
|---|---|---|
| 2026-01 | Northeast | 28.3 |
| 2026-02 | Northeast | 28.4 |
| 2026-03 | Northeast | 27.9 |
| 2026-04 | Northeast | 28.2 |
| 2026-05 | Northeast | 28.2 |
| 2026-06 | Northeast | 28.2 |
| 2026-07 | Northeast | 28.2 |
| 2026-08 | Northeast | 28.1 |
| 2026-09 | Northeast | 28.4 |
| 2026-10 | Northeast | 28.2 |
| 2026-11 | Northeast | 28.2 |
| 2026-12 | Northeast | 27.8 |
| 2027-01 | Northeast | 27.6 |
| 2026-01 | Northwest | 30.0 |
| 2026-02 | Northwest | 29.9 |
| 2026-03 | Northwest | 29.9 |
| 2026-04 | Northwest | 29.5 |
| 2026-05 | Northwest | 29.8 |
| 2026-06 | Northwest | 29.7 |
| 2026-07 | Northwest | 29.7 |
| 2026-08 | Northwest | 29.6 |
| 2026-09 | Northwest | 29.4 |
| 2026-10 | Northwest | 29.6 |
| 2026-11 | Northwest | 29.5 |
| 2026-12 | Northwest | 29.6 |
| 2027-01 | Northwest | 29.7 |
| 2026-01 | Southeast | 30.8 |
| 2026-02 | Southeast | 30.9 |
| 2026-03 | Southeast | 30.9 |
| 2026-04 | Southeast | 30.6 |
| 2026-05 | Southeast | 30.6 |
| 2026-06 | Southeast | 30.8 |
| 2026-07 | Southeast | 30.7 |
| 2026-08 | Southeast | 31.0 |
| 2026-09 | Southeast | 30.6 |
| 2026-10 | Southeast | 30.9 |
| 2026-11 | Southeast | 30.6 |
| 2026-12 | Southeast | 30.7 |
| 2027-01 | Southeast | 30.4 |
| 2026-01 | Southwest | 27.8 |
| 2026-02 | Southwest | 28.2 |
| 2026-03 | Southwest | 28.3 |
| 2026-04 | Southwest | 28.3 |
| 2026-05 | Southwest | 28.1 |
| 2026-06 | Southwest | 28.3 |
| 2026-07 | Southwest | 28.1 |
| 2026-08 | Southwest | 28.3 |
| 2026-09 | Southwest | 28.4 |
| 2026-10 | Southwest | 28.1 |
| 2026-11 | Southwest | 28.0 |
| 2026-12 | Southwest | 28.1 |
| 2027-01 | Southwest | 28.1 |

<details><summary>Tool calls and citations</summary>

- `field_temperature({"end": "2027-01-15", "group_by": "region", "start": "2026-01-15"})`
- `show_visual({"fields": {"group": "group", "month": "month", "mean_delta_c": "mean_delta_c"}, "source": "r_c85d", "title": "Mean Wellhead Temperature Above Ambient by Region and Month", "type": "heatmap"})`

</details>

_Check: passed — verified against the tool results: 11 numbers_
