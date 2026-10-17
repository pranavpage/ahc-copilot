# Asset Intelligence Copilot: submission

FlytBase Hack Day, 17 Oct 2026 · Pranav Page · repo: `pranavpage/ahc-copilot`

A chat copilot for an oil field. Operators ask in plain English and get an answer with its
sources and one visual. It runs on the test dataset: 600 wells, 7 areas, 125,198 inspections,
17,415 repair jobs, 4,437 repair reports, 1,887 notes and 12 manuals and procedures. In the
data, "today" is 15 Jan 2027.

## 1. System architecture

```mermaid
flowchart LR
    user(["👤 Field team member<br/>picks who they are, asks"]) --> web["💬 Web chat<br/>Next.js + assistant-ui"]
    web <--> srv["🗂️ LangGraph server<br/>private threads per user"]
    srv <--> agent

    subgraph agent["🤖 Copilot (copilot/agent.py)"]
        direction TB
        p["0 · Prompt from the DB<br/>today, who is asking, their team,<br/>wells and saved preferences"]
        l["1 · Look it up<br/>ReAct loop picks from 27 lookups"]
        v{"2 · Verify in code<br/>every ID and number is<br/>in a tool result?"}
        m["3 · Remember<br/>private chat index"]
        p --> l --> v
        v -- "no: rewrite once" --> l
        v -- yes --> m
    end

    l <--> llm["🧠 Gemma 4 26B<br/>(OpenRouter) + fallback"]
    l <--> tools["🔧 Lookups = the rules, in code<br/>status (OPS-3) · gas response (OPS-1)<br/>bypass vs MOC (OPS-2) · freeze checks (OPS-5)<br/>regulator letter · recalled pumps · waiting reasons<br/>status conflicts · operator concerns · temperature<br/>data coverage · docs search · notes, corrections, rules"]
    tools <--> db

    subgraph db["📦 SQLite (db/schema.sql)"]
        direction TB
        L1["Layer 1 · Field records<br/>loaded from the dataset, never edited"]
        L2["Layer 2 · Learned<br/>shared: notes, corrections, rules (who + when)<br/>private: chats, preferences"]
        L3["Layer 3 · Views<br/>corrected readings · rules per well ·<br/>status now · spills · current pump"]
        L1 --> L3
        L2 --> L3
    end
    files["📄 Dataset files"] -- "db/load.py, one command, ~7 s" --> L1
```

**Design decisions**
- **Rules live in code, not in the prompt.** Each procedure rule (OPS-1 to OPS-6, the MOC
  memos and their extensions, the recall notice, the regulator letter, the well-type
  thresholds) is a tested lookup. The small model picks a lookup and presents its rows.
- **Every answer is checked by code, not by a second model.** Every well ID, record ID and
  number in an answer must appear in a tool result, or the model rewrites once.
- **Field records are never overwritten.** What users say is stored next to the records, with
  who said it and when, and is marked *unconfirmed* until a record backs it up. Second-hand
  claims stay unconfirmed and don't change any list.
- **Memory has two scopes.** Notes and corrections are shared with everyone. Chats and
  preferences are private to each user.
- **"Today" and the rules come from the data.** The loader reads "today" from the dataset
  README and the thresholds from the manuals, so loading the test data is one command.

<div style="page-break-after: always;"></div>

## Evaluation and lessons

**How we evaluated it** (details in `EVALS.md`). There are three levels, from fast to slow:

1. **Unit tests, no LLM (317).** Every tool rule, the answer check, memory and the loader.
2. **Eval set, live LLM (23 cases).** The organisers' 18 sample questions on the sample data,
   including multi-turn and memory cases. Each case gets the three metrics below (built on deepeval).
3. **The final questions, end to end.** `scripts/run_final.py` runs all 21 turns on a fresh copy
   of the database (about 100 s). We read every answer.

| Metric | Checked by | Passes when |
|---|---|---|
| FactRecall | code | every expected ID, number and date is in the answer, its citations or its visual; no forbidden item |
| VisualMatch | code | the expected visual type is shown |
| LLM as a judge | DeepSeek V4 Pro (a different model family from the copilot) | the answer text *and its visuals* meet the case's rubric (the reasoning, the caveats, the conflicts shown), with no contradictions. Facts are not its job, because FactRecall checks them exactly |

Each failure gets a category that points at the fix. *Retrieval* means the fact is in no tool
result, so the tool or its arguments are wrong. *Generation* means the fact is in a tool result
but not in the answer, so the prompt is at fault. The others are *no visual*, *wrong visual* and
*judge*. One-turn cases run in parallel. Memory chains run in order on a database restored from a
snapshot. Each run is compared with a baseline (fixes and regressions) and logged in
`evals/history.csv`. **In one day: 4 → 15 of 23 pass, FactRecall 0.69 → 0.97, judge 0.54 →
0.78, 0 regressions in the last run.**

**Lessons learnt**
1. With a small model, every option you expose is a way to be wrong. When we gave a tool a
   "count workover-rig waits separately" switch, the model turned it on and gave the wrong
   breakdown. We removed the switch.
2. Read the raw data before trusting a question. Q1 asks for reservoir pressure, and the data
   has none. WELL-0010 changed type in November, which changes its producing threshold.
   MOC-2026-044 extends another memo's expiry date.
3. Run the real questions end to end early. Running all 21 turns takes about 100 s, and it
   found 4 bugs that 317 passing unit tests had missed.
4. Most early failures were *retrieval* failures: wrong date ranges, or missing columns in a
   tool. Fixing the tools helped more than changing the prompt.
