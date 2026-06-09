# Spec: Tool Functions

**File:** `tools.py`
**Status:** `get_seasonal_conditions` — Pre-implemented, read through. `lookup_plant` — complete spec fields before implementing.

---

## Purpose

These two functions are the tools the agent can call. They retrieve structured data from the local plant database and seasonal data files and return it to the agent loop, which passes it to the LLM as context for generating a response.

---

## Function 1: `lookup_plant()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `plant_name` | `str` | The plant name as entered by the user or chosen by the LLM — may be any casing, common name, scientific name, or alias |

**Output:** `dict`

When the plant is **found**, return:
```python
{"found": True, "plant": <the full plant dict from _plant_db>}
```

When the plant is **not found**, return:
```python
{"found": False, "name": <normalized input>, "message": <helpful string>}
```

---

### Design Decisions

*Complete the two blank fields below before writing code. The others are pre-filled for you.*

---

#### Input normalization

Strip leading/trailing whitespace and convert to lowercase before any comparison.

```python
normalized = plant_name.strip().lower()
```

---

#### Search order

Search in this order: direct key → display name → aliases. Keys are the fastest
lookup (O(1) dict access), so check those first. Display names are the next most
likely match for clean user input. Aliases are the broadest net, so they go last.

```
1. Direct key match: normalized in _plant_db
2. Display name match: plant["display_name"].lower() == normalized
3. Alias match: normalized in [alias.lower() for alias in plant["aliases"]]
```

---

#### Alias matching approach

*Aliases are stored as a list of strings. How will you check if the normalized input matches any alias in the list? Write your approach in pseudocode or plain English.*

```
Iterate over every plant in _plant_db. For each one, lowercase its aliases on
the fly and test membership:

    if normalized in (alias.lower() for alias in plant["aliases"]):
        return {"found": True, "plant": plant}

A generator expression keeps it case-insensitive without building a throwaway
list. This is O(total aliases) per lookup — fine for 15 plants. If the DB grew
to thousands, I'd precompute a flat {alias_lower: slug} index once at module
load so each lookup is O(1) instead of scanning every plant.
```

---

#### Not-found message

*When a plant isn't found, the agent will read your message and use it to decide what to tell the user. Write the exact string you'll return — make it useful to the agent, not just to a human reading logs.*

```
"'<name>' is not in the plant care database. Do not invent specific care
numbers for it. Acknowledge to the user that this plant isn't in your
database, then offer general houseplant guidance based on what they describe
(light, watering, symptoms) and suggest they confirm specifics against a
dedicated source."

This is an instruction to the agent, not a log line. It (a) states the fact,
(b) forbids hallucinating specifics — the key grounding guardrail — and
(c) tells the agent what useful thing to do instead. The behavior is enforced
in two layers: this message AND a matching rule in the system prompt.
```

---

#### Implementation Notes

*Fill this in after implementing and running the app.*

**Test: does `"devil's ivy"` return the pothos entry?**
```
Yes — matches via the alias list, returns found: True with display_name "Pothos".
```

**Test: does `"SNAKE PLANT"` return the snake plant entry?**
```
Yes — " SNAKE PLANT " (with stray whitespace) also works; strip().lower()
normalizes to "snake plant", which matches the display name. "sansevieria"
(scientific-ish alias) also resolves to Snake Plant.
```

**One edge case you discovered while implementing:**
```
The slug keys use underscores ("snake_plant") but users type spaces
("snake plant"). The space form never matches the direct key — it only
resolves because "Snake Plant" is also the display_name. So the display-name
and alias passes aren't redundant niceties; they're what makes natural input
work at all. A plant whose slug differed from its display name with no alias
covering the spaced form would be unreachable by normal typing.
```

---

## Function 2: `get_seasonal_conditions()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `season` | `str \| None` | One of `"spring"`, `"summer"`, `"fall"`, `"winter"`, or `None` to auto-detect |

**Output:** `dict`

The full season dict from `_season_data`, plus one additional field:

| Added field | Type | Value |
|-------------|------|-------|
| `"detected_season"` | `bool` | `True` if auto-detected from the month; `False` if season was passed as an argument |

---

### Design Decisions

*This function is pre-implemented — read through these fields and the code before working on `lookup_plant`.*

---

#### Auto-detection logic

When `season` is `None`, get the current calendar month with `datetime.now().month`
and look it up in the `_MONTH_TO_SEASON` dict, which maps month numbers to season strings.

```python
current_month = datetime.now().month
season_key = _MONTH_TO_SEASON[current_month]
```

---

#### Season validation

If the caller passes an invalid season string (e.g., `"monsoon"`), the function
falls back to auto-detection — same as if `None` were passed. The `VALID_SEASONS`
set acts as the gate:

```python
VALID_SEASONS = {"spring", "summer", "fall", "winter"}
if season and season.lower() in VALID_SEASONS:
    ...  # use provided season
else:
    ...  # auto-detect
```

---

#### Return structure

The full season dict from `_season_data`, plus a `detected_season` boolean. Example for spring:

```python
{
    "season": "spring",
    "watering": "Increase watering frequency as plants break dormancy ...",
    "fertilizing": "Resume feeding with a balanced fertilizer ...",
    "light": "Days are lengthening — move plants closer to windows ...",
    "pests": "Watch for spider mites and aphids as temperatures rise ...",
    "detected_season": True   # True = auto-detected; False = caller specified
}
```

---

#### Implementation Notes

*Fill this in after testing.*

**Test: does calling with `season=None` return the correct season for the current month?**
```
Current month: 6 (June)
Expected season: summer
Returned season: Summer (detected_season: True)
```

**Test: does calling with `season="winter"` return winter data regardless of the current month?**
```
Yes — returns Winter data with detected_season: False, even though it's
currently June. Invalid strings (e.g. "monsoon") fall back to auto-detection.
```

---

## Function 3: `get_plant_list()`  *(optional challenge)*

### Input / Output Contract

**Inputs:** none.

**Output:** `dict`

```python
{
    "count": 15,
    "plants": [
        {"display_name": "Pothos", "difficulty": "easy"},
        {"display_name": "Snake Plant", "difficulty": "easy"},
        ...
    ],
}
```

### Purpose

Answers questions about the collection as a whole rather than a single named
plant — "what plants do you know about?", "what's a good beginner plant?".
Without this, the agent can only look plants up by name and has no way to
enumerate or filter by difficulty.

### Design decisions

- **Returns name + difficulty only**, not full care records. The agent uses it
  to *survey* the catalog or pick a beginner plant; if the user then drills
  into one, it calls `lookup_plant` for the details. Keeping the payload small
  avoids flooding the context with 15 full entries.
- **Tool description** steers the model to use it for broad/collection
  questions and to prefer `lookup_plant` for specific named plants, so the two
  tools don't compete.
- Registered in `TOOL_DEFINITIONS` (empty `parameters`) and routed in
  `dispatch_tool`.

### Implementation Notes

```
"What plants do you know about?" → get_plant_list({}) → agent lists all 15.
"What's a good beginner plant?"  → get_plant_list({}) → agent recommends the
   "easy" ones (Pothos, Snake Plant, ZZ Plant...).
Note: with empty-parameter tools, llama-3.3 on Groq more often emits the
malformed tool syntax that trips 'tool_use_failed' — the retry wrapper in
agent.py covers it.
```
