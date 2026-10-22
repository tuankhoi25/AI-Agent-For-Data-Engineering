"""Bridge AG-UI browser tools into LangChain without executing them on the server."""

from typing import Any
from typing_extensions import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, hook_config
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode


class FrontendToolState(AgentState):
    tools: NotRequired[list[dict[str, Any]]]


class FrontendToolsMiddleware(AgentMiddleware):
    state_schema = FrontendToolState

    # Only presentation tools supported by this application may be advertised by a client.
    allowed_tools = frozenset({"inspect_perspective", "render_perspective"})

    def __init__(self, backend_tools=()):
        # Used only for mixed server/browser calls. Backend-only turns retain
        # create_agent's usual tools node; browser tools never enter this node.
        self.backend_node = ToolNode(list(backend_tools))

    def _handoff_calls(self, state):
        advertised = {tool.get("name") for tool in state.get("tools", [])}
        browser_names = self.allowed_tools & advertised
        calls = getattr(state["messages"][-1], "tool_calls", [])
        if not any(call["name"] in browser_names for call in calls):
            return None
        return [call for call in calls if call["name"] not in browser_names]

    @staticmethod
    def _handoff_update(result):
        # Preserve real contents/artifacts/errors. Wire/checkpoint IDs match
        # the IDs assistant-ui uses when it echoes these tool results on resume.
        messages = result.get("messages", [])
        if not all(isinstance(message, ToolMessage) for message in messages):
            raise RuntimeError("Backend handoff requires ToolMessage results.")
        return {
            "messages": [message.model_copy(update={"id": message.tool_call_id}) for message in messages],
            "jump_to": "end",
        }

    def _model_request(self, request: ModelRequest) -> ModelRequest:
        frontend_tools = [
            {"type": "function", "function": tool}
            for tool in request.state.get("tools", [])
            if tool.get("name") in self.allowed_tools
        ]
        return request.override(tools=[*request.tools, *frontend_tools])

    def wrap_model_call(self, request, handler):
        return handler(self._model_request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._model_request(request))

    @hook_config(can_jump_to=["end"])
    def after_model(self, state, runtime):
        calls = self._handoff_calls(state)
        if calls is None:
            return None
        result = self.backend_node.invoke(calls) if calls else {"messages": []}
        return self._handoff_update(result)

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state, runtime):
        calls = self._handoff_calls(state)
        if calls is None:
            return None
        result = await self.backend_node.ainvoke(calls) if calls else {"messages": []}
        # Unresolved calls now belong exclusively to the browser toolkit. Its
        # execute handlers supply results automatically after AG-UI settles.
        return self._handoff_update(result)
