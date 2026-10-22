"""AG-UI frontend-tool round trip without a model API key or external services."""
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from ag_ui.core import RunAgentInput, Tool
from ag_ui_langgraph import LangGraphAgent
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from frontend_tools import FrontendToolsMiddleware
from message_identity import StreamMessageIdentityMiddleware, _StreamIdentity


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # Stateless fixture, like an API model: middleware copies must not reset
        # a counter that decides the next response.
        index = 1 if messages[-1].type == "tool" else 0
        return ChatResult(generations=[ChatGeneration(message=self.responses[index])])


class FrontendToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_backend_and_browser_calls_then_resume(self):
        executed = []

        @tool
        async def read_orders():
            """Return fixture receipt metrics."""
            executed.append("orders")
            return {"receipts": 41, "revenue": 9700400}

        @tool
        async def read_units():
            """Return fixture selling quantity."""
            executed.append("units")
            return {"units": 106}

        await self.mixed_round_trip([read_orders, read_units], [
            {"name": "read_orders", "args": {}, "id": "orders-call", "type": "tool_call"},
            {"name": "inspect_perspective", "args": {}, "id": "browser-call", "type": "tool_call"},
            {"name": "read_units", "args": {}, "id": "units-call", "type": "tool_call"},
        ], {"orders-call": {"receipts": 41, "revenue": 9700400}, "units-call": {"units": 106}})
        self.assertCountEqual(executed, ["orders", "units"], "Backend calls execute once, including after browser resume")

    async def test_mixed_call_preserves_backend_error(self):
        @tool
        async def failing_query():
            """Return a failed query result."""
            return ToolMessage(content='{"error":"fixture query failed"}', tool_call_id="failed-call", status="error")

        await self.mixed_round_trip([failing_query], [
            {"name": "inspect_perspective", "args": {}, "id": "browser-call", "type": "tool_call"},
            {"name": "failing_query", "args": {}, "id": "failed-call", "type": "tool_call"},
        ], {"failed-call": {"error": "fixture query failed"}})

    async def mixed_round_trip(self, backend_tools, calls, expected):
        model = ToolModel(responses=[AIMessage(content="", tool_calls=calls), AIMessage(content="Automatic tools completed.")])
        graph = create_agent(model=model, tools=backend_tools,
            middleware=[StreamMessageIdentityMiddleware(), FrontendToolsMiddleware(backend_tools)], checkpointer=InMemorySaver())
        bridge = LangGraphAgent(name="mixed-test", graph=graph, emit_raw_events=False)
        thread_id = str(uuid4())
        browser_tools = [Tool(name="inspect_perspective", description="Inspect plugins", parameters={"type":"object","properties":{}})]
        first = RunAgentInput(thread_id=thread_id, run_id=str(uuid4()), state={},
            messages=[{"id":"mixed-user","role":"user","content":"Query and inspect the chart plugins."}], tools=browser_tools, context=[])
        events = [event.model_dump(mode="json", by_alias=True) async for event in bridge.clone().run(first)]
        self.assertFalse(any(event["type"] == "RUN_ERROR" for event in events), events)
        snapshot = next(event["messages"] for event in reversed(events) if event["type"] == "MESSAGES_SNAPSHOT")
        results = {msg["toolCallId"]: msg for msg in snapshot if msg["role"] == "tool"}
        self.assertEqual(set(results), set(expected), "Only actual backend results exist before browser handoff")
        for call_id, content in expected.items():
            self.assertEqual(json.loads(results[call_id]["content"]), content)
            self.assertEqual(results[call_id]["id"], call_id)
        checkpoint = await graph.aget_state({"configurable":{"thread_id":thread_id}})
        if "failed-call" in expected:
            failed = next(msg for msg in checkpoint.values["messages"] if isinstance(msg, ToolMessage))
            self.assertEqual(failed.status, "error")
        self.assertFalse(any(event.get("outcome", {}).get("type") == "interrupt" for event in events))
        snapshot.append({"id":"browser-call","role":"tool","toolCallId":"browser-call","content":'{"plugins":["Y Line"]}'})
        second = RunAgentInput(thread_id=thread_id,run_id=str(uuid4()),state={},messages=snapshot,tools=browser_tools,context=[])
        resumed = [event.model_dump(mode="json",by_alias=True) async for event in bridge.clone().run(second)]
        self.assertFalse(any(event["type"] == "RUN_ERROR" for event in resumed),resumed)
        final = next(event["messages"] for event in reversed(resumed) if event["type"] == "MESSAGES_SNAPSHOT")
        self.assertEqual(final[-1]["content"],"Automatic tools completed.")
        self.assertEqual(sum(msg["role"] == "tool" for msg in final),len(expected)+1)
        self.assertNotIn("Approved by user",json.dumps(final))

    async def test_browser_call_then_resume(self):
        await self.browser_call_then_resume("render_perspective")

    async def test_inspection_call_then_resume(self):
        await self.browser_call_then_resume("inspect_perspective")

    async def browser_call_then_resume(self, tool_name):
        args = {"title": "Fixture", "tables": [], "panels": []} if tool_name == "render_perspective" else {}
        model = ToolModel(responses=[
            AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": "chart-call", "type": "tool_call"}]),
            AIMessage(content="Browser tool completed."),
        ])
        graph = create_agent(model=model, tools=[], middleware=[StreamMessageIdentityMiddleware(), FrontendToolsMiddleware()], checkpointer=InMemorySaver())
        bridge = LangGraphAgent(name="test", graph=graph, emit_raw_events=False)
        thread_id = str(uuid4())
        tools = [Tool(name=tool_name, description="Render verified results", parameters={"type": "object", "properties": {"title": {"type": "string"}, "tables": {"type": "array", "items": {"type": "object"}}, "panels": {"type": "array", "items": {"type": "object"}}}, "required": []})]
        first = RunAgentInput(thread_id=thread_id, run_id=str(uuid4()), state={}, messages=[{"id": "user-1", "role": "user", "content": "Draw the fixture."}], tools=tools, context=[])
        events = [event.model_dump(mode="json", by_alias=True) async for event in bridge.clone().run(first)]
        errors = [event for event in events if event["type"] == "RUN_ERROR"]
        self.assertEqual(errors, [])
        messages = next(event["messages"] for event in reversed(events) if event["type"] == "MESSAGES_SNAPSHOT")
        # This deterministic fake model does not stream chunks; real ChatOpenAI
        # also emits TOOL_CALL_* events, covered by the live browser check.
        self.assertEqual(messages[-1]["toolCalls"][0]["function"]["name"], tool_name)
        self.assertFalse(any(message["role"] == "tool" for message in messages), "The server must not invent the browser result")
        messages.append({"id": "browser-result", "role": "tool", "toolCallId": "chart-call", "content": json.dumps({"status": "ready"})})
        second = RunAgentInput(thread_id=thread_id, run_id=str(uuid4()), state={}, messages=messages, tools=tools, context=[])
        resumed = [event.model_dump(mode="json", by_alias=True) async for event in bridge.clone().run(second)]
        self.assertFalse(any(event["type"] == "RUN_ERROR" for event in resumed), resumed)
        snapshot = next(event["messages"] for event in reversed(resumed) if event["type"] == "MESSAGES_SNAPSHOT")
        self.assertEqual(snapshot[-1]["content"], "Browser tool completed.")
        self.assertEqual(sum(message["role"] == "user" for message in snapshot), 1)
        self.assertEqual(sum(message["role"] == "tool" for message in snapshot), 1)

    async def test_unregistered_frontend_tools_not_advertised(self):
        middleware = FrontendToolsMiddleware()
        from types import SimpleNamespace
        request = SimpleNamespace(state={"tools": [{"name": "untrusted", "parameters": {}}]}, tools=[])
        request.override = lambda **kwargs: kwargs
        self.assertEqual(middleware._model_request(request)["tools"], [])


