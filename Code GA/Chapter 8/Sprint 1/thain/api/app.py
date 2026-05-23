from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from api.schemas import ChatRequest, ChatResponse
from main import MissingConfigError, load_config, run_thain_text  # type: ignore


app = FastAPI(title="Thain API", version="0.1")
logger = logging.getLogger("thain.api")


def run_turn_http(message: str) -> ChatResponse:
    try:
        text, trace_id = run_thain_text(message, config=load_config())
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
def chat(request: ChatRequest) -> ChatResponse:
    return run_turn_http(request.message)
