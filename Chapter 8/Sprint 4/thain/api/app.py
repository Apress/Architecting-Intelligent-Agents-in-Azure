from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from api.schemas import ChatRequest, ChatResponse
from main import MissingConfigError, load_config, run_thain_text_async  # type: ignore


app = FastAPI(title="Thain API", version="0.1")
logger = logging.getLogger("thain.api")


async def run_turn_http(message: str) -> ChatResponse:
    try:
        # Keep API calls on FastAPI's running event loop.
        text, trace_id = await run_thain_text_async(message, config=load_config())
    except MissingConfigError as exc:
        logger.error("Missing config for /chat: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - runtime issues
        logger.exception("Unhandled /chat error")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return ChatResponse(response=text, trace_id=trace_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await run_turn_http(request.message)
