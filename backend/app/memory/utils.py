# app/memory/utils.py
import tiktoken

MAX_MEMORY_TOKENS = 1000
ENCODING_MODEL = "gpt-3.5-turbo"

enc = tiktoken.encoding_for_model(ENCODING_MODEL)


def trim_memory(texts: list[str], max_tokens: int = MAX_MEMORY_TOKENS) -> str:
    """Join, tokenize and trim memory to the last `max_tokens`."""
    joined = "\n\n".join(texts)
    tokens = enc.encode(joined)
    if len(tokens) > max_tokens:
        tokens = tokens[-max_tokens:]
    return enc.decode(tokens)