5. Use the LLM judge only for what code cannot check, like reasoning and caveats. When exact
   facts are in code, they cost nothing and never give different results on a re-run. The judge
   is the strictest metric: it failed 7 of the 8 cases that still fail, most with the rubric
   partly met.

<div style="page-break-after: always;"></div>

## 2. Answers to the final questions

All 21 turns were asked in order through the web UI's LangGraph server, each as the named
person, with "same session" turns in one thread (`scripts/seed_demo.py --final`; model
`google/gemma-4-26b-a4b-it`, about 3 min). These are the threads shown in the demo. Text in
quotes is the copilot's answer. The tables show the rows of the copilot's visual (or of its tool
result, where it drew none), with the columns the question asks for. The full answer to every
turn, with its tool calls and citations, is in [`TRANSCRIPT.md`](TRANSCRIPT.md)
(`scripts/export_threads.py`).

| Q | Asked by | Result | Notes |
|---|---|---|---|
| Q1 Reservoir pressure | Michael Turner | ✅ | Says the data has no pressure; offers a labelled proxy |
| Q2 Best producer | Robert Hayes | ✅ | No oil volumes in the data; gives the labelled days-producing proxy: WELL-0212 (371 days, 52 wells tied) |
| Q3 Gas reports | Laura Simmons | ✅ | 26 reports since 1 Nov: 17 met, 9 missed (2 with no response at all) |
| Q4 Bypasses | Chris Dalton | ✅ | In place now: WELL-0248 allowed, WELL-0249 expired, WELL-0405 not approved. Also WELL-0087 and WELL-0158 expired, WELL-0561 not approved |
| Q5 Regulator letter | Michael Turner | ✅ | 6 spills covered; not compliant: WELL-0123, WELL-0182, WELL-0262 |
| Q6 Status conflicts | Nathan Pierce | ✅ | 12 wells, each with its OPS-3 status and reason |
| Q7 Operator notes | Robert Hayes | ✅ | Top 10 with the notes quoted. Send crews first to WELL-0336, WELL-0344, WELL-0401 |
| Q8 Who told you that? | 4 users | ✅ / ⚠️ | Claims stay unconfirmed and both wells stay listed; Nathan's preferences ($k, sort order) are applied in a new session. Turn 1 also says "will treat this as a replacement in our discussions"; turn 4 doesn't say Nathan's own report was about WELL-0333 |
| Q9 One conversation | Robert Hayes | ✅ | 9 pumps by area; Northwest Production = Nathan Pierce, 150 wells; OPS-5, with WELL-0310 missed; no H2S reading on 3 Dec (no response); not producing: WELL-0160, WELL-0263; deal with WELL-0160 first |
| Q10 Waiting reasons | Michael Turner | ✅ | Contractors are the top reason field-wide (32.6%); Southeast Block 31 stands out (42.5%, 14 typical extra days); stacked bar chart |
| Q11 Hotter region | Olivia Grant | ✅ | The Southeast reads hotter only because of its share of T500 wells; like-for-like, no region runs hotter |

<div style="page-break-after: always;"></div>

### Q1. Reservoir pressure — Michael Turner

> *"All our wells feed one reservoir. Map the reservoir pressure across the field from the pressure data."*

> "The data has no measurement for reservoir pressure. I cannot create a reservoir pressure map because
> pressure is not a recorded field in the inspection or well data. The closest proxy available is wellhead
> temperature, which is recorded during inspections and can be mapped by area to show thermal trends across
> the field. Would you like me to show a map of wellhead temperatures instead?"

**How:** `data_coverage("reservoir pressure")` returned no pressure series in the dataset. So the copilot
drew no map. The request is a trap: a "pressure map" built from a proxy would be made-up data. The copilot
says plainly that the data does not exist, and offers a proxy that it labels as a proxy.

### Q2. Best producer — Robert Hayes

> *"Which well produced the most oil in 2026?"*

> "The data has no recorded oil volumes or production rates. As a proxy, I have identified the well with the
> most producing days (uptime) during 2026 (from 2026-01-01 to 2026-12-31)."

| Well | Area | Type | Producing days (proxy) | Inspections (producing / all) | Mean °C above air |
|---|---|---|---|---|---|
| WELL-0212 | Southeast Block 31 | T500 | 371 | 53 / 53 | 36.6 |

> "This ranking is based on weekly inspections multiplied by 7 days and does not represent actual barrels of
> oil produced."

**How:** `data_coverage("oil volume")` → no volume data. Then `producing_days(2026-01-01, 2026-12-31)`. The
producing test is each well type's manual rule (wellhead temperature above air ≥ threshold). 52 wells
tie at 371 days, because they read as producing at every inspection in 2026. The tie is broken by mean
temperature above air, which is also not a measure of oil volume. Visual: table.

<div style="page-break-after: always;"></div>

### Q3. Gas reports — Laura Simmons (HSE)

> *"Since 1 Nov 2026, every time an operator note reports gas at a well, did we get someone out to that well
> in time under our operating procedures? List every report and whether the response met the deadline."*

> "Since 1 November 2026, there have been 26 gas reports. Of these, 17 met the response deadline and 9
> missed it. The response deadline is 24 hours for reports before 1 January 2027, and 12 hours for reports
> on or after 1 January 2027 (per Operations SOP rev 2, §OPS-1)."

