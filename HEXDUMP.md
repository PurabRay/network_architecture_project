# Annotated hexdump: one complete request and response

Captured with:

```
$ ./bserve ./www 9000
$ ./bcurl -v localhost:9000/docs/notes.txt
```

The client sends 66 bytes and the server sends 119. Every byte is accounted for below. Values are hex unless marked otherwise.

## Client → server

### Preface (4 bytes, sent once per connection)

```
42 48 2f 31                                   "BH/1"
```

### Frame 1: HEADERS (the request): 8 header bytes + 54 payload bytes

```
00 36                 Length    = 0x0036 = 54 payload bytes follow
01                    Type      = 0x01   = HEADERS
01                    Flags     = 0x01   = END_STREAM (the whole request is this one frame)
00 00 00 01           R = 0, Stream ID = 1 (the first request on this connection)
--- payload: the header block, 5 fields ---
81                    1000 0001 -> indexed name, table #1 = :method
   00 03              value length = 3
   47 45 54           "GET"
82                    indexed, #2 = :path
   00 0f              value length = 15
   2f 64 6f 63 73 2f 6e 6f 74 65 73 2e 74 78 74    "/docs/notes.txt"
84                    indexed, #4 = host
   00 09              value length = 9
   6c 6f 63 61 6c 68 6f 73 74                      "localhost"
85                    indexed, #5 = user-agent
   00 09              value length = 9
   62 63 75 72 6c 2f 31 2e 30                      "bcurl/1.0"
86                    indexed, #6 = accept
   00 03              value length = 3
   2a 2f 2a           "*/*"
```

Payload check: 6 + 18 + 12 + 12 + 6 = 54 = `0x36`. ✓
Total sent: 4 + 8 + 54 = **66 bytes**.

## Server → client

### Frame 2: HEADERS (the response head): 8 + 69 bytes

```
00 45                 Length    = 0x0045 = 69
01                    Type      = HEADERS
00                    Flags     = none (not END_STREAM: a body follows)
00 00 00 01           Stream ID = 1 (answers request 1)
--- payload ---
83                    indexed, #3 = :status   (always the first field)
   00 03  32 30 30                                 "200"
87                    indexed, #7 = content-type
   00 0a  74 65 78 74 2f 70 6c 61 69 6e            "text/plain"
88                    indexed, #8 = content-length
   00 02  33 34                                    "34"
89                    indexed, #9 = server
   00 0a  62 73 65 72 76 65 2f 31 2e 30            "bserve/1.0"
8a                    indexed, #10 = date
   00 1d  54 75 65 2c 20 32 39 20 53 65 70 20 32 30 32 36
          20 30 36 3a 35 38 3a 32 35 20 47 4d 54   "Tue, 29 Sep 2026 06:58:25 GMT" (29 bytes)
```

Payload check: 6 + 13 + 5 + 13 + 32 = 69 = `0x45`. ✓

### Frame 3: DATA (the body): 8 + 34 bytes

```
00 22                 Length    = 0x0022 = 34
00                    Type      = 0x00 = DATA
01                    Flags     = END_STREAM (last frame of response 1)
00 00 00 01           Stream ID = 1
--- payload: the file's bytes, unchanged ---
41 20 73 6d 61 6c 6c 20 74 65 78 74 20 66 69 6c   "A small text fil"
65 20 69 6e 20 61 20 73 75 62 66 6f 6c 64 65 72   "e in a subfolder"
2e 0a                                             ".\n"
```

34 matches `content-length: 34`. ✓
Total received: 8 + 69 + 8 + 34 = **119 bytes**.

## What to notice

- **No name is spelled out.** All 10 header names cost 1 byte each. As HTTP/1.1 text, `content-length: ` alone is 16 bytes.
- **The client never searches for a delimiter.** It reads 8 bytes, learns the length, and reads exactly that many. HTTP/1.1 has to scan for `\r\n\r\n` instead.
- **After this exchange the connection is still open.** A second request would go out as the same kind of frame with Stream ID 2.
