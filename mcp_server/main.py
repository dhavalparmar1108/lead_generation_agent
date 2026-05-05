from __future__ import annotations

import re
import logging
import aiosqlite
import json
import uuid
from pathlib import Path
from typing import Optional

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import types
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
import uvicorn
from mcp_server.agent import process_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = Path("salesbot.db")

# ─────────────────────────────────────────────────────────────────────────────
# Import agent from notebook logic
# ─────────────────────────────────────────────────────────────────────────────

# These should be extracted from your notebook into a separate module
# For now, we'll define the minimal structures here
from typing import TypedDict
from pydantic import BaseModel, field_validator
import re as regex_module
from typing_extensions import TypedDict

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
        if not regex_module.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError(f"Invalid email: {v}")
        return v.lower().strip()

    @field_validator("mobile", mode="before")
    @classmethod
    def validate_mobile(cls, v):
        if v is None:
            return v
        digits = regex_module.sub(r"[\s\-\+\(\)]", "", str(v))
        if not regex_module.match(r"^\d{7,15}$", digits):
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
# Database Functions
# ─────────────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Initialize database schema."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Conversations table (stores full state as JSON)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                lead_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Leads table (denormalized for querying)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                mobile TEXT NOT NULL,
                requirement TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)
        
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def get_conversation_state(conv_id: str) -> Optional[AgentState]:
    """Load conversation state from database."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT state FROM conversations WHERE id = ?",
            (conv_id,)
        )
        row = await cursor.fetchone()
    
    if row:
        return json.loads(row[0])
    return None


async def save_conversation_state(conv_id: str, state: AgentState) -> None:
    """Save conversation state to database (thread-safe via SQLite)."""
    state_json = json.dumps(state, default=str)  # Handle non-JSON-serializable objects
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO conversations (id, state, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                state = excluded.state,
                updated_at = CURRENT_TIMESTAMP
            """,
            (conv_id, state_json)
        )
        await db.commit()


async def save_lead(lead: LeadData, conv_id: str) -> int:
    """Save lead to database."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO leads (conversation_id, name, email, mobile, requirement)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conv_id, lead.name, lead.email, lead.mobile, lead.requirement),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_leads() -> list[dict]:
    """Get all captured leads."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM leads ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# MCP Server & Tools
# ─────────────────────────────────────────────────────────────────────────────

app = Server("salesbot-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_product_info",
            description="Search the product catalog for products matching a user query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "User product query or keywords",
                    }
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="capture_lead",
            description="Save a captured lead to the database once all details are collected.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name":        {"type": "string", "description": "Full name of the lead"},
                    "email":       {"type": "string", "description": "Email address"},
                    "mobile":      {"type": "string", "description": "Mobile number"},
                    "requirement": {"type": "string", "description": "What the lead is looking for"},
                },
                "required": ["name", "email", "mobile", "requirement"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_product_info":
        return await _get_product_info(arguments["query"])
    if name == "capture_lead":
        return await _capture_lead(arguments)
    raise ValueError(f"Unknown tool: {name}")



async def _get_product_info(query: str) -> list[types.TextContent]:
    try:
        import time

        start = time.perf_counter()

        from mcp_server.vector_store.store import hybrid_search

        end = time.perf_counter()
        
        logger.info(f"Import time : {end - start:.4f} seconds")
        
        results = hybrid_search(query, top_k=3)
        if not results:
            return [types.TextContent(type="text", text="No matching products found.")]
        text = "\n\n".join(
            f"Product: {r['name']}\n{r['description']}" for r in results
        )
        return [types.TextContent(type="text", text=text)]
    except Exception as e:
        logger.exception("get_product_info error")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


async def _capture_lead(args: dict) -> list[types.TextContent]:
    email = args["email"].lower().strip()
    if not regex_module.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email):
        return [types.TextContent(type="text", text="Error: Invalid email format.")]

    async with aiosqlite.connect(DB_PATH) as db:
        # Check if email already exists
        cur = await db.execute("SELECT 1 FROM leads WHERE email = ?", (email,))
        if await cur.fetchone():
            return [types.TextContent(
                type="text",
                text="Lead already exists for this email."
            )]

    # Save to database
    await save_lead(
        LeadData(
            name=args["name"],
            email=email,
            mobile=args["mobile"],
            requirement=args["requirement"]
        ),
        conv_id="unknown"  # Will be set by chat endpoint
    )

    return [types.TextContent(
        type="text",
        text=f"Lead captured successfully for {args['name']}."
    )]