| Well | Area | Reported at (UTC) | Response (record, time) | Hours | Deadline | Met / Missed |
|---|---|---|---|---|---|---|
| WELL-0163 | Northeast Block 8 | 2026-11-03 20:55 | MNT-0163-019, 2026-11-14 08:00 | 251.1 | 24 h | **Missed** |
| WELL-0149 | Northeast Block 7 | 2026-11-06 18:20 | MNT-0149-029, 2026-11-07 08:00 | 13.7 | 24 h | Met |
| WELL-0165 | Northeast Block 8 | 2026-11-13 20:35 | MNT-0165-031, 2026-11-14 08:00 | 11.4 | 24 h | Met |
| WELL-0341 | Northwest Block 12 | 2026-11-19 07:40 | INS-0341-0109, 2026-12-17 13:30 | 677.8 | 24 h | **Missed** |
| WELL-0091 | Southwest Block 24 | 2026-11-27 22:25 | MNT-0091-019, 2026-11-28 08:00 | 9.6 | 24 h | Met |
| WELL-0423 | Northwest Block 12 | 2026-12-03 05:25 | INS-0423-0213, 2026-12-03 09:15 | 3.8 | 24 h | Met |
| WELL-0059 | Southwest Block 24 | 2026-12-03 06:10 | INS-0059-0213, 2026-12-03 12:15 | 6.1 | 24 h | Met |
| WELL-0332 | Northwest Block 12 | 2026-12-03 12:10 | none | — | 24 h | **Missed** |
| WELL-0401 | Northwest Block 12 | 2026-12-05 13:50 | MNT-0401-033, 2026-12-11 08:00 | 138.2 | 24 h | **Missed** |
| WELL-0189 | Northeast Block 8 | 2026-12-10 12:35 | MNT-0189-037, 2026-12-11 08:00 | 19.4 | 24 h | Met |
| WELL-0403 | Northwest Block 12 | 2026-12-10 21:15 | MNT-0403-024, 2026-12-11 08:00 | 10.8 | 24 h | Met |
| WELL-0244 | Southeast Block 31 | 2026-12-11 05:25 | MNT-0244-026, 2026-12-11 08:00 | 2.6 | 24 h | Met |
| WELL-0040 | Southwest Block 23 | 2026-12-12 01:55 | MNT-0040-029, 2026-12-12 08:00 | 6.1 | 24 h | Met |
| WELL-0228 | Southeast Block 31 | 2026-12-16 19:50 | INS-0228-0144, 2026-12-17 12:45 | 16.9 | 24 h | Met |
| WELL-0052 | Southwest Block 24 | 2026-12-18 06:45 | none | — | 24 h | **Missed** |
| WELL-0370 | Northwest Block 12 | 2026-12-21 12:45 | MNT-0370-028, 2026-12-22 08:00 | 19.2 | 24 h | Met |
| WELL-0362 | Northwest Block 12 | 2026-12-24 00:15 | MNT-0362-030, 2026-12-25 08:00 | 31.8 | 24 h | **Missed** |
| WELL-0161 | Northeast Block 8 | 2026-12-25 15:45 | INS-0161-0168, 2027-01-14 11:00 | 475.2 | 24 h | **Missed** |
| WELL-0135 | Northeast Block 7 | 2026-12-27 03:50 | MNT-0135-034, 2026-12-27 08:00 | 4.2 | 24 h | Met |
| WELL-0324 | Northwest Block 12 | 2027-01-01 22:40 | MNT-0324-036, 2027-01-02 08:00 | 9.3 | 12 h | Met |
| WELL-0330 | Northwest Block 12 | 2027-01-02 21:40 | MNT-0330-030, 2027-01-03 08:00 | 10.3 | 12 h | Met |
| WELL-0599 | Southeast Block 32 | 2027-01-06 17:20 | INS-0599-0196, 2027-01-07 09:45 | 16.4 | 12 h | **Missed** |
| WELL-0516 | Southeast Block 32 | 2027-01-06 21:15 | INS-0516-0215, 2027-01-07 12:15 | 15.0 | 12 h | **Missed** |
| WELL-0425 | Northwest Block 12 | 2027-01-07 05:20 | INS-0425-0218, 2027-01-07 09:00 | 3.7 | 12 h | Met |
| WELL-0465 | Southeast Block 32 | 2027-01-08 23:35 | MNT-0465-031, 2027-01-09 08:00 | 8.4 | 12 h | Met |
| WELL-0137 | Northeast Block 7 | 2027-01-10 23:30 | MNT-0137-032, 2027-01-11 08:00 | 8.5 | 12 h | Met |

**How:** `gas_reports(start=2026-11-01)` finds every operator note that reports gas (odor, H2S alarm,
rotten-egg smell). The response is the first maintenance job or *manual* inspection at that well after the
note (drone flights do not count). The deadline is the OPS-1 deadline in force on the report date (24 h, then 12 h from 1 Jan 2027). Two
reports had no response at all (WELL-0332, WELL-0052). Visual: table.

<div style="page-break-after: always;"></div>

### Q4. Temporary flowline bypasses — Chris Dalton (HSE)

> *"Across all areas, which temporary flowline bypasses are in place right now, and is each one allowed?
> Also list any bypass, past or present, that stayed in after its approval ran out or was never approved at
> all."*

> "There are currently 3 temporary flowline bypasses in place:" WELL-0248 (**Allowed**, MOC-2026-031),
> WELL-0249 (**Expired**, MOC-2026-036), WELL-0405 (**Not approved**). "The following bypasses are recorded
> as having stayed in after their approval expired or were never approved:" WELL-0087, WELL-0158, WELL-0249
> (Expired) and WELL-0405, WELL-0561 (Not approved).

