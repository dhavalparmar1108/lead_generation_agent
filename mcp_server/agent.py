"""
SalesBot Agent Module
Extracted from Jupyter notebook - uses LangGraph for multi-turn conversations
No while loop - designed for async request/response pattern
"""

import os
import re
import json
import logging
from typing import Optional
from typing_extensions import TypedDict
import httpx
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, field_validator

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────

class LeadData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    requirement: Optional[str] = None

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.name:
            missing.append("name")
        if not self.email:
            missing.append("email")
        if not self.mobile:
            missing.append("mobile number")
        if not self.requirement:
            missing.append("requirement")
        return missing

    def is_complete(self) -> bool:
        return all([self.name, self.email, self.mobile, self.requirement])

    def filled_summary(self) -> str:
        parts = []
        if self.name:
            parts.append(f"name: {self.name}")
        if self.email:
            parts.append(f"email: {self.email}")
        if self.mobile:
            parts.append(f"mobile: {self.mobile}")
        if self.requirement:
            parts.append(f"requirement: {self.requirement}")
        return ", ".join(parts) if parts else "none"

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError(f"Invalid email: {v}")
        return v.lower().strip()

    @field_validator("mobile", mode="before")
    @classmethod
    def validate_mobile(cls, v):
        if v is None:
            return v
        digits = re.sub(r"[\s\-\+\(\)]", "", str(v))
        if not re.match(r"^\d{10}$", digits):
            raise ValueError(f"Invalid mobile: {v}")
        return digits

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name too short")
        return v


class AgentState(TypedDict):
    messages: list[dict]
    user_input: str
    intent: str
    product_query: str
    product_results: list[dict]
    lead: LeadData


# ─────────────────────────────────────────────────────────────────────────────
# LLM & Utilities
# ─────────────────────────────────────────────────────────────────────────────

async def call_llm(
    messages: list[dict],
    system: str = "",
    max_tokens: int = 500
) -> str:
    """Call OpenRouter API with gpt-4o-mini."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set")
    
    payload_messages = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": payload_messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
    
    return resp.json()["choices"][0]["message"]["content"].strip()


def parse_json(text: str) -> dict:
    """Parse JSON from LLM response."""
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool Calling
# ─────────────────────────────────────────────────────────────────────────────

from mcp import ClientSession
from mcp.client.sse import sse_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8001/sse")


# Replace this in agent.py
async def call_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Bypasses the network to avoid deadlock when co-hosted."""
    from mcp_server.main import _get_product_info, _capture_lead
    
    if tool_name == "get_product_info":
        # Call the logic directly
        result_contents = await _get_product_info(arguments["query"])
        return result_contents[0].text
        
    if tool_name == "capture_lead":
        # Call the logic directly
        result_contents = await _capture_lead(arguments)
        return result_contents[0].text
        
    raise ValueError(f"Unknown tool: {tool_name}")

# async def call_mcp_tool(tool_name: str, arguments: dict) -> str:
#     """Call MCP tool via SSE connection."""
#     async with sse_client(url=MCP_URL) as (read, write):
#         async with ClientSession(read, write) as session:
#             await session.initialize()
#             result = await session.call_tool(tool_name, arguments)
#             return result.content[0].text


# ─────────────────────────────────────────────────────────────────────────────
# Graph Nodes
# ─────────────────────────────────────────────────────────────────────────────

def user_input_node(state: AgentState) -> AgentState:
    """Append user message to history."""
    state["messages"].append({"role": "user", "content": state["user_input"]})
    return state


CLASSIFY_SYSTEM = """
You are the brain of a sales assistant chatbot.

Given the conversation history and the latest user message, return a JSON with:
{
  "intent": "product_query" | "follow_up" | "closing" | "irrelevant",
  "product_query_text": "<refined search query if product_query, else null>",
  "name": "<extracted name or null>",
  "email": "<extracted email or null>",
  "mobile": "<extracted mobile number or null>",
  "requirement": "<what user is looking for or null>"
}

Intent definitions:
- product_query: user asking about a product, feature, pricing, or comparison
- follow_up: user has a follow-up question about something already discussed regarding products
- closing: user signals end (ok, thanks, sounds good, got it, perfect, that's all, etc.) or shows interest in next steps (purchase, demo, trial, contact) or to reach out to sales team
- irrelevant: completely off-topic (sports, weather, etc.)

Return ONLY the JSON object. No explanation.
"""


async def classify_node(state: AgentState) -> AgentState:
    """Classify intent and extract lead data."""
    raw = await call_llm(
        messages=state["messages"],
        system=CLASSIFY_SYSTEM,
        max_tokens=300,
    )
    
    parsed = parse_json(raw)
    
    state["intent"] = parsed.get("intent", "follow_up")
    state["product_query"] = parsed.get("product_query_text") or state["user_input"]
    
    # Merge extracted lead fields
    lead = state["lead"]
    
    for field in ("name", "email", "mobile", "requirement"):
        value = parsed.get(field)
        if value:
            try:
                updated = lead.model_copy(update={field: value})
                setattr(lead, field, getattr(updated, field))
            except Exception as e:
                logger.warning(f"Lead validation {field} skipped: {e}")
    
    state["lead"] = lead
    logger.info(f"Intent: {state['intent']}, Lead: {lead.filled_summary()}")
    
    logger.debug(f"state lead : {state['lead']}")
    return state


