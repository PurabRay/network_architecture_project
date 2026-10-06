"""
Tests for bserve and bcurl.   Run from the repo root:

    python3 -m unittest -v tests/test_bh1.py

Three kinds of test:
  * ServerTests hand-build bytes and send them to bserve, so they check the
    server against the SPEC, not against bcurl.
  * ClientTests run the real ./bcurl program against ./bserve.
  * RealWorldTests: the exact commands from the brief, one connection for many
    requests, a very slow sender, and many clients at once.
"""
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(ROOT, "www")
PORT = 9123


# ---- tiny helpers that follow SPEC.md -------------------------------------------
def frame(ftype, flags, stream, payload=b""):
    return struct.pack("!HBBI", len(payload), ftype, flags, stream) + payload


def field(index, value):
    v = value.encode()
    return bytes([0x80 | index]) + struct.pack("!H", len(v)) + v


def get(path):
    return field(1, "GET") + field(2, path)


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def read_response(sock):
    """Read frames until END_STREAM. Returns (status, body, stream)."""
    status, body = None, b""
    while True:
        length, ftype, flags, stream = struct.unpack("!HBBI", recv_exact(sock, 8))
        payload = recv_exact(sock, length)
        if ftype == 1:
            # the server always puts :status (index 3) first
            assert payload[0] == 0x83
            vlen = struct.unpack("!H", payload[1:3])[0]
            status = int(payload[3:3 + vlen])
        elif ftype == 0:
            body += payload
        if flags & 1:
            return status, body, stream


def connect():
    s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    s.sendall(b"BH/1")
    return s


class Base(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)   # tests leave sockets open

    @classmethod
    def setUpClass(cls):
        # The server's log goes to a temp file so tests can read it.
        cls.log = tempfile.NamedTemporaryFile(mode="w+", suffix=".log")
        cls.server = subprocess.Popen([sys.executable, os.path.join(ROOT, "bserve"),
                                       WWW, str(PORT)], stderr=cls.log)
        for _ in range(50):                         # wait until it listens
            try:
                socket.create_connection(("127.0.0.1", PORT)).close()
                return
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait()
        cls.log.close()

    def server_log(self):
        time.sleep(0.2)                             # let the server finish writing
        self.log.seek(0)                            # works on Windows too
        return self.log.read().splitlines()


class ServerTests(Base):
    def test_200_body_matches_file(self):
        s = connect()
        s.sendall(frame(1, 1, 1, get("/index.html")))
        status, body, stream = read_response(s)
        self.assertEqual((status, stream), (200, 1))
        self.assertEqual(body, open(os.path.join(WWW, "index.html"), "rb").read())

    def test_slash_means_index_html(self):
        s = connect()
        s.sendall(frame(1, 1, 1, get("/")))
        self.assertEqual(read_response(s)[0], 200)

    def test_404(self):
        s = connect()
        s.sendall(frame(1, 1, 1, get("/missing.html")))
        self.assertEqual(read_response(s)[0], 404)

    def test_cannot_escape_root(self):
        s = connect()
        s.sendall(frame(1, 1, 1, get("/../../../../etc/passwd")))
        self.assertEqual(read_response(s)[0], 404)

    def test_405_for_other_methods(self):
        s = connect()
        s.sendall(frame(1, 1, 1, field(1, "POST") + field(2, "/")))
        self.assertEqual(read_response(s)[0], 405)

    def test_big_file_arrives_in_many_frames(self):
        s = connect()
        s.sendall(frame(1, 1, 1, get("/big.bin")))
        _, body, _ = read_response(s)
        self.assertEqual(body, open(os.path.join(WWW, "big.bin"), "rb").read())

    def test_empty_file_is_one_headers_frame(self):
        s = connect()
        s.sendall(frame(1, 1, 1, get("/empty.txt")))
        self.assertEqual(read_response(s)[:2], (200, b""))

    def test_connection_stays_open(self):
        s = connect()
        for stream in (1, 2, 3):
            s.sendall(frame(1, 1, stream, get("/index.html")))
            self.assertEqual(read_response(s)[::2], (200, stream))

    def test_unknown_frame_type_is_skipped(self):
        s = connect()
        s.sendall(frame(0x42, 0, 1, b"some future frame") +
                  frame(0xFF, 0xFF, 0, b"") +
                  frame(1, 1, 1, get("/index.html")))
        self.assertEqual(read_response(s)[0], 200)

    def test_literal_header_name_is_accepted(self):
        name = b"x-custom"
        literal = bytes([0, len(name)]) + name + struct.pack("!H", 2) + b"hi"
        s = connect()
        s.sendall(frame(1, 1, 1, get("/index.html") + literal))
        self.assertEqual(read_response(s)[0], 200)

    # ---- every kind of malformed request -> 400, connection stays open ------
    def assert_400_then_still_open(self, bad_bytes):
        s = connect()
        s.sendall(bad_bytes)
        self.assertEqual(read_response(s)[0], 400)
        s.sendall(frame(1, 1, 7, get("/index.html")))   # still usable?
        self.assertEqual(read_response(s)[0], 200)

    def test_400_truncated_header_block(self):
        self.assert_400_then_still_open(frame(1, 1, 1, get("/index.html")[:-3] + b"\x81\x00"))

    def test_400_unknown_table_index(self):
        self.assert_400_then_still_open(frame(1, 1, 1, get("/") + field(99, "x")))

    def test_400_missing_path(self):
        self.assert_400_then_still_open(frame(1, 1, 1, field(1, "GET")))

    def test_400_path_without_slash(self):
        self.assert_400_then_still_open(frame(1, 1, 1, get("index.html")))

    def test_400_stream_zero(self):
        self.assert_400_then_still_open(frame(1, 1, 0, get("/")))

    def test_400_data_from_client(self):
        self.assert_400_then_still_open(frame(0, 1, 1, b"hello"))

    def test_400_headers_without_end_stream(self):
        self.assert_400_then_still_open(frame(1, 0, 1, get("/")))

    def test_bad_preface_gets_400_and_close(self):
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        s.sendall(b"GET / HTTP/1.1\r\n\r\n")     # someone speaking plain HTTP
        status, _, stream = read_response(s)
        self.assertEqual((status, stream), (400, 0))
        self.assertEqual(s.recv(1), b"")         # server hung up


