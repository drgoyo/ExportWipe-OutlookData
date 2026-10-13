"""Model UI copy distinguishes compatible, live-verified, and validated-installation states."""

from pipelines.configuration_gui.model_picker import model_summary


def test_model_summary_does_not_imply_local_registry_models_are_downloaded() -> None:
    text = model_summary(
        {
            "model": "compatible/model",
            "hf_repo": "verified/source",
            "dim": 384,
            "size_gb": 0.22,
            "license": "apache-2.0",
            "live_status": "not_checked",
            "installed_revision": "",
            "recommendation": "128-token truncation; use short chunks.",
        }
    )
    assert "not_checked" in text
    assert "Not installed" in text
    assert "Hub license: not checked" in text
    assert "128-token truncation" in text
    assert "separate Chroma collection" in text


def test_model_summary_shows_network_failure_and_installed_revision_separately() -> None:
    text = model_summary(
        {
            "model": "compatible/model",
            "hf_repo": "verified/source",
            "dim": 384,
            "size_gb": 0.22,
            "license": "apache-2.0",
            "live_status": "unavailable",
            "live_error": "Hugging Face returned HTTP 403",
            "installed_revision": "abc",
        }
    )
    assert "Validated installation: abc" in text
    assert "HTTP 403" in text
