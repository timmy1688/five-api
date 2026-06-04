from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    user: str | None = None


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    prompt: str | list[str]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stream: bool = False
    stop: str | list[str] | None = None


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[str]
    encoding_format: str | None = None
