"""Streamlit analytics and separate agent interfaces with injected data/agent ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import streamlit as st

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_name.core.ports import MetadataStore
    from project_name.core.records import Answer, JsonRow


def chart_frame(metrics: JsonRow, key: str) -> pl.DataFrame:
    values = metrics.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"Invalid analytics result: {key}")
    rows = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"Invalid analytics row: {key}")
        row: dict[str, str | int | float | bool | None] = {}
        for name, cell in value.items():
            if isinstance(cell, (list, dict)):
                raise ValueError("Chart values must be scalar")
            row[name] = cell
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def render(
    metadata: MetadataStore,
    *,
    vector_count: Callable[[], int] | None = None,
    ask_metadata: Callable[[str, str], Answer] | None = None,
    ask_deep: Callable[[str], Answer] | None = None,
) -> None:
    st.set_page_config(page_title="Outlook Dual-Track RAG", layout="wide")
    st.title("Outlook Dual-Track RAG")
    analytics, light, deep = st.tabs(["Analytics", "Track 1 · Metadata", "Track 2 · Deep RAG"])
    with analytics:
        if st.button("Refresh metrics"):
            st.rerun()
        metrics = metadata.statistics()
        vectors: int | None = None
        if vector_count is not None:
            try:
                vectors = vector_count()
            except (ValueError, RuntimeError, OSError, ImportError):
                st.warning("Chroma is unavailable; SQLite metrics remain available.")
        columns = st.columns(5)
        for column, label, value in zip(
            columns,
            ["Emails", "Ready documents", "Ready chunks", "Pending sync", "Physical vectors"],
            [
                metrics["email_count"],
                metrics["document_count"],
                metrics["chunk_count"],
                metrics["pending_count"],
                vectors if vectors is not None else "Unavailable",
            ],
            strict=True,
        ):
            column.metric(label, str(value))
        size = metrics["sqlite_bytes"]
        st.caption(
            f"SQLite + WAL storage: {size} bytes. Physical vectors may include pending writes; "
            "retrieval uses ready SQL revisions."
        )
        for key, title, x, y in [
            ("email_volumes", "Emails by received date", "day", "count"),
            ("top_senders", "Top senders", "sender", "count"),
            ("file_types", "Parsed file types", "file_type", "count"),
            ("growth", "Database growth (daily snapshots)", "day", "documents"),
        ]:
            st.subheader(title)
            frame = chart_frame(metrics, key)
            if frame.is_empty():
                st.info("No records yet. Export and ingest a test folder first.")
            elif key in {"email_volumes", "growth"}:
                st.line_chart(frame, x=x, y=y)
                if key == "growth" and "sqlite_bytes" in frame.columns:
                    st.line_chart(frame, x="day", y="sqlite_bytes")
            else:
                st.bar_chart(frame, x=x, y=y)
    with light:
        st.subheader("Metadata-only file upload")
        st.caption(
            "Upload Master_Index.jsonl. Bodies and attachment content fields are stripped "
            "before any provider call."
        )
        upload = st.file_uploader("Email metadata JSONL", type=["jsonl"], max_upload_size=20)
        question = st.text_input("Metadata question", key="metadata_question")
        if ask_metadata is None:
            st.info("Track 1 is disabled in configuration.")
        elif st.button("Ask metadata agent", disabled=upload is None or not question.strip()):
            try:
                if upload is not None:
                    answer = ask_metadata(upload.getvalue().decode("utf-8-sig"), question)
                    st.write(answer.text)
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
    with deep:
        st.subheader("Grounded document retrieval")
        deep_question = st.text_input("Document question", key="deep_question")
        if ask_deep is None:
            st.info("Track 2 is disabled in configuration.")
        elif st.button("Ask deep RAG agent", disabled=not deep_question.strip()):
            try:
                answer = ask_deep(deep_question)
                st.write(answer.text)
                if answer.citations:
                    st.caption("Evidence chunk IDs: " + ", ".join(answer.citations))
            except (ValueError, RuntimeError, OSError, ImportError) as exc:
                st.error(str(exc))
