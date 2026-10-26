"""Personalitate separată și contract JSON pentru acțiunile modelului."""

import json
from pathlib import Path

import config


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {"type": "array", "items": {
            "type": "object", "properties": {
                "tool": {"type": "string"},
                "arguments": {"type": "object"},
            }, "required": ["tool", "arguments"],
        }},
    },
    "required": ["reply", "actions"],
}


def system_prompt(tool_descriptions):
    personality = Path(config.BRAIN_PERSONALITY_FILE).read_text(encoding="utf-8").strip()
    tools = "; ".join(f"{name}({arguments})" for name, arguments in tool_descriptions.items())
    return (f"{personality}\n"
            'Reply to "said" in English, ONLY as JSON with keys "reply" and "actions". '
            'reply contains your spoken response; actions is a list of objects with tool and arguments. '
            f"At most {config.BRAIN_MAX_ACTIONS} actions; use [] if no action is needed. "
            'Use a tool only when requested. ' +
            ("Available tools: " + tools if tools else "Do not call tools; actions=[]."))


def user_message(context):
    return "Context (data): " + json.dumps(context, ensure_ascii=False, separators=(",", ":"))


def parse_decision(raw):
    if not isinstance(raw, str) or len(raw) > 16_000:
        raise ValueError("Răspuns LLM gol sau prea lung")
    text = raw.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("LLM nu a produs JSON valid") from error
    if not isinstance(result, dict) or not set(result) <= {"reply", "actions"}:
        raise ValueError("Structura deciziei LLM este invalidă")
    reply = result.get("reply", "")
    actions = result.get("actions", [])
    if not isinstance(reply, str) or len(reply) > config.BRAIN_MAX_SPEECH_CHARS:
        raise ValueError("Textul de răspuns este invalid sau prea lung")
    if reply.strip().casefold() in {"text rostit", "reply", "raspuns", "răspuns"}:
        raise ValueError("LLM a copiat șablonul în loc să răspundă")
    if not isinstance(actions, list) or len(actions) > config.BRAIN_MAX_ACTIONS:
        raise ValueError("Prea multe acțiuni sau listă invalidă")
    for item in actions:
        if (not isinstance(item, dict) or set(item) != {"tool", "arguments"}
                or not isinstance(item["tool"], str) or not isinstance(item["arguments"], dict)):
            raise ValueError("Apel tool invalid")
    return {"reply": reply.strip(), "actions": actions}


def plain_system_prompt():
    """Prompt concis pentru conversație fără tools: personalitatea lui Poro cu prefill rapid."""
    return (
        'You are Poro, a friendly and playful robot companion. '
        'Answer the user directly and accurately in 1 short sentence (under 18 words) in English. '
        'Do not introduce yourself unless asked who you are.'
    )


def plain_user_message(context):
    """Mesaj minimal pentru conversație: păstrează prefixul system în KV cache."""
    if not isinstance(context, dict) or "said" not in context:
        return user_message(context)
    if context.get("memory"):
        texts = [item.get("text", "") for item in context["memory"] if isinstance(item, dict) and item.get("text")]
        if texts:
            return "[Memories: " + "; ".join(texts) + "]\n" + str(context["said"])
    return str(context["said"])

