# Spec: `run_agent()`

**File:** `agent.py`
**Status:** Partially pre-filled — complete the two blank fields before implementing

---

## Purpose

Orchestrate a single conversational turn for the Plant Advisor agent. Given a user message and the conversation history, call the LLM with available tools, execute any tool calls the LLM requests, and return the final text response.

This is the core of what makes Plant Advisor an *agent* rather than a simple chatbot: the ability to decide which tools to call, use their results to inform its response, and loop until it has everything it needs.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_message` | `str` | The user's current message |
| `history` | `list` | Gradio conversation history — list of `[user_msg, assistant_msg]` pairs |

**Output:** `str`

The agent's final text response for this turn. Should never be empty — if something goes wrong, return a user-readable fallback message.

---

## Design Decisions

*Read `specs/system-design.md` (especially the "How the Groq Tool Calling API Works" section) before reviewing these. Complete the two blank fields before writing any code.*

---

### Messages list structure

The messages list must start with the system prompt, then replay the conversation
history, then add the new user message. Gradio history is a list of `[user, assistant]`
pairs — convert each pair to two API-format dicts:

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for user_msg, assistant_msg in history:
    messages.append({"role": "user", "content": user_msg})
    if assistant_msg:
        messages.append({"role": "assistant", "content": assistant_msg})

messages.append({"role": "user", "content": user_message})
```

---

### Initial LLM call

Pass the model, the messages list, the tool definitions, and `tool_choice="auto"`
so the LLM can decide whether to call a tool or respond directly:

```python
response = client.chat.completions.create(
    model=LLM_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

---

### Detecting tool calls in the response

The response object has a `choices` list. Index 0 gives the assistant message.
Check its `tool_calls` attribute — if it's truthy, the LLM wants to call tools:

```python
assistant_message = response.choices[0].message

if not assistant_message.tool_calls:
    # No tool calls — LLM has a final answer
    ...
```

---

### Appending the assistant message

When there are tool calls, append the full assistant message object to `messages`
**before** appending any tool results. The API requires this ordering — a tool
result message must immediately follow the assistant message that requested it:

```python
messages.append(assistant_message)  # must come first
```

---

### Executing and appending tool results

For each tool call, extract the name and arguments, call `dispatch_tool()`, and
append the result as a `"tool"` role message. The `tool_call_id` links this result
back to the specific tool call that requested it:

```python
for tool_call in assistant_message.tool_calls:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    tool_result = dispatch_tool(tool_name, tool_args)

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": tool_result,
    })
```

---

### Loop termination conditions

*The loop should stop when: (a) the LLM returns a response with no tool calls, OR (b) the MAX_TOOL_ROUNDS limit is reached. Describe how you will detect each condition and what you will return in each case.*

```
The loop is a `for _ in range(MAX_TOOL_ROUNDS)`.

(a) No tool calls: after each API call, check `assistant_message.tool_calls`.
    If falsy, the LLM has produced a final answer — return
    `assistant_message.content` immediately, exiting the loop.

(b) Limit reached: if the for-loop runs all MAX_TOOL_ROUNDS iterations without
    hitting (a), fall through and make ONE more call with NO tools attached.
    This forces the model to answer from what it has already gathered instead
    of requesting yet another tool. Return that content, or a friendly
    fallback string if it's somehow empty (the contract is: never return "").

Robustness: the whole loop is wrapped in try/except so a transient API error
returns a readable apology rather than crashing the turn. The completion call
is also retried on Groq's intermittent 'tool_use_failed' parse error.
```

---

### Extracting the final text response

*Once the loop exits because there are no more tool calls, how do you extract the text content from the response object? What field holds the string you should return?*

```
response.choices[0].message.content

choices[0] is the first (and only, since n defaults to 1) completion. Its
.message is the assistant message object; .content is the generated text. On a
final answer this is a non-empty string and tool_calls is None — the inverse
of a tool-requesting turn, where content is None and tool_calls is populated.
```

---

## Implementation Notes

*Fill this in after implementing and testing.*

**Trace of a working agent turn (what tools were called and in what order):**

```
Query: "How should I water my monstera this time of year?"
Round 1 tool calls: lookup_plant({'plant_name': 'monstera'})
                    get_seasonal_conditions({})   ← both requested in one round
Round 2: no tool calls — LLM returns the final answer
Final response: cites Monstera's "every 1–2 weeks" watering and adjusts it for
the detected summer season ("water more frequently"). Both tools, connected.
```

**What happens when you ask about a plant that isn't in the database?**

```
"How do I care for my bird of paradise?" → lookup_plant returns found: False
with the guardrail message. The agent acknowledges the plant isn't in the
database and offers general tropical-plant guidance WITHOUT inventing specific
watering numbers — graceful degradation, driven by the not-found message plus
the matching system-prompt rule.
```

**One thing about the tool call API that surprised you:**

```
The model can request MULTIPLE tools in a single assistant message (monstera
fired lookup_plant and get_seasonal_conditions together), so the inner loop
must iterate over assistant_message.tool_calls and append a tool result for
each — appending one is not enough.

Also surprising: llama-3.3 on Groq intermittently emits malformed tool syntax
(e.g. `<function=lookup_plant{...}</function>`) that the API rejects as
'tool_use_failed'. It's non-deterministic, so a plain retry of the same
request fixes it — worth knowing this is a real-world rough edge of tool use.
```
