# 5-minute demo script

Each part tells you what to **show**, what to **do** and what to **say**.
Read the "Say" lines out loud. They are short on purpose.

---

## Before you record

**1. Start the copilot** (two terminals, in the repo folder):

```bash
# Terminal 1: the copilot server, on a fresh copy of the database
cp data/copilot.db .context/demo.db
DB_PATH=.context/demo.db uv run langgraph dev --no-browser --port 2024 --allow-blocking

# Terminal 2: the website
cd web && npm run dev -- -p 3000
```

Open **http://localhost:3000**.

**2. Get backup answers ready** (optional, about 3 min). These are finished chats you can show
if a live answer is slow:

```bash
uv run python scripts/seed_demo.py --final --cases Q1 Q2 Q3 Q4 Q5 Q6 Q7 Q10 Q11
```

Do not seed Q8 or Q9. You will ask Q8 live, and it must start with no saved notes.

**3. Open these:**
- The website, with the window big and zoomed in (**Command +**).
- `ARCHITECTURE.md` in a preview. It has the two diagrams.

**4. Remember:** each answer takes 15–25 seconds. Keep recording, and cut the waits later.

**To change who is talking:** use the **"Talking as"** box at the top left of the website.
**To start a new chat:** click **"New Thread"**.

---

## Part 1: What it is and how it works (0:00–2:00)

### 0:00–0:15 · What it is
**Show:** the chat website.

**Say:**
> "This is a chat assistant for an oil field. It has 600 wells and four years of records:
> inspections, repairs, spills and procedures. You ask a question in plain English. You get an
> answer, the records it came from, and one picture."

### 0:15–1:05 · How it answers a question
**Show:** diagram 1 in `ARCHITECTURE.md`.

**Say:**
> "Every question goes through four steps. It's a LangGraph graph, running on the LangGraph
> server behind this website.
>
> **One: get ready.** The system prompt is built from the database: today's date and who is
> asking, with their role, team and wells.
>
> **Two: look it up.** This is a ReAct loop. A small open model, Gemma 4 26B on OpenRouter, calls
> a tool, reads the result, and repeats until it can answer. It has 27 typed tools. Each one is one
> rule from our procedures, written in Python over SQL. For example: how fast we must respond to a
> gas report, or which pumps are recalled. Charts work the same way: the model points at a tool
> result by its ID, and never types the numbers itself.
>
> **Three: double-check.** Before you see the answer, plain code (not a second AI) checks every
> well ID, record ID and number in it. Each one must be in a tool result. If not, the model gets
> the list of problems and writes the answer again, once.
>
> **Four: remember.** Your chats are private. What you tell it is shared with everyone, with your
> name and the date."

### 1:05–1:20 · How the data is stored
**Show:** diagram 2 in `ARCHITECTURE.md`.

**Say:**
> "It's one SQLite database with three layers. Layer 1 is the field records. The assistant never
> changes them. Layer 2 is what people told it: corrections, notes and rules, plus each person's
> private chats and settings. Layer 3 is SQL views that combine the two. For example, a user's
> rule beats the manual, and a rule for one well beats a rule for all wells. The new test data
> came out today. Loading it took one command and 7 seconds."

### 1:20–2:00 · What we learned
**Say:**
> "We learned three things.
>
> **First: with a small AI, put the logic in code.** The AI only explains the result. Every choice
> you give it is a chance to get it wrong.
>
> **Second: check answers with code, not with another AI.** It is exact, and it is free.
>
> **Third: read the data and run the real questions early.** The data had traps. There is no
> pressure data at all, and one well changed type in November. Running all 21 questions takes
> about 100 seconds. It found four bugs that our 317 tests missed."

---

## Part 2: Live demo (2:00–5:00)

### 2:00–2:20 · It says when it doesn't know (Q1)
**Do:** talk as **Michael Turner**. Type:
> All our wells feed one reservoir. Map the reservoir pressure across the field from the pressure data.

**Say:**
> "There is no pressure data. Many chatbots would draw a map anyway. Ours says the data doesn't
> exist, and it offers something close instead, clearly labelled."

### 2:20–3:15 · A safety audit (Q4)
**Do:** talk as **Chris Dalton**. Type:
> Across all areas, which temporary flowline bypasses are in place right now, and is each one allowed? Also list any bypass, past or present, that stayed in after its approval ran out or was never approved at all.

**Say while it works:**
> "A bypass is a temporary pipe work-around. It needs a written approval, and the approval runs
> out. The model calls one tool, `bypasses`. In code, the tool matches the notes for each bypass
> going in and coming out, then checks each one against the approval memos. One memo even
> extends another one. You can open the tool call under the answer."

**Say on the answer:**
> "Three bypasses are in place now. WELL-0248 is allowed. WELL-0249's approval ran out.
> WELL-0405 was never approved. Every row shows the records it came from. A safety officer
> would normally do this by hand."

### 3:15–4:45 · "Who told you that?" (Q8)
Five short steps. Each person starts a **new chat**.

**1. Talk as Nathan Pierce.** Type:
> WELL-0333's recalled pump was swapped out yesterday. The work order isn't in the system yet. Please count it as replaced from now on.

**Say:** "It saves this as a note, with Nathan's name and the date. The official records don't change."

**2. Same chat.** Type:
> Also, just for me: whenever you list wells, sort them by area and then by well ID, and show costs in thousands of dollars.

**Say:** "This is a private setting. Only Nathan gets it."

**3. Talk as Robert Hayes.** Type:
> Which recalled pumps are still in the ground right now?

**Say:** "Nine pumps. WELL-0333 is still on the list, with a flag: Nathan says it was swapped,
but no record confirms it yet. Robert sees what Nathan said, and who said it."

**4. Talk as Olivia Grant.** Type:
> Nathan told me the recalled pump on WELL-0577 was swapped as well. Take it off the recall list.

**Say:** "This is second-hand, and there is no work order. So it keeps the well on the list and
asks for the work order."

**5. Talk as Nathan Pierce.** Type:
> Show me the recalled pumps that are still in the ground in my area, and what it cost to install each one.

**Say:** "Four pumps in his area. The costs are in thousands of dollars, so his private setting
from the earlier chat works. His own note about WELL-0333 is shown next to it."

### 4:45–5:00 · Close
**Say:**
> "All 11 test questions run from one script, and every answer shows where it came from.
> A small AI, the rules in code, and every answer checked. Thank you."

---

## If something goes wrong: backup questions

Use one of these instead, or show its finished chat from step 2 of "Before you record".

| Talk as | Type | What to point out |
|---|---|---|
| Nathan Pierce | *Across the whole field, not just my area, for which wells do the latest inspection and the operator notes disagree about whether the well is producing oil?* | 12 wells. For each one, the newer record decides. WELL-0010 changed type in November, so the same temperature now means "not producing". |
| Olivia Grant | *Which region of the field consistently runs hotter?* | The Southeast looks hotter every month. But that is only because it has more of the hotter T500 wells. Compared type by type, no region runs hotter. |
| Laura Simmons | *Since 1 Nov 2026, every time an operator note reports gas at a well, did we get someone out to that well in time under our operating procedures?* | 26 gas reports. 17 met the deadline and 9 missed it. Two had no response at all. |