class MessageIdentityTests(unittest.TestCase):
    def test_reasoning_chunk_without_id_uses_langchain_stream_identity(self):
        from types import SimpleNamespace
        from langchain_core.language_models.chat_models import LC_ID_PREFIX
        run_id = uuid4()
        recorder = _StreamIdentity()
        recorder.on_chat_model_start({}, [], run_id=run_id)
        recorder.on_llm_new_token("", chunk=SimpleNamespace(message=AIMessageChunk(content="")))
        recorder.first_chunk.id = "provider-id-at-completion"
        result = AIMessage(content="Done", id="response-1")
        recorder.align(SimpleNamespace(result=[result]))
        self.assertEqual(result.id, f"{LC_ID_PREFIX}-{run_id}")

    def test_backend_tool_result_has_stable_wire_id(self):
        result = ToolMessage(content="Verified data", id="server-generated-id", tool_call_id="call-1")
        normalized = StreamMessageIdentityMiddleware._tool_result(result)
        self.assertEqual(normalized.id, "call-1")
        self.assertEqual(normalized.content, result.content)

    def test_final_id_matches_stream_and_preserves_provider_metadata(self):
        from types import SimpleNamespace
        recorder = _StreamIdentity()
        chunk = AIMessageChunk(content="", id="stream-1")
        recorder.on_llm_new_token("", chunk=SimpleNamespace(message=chunk))
        result = AIMessage(content="Done", id="response-1", response_metadata={"id": "response-1"})
        response = SimpleNamespace(result=[result])
        self.assertIs(recorder.align(response), response)
        self.assertEqual(result.id, "stream-1")
        self.assertEqual(result.response_metadata["id"], "response-1")

    def test_recorders_do_not_share_thread_state(self):
        from types import SimpleNamespace
        first, second = _StreamIdentity(), _StreamIdentity()
        first.on_llm_new_token("A", chunk=SimpleNamespace(message=AIMessageChunk(content="A", id="thread-a")))
        second.on_llm_new_token("B", chunk=SimpleNamespace(message=AIMessageChunk(content="B", id="thread-b")))
        a, b = AIMessage(content="A"), AIMessage(content="B")
        first.align(SimpleNamespace(result=[a]))
        second.align(SimpleNamespace(result=[b]))
        self.assertEqual((a.id, b.id), ("thread-a", "thread-b"))


if __name__ == "__main__":
    unittest.main()
