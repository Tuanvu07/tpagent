"""`python -m tpagent.server [--port N] [--workspace DIR] [--token T]`."""
from __future__ import annotations

import argparse
import sys

import uvicorn

from .app import create_app
from .settings import DEFAULT_PORT, Settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tpagent.server", description="TPAgent web UI server")
    parser.add_argument("--port", type=int, default=None, help=f"Cổng (mặc định: $PORT hoặc {DEFAULT_PORT})")
    parser.add_argument("--host", default="0.0.0.0", help="Địa chỉ lắng nghe (mặc định 0.0.0.0)")
    parser.add_argument("--workspace", default=None, help="Thư mục chứa file của các phiên ($TPAGENT_WORKSPACE, mặc định ./workspace)")
    parser.add_argument("--token", default=None, help="Mã đăng nhập ($TPAGENT_TOKEN; bỏ trống để tự sinh)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings.from_env(token=args.token, workspace=args.workspace, port=args.port)
    settings.host = args.host
    banner = [
        f"TPAgent web: http://{settings.host}:{settings.port}  (mở trình duyệt, dán token để đăng nhập)",
        f"Workspace: {settings.workspace}",
    ]
    if settings.generated_token:
        banner.append(f"Token (tự sinh, đặt TPAGENT_TOKEN để cố định): {settings.token}")
    print("\n".join(banner), file=sys.stderr, flush=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
