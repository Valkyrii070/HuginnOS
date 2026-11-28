"""Carries a language-server conversation between Code (standard input and output) and a helper that listens on a
port instead. Godot is the one that does: while a project is open in its editor it answers GDScript questions on
127.0.0.1:6005.
    python3 huginn_lsp_tcp.py <host> <port>
Ends (with 1) when the port can't be reached, and when either side closes."""
import os
import socket
import sys
import threading


def port_open(host: str, port: int, wait: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=wait):
            return True
    except OSError:
        return False


def main() -> int:
    if len(sys.argv) != 3 or not sys.argv[2].isdigit() or sys.argv[1] not in ("127.0.0.1", "localhost", "::1"):
        print("usage: huginn_lsp_tcp.py 127.0.0.1 <port>   (this computer only)", file=sys.stderr)
        return 2
    try:
        sock = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3)
    except OSError as e:
        print(f"nothing is listening on {sys.argv[1]}:{sys.argv[2]} ({e})", file=sys.stderr)
        return 1
    sock.settimeout(None)

    def to_helper():
        try:
            while True:
                data = os.read(0, 65536)
                if not data:
                    break
                sock.sendall(data)
        except OSError:
            pass
        # Code has finished speaking: the helper is told so, and given a moment to finish its answer
        closed.set()
        try:
            sock.shutdown(socket.SHUT_WR)
            sock.settimeout(2)
        except OSError:
            pass

    closed = threading.Event()
    threading.Thread(target=to_helper, daemon=True).start()
    try:
        while True:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                if closed.is_set():
                    break
                continue
            if not data:
                break
            os.write(1, data)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
