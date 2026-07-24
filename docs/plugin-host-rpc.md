# Plugin Host RPC

RPC is JSON-RPC 2.0 over 4-byte unsigned big-endian length-prefixed UTF-8 JSON frames over stdin/stdout. Stdout is protocol-only. Pickle, marshal, object YAML, MessagePack, batch requests, arbitrary method invocation, and oversized frames are rejected.