| Well | Area | Bypass in | Bypass out | Approval | Valid until | Status |
|---|---|---|---|---|---|---|
| WELL-0248 | Southeast Block 31 | 2026-11-05 | still in | MOC-2026-031 | 2027-02-28 | Allowed |
| WELL-0249 | Southeast Block 31 | 2026-11-25 | still in | MOC-2026-036 | 2026-12-15 | **Expired** |
| WELL-0405 | Northwest Block 12 | 2026-12-20 | still in | none | — | **Not approved** |
| WELL-0087 | Southwest Block 24 | 2026-12-02 | 2027-01-06 | MOC-2026-036 | 2026-12-15 | **Expired** |
| WELL-0158 | Northeast Block 8 | 2026-11-20 | 2026-12-28 | MOC-2026-036 | 2026-12-15 | **Expired** |
| WELL-0561 | Southeast Block 32 | 2026-12-08 | 2026-12-19 | none | — | **Not approved** |
| WELL-0013 | Southwest Block 23 | 2026-11-10 | 2027-01-08 | MOC-2026-031 | 2027-02-28 | Allowed |
| WELL-0062 | Southwest Block 24 | 2026-11-02 | 2026-11-27 | MOC-2026-031 | 2027-02-28 | Allowed |
| WELL-0284 | Southwest Block 24 | 2026-11-12 | 2026-12-10 | MOC-2026-036 | 2026-12-15 | Allowed |
| WELL-0356 | Northwest Block 12 | 2026-11-18 | 2026-12-05 | MOC-2026-036 | 2026-12-15 | Allowed |
| WELL-0461 | Southeast Block 32 | 2026-11-14 | 2026-12-12 | MOC-2026-036 | 2026-12-15 | Allowed |
| WELL-0476 | Southeast Block 32 | 2026-10-22 | 2026-11-18 | MOC-2026-031 | 2027-02-28 | Allowed |

**How:** `bypasses()` pairs each "bypass in" operator note with its "bypass out" note. It finds the MOC memo
that names the well and applies OPS-2. MOC-2026-031 was extended to 2027-02-28 by MOC-2026-044, so its wells
are allowed. MOC-2026-036 ran out at the end of 2026-12-15. Visual: table (all 12 bypasses; the top six rows
answer the question).

### Q5. The regulator's letter — Michael Turner

> *"The State Oil & Gas Commission wrote to us in November 2026 about spills. Which of our spills does the
> letter cover, and on which ones are we not compliant? Show me a table."*

> "The State Oil & Gas Commission letter covers reportable spills (≥ 5 bbl) in Northeast Block 7 and
> Northeast Block 8 discovered since 2026-06-01. There are **6 spills** covered by the letter, and we are
> **not compliant on 3** of them because the clean-up reports did not include the required statement: 'Soil
> samples sent to the lab.' (Note: field soil readings/TPH results do not satisfy this requirement)."

| Well | Area | Inspection | Volume (bbl) | Clean-up job | Compliant? |
|---|---|---|---|---|---|
| WELL-0123 | Northeast Block 7 | INS-0123-0093 (2026-09-24) | 6.0 | MNT-0123-014 | **No**: no "Soil samples sent to the lab."; only field TPH readings, which do not count |
| WELL-0277 | Northeast Block 7 | INS-0277-0205 (2026-10-01) | 6.2 | MNT-0277-031 | Yes |
| WELL-0119 | Northeast Block 7 | INS-0119-0209 (2026-11-05) | 6.0 | MNT-0119-029 | Yes |
| WELL-0168 | Northeast Block 8 | INS-0168-0190 (2026-06-11) | 5.6 | MNT-0168-024 | Yes |
| WELL-0182 | Northeast Block 8 | INS-0182-0208 (2026-12-03) | 5.2 | MNT-0182-028 | **No**: no "Soil samples sent to the lab."; only field TPH readings, which do not count |
| WELL-0262 | Northeast Block 8 | INS-0262-0218 (2027-01-07) | 6.1 | MNT-0262-029 | **No**: no "Soil samples sent to the lab."; only field TPH readings, which do not count |

**How:** `regulator_letter_spills` reads the letter's scope (areas, start date, size class) from
`regulator-letter-2026-11-20`. It applies the spill-response SOP classes and the false-positive rule. Then it
reads each clean-up report for the exact sentence that the letter and the HSE note require. Visual: two
tables, one per area.

<div style="page-break-after: always;"></div>

### Q6. Which status is right? — Nathan Pierce

> *"Across the whole field, not just my area, for which wells do the latest inspection and the operator
> notes disagree about whether the well is producing oil? For each one, what is its real status right now,
> and why?"*

> "There are 12 wells across the field where the latest inspection and the latest operator note disagree on
> production status. Per Operations SOP OPS-3, the most recent record (either the inspection or the note)
> determines the current status."

