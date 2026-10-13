"""CLI composition for extraction settings, ETL, both agent tracks, MCP, and API hosting."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from config.application import AppConfig, load_config, save_config, write_vba_ini
from project_name.application import Runtime

if TYPE_CHECKING:
    from project_name.core.records import JsonRow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outlook-rag")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-config")
    init.add_argument("--output", type=Path, default=Path("config.yaml"))
    ini = commands.add_parser("export-vba-config")
    ini.add_argument("--output", type=Path)
    catalog = commands.add_parser("catalog", help="Build metadata indexes with DuckDB and Polars")
    catalog.add_argument("--batch-size", type=int, default=256)
    commands.add_parser("catalog-recover", help="Restore a catalog interrupted during publication")
    models = commands.add_parser("models", help="Discover, verify and install embedding models")
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_list = model_commands.add_parser("list")
    model_list.add_argument("--language", choices=["de", "en"], default="de")
    model_list.add_argument("--online", action="store_true")
    model_check = model_commands.add_parser("check")
    model_check.add_argument("model")
    model_download = model_commands.add_parser("download")
    model_download.add_argument("model")
    model_download.add_argument("--max-size-gb", type=float, default=1.0)
    llm_models = commands.add_parser("llm-models", help="Discover and install local GGUF LLMs")
    llm_commands = llm_models.add_subparsers(dest="model_command", required=True)
    llm_list = llm_commands.add_parser("list")
    llm_list.add_argument("--search", default="Qwen")
    llm_list.add_argument("--limit", type=int, default=8)
    llm_check = llm_commands.add_parser("check")
    llm_check.add_argument("repository")
    llm_download = llm_commands.add_parser("download")
    llm_download.add_argument("repository")
    llm_download.add_argument("--filename")
    llm_download.add_argument("--max-size-gb", type=float, default=5.0)
    llm_download.add_argument("--install-ollama", action="store_true")
    llm_download.add_argument("--name", "--ollama-name", dest="name", default="outlook-rag")
    parse = commands.add_parser("parse")
    parse.add_argument("input", type=Path)
    parse.add_argument("--output", type=Path, required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--manifest", type=Path, required=True)
    ingest.add_argument(
        "--force", action="store_true", help="Rebuild vectors for unchanged documents"
    )
    commands.add_parser("sync")
    commands.add_parser("stats")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    ask = commands.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--track", type=int, choices=[1, 2], default=2)
    ask.add_argument("--metadata-file", type=Path)
    commands.add_parser("mcp")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def execute(args: argparse.Namespace) -> None:
    if args.command == "init-config":
        output: Path = args.output
        if output.exists():
            raise ValueError("Config already exists; use the GUI to edit it")
        save_config(output, AppConfig())
        print(f"Created {output}")
        return
    config_path: Path = args.config
    config = load_config(config_path)
    if args.command == "export-vba-config":
        ini_path: Path = args.output or config.extraction.output_directory / "extractor.ini"
        write_vba_ini(ini_path, config)
        print(f"Created {ini_path}")
        return
    if args.command == "catalog":
        from pipelines.export_catalog.catalog import build_catalog

        catalog_report = build_catalog(
            config.extraction.output_directory, batch_size=args.batch_size
        )
        print(
            json.dumps(
                {**asdict(catalog_report), "complete": catalog_report.complete},
                default=str,
                ensure_ascii=False,
            )
        )
        if not catalog_report.complete:
            raise SystemExit(1)
        return
    if args.command == "catalog-recover":
        from pipelines.export_catalog.catalog import recover_catalog

        print(
            json.dumps(
                asdict(recover_catalog(config.extraction.output_directory)),
                default=str,
                ensure_ascii=False,
            )
        )
        return
    if args.command == "models":
        from project_name.infrastructure.model_catalog import ModelCatalog

        catalog = ModelCatalog(config.storage.model_cache)
        result: list[JsonRow] | JsonRow
        if args.model_command == "list":
            result = catalog.list_models(language=args.language, online=args.online)
        elif args.model_command == "check":
            result = catalog.check(args.model)
        else:
            result = catalog.download(args.model, max_size_gb=args.max_size_gb)
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command == "llm-models":
        from project_name.infrastructure.local_llm_models import (
            LocalLLMModelCatalog,
            install_ollama,
        )

        llm_catalog = LocalLLMModelCatalog(config.storage.model_cache / "llm")
        llm_result: list[JsonRow] | JsonRow
        if args.model_command == "list":
            llm_result = llm_catalog.list_models(search=args.search, limit=args.limit)
        elif args.model_command == "check":
            llm_result = llm_catalog.check(args.repository)
        else:
            llm_result = llm_catalog.download(
                args.repository, args.filename, max_size_gb=args.max_size_gb
            )
            if args.install_ollama:
                llm_result = install_ollama(llm_result, name=args.name)
        print(json.dumps(llm_result, ensure_ascii=False))
        return
    runtime = Runtime(config, config_path)
    if args.command == "parse":
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(runtime.parser().parse(args.input), encoding="utf-8")
    elif args.command == "ingest":
        report = runtime.ingestor().ingest(args.manifest, force=args.force)
        print(json.dumps(asdict(report), ensure_ascii=False))
        if report.errors:
            raise SystemExit(1)
    elif args.command == "sync":
        print(json.dumps({"synchronized": runtime.metadata.synchronize(runtime.vectors())}))
    elif args.command == "stats":
        print(json.dumps(runtime.metadata.statistics(), ensure_ascii=False))
    elif args.command == "search":
        print(
            json.dumps(
                [asdict(hit) for hit in runtime.deep_agent().search(args.query, args.limit)],
                ensure_ascii=False,
            )
        )
    elif args.command == "ask":
        if args.track == 1:
            if args.metadata_file is None:
                raise ValueError("Track 1 requires --metadata-file")
            with args.metadata_file.open("rb") as stream:
                content = stream.read(20_000_001)
            if len(content) > 20_000_000:
                raise ValueError("Track 1 upload exceeds 20 MB; use MCP SQL for larger catalogs")
            text = content.decode("utf-8-sig")
            answer = runtime.metadata_agent().ask(text, args.question)
        else:
            answer = runtime.deep_agent().ask(args.question)
        print(json.dumps(asdict(answer), ensure_ascii=False))
    elif args.command == "mcp":
        from project_name.mcp_server import create_server

        create_server(runtime).run(transport="stdio")
    elif args.command == "serve":
        import uvicorn

        from project_name.api import create_app

        if not runtime.environment.api_token.get_secret_value():
            raise ValueError("Set EW_API_TOKEN before starting the HTTP backend")
        uvicorn.run(create_app(runtime), host=args.host, port=args.port, loop="asyncio", http="h11")


def main() -> None:
    parser = build_parser()
    try:
        execute(parser.parse_args())
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
