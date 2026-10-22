"""Keep graph/checkpoint message IDs consistent with the model's streamed chunks."""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.language_models.chat_models import LC_ID_PREFIX


class _StreamIdentity(BaseCallbackHandler):
    run_inline = True

    def __init__(self):
        self.first_chunk = None
        self.run_message_id = None

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        # Reasoning-only initial chunks can have no ID. This is the same fallback
        # the LangChain stream assigns to chunks before a provider supplies an ID.
        self.run_message_id = f"{LC_ID_PREFIX}-{run_id}"

    def on_llm_new_token(self, token, *, chunk=None, **kwargs):
        if self.first_chunk is None and chunk is not None:
            self.first_chunk = chunk.message

    def align(self, response):
        # The provider can mutate the initial chunk's ID too at completion.
        # LangChain's run identity stays stable throughout the stream.
        message_id = self.run_message_id or (self.first_chunk.id if self.first_chunk is not None else None)
        if message_id:
            for message in response.result:
                if isinstance(message, AIMessage):
                    message.id = message_id
        return response


class StreamMessageIdentityMiddleware(AgentMiddleware):
    """Responses can replace an AIMessage ID at completion; retain its stream ID.

    A fresh recorder/model configuration is used per invocation, so simultaneous
    conversations never share identity state. Provider response IDs remain in metadata.
    """

    @staticmethod
    def _record(request):
        identity = _StreamIdentity()
        model = request.model.model_copy(update={
            "callbacks": [*(request.model.callbacks or []), identity],
        })
        return request.override(model=model), identity

    def wrap_model_call(self, request, handler):
        request, identity = self._record(request)
        return identity.align(handler(request))

    async def awrap_model_call(self, request, handler):
        request, identity = self._record(request)
        return identity.align(await handler(request))

    @staticmethod
    def _tool_result(result):
        # assistant-ui exports backend tool results under the tool call ID.
        # Store that same ID so echoes in later transcripts update the message
        # rather than adding a second result to the graph checkpoint.
        if isinstance(result, ToolMessage):
            return result.model_copy(update={"id": result.tool_call_id})
        return result

    def wrap_tool_call(self, request, handler):
        return self._tool_result(handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._tool_result(await handler(request))
