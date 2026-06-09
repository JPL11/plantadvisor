import json
from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL, MAX_TOOL_ROUNDS
from tools import lookup_plant, get_seasonal_conditions, get_plant_list

_client = Groq(api_key=GROQ_API_KEY)

# ──────────────────────────────────────────────
# Tool definitions
#
# These are the schemas that tell the LLM what tools are available and how to
# call them. The LLM reads these descriptions and decides when (and how) to use
# each tool. They're already complete — your job is to implement the tool
# functions in tools.py and the agent loop below.
# ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_plant",
            "description": (
                "Look up care information for a specific houseplant by name. "
                "Returns detailed watering, light, humidity, and temperature requirements. "
                "Use this whenever the user asks about a specific plant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plant_name": {
                        "type": "string",
                        "description": "The plant name to look up. Can be a common name, scientific name, or nickname (e.g., 'pothos', 'devil's ivy', 'Monstera deliciosa').",
                    }
                },
                "required": ["plant_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_conditions",
            "description": (
                "Get seasonal care adjustments for houseplants. "
                "Returns guidance on watering, fertilizing, light, and pests for the current or specified season. "
                "Use this when a user asks a season-specific question, or to complement plant care advice with seasonal context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "season": {
                        "type": "string",
                        "description": "The season to get care conditions for. If omitted, the current season is detected automatically.",
                        "enum": ["spring", "summer", "fall", "winter"],
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plant_list",
            "description": (
                "List every plant in the database with its name and difficulty level. "
                "Use this for broad questions about the collection as a whole — e.g. "
                "'what plants do you know about?' or 'what's a good beginner plant?' — "
                "rather than questions about one specific named plant."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ──────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a knowledgeable and friendly plant care advisor. "
    "Help users care for their houseplants by looking up specific plant information "
    "and current seasonal conditions using your available tools.\n\n"
    "Always use your tools to look up plant-specific information before answering — "
    "don't rely on your general knowledge alone.\n\n"
    "Answer every part of a multi-part question. If the user asks what a plant "
    "is AND how to care for it, open with one or two sentences identifying the "
    "plant (type, e.g. succulent/fern/tropical, and a defining trait drawn from "
    "its care data), THEN give the care guidance.\n\n"
    "Seasonal advice: each plant's care data has its own 'seasonal_notes' — use "
    "those for season adjustments to a SPECIFIC plant, because they're tailored "
    "to it. The get_seasonal_conditions tool gives GENERIC, all-plant guidance; "
    "only call it for general seasonal questions or plants not in the database, "
    "and never let its generic advice override or contradict a plant's own data "
    "(e.g. do not tell the user to fertilize a plant whose data says it rarely "
    "needs feeding). When the two disagree, the plant's own data wins.\n\n"
    "When lookup_plant returns found: False, do NOT invent specific care instructions "
    "or numbers for that plant. Clearly acknowledge it isn't in your database, then "
    "offer general guidance for that type of plant based on what the user describes "
    "and suggest where they might confirm the specifics.\n\n"
    "Keep your advice practical and specific. Cite the source of your information "
    "when you have it (e.g., 'According to the care data for your monstera...')."
)

# ──────────────────────────────────────────────
# Tool dispatch
#
# This is already complete. It routes tool calls from the LLM to the actual
# Python functions in tools.py, and returns results as JSON strings (which is
# what the Groq API expects for tool results).
# ──────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_args: dict) -> str:
    """Route a tool call to the correct function and return the result as a JSON string."""
    print(f"  → Tool call: {tool_name}({tool_args})")
    if tool_name == "lookup_plant":
        result = lookup_plant(tool_args["plant_name"])
    elif tool_name == "get_seasonal_conditions":
        result = get_seasonal_conditions(tool_args.get("season"))
    elif tool_name == "get_plant_list":
        result = get_plant_list()
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    print(f"  ← Result: {json.dumps(result)[:120]}{'...' if len(json.dumps(result)) > 120 else ''}")
    return json.dumps(result)


# ──────────────────────────────────────────────
# Agent loop
# ──────────────────────────────────────────────

def _create_with_retry(retries: int = 2, **kwargs):
    """
    Wrapper around the Groq completions call.

    llama-3.3 on Groq intermittently emits malformed tool-call syntax that the
    API rejects with code 'tool_use_failed'. The bad output is non-deterministic,
    so simply re-issuing the identical request usually succeeds. We retry only
    that specific error and let everything else propagate.
    """
    for attempt in range(retries + 1):
        try:
            return _client.chat.completions.create(model=LLM_MODEL, **kwargs)
        except Exception as exc:
            if "tool_use_failed" in str(exc) and attempt < retries:
                print(f"  ↻ Retrying after tool_use_failed (attempt {attempt + 1})")
                continue
            raise


def run_agent(user_message: str, history: list) -> str:
    """
    Run the plant care agent for one user turn and return its response.

    TODO — Milestone 2:

    The agent loop follows a specific pattern that you'll implement here. Read
    specs/agent-loop-spec.md carefully before writing any code — understand the
    full loop before implementing any part of it.

    The loop works like this:
      1. Build a messages list: system prompt + conversation history + new user message
      2. Call the LLM with messages and TOOL_DEFINITIONS
      3. If the response contains tool_calls:
           a. Append the assistant message (with tool_calls) to messages
           b. For each tool call: execute via dispatch_tool(), append the result
           c. Call the LLM again with the updated messages
           d. Repeat until no more tool_calls (or MAX_TOOL_ROUNDS is reached)
      4. Return the final text response

    Key details to get right:
      - The assistant message must be appended BEFORE tool results
      - Tool result messages use role="tool" with a tool_call_id field
      - Append the assistant's message object directly (not just its content)
      - The history format from Gradio: list of [user_message, assistant_message] pairs

    Before writing code, complete specs/agent-loop-spec.md.
    """
    # 1. Build the messages list: system prompt + replayed history + new message.
    #
    # Gradio's ChatInterface(type="messages") passes history as a list of
    # {"role", "content", ...} dicts (it may also carry a "metadata" key). We
    # also tolerate the legacy [user, assistant] pair format for safety.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        if isinstance(turn, dict):
            if turn.get("content"):
                messages.append({
                    "role": turn["role"],
                    "content": turn["content"],
                })
        else:  # legacy [user_msg, assistant_msg] pair
            user_msg, assistant_msg = turn
            messages.append({"role": "user", "content": user_msg})
            if assistant_msg:
                messages.append({"role": "assistant", "content": assistant_msg})
    messages.append({"role": "user", "content": user_message})

    # 2. Tool-calling loop, capped at MAX_TOOL_ROUNDS to prevent runaway loops.
    #    Wrapped so a transient API error never crashes the turn — the contract
    #    is that run_agent always returns a user-readable string.
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = _create_with_retry(
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message

            # Exit condition (a): no tool calls means the LLM has its final answer.
            if not assistant_message.tool_calls:
                return assistant_message.content

            # Assistant message MUST be appended before its tool results so each
            # tool_call_id can be matched to the request that produced it.
            messages.append(assistant_message)
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                # Some models emit "null" or "" for no-argument tool calls —
                # coerce to an empty dict so dispatch_tool gets a mapping.
                tool_args = json.loads(tool_call.function.arguments or "{}") or {}
                tool_result = dispatch_tool(tool_name, tool_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

        # Exit condition (b): hit MAX_TOOL_ROUNDS. Make one final call WITHOUT
        # tools so the LLM answers from what it gathered instead of looping.
        final = _create_with_retry(messages=messages)
        return final.choices[0].message.content or (
            "I gathered some information but couldn't quite put together a "
            "complete answer. Could you try rephrasing your question?"
        )
    except Exception as exc:
        print(f"  ⚠️  Agent error: {exc}")
        return (
            "Sorry — I ran into a problem while looking that up. Please try "
            "asking again, ideally about one plant at a time."
        )