PRODUCT_SYSTEM = """
You are a helpful sales assistant. Answer the user's product query using ONLY
the product results provided below. Do not invent any products or features.
If nothing relevant is found, say so politely.

{product_context}
"""


async def product_node(state: AgentState) -> AgentState:
    """Search products and generate response."""
    product_text = await call_mcp_tool(
        "get_product_info",
        {"query": state["product_query"]}
    )

    reply = await call_llm(
        messages=state["messages"],
        system=f"You are a helpful sales assistant. Answer using ONLY these products:\n\n{product_text}",
    )
    state["messages"].append({"role": "assistant", "content": reply})
    return state


FOLLOWUP_SYSTEM = """
You are a helpful and concise sales assistant. Continue the conversation naturally.
Answer follow-up questions based on what has already been discussed and product information fetched earlier.
Do not refer to any products that have not been mentioned in the conversation or the provided product information.
If the query is irrelevant to sales or products, politely redirect.
"""


async def followup_node(state: AgentState) -> AgentState:
    """Handle follow-up questions."""
    reply = await call_llm(
        messages=state["messages"],
        system=FOLLOWUP_SYSTEM,
    )
    state["messages"].append({"role": "assistant", "content": reply})
    return state


IRRELEVANT_SYSTEM = """
If the query is irrelevant to sales or products, reply with polite messages saying you can't help with that topic.
NOTE: Greetings are not considered irrelevant. If the user says "hi" or "hello", respond with a greeting and then ask how you can assist with sales or products.
"""


async def irrelevant_node(state: AgentState) -> AgentState:
    """Handle off-topic queries."""
    reply = await call_llm(
        messages=state["messages"],
        system=IRRELEVANT_SYSTEM,
    )
    state["messages"].append({"role": "assistant", "content": reply})
    return state


LEAD_SYSTEM = """
You are a sales assistant capturing a lead information.

Already captured lead info: {filled}
Still missing: {missing}

Guidelines:
- Ask ONLY for the missing fields in a natural, friendly way.
- Do NOT ask for any information that is already captured.
- Keep the message conversational and concise.

Special case:
- If multiple products have been discussed and the user’s interest is unclear, first ask a clarification question about which product they are interested in before asking for missing lead details.

Completion:
- If all required fields are captured, do not ask any more questions.
- Thank the user politely and inform them that a team member will contact them soon.

Tone:
- Friendly, helpful, and non-pushy.
"""


async def lead_node(state: AgentState) -> AgentState:
    """Handle lead capture."""
    lead = state["lead"]
    missing = lead.missing_fields()

    if lead.is_complete():
        # All fields collected — persist via MCP tool
        result = await call_mcp_tool("capture_lead", {
            "name": lead.name,
            "email": lead.email,
            "mobile": lead.mobile,
            "requirement": lead.requirement,
        })
        reply = await call_llm(
            messages=state["messages"],
            system=f"Lead capture result: {result}. Thank the user warmly and say a team member will reach out.",
        )
    else:
        # Still collecting — ask only for missing fields
        reply = await call_llm(
            messages=state["messages"],
            system=f"Already captured: {lead.filled_summary()}. Politely ask only for: {', '.join(missing)}.",
        )

    state["messages"].append({"role": "assistant", "content": reply})
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Router Function
# ─────────────────────────────────────────────────────────────────────────────

def route(state: AgentState) -> str:
    """Route based on detected intent."""
    intent = state["intent"]
    if intent == "product_query":
        return "product"
    if intent == "closing":
        return "lead"
    if intent == "follow_up":
        return "followup"
    return "irrelevant"


# ─────────────────────────────────────────────────────────────────────────────
# Graph Compilation
# ─────────────────────────────────────────────────────────────────────────────

def build_agent():
    """Build and compile the LangGraph agent."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("user_input", user_input_node)
    graph.add_node("classify", classify_node)
    graph.add_node("product", product_node)
    graph.add_node("followup", followup_node)
    graph.add_node("lead", lead_node)
    graph.add_node("irrelevant", irrelevant_node)

    # Set entry point
    graph.set_entry_point("user_input")
    graph.add_edge("user_input", "classify")

    # Conditional routing based on intent
    graph.add_conditional_edges(
        "classify",
        route,
        {
            "product": "product",
            "followup": "followup",
            "lead": "lead",
            "irrelevant": "irrelevant",
        },
    )

    # Terminal edges
    graph.add_edge("product", END)
    graph.add_edge("followup", END)
    graph.add_edge("lead", END)
    graph.add_edge("irrelevant", END)

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Agent Instance
# ─────────────────────────────────────────────────────────────────────────────

agent = None


def get_agent():
    """Get or build the global agent instance."""
    global agent
    if agent is None:
        logger.info("Building SalesBot agent...")
        agent = build_agent()
        logger.info("Agent ready!")
    return agent


async def process_message(state: AgentState) -> AgentState:
    """Process a user message through the agent."""
    agent_instance = get_agent()
    return await agent_instance.ainvoke(state)
