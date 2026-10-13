"""Launch Streamlit in-process so the same entry point works in frozen executables."""

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Outlook RAG analytics and agent UI")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    config_path: Path = args.config
    if not config_path.exists():
        parser.error("Configuration not found; run outlook-rag init-config first")
    os.environ["EW_CONFIG_PATH"] = str(config_path.resolve())
    from streamlit.web import cli

    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).with_name("dashboard_app.py")),
        "--global.developmentMode",
        "false",
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
        "--server.maxUploadSize",
        "20",
        "--browser.gatherUsageStats",
        "false",
    ]
    cli.main()


if __name__ == "__main__":
    main()
