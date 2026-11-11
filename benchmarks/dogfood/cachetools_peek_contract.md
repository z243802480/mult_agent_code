# S116 public task: cache inspection without access side effects

Use unmodified cachetools v6.2.1 (MIT), commit
`ca7508fd56103a1b6d6f17c8e93e36c60b44ca25`; archive SHA256
`74a81ab41704515b4c33c87f01e5db3ad024ac24653a0472715b6745567aca33`.

Add two public inspection methods to the standard cache family: Cache, FIFOCache,
LFUCache, LRUCache, RRCache, TTLCache and TLRUCache. Existing APIs keep their behavior.

## Public behavior

1. `cache.peek(key)` returns the currently available stored value, by identity. A missing
   or expired key raises `KeyError(key)`. `cache.peek(key, default)` returns that exact
   default object instead. Explicit None defaults and stored None values work normally;
   a supplied default does not hide an unhashable-key TypeError.
2. Inspection does not count as access: it cannot change access frequency, recency,
   insertion order, size or contents, trigger eviction/random-choice/size callbacks, or
   invoke an overridden cache `__getitem__` or `__missing__` hook. In particular a missing
   inspection cannot populate a cache through `__missing__`. Ordinary get/item access,
   decorators, eviction and custom sizing remain compatible.
3. `cache.peekitems()` returns a fresh list of key/value pairs for the currently available
   items, each exactly once. Pair containers may be tuples or lists; no ordering beyond
   the existing public cache contract is prescribed. The list/pair membership is a
   snapshot: later insertion, deletion or caller edits to that list do not change the
   other container. Values retain normal cache reference identity; deep-copying values
   is neither required nor desired. It has the same no-access-side-effects guarantee.
4. For TTLCache/TLRUCache, an item is available only strictly before its expiry boundary;
   equality is expired. Each inspection uses at most one underlying timer sample, giving
   peekitems one consistent time instant rather than expiring entries during iteration.
   Existing valid numeric or datetime/timedelta timer configurations must work.
5. These inspections do not eagerly remove expired entries or run the TLRU time-to-use
   callback. After inspecting expired items, a subsequent explicit `expire(time)` must
   still report those expired key/value pairs. Returned live items keep their references.
   Do not turn the existing normal mapping methods into non-mutating inspections.
6. Preserve original cache customization and writable behavior. Arbitrary caller callbacks
   that themselves mutate external state, thread safety/concurrent writers, serialization
   compatibility across versions and new decorators/transactions are outside this task.
   Do not add a new dependency or redesign cache storage/eviction internals.

## Allowed changes and verification

Production edits only `src/cachetools/__init__.py`, optional new
`src/cachetools/_inspection.py`; update `docs/index.rst` to document the new methods and
their time/side-effect semantics. Add meaningful regressions only in
`tests/test_peek_s116.py`. Preserve every original test, other source/config and LICENSE.
Equivalent internal representations are allowed; no private attribute layout is required.

This is a src-layout repository. Use the existing interpreter:
`/home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o pythonpath=src tests -q`.
Run all original tests and new regressions. For a direct import/source-binding check,
insert this workspace's `src` into sys.path before importing cachetools and print its
`__file__`; it must resolve inside this workspace's src/cachetools. Do not read or inspect
an installed copy's implementation. Sphinx/Ruff/mypy/coverage are unavailable in that
Linux venv; do not install dependencies, alter configuration or claim those checks ran.

Read AGENTS.md and this complete contract, inspect the original implementation/tests,
choose your plan, implement and verify. All normal permitted file/search/shell tools are
available; there is no required navigation strategy. No artificial wait or repeated
unchanged verification. No controller hints or planned pause will be supplied.

Work only in this target. No network/Git/subagents/installs/credentials, parent/sibling or
other-experiment scans, reference solutions, executing-runtime implementation or installed
package source introspection, hidden oracle or control-script access. Normal Python/pytest
invocation and the declared import-binding check are allowed. Keep partial work durable,
finish when verified, and report actual checks and remaining limits honestly.
