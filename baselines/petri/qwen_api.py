"""DashScope wire format for reasoning history and assistant partial completion."""

from time import monotonic

from inspect_ai.model import ContentReasoning, ModelCall, modelapi
from inspect_ai.model._openai import (
    chat_choices_from_openai, model_output_from_openai, openai_chat_messages,
    openai_chat_tool_choice, openai_chat_tools,
)
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI


async def qwen_messages(messages):
    wire = await openai_chat_messages(messages)
    for index, (message, item) in enumerate(zip(messages, wire)):
        if message.role != "assistant":
            continue
        item["content"] = message.text
        reasoning = [part.reasoning for part in message.content
                     if isinstance(part, ContentReasoning)] if isinstance(message.content, list) else []
        if reasoning:
            item["reasoning_content"] = "".join(reasoning)
        if index == len(messages) - 1 and (message.metadata or {}).get("prefill"):
            item["partial"] = True
    return wire


@modelapi(name="qwen")
class QwenAPI(OpenAICompatibleAPI):
    def __init__(self, model_name, **kwargs):
        super().__init__(model_name, service="qwen", **kwargs)

    def emulate_reasoning_history(self):
        return False

    def force_reasoning_history(self):
        return "all"

    async def generate(self, input, tools, tool_choice, config):
        request = self.completion_params(config, bool(tools))
        request["max_completion_tokens"] = request.pop("max_tokens")
        request["messages"] = await qwen_messages(input)
        if tools:
            request.update(tools=openai_chat_tools(tools),
                           tool_choice=openai_chat_tool_choice(tool_choice))
        start = monotonic()
        completion = await self.client.chat.completions.create(**request)
        return (
            model_output_from_openai(completion, chat_choices_from_openai(completion, tools)),
            ModelCall.create(request=request, response=completion.model_dump(),
                             time=monotonic() - start),
        )