| Well | Area | Latest inspection | Latest operator note | Status now |
|---|---|---|---|---|
| WELL-0323 | Northwest Block 12 | INS-0323-0219, 01-14 14:45: producing (24.5 °C above air) | CTX-0323-002, 01-14 19:20: "Shut-in … after the pumper reported a stuffing box leak." | **Not producing oil**: newer note decides |
| WELL-0330 | Northwest Block 12 | INS-0330-0213, 01-14 07:15: not producing (4.4 °C) | CTX-0330-002, 2026-12-19 06:00: "put back on production after the repair crew finished." | **Not producing oil**: newer inspection decides |
| WELL-0355 | Northwest Block 12 | INS-0355-0213, 01-14 15:15: producing (31.1 °C) | CTX-0355-004, 01-14 19:05: "leaking at the stuffing box, shut the well in." | **Not producing oil**: newer note |
| WELL-0422 | Northwest Block 12 | INS-0422-0215, 01-14 15:15: producing (27.7 °C) | CTX-0422-003, 01-14 21:35: "Shut in … high pressure alarm on the separator." | **Not producing oil**: newer note |
| WELL-0479 | Southeast Block 32 | INS-0479-0213, 01-14 11:45: producing (23.6 °C) | CTX-0479-004, 01-14 15:35: "leaking at the stuffing box, shut the well in." | **Not producing oil**: newer note |
| WELL-0481 | Southeast Block 32 | INS-0481-0220, 01-14 14:30: producing (22.4 °C) | CTX-0481-006, 01-14 18:50: "Shut in … high pressure alarm on the separator." | **Not producing oil**: newer note |
| WELL-0010 | Southwest Block 23 | INS-0010-0219, 01-14 14:00: not producing (17.5 °C; needs ≥ 20) | CTX-0010-004, 01-09 04:00: "Restarted … after the crew cleared the lockout." | **Not producing oil**: newer inspection |
| WELL-0026 | Southwest Block 23 | INS-0026-0216, 01-14 12:15: not producing (5.4 °C) | CTX-0026-001, 01-15 10:25: "put back on production after the repair crew finished." | **Producing oil (unconfirmed)** |
| WELL-0032 | Southwest Block 23 | INS-0032-0219, 01-14 08:30: not producing (7.4 °C) | CTX-0032-006, 01-15 10:25: "Brought … back online after the pump change." | **Producing oil (unconfirmed)** |
| WELL-0033 | Southwest Block 23 | INS-0033-0222, 01-14 14:45: not producing (10.0 °C) | CTX-0033-003, 01-15 10:25: "Restarted WELL-0033, unit running smooth." | **Producing oil (unconfirmed)** |
| WELL-0044 | Southwest Block 23 | INS-0044-0218, 01-14 07:30: producing (23.7 °C) | CTX-0044-008, 01-14 13:05: "Shut in … flowline leak suspected." | **Not producing oil**: newer note |
| WELL-0046 | Southwest Block 23 | INS-0046-0220, 01-14 13:00: not producing (2.1 °C) | CTX-0046-004, 01-15 10:25: "put back on production after the repair crew finished." | **Producing oil (unconfirmed)** |

Dates are 2027 unless shown. **How:** `status_conflicts()` compares each well's latest inspection (manual
temperature rule for its type) with its latest shut-in or restart note, and applies OPS-3: the newer record
decides. A restart that no inspection has confirmed yet is "producing (unconfirmed)". Visual: table.

<div style="page-break-after: always;"></div>

### Q7. What the operators are hearing — Robert Hayes

**Turn 1.** *"Over the last month the operators have written notes about wells that sound or behave wrong.
Which of those wells haven't had a repair since? Rank the 10 most likely to need a repair in the next 90
days, other than a spill clean-up, and quote the notes as evidence."*

> "Based on operator notes from the last month (2026-12-16 to 2027-01-15), here are the 10 wells most likely
> to need a repair in the next 90 days … The risk scores are a judgement based on the severity of the
> reported symptoms and historical repair frequency."

| # | Well | Area | Operator-note evidence | Other warning signs | Last repair |
|---|---|---|---|---|---|
| 1 | WELL-0336 | NW Block 12 | 12-24 "amps hunting on the drive panel, still running." (CTX-0336-003); 01-07 "drive tripping on underload, restarted from the panel." (CTX-0336-004); 01-14 "amps hunting…" (CTX-0336-005) | T500 falling wellhead-to-air Δ 37.3 → 33.1 °C (INS-0336-0215..0218), T500 §5 early warning; 1 corrective repair in 12 mo | MNT-0336-029, 2026-11-22, wellhead valve service |
| 2 | WELL-0344 | NW Block 12 | 12-21, 12-24 "Drive … showing amps hunting between 38 and 44 A." (CTX-0344-002, -003); 01-04 "drive tripping on and off overnight, reset it each time." (CTX-0344-004) | 5 corrective repairs in 12 mo | MNT-0344-035, 2026-12-01, wellhead valve service |
| 3 | WELL-0401 | NW Block 12 | 12-18, 01-14 "amps hunting on the drive panel, still running." (CTX-0401-003, -004) | T500 falling Δ 34.1 → 30.3 °C, T500 §5; 3 corrective repairs in 12 mo | MNT-0401-033, 2026-12-11, wellhead valve service |
| 4 | WELL-0498 | SE Block 32 | 01-09 "drive tripping on and off overnight…" (CTX-0498-004); 01-11, 01-12 "drive tripping on underload, restarted from the panel." (CTX-0498-005, -006) | 1 corrective repair in 12 mo | MNT-0498-031, 2027-01-03, separator level controller fault |
| 5 | WELL-0263 | SW Block 23 | 01-11 "Heard fluid pound…, unit still running." (CTX-0263-004); 01-14 "Rod squeal at … stuffing box, greased the polished rod." (CTX-0263-005) | Recalled pump in the ground; 4 corrective repairs in 12 mo; latest inspection not producing (4.0 °C) | MNT-0263-035, 2027-01-09, flowline pinhole leak |
| 6 | WELL-0175 | NE Block 8 | 12-17 "Heard fluid pound…" (CTX-0175-003); 12-21 "Rod squeal…" (CTX-0175-006); 12-26 "tagging bottom on the downstroke…" (CTX-0175-007) | 3 corrective repairs in 12 mo; latest inspection not producing (5.5 °C) | MNT-0175-035, 2026-11-28, wellhead valve service |
| 7 | WELL-0182 | NE Block 8 | 12-27 "rattling at … pump jack, keep an eye on it." (CTX-0182-005); 12-30 "tagging bottom…" (CTX-0182-007); 01-05 "Heard fluid pound…" (CTX-0182-008) | 6 corrective repairs in 12 mo | MNT-0182-029, 2026-12-26, walking beam bearing wear |
| 8 | WELL-0197 | NE Block 8 | 01-04 "rattling at … pump jack…" (CTX-0197-002); 01-08, 01-12 "Heard fluid pound…" (CTX-0197-003, -004) | 2 corrective repairs in 12 mo; latest inspection not producing (1.2 °C) | MNT-0197-029, 2027-01-01, sucker rod parted |
| 9 | WELL-0219 | SE Block 31 | 01-05 "drive tripping on underload…" (CTX-0219-006); 01-13 "amps hunting between 38 and 44 A." (CTX-0219-007) | 2 corrective repairs in 12 mo; latest inspection not producing (4.5 °C) | MNT-0219-022, 2026-11-24, wellhead valve service |
| 10 | WELL-0005 | SW Block 23 | 12-24 "Heard fluid pound…" (CTX-0005-004); 12-30 "tagging bottom…" (CTX-0005-005); 01-08 "Rod squeal…" (CTX-0005-006) | 4 corrective repairs in 12 mo | MNT-0005-035, 2026-12-14, lubrication and belt inspection |

