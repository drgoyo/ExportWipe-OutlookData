"""Prove legacy body fields cannot enter the Track 1 provider payload."""

import json

from pipelines.rag_agents.agents import MetadataAgent
from tests.support import RecordingLLM


def test_metadata_track_strips_legacy_body_and_nested_attachment_contents() -> None:
    llm = RecordingLLM()
    payload = {
        "email_id": "id-1",
        "sender": "a@company.example",
        "date": "2026-01-01",
        "subject": "Metadata",
        "body": "SECRET_BODY",
        "attachment_content": "SECRET_ATTACHMENT",
        "extracted_attachments": ["report.docx"],
    }
    answer = MetadataAgent(llm).ask(json.dumps(payload), "Who sent this?")
    assert answer.text
    assert "SECRET_BODY" not in llm.contexts[0]
    assert "SECRET_ATTACHMENT" not in llm.contexts[0]
    assert "a@company.example" in llm.contexts[0]
