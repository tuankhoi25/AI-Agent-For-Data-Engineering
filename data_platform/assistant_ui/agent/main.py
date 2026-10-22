"""Bakery LangGraph agent exposed through the AG-UI protocol."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from frontend_tools import FrontendToolsMiddleware
from message_identity import StreamMessageIdentityMiddleware


def load_skill_instructions() -> str:
    skill_roots = [
        Path(os.getenv("BAKERY_SKILLS_DIR", "/app/skills")),
        Path(__file__).parent / "instructions",
    ]
    sections: list[str] = []
    for skill_root in skill_roots:
        for skill_file in sorted(skill_root.glob("*/SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            instructions = parts[2].strip() if len(parts) == 3 else text.strip()
            sections.append(f"## {skill_file.parent.name}\n{instructions}")
    return "\n\n".join(sections)


def mcp_config() -> dict[str, dict[str, Any]]:
    marmot_headers = {}
    if api_key := os.getenv("MARMOT_API_KEY"):
        marmot_headers["X-API-Key"] = api_key

    return {
        "bakery_cube": {
            "transport": "http",
            "url": os.getenv("CUBE_MCP_URL", "http://mcp_server:8001/mcp"),
        },
        "bakery_marmot": {
            "transport": "http",
            "url": os.getenv("MARMOT_MCP_URL", "http://marmot:8080/api/v1/mcp"),
            "headers": marmot_headers,
        },
        "bakery_dbhub": {
            "transport": "http",
            "url": os.getenv("DBHUB_MCP_URL", "http://dbhub:8080/mcp"),
        },
    }


async def load_mcp_tools() -> tuple[MultiServerMCPClient, list[Any]]:
    attempts = int(os.getenv("MCP_DISCOVERY_ATTEMPTS", "20"))
    delay_seconds = float(os.getenv("MCP_DISCOVERY_DELAY_SECONDS", "2"))
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        client = MultiServerMCPClient(mcp_config())
        try:
            return client, await client.get_tools()
        except Exception as exc:  # services can still be starting under Docker Compose
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)

    raise RuntimeError(f"Could not discover Bakery MCP tools after {attempts} attempts") from last_error


async def build_graph() -> tuple[Any, list[str]]:
    global MCP_CLIENT
    MCP_CLIENT, mcp_tools = await load_mcp_tools()

    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    system_prompt = f"""
You are a data analyst for a French bakery and beverage shop. Answer in the user's language.
Today is {today} in Asia/Ho_Chi_Minh.

Marmot is your authoritative business knowledge base for this bakery. Its data catalog
contains the documented business context: definitions, operating processes, business rules,
source tables and columns, relationships, data grain, units and currencies, lineage and
ownership. For business questions, consult the relevant Marmot knowledge to understand
the question and establish its meaning before planning calculations or interpreting results.
Reuse catalog knowledge already retrieved in the conversation when it is sufficient. If
information is missing or ambiguous, state the gap and make any assumptions explicit.

Cube model inspection describes the measures and dimensions available to semantic queries.
Use Cube structured queries for model-supported calculations. Use DBHub's read-only Cube
SQL connection for calculations that need CTEs, subqueries, window functions or other
SQL composition. Interpret query results using the business knowledge established in Marmot.

Use the date range in the user's question and Asia/Ho_Chi_Minh unless they specify another
timezone. Explain calculation grain and material limitations. Use verified query values or
clearly stated calculations from them; never invent data. Choose an appropriate presentation
for the user's analytical task.
""".strip()

    skills = load_skill_instructions()
    if skills:
        system_prompt += f"\n\n# Tool skills\n\n{skills}"

    model = ChatOpenAI(
        model=os.getenv("BAKERY_AGENT_MODEL", "gpt-5.6-luna"),
        use_responses_api=True,
        reasoning={"effort": os.getenv("BAKERY_AGENT_REASONING_EFFORT", "low")},
        model_kwargs={"parallel_tool_calls": True},
    )
    graph = create_agent(
        model=model,
        tools=mcp_tools,
        middleware=[StreamMessageIdentityMiddleware(), FrontendToolsMiddleware(mcp_tools)],
        system_prompt=system_prompt,
        checkpointer=InMemorySaver(),
    )
    return graph, [tool.name for tool in mcp_tools]


MCP_CLIENT: MultiServerMCPClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    graph, mcp_tool_names = await build_graph()
    app.state.mcp_tool_names = mcp_tool_names
    add_langgraph_fastapi_endpoint(
        app=app,
        agent=LangGraphAgent(
            name="bakery_analyst",
            description="Analyzes governed bakery operations data through Marmot, Cube and DBHub.",
            graph=graph,
            config={"recursion_limit": 150},
            emit_raw_events=False,
        ),
        path="/agent",
    )
    yield


app = FastAPI(
    title="Bakery AG-UI Agent",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent": "bakery_analyst",
        "mcp_tools": app.state.mcp_tool_names,
    }
