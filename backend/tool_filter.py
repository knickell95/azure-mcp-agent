"""
tool_filter — score and select the most relevant MCP tools for a given query.

Strategy:
  1. Tokenise the query (user message + recent history) into a word set.
  2. Expand with Azure-domain synonyms so "vm" matches the "compute" tool, etc.
  3. Score each tool: name-match outweighs description-match.
  4. Always include a small baseline set of tools (subscription, resource groups).
  5. Return the top MAX_TOOLS by score.

No external dependencies — pure Python string ops.
"""

import logging
import re
from typing import Any

from mcp.types import Tool

log = logging.getLogger(__name__)

# Tools that are always included regardless of score — they provide context
# that Claude almost always needs (subscription scope, resource groups).
BASELINE_TOOLS = {
    "subscription_list",
    "group_list",
    "group_resource_list",
}

MAX_TOOLS = 20

# Synonym map: query words → additional score tokens.
# Keys are lowercased words the user might write; values are tool name fragments
# or description words that should boost the score for related tools.
_SYNONYMS: dict[str, list[str]] = {
    # Compute
    "vm":               ["compute"],
    "vms":              ["compute"],
    "virtual machine":  ["compute"],
    "virtual machines": ["compute"],
    "scale set":        ["compute"],
    "vmss":             ["compute"],
    # Containers
    "kubernetes":       ["aks"],
    "k8s":              ["aks"],
    "container app":    ["containerapps"],
    "container apps":   ["containerapps"],
    "docker":           ["containerapps", "acr"],
    "registry":         ["acr"],
    # Serverless
    "function":         ["functionapp", "functions"],
    "functions":        ["functionapp", "functions"],
    "serverless":       ["functionapp", "functions"],
    # Storage
    "blob":             ["storage"],
    "blobs":            ["storage"],
    "file share":       ["fileshares", "storage"],
    "queue":            ["storage"],
    "table":            ["storage"],
    # Secrets / identity
    "secret":           ["keyvault"],
    "secrets":          ["keyvault"],
    "certificate":      ["keyvault"],
    "certificates":     ["keyvault"],
    "key vault":        ["keyvault"],
    "keyvault":         ["keyvault"],
    # Databases
    "database":         ["sql", "cosmos", "mysql", "postgres"],
    "sql":              ["sql"],
    "cosmos":           ["cosmos"],
    "mongodb":          ["cosmos"],
    "mysql":            ["mysql"],
    "postgres":         ["postgres"],
    "postgresql":       ["postgres"],
    # Messaging
    "event hub":        ["eventhubs"],
    "event hubs":       ["eventhubs"],
    "service bus":      ["servicebus"],
    "event grid":       ["eventgrid"],
    # Monitoring / observability
    "log":              ["monitor"],
    "logs":             ["monitor"],
    "metrics":          ["monitor"],
    "alert":            ["monitor"],
    "alerts":           ["monitor"],
    "insights":         ["applicationinsights"],
    "app insights":     ["applicationinsights"],
    "diagnostic":       ["monitor"],
    # Policy / compliance
    "policy":           ["policy"],
    "compliance":       ["policy"],
    "rbac":             ["role"],
    "role":             ["role"],
    "permission":       ["role"],
    # Networking / DNS / domains
    "dns":              ["appservice"],
    "domain":           ["appservice"],
    # Web / app service
    "web app":          ["appservice"],
    "app service":      ["appservice"],
    "website":          ["appservice"],
    # AI / ML
    "openai":           ["foundry"],
    "ai":               ["foundry", "search", "speech"],
    "search":           ["search"],
    "speech":           ["speech"],
    # Cost
    "cost":             ["advisor"],
    "price":            ["pricing"],
    "pricing":          ["pricing"],
    "spend":            ["advisor"],
    # Recommendations
    "recommendation":   ["advisor"],
    "best practice":    ["advisor", "get_azure_bestpractices"],
    # Infrastructure
    "bicep":            ["bicepschema"],
    "terraform":        ["azureterraformbestpractices"],
    "deploy":           ["deploy"],
    "deployment":       ["deploy"],
    # Redis / cache
    "cache":            ["redis"],
    "redis":            ["redis"],
    # SignalR / real-time
    "signalr":          ["signalr"],
    "real-time":        ["signalr"],
    # Grafana
    "grafana":          ["grafana"],
    "dashboard":        ["grafana", "workbooks"],
    # Kusto / ADX
    "kusto":            ["kusto"],
    "adx":              ["kusto"],
    "data explorer":    ["kusto"],
    # Load testing
    "load test":        ["loadtesting"],
    "performance":      ["loadtesting"],
    # Health / resource health
    "health":           ["resourcehealth"],
    "outage":           ["resourcehealth"],
    # Quota / limits
    "quota":            ["quota"],
    "limit":            ["quota"],
}


def _tokenise(text: str) -> set[str]:
    """Lowercase, split on non-alphanumeric, return word set."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _expand(tokens: set[str], raw_text: str) -> set[str]:
    """
    Add synonym-derived tokens.  Check both individual tokens and
    common two-word phrases (e.g. "key vault", "app service").
    """
    extra: set[str] = set()
    lower = raw_text.lower()
    for phrase, expansions in _SYNONYMS.items():
        if phrase in lower or phrase in tokens:
            extra.update(expansions)
    return tokens | extra


def _score(tool: Tool, query_tokens: set[str]) -> int:
    name_tokens  = _tokenise(tool.name)
    desc_tokens  = _tokenise(tool.description or "")

    name_overlap = len(query_tokens & name_tokens)
    desc_overlap = len(query_tokens & desc_tokens)

    # Name matches are worth much more — the tool name is the service identifier
    return name_overlap * 10 + desc_overlap


def select(
    tools: list[Tool],
    user_message: str,
    history: list[dict[str, Any]],
    max_tools: int = MAX_TOOLS,
) -> list[Tool]:
    """
    Return at most `max_tools` tools most relevant to the current query.

    `history` is the Anthropic-format message history; the last few turns
    are used to maintain topical continuity across multi-turn conversations.
    """
    # Build query context from recent history (last 4 messages) + current message
    recent_text = user_message
    for msg in history[-4:]:
        content = msg.get("content", "")
        if isinstance(content, str):
            recent_text += " " + content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    recent_text += " " + block.get("text", "")

    tokens = _expand(_tokenise(recent_text), recent_text)

    # Separate baseline from candidates
    baseline = [t for t in tools if t.name in BASELINE_TOOLS]
    candidates = [t for t in tools if t.name not in BASELINE_TOOLS]

    # Score and sort candidates
    scored = sorted(candidates, key=lambda t: _score(t, tokens), reverse=True)

    # Fill remaining slots after baseline
    slots = max_tools - len(baseline)
    selected = baseline + scored[:slots]

    names = [t.name for t in selected]
    log.debug("Tool filter: %d/%d tools selected: %s", len(selected), len(tools), names)
    return selected