# ─────────────────────────────────────────────────────────────────────────────
# Chat HTTP Endpoint (Bridges HTTP and MCP)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_endpoint(request: Request) -> JSONResponse:
    """
    Main chat endpoint.
    
    POST /chat
    {
        "message": "I need a CRM",
        "conversation_id": "optional"
    }
    
    Response:
    {
        "reply": "Here are products...",
        "conversation_id": "conv_abc123",
        "lead": {
            "captured": false,
            "data": null,
            "missing_fields": ["name", "email", "mobile", "requirement"]
        }
    }
    """
    try:
        data = await request.json()
        message = data.get("message", "").strip()
        conv_id = data.get("conversation_id") or str(uuid.uuid4())
        
        if not message:
            return JSONResponse({"error": "message is required"}, status_code=400)
        
        # 1. Load existing state or create new
        state_dict = await get_conversation_state(conv_id)
        if state_dict is None:
            state = {
                "messages": [],
                "user_input": message,
                "intent": "",
                "product_query": "",
                "product_results": [],
                "lead": LeadData() 
            }
        else:
            # Ensure lead is a LeadData object for validation logic
            state_dict["lead"] = LeadData(**state_dict["lead"])
            state = state_dict
            state["user_input"] = message

        # 2. CALL THE ACTUAL AGENT (This replaces the placeholder)
        final_state = await process_message(state)
        
        # 3. Get the last message from the agent
        reply = final_state["messages"][-1]["content"]
        
        # 4. Save state (convert LeadData back to dict for JSON)
        save_state = final_state.copy()
        save_state["lead"] = final_state["lead"].model_dump()
        await save_conversation_state(conv_id, save_state)
        
        # 5. Check lead completion
        lead_complete = final_state["lead"].is_complete()
        
        return JSONResponse({
            "reply": reply,
            "conversation_id": conv_id,
            "lead": {
                "captured": lead_complete,
                "data": save_state["lead"] if lead_complete else None,
                "missing_fields": final_state["lead"].missing_fields()
            }
        })
    
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON"},
            status_code=400
        )
    except Exception as e:
        logger.exception("Chat endpoint error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


# ─────────────────────────────────────────────────────────────────────────────
# Additional Endpoints
# ─────────────────────────────────────────────────────────────────────────────

async def get_leads_endpoint(request: Request) -> JSONResponse:
    """GET /leads - Get all captured leads."""
    try:
        leads = await get_all_leads()
        return JSONResponse({"leads": leads, "count": len(leads)})
    except Exception as e:
        logger.exception("Error fetching leads")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_conversation_endpoint(request: Request) -> JSONResponse:
    """GET /conversations/{conv_id} - Get conversation history."""
    try:
        conv_id = request.path_params["conv_id"]
        state = await get_conversation_state(conv_id)
        
        if not state:
            return JSONResponse({"error": "Conversation not found"}, status_code=404)
        
        return JSONResponse({
            "conversation_id": conv_id,
            "messages": state.get("messages", []),
            "lead": state.get("lead", {}),
            "created_at": None  # Would need to fetch from DB
        })
    except Exception as e:
        logger.exception("Error fetching conversation")
        return JSONResponse({"error": str(e)}, status_code=500)


async def health_check(request: Request) -> JSONResponse:
    """GET /health - Health check."""
    return JSONResponse({"status": "ok", "service": "SalesBot"})


# ─────────────────────────────────────────────────────────────────────────────
# SSE Transport (for MCP)
# ─────────────────────────────────────────────────────────────────────────────

sse_transport = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    """Handle SSE connections for MCP."""
    async with sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send,
    ) as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )
    return Response()


async def handle_messages_asgi(scope, receive, send):
    """Handle POST messages for MCP."""
    await sse_transport.handle_post_message(scope, receive, send)


# ─────────────────────────────────────────────────────────────────────────────
# Starlette App Setup
# ─────────────────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    await init_db()
    logger.info("SalesBot server ready!")
    yield
    # cleanup if needed


starlette_app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health",               endpoint=health_check,           methods=["GET"]),
        Route("/chat",                 endpoint=chat_endpoint,          methods=["POST"]),
        Route("/leads",                endpoint=get_leads_endpoint,     methods=["GET"]),
        Route("/conversations/{conv_id}", endpoint=get_conversation_endpoint, methods=["GET"]),
        Route("/sse",                  endpoint=handle_sse,             methods=["GET"]),
        Mount("/messages",             app=handle_messages_asgi),
    ]
)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


# async def startup():
#     """Initialize on startup."""
#     await init_db()
#     logger.info("SalesBot server ready!")

if __name__ == "__main__":
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=8001,
        log_level="info",
        lifespan="auto"  # Will call startup
    )