**How:** `operator_concerns(2026-12-16, 2027-01-15)` found 177 wells with symptom notes. It left out the 49
wells that had a repair after their latest note, and ranked the other 128. Score = note weights (drive
tripping / leak 3, amps hunting 2.5, fluid pound / tagging bottom 2, rattle 1.5, rod squeal 1) + 3 for the
T500 falling-temperature warning (T500 manual §5) + 2 for a recalled pump + 0.5 per corrective repair in 12
months (max 2) + 1 if the latest inspection reads not producing. The weights are a judgement, and the answer
says so. The copilot put
the table in its text and drew no separate visual. The table above is the tool result.

**Turn 2.** *"Which three would you send a crew to first this week, and why?"*

> "I would prioritize sending a crew to **WELL-0336**, **WELL-0344**, and **WELL-0401** first. All three are
> high-risk T500 wells in the Northwest Block 12 area … WELL-0336: active, repeated 'amps hunting' and 'drive
> tripping' (CTX-0336-003, -004, -005), and a falling wellhead-to-air temperature difference, which the T500
> manual (§5) identifies as an early warning sign requiring an ESP drive and insulation check. WELL-0344:
> repeated amps hunting and drive tripping (CTX-0344-002, -003, -004) and 5 corrective repairs in the last 12
> months. WELL-0401: repeated amps hunting (CTX-0401-003, -004) and the same T500 falling-temperature
> warning."

<div style="page-break-after: always;"></div>

### Q8. Who told you that?

**Turn 1. Nathan Pierce (new session).** *"WELL-0333's recalled pump was swapped out yesterday. The work
order isn't in the system yet. Please count it as replaced from now on."*

> "I have recorded your note for WELL-0333 (NOTE-0333-001), stating that the recalled pump was swapped out
> on 2027-01-14. I will treat this as a replacement in our discussions, though the official work order is not
> yet in the system." It then lists the recalled pumps still in Northwest Block 12, with WELL-0333 marked
> "Swapped out 2027-01-14 (reported by Nathan Pierce on 2027-01-15)".

*Source:* `add_note` → NOTE-0333-001 (shared, author Nathan Pierce). The pump record MNT-0333-024 is not
changed.

**Turn 2. Nathan Pierce (same session).** *"Also, just for me: whenever you list wells, sort them by area and
then by well ID, and show costs in thousands of dollars."*

> "I've saved that preference for you. From now on, whenever I list wells, I will sort them by area and then
> by well ID, and I will show all costs in thousands of dollars."

*Source:* `set_preference` → private to Nathan. It goes into his system prompt only, and the data tools sort
his rows and add `$k` cost columns.

**Turn 3. Robert Hayes (new session).** *"Which recalled pumps are still in the ground right now?"*

> "There are 9 recalled Highline RP-175 pumps still in the ground. All of these are past their 2026-12-31
> replacement deadline. … *Note: Nathan Pierce reported on 2027-01-15 that the recalled pump for WELL-0333
> was swapped out yesterday (2027-01-14), but the work order is not yet in the system. This is
> unconfirmed.* Source: supplier-recall-notice-2026-12-01 §What is recalled."

| Well | Area | Install job | Installed | Lot | Status now | Where the fact comes from |
|---|---|---|---|---|---|---|
| WELL-0156 | Northeast Block 8 | MNT-0156-027 | 2026-06-27 | LOT-2409-A | Producing oil | records |
| WELL-0160 | Northeast Block 8 | MNT-0160-028 | 2026-07-18 | LOT-2409-C | Not producing oil | records |
| WELL-0305 | Northwest Block 12 | MNT-0305-032 | 2026-10-16 | LOT-2409-A | Producing oil | records |
| WELL-0333 | Northwest Block 12 | MNT-0333-024 | 2026-05-09 | LOT-2409-A | Producing oil | records + **user report NOTE-0333-001 (unconfirmed swap)** |
| WELL-0426 | Northwest Block 12 | MNT-0426-030 | 2026-06-19 | LOT-2409-C | Producing oil | records |
| WELL-0428 | Northwest Block 12 | MNT-0428-022 | 2026-03-07 | LOT-2410-B | Producing oil | records |
| WELL-0577 | Southeast Block 32 | MNT-0577-028 | 2026-07-31 | LOT-2409-A | Producing oil | records |
| WELL-0031 | Southwest Block 23 | MNT-0031-027 | 2026-04-24 | LOT-2409-A | Producing oil | records |
| WELL-0263 | Southwest Block 23 | MNT-0263-033 | 2026-10-16 | LOT-2410-B | Not producing oil | records |

Robert does **not** get Nathan's sorting or $k preference (it is private). He does see Nathan's note, because
notes are shared. The note is labeled as a user report, not as a record.

