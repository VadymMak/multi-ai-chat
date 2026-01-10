# Provider Updates for User API Keys Support

## Overview

This document describes the changes needed to support user-specific API keys in providers.

---

## 1. openai_provider.py

### Add helper function after \_get_client() (around line 95):

```python
def _get_client_with_key(api_key: str) -> Any:
    """Create a NEW OpenAI client with a specific API key (not cached)."""
    if not _HAVE_OPENAI:
        raise RuntimeError("[OpenAI Error] openai package not installed")

    base_url = os.getenv("OPENAI_BASE_URL") or None
    organization = os.getenv("OPENAI_ORG") or None

    http_client = httpx.Client(
        timeout=httpx.Timeout(TIMEOUT_SECS, connect=10.0),
        trust_env=False
    )

    return _RuntimeOpenAIClient(
        api_key=api_key,
        base_url=base_url,
        organization=organization,
        http_client=http_client
    )
```

### Update ask_openai function signature (line ~315):

BEFORE:

```python
def ask_openai(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system_prompt: Optional[str] = None,
    *,
    json_mode: Optional[bool] = None,
    force_text_only: Optional[bool] = None,
) -> str:
```

AFTER:

```python
def ask_openai(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system_prompt: Optional[str] = None,
    *,
    api_key: Optional[str] = None,  # NEW: User's API key
    json_mode: Optional[bool] = None,
    force_text_only: Optional[bool] = None,
) -> str:
```

### Update client creation inside ask_openai (after docstring, ~line 330):

BEFORE:

```python
    try:
        client = _get_client()
```

AFTER:

```python
    try:
        # Use user's key if provided, otherwise fall back to env key
        if api_key:
            client = _get_client_with_key(api_key)
        else:
            client = _get_client()
```

---

## 2. claude_provider.py

### Add helper function after \_get_client() (around line 70):

```python
def _get_client_with_key(api_key: str) -> Any:
    """Create a NEW Anthropic client with a specific API key (not cached)."""
    if not _HAVE_ANTHROPIC:
        raise RuntimeError("[Claude Error] anthropic package not installed")

    import httpx

    http_client = httpx.Client(
        timeout=httpx.Timeout(TIMEOUT_SECS, connect=15.0),
        trust_env=True
    )

    return Anthropic(
        api_key=api_key,
        http_client=http_client
    )
```

### Find ask_claude function and update signature:

BEFORE:

```python
def ask_claude(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system: Optional[str] = None,
) -> str:
```

AFTER:

```python
def ask_claude(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system: Optional[str] = None,
    *,
    api_key: Optional[str] = None,  # NEW: User's API key
) -> str:
```

### Update client creation inside ask_claude:

BEFORE:

```python
    client = _get_client()
```

AFTER:

```python
    # Use user's key if provided, otherwise fall back to env key
    if api_key:
        client = _get_client_with_key(api_key)
    else:
        client = _get_client()
```

---

## 3. factory.py

### Update ask_model function to accept and pass api_key:

Find ask_model function and add api_key parameter:

```python
def ask_model(
    messages: List[dict],
    model_key: str = "gpt-4o-mini",
    system_prompt: Optional[str] = None,
    *,
    api_key: Optional[str] = None,  # NEW
) -> str:
```

Then pass it to the provider calls:

```python
    if provider == "openai":
        return ask_openai(
            final_messages,
            model=model,
            system_prompt=system_prompt,
            api_key=api_key,  # NEW
        )
    elif provider == "anthropic":
        return ask_claude(
            final_messages,
            model=model,
            system=system_prompt,
            api_key=api_key,  # NEW
        )
```

---

## 4. ask_ai_to_ai.py - Integration

### Add imports at top (after line 22):

```python
from app.deps import get_current_active_user
from app.memory.models import User
from app.utils.api_key_resolver import get_openai_key, get_anthropic_key, get_google_search_key
```

### Update the endpoint to require authentication and get user keys:

Find the main endpoint function and add user dependency:

```python
@router.post("/ask-ai-to-ai")
async def ask_ai_to_ai(
    data: AiToAiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),  # NEW
):
```

### Get user's API keys at the start of the function:

```python
    # Get user's API keys
    openai_key = get_openai_key(current_user, db, required=True)
    anthropic_key = get_anthropic_key(current_user, db, required=True)
    google_key = get_google_search_key(current_user, db, required=False)  # Optional
```

### Pass keys to provider calls:

Find where ask_openai is called (line ~608) and update:

BEFORE:

```python
first_reply_raw: str = await run_in_threadpool(ask_openai, starter_messages)
```

AFTER:

```python
first_reply_raw: str = await run_in_threadpool(
    ask_openai,
    starter_messages,
    api_key=openai_key
)
```

Find where ask_claude is called (line ~394) and update:

BEFORE:

```python
ans = await run_in_threadpool(ask_claude, filtered_messages, system=system)
```

AFTER:

```python
ans = await run_in_threadpool(
    ask_claude,
    filtered_messages,
    system=system,
    api_key=anthropic_key
)
```

---

## 5. ask.py - Integration

Similar pattern - add user dependency and pass api_key to ask_model calls.

### Add imports:

```python
from app.deps import get_current_active_user
from app.memory.models import User
from app.utils.api_key_resolver import get_api_key
```

### Update endpoint:

```python
@router.post("/ask")
async def ask_endpoint(
    request: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),  # NEW
):
```

### Get and use key:

```python
    # Determine provider and get user's key
    provider = request.provider  # "openai" or "anthropic"
    user_key = get_api_key(current_user, provider, db)

    # Pass to ask_model
    response = ask_model(
        messages,
        model_key=model_key,
        system_prompt=system_prompt,
        api_key=user_key,  # NEW
    )
```

---

## Testing

1. Login as regular user (not superuser)
2. Go to Settings → API Keys
3. Add your OpenAI and Anthropic keys
4. Send a message in Debate Mode
5. Check Railway logs - should show requests using user's keys
6. If no keys added → should get 403 error "Please add your API key"

---

## Notes

- Superusers automatically fall back to .env keys
- Regular users MUST add their own keys
- Google Search key is optional (graceful degradation)
- YouTube key follows same pattern
