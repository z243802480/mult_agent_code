# BoardKit: finish a persistent local task board

The existing skeleton must become a dependency-free local task board. This is one complete
product goal, not a request to keep a process alive for a minimum duration. Implement only
boardkit/*.py. Preserve public signatures and all tests/requirements. Run
`python -m pytest tests -q`; do not install packages or use external services.

## Storage contract

`Store(path)` persists to a local SQLite file. Each item has positive integer id, normalized
title, status, tags, positive integer version, UTC ISO created_at/updated_at strings, and a
comments list. Every returned item is an independent snapshot, not shared mutable state.

- Titles trim surrounding whitespace and contain 1–120 characters. Status is open, doing or
  done. Tags are a list of strings: trim, lowercase, deduplicate, sort; at most 8 normalized
  tags, each 1–24 characters. Invalid data raises ValueError before any mutation.
- create(title, tags=None, idempotency_key=None) starts open/version 1. A nonempty key gives
  idempotent creation: repeat with the same normalized title/tags returns the existing item
  unchanged; a different payload for that key raises ConflictError.
- get(id) returns the item; missing ids raise NotFoundError.
- list(status=None, tag=None, query=None, limit=20, offset=0) returns items and total, sorted
  by ascending id. Filters combine, title search is case-insensitive for ASCII, tag matching
  is normalized. total is before pagination. limit is an integer 1–100, offset is an integer
  >=0, booleans are not valid integers. Invalid filters raise ValueError.
- update(id, expected_version, title=None, status=None, tags=None) and delete(id,
  expected_version) use optimistic concurrency. Missing ids raise NotFoundError; stale
  versions raise ConflictError without mutation. Update increments version once, preserves
  created_at and comments. None fields are left unchanged. No-op updates still increment.
- add_comment(id, text, expected_version) trims 1–1000 characters, appends a comment with
  text and created_at, increments the item version once, and returns the updated item.
  Invalid/stale operations do not partly mutate state.
- Separate Store instances/processes using the same DB see committed data. Concurrent
  creates lose no items; competing updates with one expected_version permit exactly one.

## Interchange

export_snapshot() returns {schema_version: 1, items: [...]} in id order, including comments,
versions and timestamps. import_snapshot(snapshot) atomically replaces item contents after
validating the entire snapshot: exact schema version, unique positive ids, valid fields,
positive versions and comment structure. Malformed imports leave all prior state unchanged.
Import/export into a new DB round-trips item data and later creates use nonconflicting ids.
`to_csv(items)` returns CSV with exactly id,title,status,tags,version columns. Tags join with
semicolons; normal CSV quoting applies; empty exports still include the header.

## HTTP contract

make_server(store, host='127.0.0.1', port=0) returns a standard HTTPServer-compatible object
without starting its loop. All responses use JSON except successful DELETE (204, empty).

- POST /tasks: title, optional tags; Idempotency-Key header as above. Returns 201 and item.
- GET /tasks: status/tag/q/limit/offset query filters, returns {items,total}.
- GET /tasks/ID: returns item. PATCH /tasks/ID: expected_version plus changed fields.
- DELETE /tasks/ID: JSON {expected_version}; returns 204.
- POST /tasks/ID/comments: text and expected_version; returns 201 and updated item.
- Validation/malformed JSON/invalid UTF-8: 400; nonexistent id or route: 404; stale version
  or idempotency conflict: 409. Error JSON is {error:{code,message}}, code is validation,
  not_found or conflict, and message is useful. Unexpected errors must not expose tracebacks.
- Invalid/oversize request bodies (>65536 bytes) are rejected with 400 before mutation.

## CLI contract

`python -m boardkit --db PATH COMMAND`: add TITLE [--tag TAG] (repeatable), list with
--status/--tag/--query/--limit/--offset, show ID, set ID --version N [--title TITLE]
[--status STATUS] [--tag TAG], delete ID --version N, comment ID --version N TEXT,
export --format json|csv (default json), import FILE, serve --port N (localhost only).
JSON commands print one JSON value; import prints {imported:N}. Successful delete prints
{deleted:ID}. User errors exit 2 and produce useful stderr without a traceback. Storage and
HTTP behavior must agree. No UI, auth, dependencies or remote deployment are requested.