**Turn 4. Olivia Grant (new session).** *"Nathan told me the recalled pump on WELL-0577 was swapped as well.
Take it off the recall list."*

> "I have recorded your note about WELL-0577 (NOTE-0577-001), but I cannot remove it from the recall list
> yet. Because this is a second-hand claim (you mentioned Nathan told you), I have marked it as unconfirmed.
> To officially clear the well from the recall list, I need a recorded work order or maintenance report
> showing the new pump installation. … the latest recorded maintenance for WELL-0577 is a scheduled
> lubrication and belt inspection (MNT-0577-033) from 2026-12-07."

**Turn 5. Nathan Pierce (new session).** *"Show me the recalled pumps that are still in the ground in my area,
and what it cost to install each one."*

> "There are 4 recalled Highline RP-175 pumps still in the ground in Northwest Block 12. All of these are
> currently overdue for replacement (deadline was 2026-12-31). … **Note on WELL-0333:** You reported that this
> pump was swapped out yesterday (2027-01-14), but the work order is not yet in the system (NOTE-0333-001)."

| Well | Area | Install job | Install cost ($k) | Status now |
|---|---|---|---|---|
| WELL-0305 | Northwest Block 12 | MNT-0305-032 | 24.5 | Producing oil |
| WELL-0333 | Northwest Block 12 | MNT-0333-024 | 15.4 | Producing oil (user report: swapped 2027-01-14, NOTE-0333-001) |
| WELL-0426 | Northwest Block 12 | MNT-0426-030 | 24.0 | Producing oil |
| WELL-0428 | Northwest Block 12 | MNT-0428-022 | 27.1 | Producing oil |

His turn-2 preference is applied in a new session: rows sorted by area then well ID, costs in $k (from the
install jobs' parts + labour). "My area" = the wells of his team, Northwest Production.

**Our judgement on WELL-0333.** Nathan asked us to "count it as replaced from now on". We keep his report
next to every answer that lists the pump. But we do not take the well off the recall list without a work
order, because the recall is a safety and regulatory list. Olivia's claim about WELL-0577 is second-hand, and
Nathan's own notes say nothing about WELL-0577. So it stays on the list, marked unconfirmed.

<div style="page-break-after: always;"></div>

### Q9. One conversation, several topics — Robert Hayes (one session)

**1.** *"How many recalled pumps are still in the ground, and in which areas?"*

> "There are **9** recalled Highline RP-175 pumps still in the ground. All are currently overdue for
> replacement (deadline was 2026-12-31)."

| Area | Count | Wells |
|---|---|---|
| Northwest Block 12 | 4 | WELL-0305, WELL-0333, WELL-0426, WELL-0428 |
| Northeast Block 8 | 2 | WELL-0156, WELL-0160 |
| Southwest Block 23 | 2 | WELL-0031, WELL-0263 |
| Southeast Block 32 | 1 | WELL-0577 |

> "**WELL-0333:** Nathan Pierce reported on 2027-01-15 that the recalled pump was swapped out yesterday … but
> the work order is not yet in the system. **WELL-0577:** Olivia Grant reported on 2027-01-15 that Nathan
> Pierce said the pump was swapped, but this is unconfirmed as there is no corresponding record for this
> well. I have kept it on the list; please provide the work order to confirm."

**2.** *"Different topic. Who leads Northwest Production, and how many wells does that team run?"*

> "Northwest Production is led by **Nathan Pierce** (U-601) and runs **150 wells**." (`team_summary`, from
> `wells.team_id`, so it counts wells that moved teams correctly.)

**3.** *"What does our operations SOP say about cold weather? Name one well that missed the check in
December."*

> "According to the Operations SOP (rev 2, §OPS-5), during the freeze protection period (1 Dec – 28 Feb), any
> inspection that records an ambient temperature of **-5 °C or below** on a well that is producing oil
> requires a maintenance job. This job must have an issue containing '**Heat trace check**' and must start
> within **7 days** of the inspection. One well that missed this check in December is **WELL-0310**
> (inspected on 2026-12-17 with an ambient temperature of -6.0 °C; ID: INS-0310-0213)."

**4.** *"An operator reported a gas smell at WELL-0332 on 3 Dec. What was the H2S reading?"*

> "There was no H2S reading taken for the gas odor reported at WELL-0332 on 2026-12-03 (ID: CTX-0332-004)
> because there was no field response following the report."

This matches Q3: WELL-0332 is one of the two reports with no response at all. The copilot does not make up a
reading.

**5.** *"Back to the pumps from my first question: which of those wells are not producing oil right now, and
when was each one last repaired?"*

> "Of the recalled pumps still in the ground, the following wells are not currently producing oil:"

| Well | Last repair |
|---|---|
| WELL-0160 | 2027-01-15 (MNT-0160-032) |
| WELL-0263 | 2027-01-09 (MNT-0263-035) |

It finds "my first question" in the same thread, with `recall_conversations`. Then it runs `well_status` on
the 9 wells (OPS-3 status now) and `well_records` to get each repair.

**6.** *"Of all the wells we've talked about today, which one would you deal with first, and why?"*

> "I would prioritize **WELL-0160** first. … 1. **Active Mechanical Issue:** It has an open corrective repair
> (MNT-0160-032) for 'Walking beam bearing wear' that is currently in progress. 2. **Recent Status Change:**
> Its non-producing status was confirmed by a drone inspection as recently as 2027-01-14 … 3. **Recalled
> Pump Urgency:** It contains a Highline RP-175 from lot LOT-2409-C, which is overdue for replacement.
> **WELL-0263** is also a high priority due to a very recent corrective repair for a 'Flowline corrosion
> pinhole leak' (MNT-0263-035) on 2027-01-09."

<div style="page-break-after: always;"></div>

### Q10. What are we waiting on? — Michael Turner

> *"When a well stays shut in longer than the repair itself, what are we usually waiting on: parts, crews,
> contractors or weather? Break it down by area for jobs started in 2026, with the typical number of extra
> days, and tell me if any area stands out."*

> "For jobs started in 2026, the most common reason wells stayed shut in longer than the repair itself was
> waiting on **contractors** (32.6% of all waiting jobs), followed by **crews** (26.9%) and **weather**
> (22.0%)."

Share of waiting jobs · typical (median) extra days, by area:

| Area | Parts | Crews | Contractors | Weather |
|---|---|---|---|---|
| Northeast Block 7 | 23.4% · 15.0 d | 21.9% · 11.5 d | 31.2% · 9.0 d | 23.4% · 9.0 d |
| Northeast Block 8 | 16.2% · 10.0 d | 31.2% · 9.0 d | 30.0% · 9.0 d | 22.5% · 8.0 d |
| Northwest Block 12 | 17.0% · 9.0 d | 31.6% · 9.0 d | 30.4% · 9.0 d | 21.1% · 9.0 d |
| **Southeast Block 31** | 15.0% · 8.5 d | 22.5% · 9.0 d | **42.5% · 14.0 d** | 20.0% · 12.5 d |
| Southeast Block 32 | 18.7% · 9.5 d | 26.6% · 10.0 d | 32.4% · 9.0 d | 22.3% · 8.0 d |
| Southwest Block 23 | 22.2% · 12.5 d | 26.4% · 7.0 d | 29.2% · 9.0 d | 22.2% · 9.0 d |
| Southwest Block 24 | 18.2% · 8.0 d | 18.2% · 12.0 d | 40.9% · 9.0 d | 22.7% · 10.0 d |
| **All areas** | 18.5% · 9.0 d | 26.9% · 9.0 d | 32.6% · 9.0 d | 22.0% · 9.0 d |

> "**Southeast Block 31** stands out significantly for contractor delays. Contractors account for **42.5%** of
> its waiting jobs (compared to the 32.6% field average), and the typical delay is **14.0 days**, much higher
> than the field-wide typical of 9.0 days. **Northeast Block 7** also shows a notable delay when waiting on
> **parts**, with a typical extra time of **15.0 days** (compared to the 9.0-day field average)."

**How:** `waiting_reasons(2026-01-01, 2026-12-31)` reads two sentences in the repair reports: "the well
stayed shut in for about N days longer than the repair itself because …" (parts back-ordered, crew busy
elsewhere, contractor slot, weather), and "<owner>'s workover rig was busy …, so the well waited about N
days". A busy company rig counts as crews and a busy contractor rig as contractors, so every wait falls into
one of the four reasons. Interim reports (job still in progress) are left out.
Visual: stacked bar chart of the share of each reason, by area (632 waiting jobs).