class ClientTests(Base):
    def bcurl(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bcurl"), *args],
                              capture_output=True)

    def test_body_to_stdout_exit_0(self):
        r = self.bcurl(f"localhost:{PORT}/index.html")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, open(os.path.join(WWW, "index.html"), "rb").read())

    def test_exit_1_on_404(self):
        self.assertEqual(self.bcurl(f"localhost:{PORT}/nope").returncode, 1)

    def test_exit_2_when_no_server(self):
        self.assertEqual(self.bcurl("localhost:1/").returncode, 2)

    def test_verbose_dumps_every_frame(self):
        r = self.bcurl("-v", f"localhost:{PORT}/index.html")
        err = r.stderr.decode()
        self.assertIn("> HEADERS", err)
        self.assertIn("< HEADERS", err)
        self.assertIn("< DATA", err)
        self.assertIn("0000  00", err)           # a hexdump line

    def test_many_paths_all_bodies_printed(self):
        r = self.bcurl(f"localhost:{PORT}/docs/notes.txt", "/docs/notes.txt")
        self.assertEqual(r.stdout.count(b"small text file"), 2)

    def test_send_unknown_still_works(self):
        r = self.bcurl("--send-unknown", f"localhost:{PORT}/index.html")
        self.assertEqual(r.returncode, 0)


def run_bcurl(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "bcurl"), *args],
                          capture_output=True)


class RealWorldTests(Base):
    def test_exact_command_from_the_brief(self):
        # $ ./bcurl -v localhost:9000/index.html   (on our test port)
        r = run_bcurl("-v", f"localhost:{PORT}/index.html")
        self.assertEqual(r.returncode, 0)
        err = r.stderr.decode()
        # preface + request HEADERS + response HEADERS + DATA = 4 things dumped
        dumped = [line for line in err.splitlines() if line[:2] in ("> ", "< ")]
        self.assertEqual(len(dumped), 4)

    def test_many_paths_really_use_one_connection(self):
        r = run_bcurl(f"localhost:{PORT}/index.html", "/docs/notes.txt", "/empty.txt")
        self.assertEqual(r.returncode, 0)
        # The server logs "IP:PORT  GET /path -> status". One TCP connection
        # means all three requests come from the same client port.
        lines = [l for l in self.server_log()
                 if "GET /index.html" in l or "GET /docs/notes.txt" in l
                 or "GET /empty.txt" in l]
        peers = {l.split()[0] for l in lines[-3:]}
        self.assertEqual(len(lines[-3:]), 3)
        self.assertEqual(len(peers), 1, f"expected one connection, saw {peers}")

    def test_request_sent_one_byte_at_a_time(self):
        # TCP may deliver a frame in pieces; the server must still read it whole.
        msg = b"BH/1" + frame(1, 1, 1, get("/docs/notes.txt"))
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        for b in msg:
            s.send(bytes([b]))
            time.sleep(0.002)
        status, body, _ = read_response(s)
        self.assertEqual((status, body), (200, b"A small text file in a subfolder.\n"))

    def test_twenty_clients_at_once(self):
        expected = open(os.path.join(WWW, "big.bin"), "rb").read()
        results = []

        def one_client():
            r = run_bcurl(f"localhost:{PORT}/big.bin")
            results.append(r.returncode == 0 and r.stdout == expected)

        threads = [threading.Thread(target=one_client) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, [True] * 20)


if __name__ == "__main__":
    unittest.main()
