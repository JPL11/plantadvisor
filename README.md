# 🪴 Plant Advisor

A conversational agent that helps users care for their houseplants. Ask it anything about a plant in its database and it looks up the care requirements, checks the current seasonal context, and gives specific, grounded advice — composed from real data, not hallucinated.

**Status: complete.** All milestones plus the optional `get_plant_list` challenge are implemented, with robustness fixes for real-world LLM tool-calling quirks. Built for AI201 Lab 2.

---

## How It Works

Unlike a RAG system, Plant Advisor is a **tool-calling agent**: the LLM decides which lookups it needs, calls local tool functions, and composes the results into an answer with clear provenance.

```
user ─→ app.py (Gradio) ─→ run_agent() ─→ Groq LLM ──── tool_calls ───┐
                               ▲                                      │
                               │            dispatch_tool() ─→ tools.py ─→ data/*.json
                               └──────────── tool results ────────────┘
                       (loop, max 5 rounds, then a final tools-off call)
```

### Tools

| Tool | What it does |
|---|---|
| `lookup_plant(plant_name)` | Three-pass search over the 15-plant database: exact key → display name → alias, all case-insensitive. Returns full care data, or a structured not-found result that triggers graceful degradation. |
| `get_seasonal_conditions(season?)` | Returns seasonal care guidance; auto-detects the current season from the system date when no (or an invalid) season is given. |
| `get_plant_list()` *(optional challenge)* | Returns all 15 plants with name + difficulty only — a deliberately small payload for broad questions like "what's a good beginner plant?". |

### The agent loop (`agent.py`)

`run_agent()` builds the message list from chat history plus a system prompt, calls Groq (`llama-3.3-70b-versatile`) with the tool schemas, executes **every** tool call in each assistant turn (the model frequently requests `lookup_plant` and `get_seasonal_conditions` together), feeds results back, and loops up to `MAX_TOOL_ROUNDS = 5` before forcing a final tools-off answer.

### Robustness work (the interesting part)

Real tool-calling LLMs misbehave in ways the happy path doesn't show:

- **Malformed tool syntax** — llama-3.3 intermittently emits `<function=...>` text instead of structured JSON, failing with `tool_use_failed`. A retry wrapper (`_create_with_retry`) resubmits the identical request, which reliably fixes it. Empty-parameter tools trigger this most often.
- **Null arguments** — empty-arg tool calls sometimes arrive as `null`/`""`; these are coerced to `{}` before dispatch.
- **Gradio history format** — Gradio's `type="messages"` passes history as role/content dicts, not `[user, assistant]` pairs; the loop handles both.
- **Graceful degradation** — for plants not in the database, the system prompt plus the structured not-found message make the agent acknowledge the gap, offer general guidance, and suggest confirming externally — never invent specifics.
- **No empty replies** — the loop is wrapped in try/except; API failures return a readable message instead of a crash or blank response.

### Tech stack

Python 3.12 · Gradio 5.x (`gradio>=5.25,<6` — 6.x removed `ChatInterface`) · Groq SDK (`llama-3.3-70b-versatile`, OpenAI-compatible tool calling) · python-dotenv

---

## Data

- **`data/plants.json`** — 15 plants (8 easy, 3 moderate, 2 hard), each with watering, light, humidity, temperature, fertilizing, common issues, per-season notes, and 3–5 aliases (so "devil's ivy" finds pothos).
- **`data/seasons.json`** — 4 seasons with watering/fertilizing/light/repotting/pest guidance and a month→season mapping for auto-detection.

When a plant has its own `seasonal_notes`, the system prompt prefers them over the generic seasonal guidance to avoid contradictory advice.

---

## Setup

**1. Clone the repo, then create and activate a virtual environment:**

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
# or: .venv\Scripts\activate   # Windows
```

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

**3. Add your Groq API key.** Copy `.env.example` to `.env` and paste in your key from [console.groq.com](https://console.groq.com).

**4. Run the app:**

```bash
python app.py
```

Plant Advisor opens in your browser with a plant-list sidebar and example questions (including an off-database plant to demo graceful degradation).

---

## Project Structure

```
plantadvisor/
├── app.py              # Gradio UI: chat, plant sidebar, example questions
├── config.py           # GROQ_API_KEY, LLM_MODEL, MAX_TOOL_ROUNDS, DATA_PATH
├── agent.py            # Tool schemas, system prompt, dispatch, run_agent() loop
├── tools.py            # lookup_plant, get_seasonal_conditions, get_plant_list
├── data/
│   ├── plants.json     # 15-plant care database
│   └── seasons.json    # Seasonal care data + month mapping
└── specs/              # Design docs, completed with real traces & findings
    ├── system-design.md
    ├── tool-functions-spec.md
    └── agent-loop-spec.md
```

The specs are filled in with design decisions, working tool-call traces, and edge cases discovered during implementation (slug vs. display-name matching, multi-tool turns, the `tool_use_failed` quirk).