### Q11. Hotter wells — Olivia Grant

> *"Which region of the field consistently runs hotter?"*

> "The **Southeast** region consistently runs the hottest, with the highest mean temperature above ambient in
> every month from January 2026 through January 2027. However, the data indicates this is primarily due to
> the well mix rather than geography. When comparing wells of the same type, the temperature differences
> between regions are minimal (less than 0.9 °C). The Southeast appears hotter because it has a significantly
> higher share of T500 (ESP) wells, which run hotter by design (T500 manual §3)."

Mean wellhead temperature above air (°C), by region and month (the copilot's heatmap):

| Region | 26-01 | 26-02 | 26-03 | 26-04 | 26-05 | 26-06 | 26-07 | 26-08 | 26-09 | 26-10 | 26-11 | 26-12 | 27-01 | T500 share of readings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Southeast** | 30.8 | 30.9 | 30.9 | 30.6 | 30.6 | 30.8 | 30.7 | 31.0 | 30.6 | 30.9 | 30.6 | 30.7 | 30.4 | 32% |
| Northwest | 30.0 | 29.9 | 29.9 | 29.5 | 29.8 | 29.7 | 29.7 | 29.6 | 29.4 | 29.6 | 29.5 | 29.6 | 29.7 | 23% |
| Northeast | 28.3 | 28.4 | 27.9 | 28.2 | 28.2 | 28.2 | 28.2 | 28.1 | 28.4 | 28.2 | 28.2 | 27.8 | 27.6 | 2% |
| Southwest | 27.8 | 28.2 | 28.3 | 28.3 | 28.1 | 28.3 | 28.1 | 28.3 | 28.4 | 28.1 | 28.0 | 28.1 | 28.1 | 3% |

**How:** `field_temperature(group_by="region")` uses producing readings and the temperature *above air*,
so the seasons and the local weather drop out. It then repeats the comparison within each well type: T200
47.7–47.8 °C, T350 52.6–52.8 °C, T500 57.8–58.7 °C in every region. The judgement: the Southeast is hotter every month, but the cause is the well mix (more T500
ESP wells), not the ground.

---

#### Known gaps in these answers

- **Q9.1 visual:** the bar chart plots each pump's install cost by area, not the count of pumps. The text
  table has the correct counts.
- **Q10 visual:** the stacked bar puts the reasons on the axis and stacks the areas. The question asked for
  bars by area, stacked by reason. The data is the same.
- **Q7 turn 1** has no separate visual. The ranked table is in the text.
- **The check** flagged Q2 and Q3 because their dates came from the question (2026-01-01, 2026-11-01), not
  from a tool result. Both answers are correct. The checker should also accept dates from the tool arguments.
