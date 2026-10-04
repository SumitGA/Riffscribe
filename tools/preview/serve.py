"""Local preview of a pipeline output dir: notation + tab rendered by alphaTab, with playback.

    make view                      # previews out/
    python tools/preview/serve.py --out path/to/out [--port 8765] [--no-browser]

Dev tool only: standard library, binds to 127.0.0.1, serves index.html and files under --out.
"""

import argparse
import contextlib
import http.server
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
MIME_TYPES = {
    ".musicxml": "application/vnd.recordare.musicxml+xml",
    ".mid": "audio/midi",
    ".flac": "audio/flac",
    ".json": "application/json",
}


class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    """Serves `/` from this folder and `/out/<path>` from the output dir, nothing else."""

    def __init__(self, *args: Any, out_dir: Path, **kwargs: Any) -> None:
        # Set before super().__init__, which handles the request.
        self.extensions_map = {**self.extensions_map, **MIME_TYPES}
        self.out_dir = out_dir.resolve()
        super().__init__(*args, directory=str(HERE), **kwargs)

    def translate_path(self, path: str) -> str:
        url_path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        if url_path in ("", "/"):
            return str(HERE / "index.html")
        if url_path.startswith("/out/"):
            return str(resolve_output(self.out_dir, url_path.removeprefix("/out/")))
        return str(HERE / "__not_found__")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")  # always show the latest run
        super().end_headers()


def resolve_output(out_dir: Path, relative: str) -> Path:
    """The file under `out_dir`, or a path that doesn't exist if `relative` tries to escape it."""
    target = (out_dir / relative).resolve()
    return target if target.is_relative_to(out_dir) else out_dir / "__not_found__"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("out"), help="pipeline output dir")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not (args.out / "notation" / "score.musicxml").exists():
        parser.error(f"no notation in {args.out}; run `make run FILE=...` first")

    def handler(*a: Any, **kw: Any) -> PreviewHandler:
        return PreviewHandler(*a, out_dir=args.out, **kw)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Previewing {args.out.resolve()} at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    main()
