"""Build through the existing cloud proxy and trust bundle without exposing their values."""

import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cache = Path("/workspace/.cache/docker")
    cache.mkdir(parents=True, exist_ok=True)
    base = [
        "docker",
        "--config",
        str(cache),
        "build",
        "--network=host",
        "--build-arg",
        "HTTP_PROXY",
        "--build-arg",
        "HTTPS_PROXY",
        "--build-arg",
        "NO_PROXY",
    ]
    for variable in ["HTTP_PROXY", "HTTPS_PROXY"]:
        host = urlsplit(os.environ.get(variable, "")).hostname
        if host:
            base += ["--add-host", f"{host}:{socket.gethostbyname(host)}"]
    ca = os.environ.get("SSL_CERT_FILE")
    if ca:
        base += ["--secret", f"id=cloud_ca,src={ca}"]
    for image, dockerfile in [
        ("outlook-rag:local", "Dockerfile"),
        ("outlook-rag-chroma:local", "docker/chroma.Dockerfile"),
    ]:
        # Fixed public image inputs, existing trusted proxy settings, no shell expansion.
        result = subprocess.run([*base, "-t", image, "-f", dockerfile, "."], cwd=root, check=False)  # noqa: S603
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
