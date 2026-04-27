"""
FastAPI application — serves the MCP bridge API and (in production) the React SPA.
"""
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import agent_loop
import config
from models import ChatRequest, ToolCallRequest
from mcp_bridge import bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# The .NET runtime inside the MCP container occasionally writes non-JSON
# diagnostics to stdout (e.g. "Failed to detect X display"). The MCP SDK
# tries to parse every stdout line as JSON-RPC and logs a spurious ERROR.
# Suppress it — the bridge continues working correctly.
class _SuppressMcpParseNoise(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Failed to parse JSONRPC message from server" not in record.getMessage()

logging.getLogger("mcp.client.stdio").addFilter(_SuppressMcpParseNoise())


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting MCP bridge (az_login_mode=%s)…", config.AZ_LOGIN_MODE)
    await bridge.start()
    log.info("MCP bridge ready.")
    yield
    log.info("Shutting down MCP bridge…")
    await bridge.stop()


app = FastAPI(title="Azure MCP Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# GET /api/tools  — tool catalogue
# ---------------------------------------------------------------------------

@app.get("/api/tools")
async def get_tools():
    tools = await bridge.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
        }
        for t in tools
    ]


# ---------------------------------------------------------------------------
# POST /api/tool/call  — direct (no Claude) tool invocation
# ---------------------------------------------------------------------------

@app.post("/api/tool/call")
async def call_tool(req: ToolCallRequest):
    try:
        result = await bridge.call_tool(req.name, req.arguments)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    contents = [
        c.text for c in result.content if hasattr(c, "text")
    ]
    return {
        "isError": bool(result.isError),
        "content": "\n".join(contents),
    }


# ---------------------------------------------------------------------------
# POST /api/chat  — agentic chat, streamed as SSE
# ---------------------------------------------------------------------------

def _sse(event: dict) -> str:
    """Encode a dict as a single SSE data line."""
    return f"data: {json.dumps(event)}\n\n"


async def _stream_chat(req: ChatRequest) -> AsyncGenerator[str, None]:
    history = [m.model_dump() for m in req.messages]
    try:
        async for event in agent_loop.run(bridge, history, req.user_message):
            yield _sse(event)
    except Exception as exc:
        log.exception("Unhandled error in agent loop")
        yield _sse({"type": "error", "message": str(exc)})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not set. Add it to .env.",
        )
    return StreamingResponse(
        _stream_chat(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )


# ---------------------------------------------------------------------------
# Static files — mount React build for production
# Kept last so API routes take precedence.
# ---------------------------------------------------------------------------

try:
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    _dist = Path(__file__).parent.parent / "frontend" / "dist"
    if _dist.exists():
        app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
        log.info("Serving frontend from %s", _dist)
    else:
        log.info("No frontend/dist found — run `npm run build` in frontend/ for production.")
except Exception as exc:
    log.warning("Could not mount static files: %s", exc)
