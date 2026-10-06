# Network Architecture Project: BH/1, HTTP in binary

> **Calculator assignment ("Build a calculator that stays on the line"):** see the separate repo:
> **LINK:** https://github.com/PurabRay/network_architecture_calculator

Network Architecture course project. HTTP requests and responses travel as binary frames: a fixed 8-byte frame header, a 10-name header table, and a rule that unknown frame types are skipped.

| What you hand in | Where |
|---|---|
| 1. The spec (two pages) | [`SPEC.md`](SPEC.md), also as [`SPEC.pdf`](SPEC.pdf) |
| 2. The program | [`bserve`](bserve) (server) and [`bcurl`](bcurl) (client) |
| 3. Annotated hexdump of one request and response | [`HEXDUMP.md`](HEXDUMP.md) |

Both programs are plain Python 3.8+ and use only the standard library, so there is nothing to install. They share **no code**. Each one implements the spec on its own, so if they work together, the spec is enough.

## Run it

```bash
# terminal 1: the server
./bserve ./www 9000

# terminal 2: the client
./bcurl localhost:9000/index.html                     # body to stdout
./bcurl -v localhost:9000/index.html                  # + hexdump of every frame (stderr)
./bcurl localhost:9000/index.html /docs/notes.txt     # two requests, one connection
./bcurl localhost:9000/missing.html; echo $?          # 404 -> exit status 1
./bcurl --send-unknown localhost:9000/                # sends an unknown frame type first;
                                                      # the server logs that it skipped it
```

On Windows, use `python` in place of `./`: `python bserve ./www 9000`, `python bcurl -v localhost:9000/index.html`.

If `./bserve` says `permission denied`, run `chmod +x bserve bcurl` once, or start them with Python: `python3 bserve ./www 9000`.

`bcurl` exit status: `0` all responses OK, `1` some response was 4xx/5xx, `2` usage or network error.

## Test it

```bash
python3 -m unittest -v tests/test_bh1.py
```

On Windows: `python -m unittest -v tests/test_bh1.py`.

There are 28 tests, in three groups:

- **Server tests** build bytes by hand straight from the spec, not with `bcurl`. They cover 200, 404, 405, path escape (`/../`), a 200 KB file split across many frames, an empty file, one connection used for several requests, skipping unknown frame types, every kind of 400 (with the connection still open afterwards), and a bad preface (400, then close).
- **Client tests** cover `bcurl`'s stdout, exit codes (0, 1, 2) and `-v`.
- **Real-world tests** run the exact command from the brief, check from the server's log that several paths really share one TCP connection, send a request one byte at a time, and run 20 clients at once downloading the 200 KB file.

## Files

```
bserve             server  (~250 lines)
bcurl              client  (~200 lines)
SPEC.md / .pdf     the protocol
HEXDUMP.md         one request and response, byte by byte
www/               sample site to serve
tests/test_bh1.py  tests
```
