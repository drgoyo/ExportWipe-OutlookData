"""Authenticated HTTP application; only root-contained manifests can be ingested."""

import secrets
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from project_name.application import Runtime
from project_name.core.records import JsonRow


class IngestRequest(BaseModel):
    manifest: str = "Master_Index.jsonl"
    force: bool = False


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    track: int = Field(default=2, ge=1, le=2)
    metadata: str = Field(default="", max_length=20_000_000)
    limit: int = Field(default=5, ge=1, le=100)


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="Outlook Dual-Track RAG", version="0.2.0", docs_url=None, redoc_url=None)
    token = runtime.environment.api_token.get_secret_value()

    def authorize(request: Request) -> None:
        supplied = request.headers.get("authorization", "")
        if not token or not secrets.compare_digest(supplied, "Bearer " + token):
            raise HTTPException(status_code=401, detail="Valid bearer token required")

    @app.get("/health")
    def health() -> JsonRow:
        try:
            runtime.metadata.statistics()
            if runtime.config.tracks.track2_enabled:
                runtime.vectors().count()
            return {"status": "ready", "track2_enabled": runtime.config.tracks.track2_enabled}
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail="Storage unavailable") from exc

    @app.get("/stats")
    def stats(request: Request) -> JsonRow:
        authorize(request)
        metrics = runtime.metadata.statistics()
        if runtime.config.tracks.track2_enabled:
            metrics["vector_count"] = runtime.vectors().count()
        return metrics

    @app.post("/ingest")
    def ingest(payload: IngestRequest, request: Request) -> JsonRow:
        authorize(request)
        try:
            path = (runtime.config.extraction.output_directory / payload.manifest).resolve()
            if not path.is_relative_to(runtime.config.extraction.output_directory.resolve()):
                raise ValueError("Manifest path escapes export root")
            return asdict(runtime.ingestor().ingest(path, force=payload.force))
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/search")
    def search(payload: AskRequest, request: Request) -> list[JsonRow]:
        authorize(request)
        try:
            return [
                asdict(hit) for hit in runtime.deep_agent().search(payload.question, payload.limit)
            ]
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ask")
    def ask(payload: AskRequest, request: Request) -> JsonRow:
        authorize(request)
        try:
            answer = (
                runtime.metadata_agent().ask(payload.metadata, payload.question)
                if payload.track == 1
                else runtime.deep_agent().ask(payload.question, payload.limit)
            )
            return {"text": answer.text, "citations": list(answer.citations)}
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
