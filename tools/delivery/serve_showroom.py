from __future__ import annotations

import argparse
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ShowroomRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


def local_address() -> str | None:
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        connection.connect(("192.0.2.1", 80))
        address = connection.getsockname()[0]
        return address if address and not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="启动客户 3D 户型预览")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    handler = lambda *values, **options: ShowroomRequestHandler(  # noqa: E731
        *values,
        directory=str(root),
        **options,
    )
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"电脑预览：http://127.0.0.1:{args.port}/")
    address = local_address()
    if address:
        print(f"同一 Wi-Fi 手机/平板：http://{address}:{args.port}/")
    print("按 Ctrl+C 停止预览。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
