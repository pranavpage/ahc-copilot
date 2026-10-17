# How the copilot works

A person asks a question on the website. The AI looks up the answer in the field database, the
copilot checks every ID and number against what it looked up, and the person gets an answer with
its sources and one picture.

## 1. How a question gets answered

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 720}}}%%
flowchart TB
    person(["👤 Someone on the field team<br/>asks a question in plain English"])
    site["💬 Chat website<br/>pick who you are · ask · read the answer<br/>with its sources and one picture"]
    server["🗂️ Copilot server<br/>keeps each person's chat threads<br/>and tells the copilot who is asking"]
    other["⌨️ Terminal chat and<br/>automatic test questions"]

    subgraph copilot["🤖 The copilot"]
        prep["0️⃣ Get ready<br/>answering rules, today's date, and who is asking:<br/>name, role, team, areas (from the database)"]
        step1["1️⃣ Look it up<br/>the AI picks lookups, reads the results,<br/>repeats until it can write the answer"]
        step2{"2️⃣ Double-check<br/>are all IDs and numbers<br/>in the looked-up data?"}
        step3["3️⃣ Remember<br/>save the question, the answer, and<br/>the wells and records it named"]
        prep --> step1 --> step2
        step2 -- "no: rewrite once,<br/>with the problems listed" --> step1
        step2 -- "yes" --> step3
    end

    ai["🧠 AI model<br/>Gemma, with a backup model<br/>if the first one fails"]

    tools["<b>🔧 27 lookups the AI can use</b><br/><br/><b>Wells and status:</b> find a well · status right now · readings over time · days down · days producing<br/><b>Spills and repairs:</b> spills · repair costs · repeat repairs that need a root-cause review · all records of a well<br/><b>Compliance:</b> gas reports · safety bypasses · regulator letters · freeze checks · waiting reasons · team summary<br/><b>Equipment and field:</b> recalled pumps · status conflicts · operator concerns · field temperature · what the data measures<br/><b>Documents:</b> search manuals and reports · find every mention of a word<br/><b>Learn from users:</b> save a correction · add a note · set a rule<br/><b>Past chats:</b> recall this person's earlier chats<br/><b>Picture:</b> status card · table · line or bar chart · map · heatmap"]

    db[("📦 Database<br/>see diagram 2")]

    person --> site
    site <--> server
    server <--> copilot
    other -.-> copilot
    step1 <--> ai
    step1 <--> tools
    tools <--> db
    step3 --> db
```

## 2. What's in the database

One file, in three layers. The copilot never changes the dataset records. What people tell it is
kept apart, so reloading the dataset keeps it.

```mermaid
flowchart TB
    files["📄 Dataset files<br/>200 wells, 4 years of history"]
    load["Loader<br/>reads the files once"]
    remember["3️⃣ Remember<br/>(end of each answer)"]

    subgraph source["Layer 1 · Field records from the dataset · never changed by the copilot"]
        direction LR
        s1[("People and places<br/>users · teams · areas<br/>wells · equipment")]
        s2[("Field work<br/>inspections · repairs<br/>repair reports")]
        s3[("Regulator<br/>regulator events<br/>change approvals<br/>pump recall notices")]
        s4[("Documents<br/>well-type manuals<br/>and procedures,<br/>split into sections")]
    end

    subgraph learned["Layer 2 · Written by the copilot · kept when the dataset is reloaded"]
        direction LR
        k1[("Shared with everyone<br/>corrections · notes · rules<br/>each with who said it and why")]
        k2[("Private to each person<br/>their chats · questions and answers<br/>wells and records each answer named")]
    end

    subgraph views["Layer 3 · Ready-made views · layers 1 and 2 combined"]
        direction LR
        v1["Readings<br/>after corrections"]
        v2["Rules in force for each well<br/>user rule beats manual ·<br/>one well beats well type beats all"]
        v3["Real spills,<br/>with their size class"]
        v4["Status of each<br/>well right now"]
        v5["Pumps in each well,<br/>and recalled ones"]
    end

    lookups["🔧 Lookups"]

    s1 ~~~ s2 ~~~ s3 ~~~ s4
    files --> load --> source
    remember --> k2
    source --> views
    k1 --> views
    views --> lookups
    k1 <-- "read, and save a correction,<br/>add a note, set a rule" --> lookups
    k2 -- "recall past chats<br/>(only your own)" --> lookups
```

## Where each box is in the code

| Box | Code |
|---|---|
| Chat website | `web/` (Next.js + assistant-ui). Sends who is talking with every message. |
| Copilot server | `langgraph dev` serving `copilot/agent.py`. Lists the users for the picker (`copilot/http_app.py`). |
| 0️⃣ Get ready | `copilot/prompt.py` |
| 1️⃣ Look it up | The ReAct agent in `copilot/agent.py` |
| 2️⃣ Double-check | `copilot/verify.py`. Plain code, not a second AI. |
| 3️⃣ Remember | `copilot/memory.py` |
| AI model | Gemma on OpenRouter, with a fallback model (`copilot/llm.py`) |
| 27 lookups | `copilot/tools/` (`status.py`, `records.py`, `compliance.py`, `assets.py`, `wells.py`, `feedback.py`, `visual.py`) and `recall_conversations` in `copilot/agent.py` |
| Database | SQLite, `data/copilot.db`. Layout in `db/schema.sql`, loader in `db/load.py` |
| Terminal chat and automatic test questions | `copilot/chat.py` and `evals/`. They call the copilot directly (`copilot.api.ask`). |
