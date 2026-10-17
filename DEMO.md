# 5-minute demo script: Asset Intelligence Copilot

## Before you record (5 min)
```bash
cp data/copilot.db .context/demo.db        # fresh memory, so Q8 starts clean
DB_PATH=.context/demo.db uv run langgraph dev --no-browser --port 2024 --allow-blocking
cd web && npm run dev -- -p 3000           # http://localhost:3000
```
- The full write-up and answers are in `SUBMISSION.md`.
- Have `ARCHITECTURE.md` open in a preview (it has the two diagrams).
- Answers take 15–25 s. Record, then cut the waits.
- Optional: ask Q4 once before recording, so a finished chat is ready if the live one is slow.

---

## Part 1: Architecture and lessons (0:00–2:00)

**[0:00–0:15] Hook (on the chat UI)**
> "This is a copilot for an oil field: 600 wells, four years of inspections, repairs, spill
> reports and procedures. Operators ask in plain English and get an answer with its sources
> and one visual. The data is synthetic; the problems in it are realistic."

**[0:15–1:05] How it works (on diagram 1 in ARCHITECTURE.md)**
> "A question goes through four steps.
> **Get ready:** the prompt is built from the database: today's date, and who is asking, with
> their role, team and wells.
> **Look it up:** a small open model, Gemma 4 26B, picks from 27 lookups. Each lookup applies
> one rule from the procedures in plain code: the gas-response deadline, the bypass approval
> rules, which pump lots are recalled.
> **Double-check:** before you see the answer, plain code checks that every well ID, record ID
> and number in it is in the looked-up data. If one isn't, the model rewrites once.
> **Remember:** each person's chats stay private. What people tell the copilot is shared,
> always with who said it and when."

**[1:05–1:20] The data layers (on diagram 2)**
> "The database has three layers. Layer 1 is the field records, which the copilot never edits.
> Layer 2 is what people taught it: corrections, notes and rules. Layer 3 is views that combine
> the two and apply the precedence rules. The test data came out today, with 400 new wells and
> new procedures. Reloading takes one command and about 7 seconds."

**[1:20–2:00] Lessons learnt**
> "Three lessons:
> 1. **With a small model, put the logic in code, not in the prompt.** Every rule is a tested
>    lookup, and the model only presents the result. Every option you give the model is a
>    chance to get it wrong. Once, it switched on an option we had added and gave the wrong
>    breakdown, so we removed that option.
> 2. **Check answers with code, not a second AI.** The ID and number check is exact and costs
>    nothing.
> 3. **Read the raw data and run the real questions early.** The data has traps: there is no
>    pressure data at all, one well changed type in November, and one approval memo extends
>    another. Running all 21 turns end to end takes about 100 seconds, and it caught four bugs
>    that the 317 unit tests missed."

---

## Part 2: Live demo (2:00–5:00)

**[2:00–2:20] It says what it doesn't know: Q1** (user: Michael Turner)
> Type: *"All our wells feed one reservoir. Map the reservoir pressure across the field from the pressure data."*

Say: *"There is no reservoir pressure in this data. A chatbot would draw a map anyway. Ours
says the measurement doesn't exist and offers a proxy, clearly labelled as one."*

**[2:20–3:15] Use case 1: a compliance audit from three documents: Q4** (user: Chris Dalton, HSE)
> Type: *"Across all areas, which temporary flowline bypasses are in place right now, and is
> each one allowed? Also list any bypass, past or present, that stayed in after its approval
> ran out or was never approved at all."*

While it runs: *"To answer this, it pairs bypass-in and bypass-out operator notes, then checks
each bypass against the approval memos, including an extension memo that changes another
memo's expiry date."*

On the answer:
- 3 bypasses in place now: WELL-0248 is allowed (MOC-2026-031, extended to 28 Feb). WELL-0249
  has expired. WELL-0405 was never approved.
- Point at the record IDs in the table: *"Every row cites the notes and the memo it came
  from. This is an audit an HSE officer would otherwise do by hand."*

**[3:15–4:45] Use case 2: "Who told you that?" Memory and sources across users: Q8**

1. **Nathan Pierce** (new chat): *"WELL-0333's recalled pump was swapped out yesterday. The
   work order isn't in the system yet. Please count it as replaced from now on."*
   → *"It saves this as a note marked unconfirmed, with his name and the date. The field
   records stay unchanged."*
2. Same chat: *"Also, just for me: whenever you list wells, sort them by area and then by well
   ID, and show costs in thousands of dollars."* → *"This is a private preference."*
3. Switch to **Robert Hayes** (new chat): *"Which recalled pumps are still in the ground right now?"*
   → *"Nine pumps. WELL-0333 is still on the list, flagged 'reported swapped by Nathan Pierce,
   unconfirmed'. Robert sees what Nathan said and who said it, but the data isn't overwritten."*
4. Switch to **Olivia Grant**: *"Nathan told me the recalled pump on WELL-0577 was swapped as
   well. Take it off the recall list."*
   → *"A second-hand claim with no work order. It keeps WELL-0577 on the list and asks for the
   work order."*
5. Switch to **Nathan** (new chat): *"Show me the recalled pumps that are still in the ground in
   my area, and what it cost to install each one."*
   → *"Four wells in his area, with costs in thousands of dollars: his preference from an earlier
   chat is applied. His own report on WELL-0333 is shown next to it."*

**[4:45–5:00] Close**
> "All 11 final questions run from one script in about 100 seconds, and every answer shows its
> sources. Small model, logic in code, every answer checked. Thanks."

---

## Backup use cases (if one of the above misbehaves)
- **Q6 (Nathan Pierce):** *"Across the whole field, not just my area, for which wells do the
  latest inspection and the operator notes disagree about whether the well is producing oil?"*
  Gives 12 wells. Point at WELL-0010: it became a T350 in November, so 17.5 °C above air now
  reads as not producing.
- **Q11 (Olivia Grant):** *"Which region of the field consistently runs hotter?"* The
  Southeast reads hottest every month, but only because a third of its wells are T500 ESP
  wells. Like-for-like, no region runs hotter.
- **Q3 (Laura Simmons):** gas reports against the 24 h and 12 h deadlines: 26 reports, 9
  missed.
