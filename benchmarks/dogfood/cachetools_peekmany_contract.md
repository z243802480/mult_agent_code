# S117 public follow-up: non-touching batch inspection

This workspace contains the accepted S116 peek/peekitems implementation on cachetools
v6.2.1 (MIT), upstream commit ca7508fd56103a1b6d6f17c8e93e36c60b44ca25.
Continue that session with a useful batch lookup API. Preserve the entire S116 public
contract in TASK_CONTRACT.md and all existing behavior; this is an additional requirement.

## Behavior

Add `cache.peekmany(keys)` and `cache.peekmany(keys, default)` to Cache, FIFOCache,
LFUCache, LRUCache, RRCache, TTLCache and TLRUCache:

1. Return a fresh list of values in input order, including repeated keys. Each hit is the
   exact stored object; explicit None values work. Missing or expired keys use the exact
   supplied default, including None. Without a default raise KeyError(first_missing_key).
   Stop consuming keys at the first missing key in that case; do not consume later keys.
2. Accept any finite iterable, including a one-shot iterator. Consume it once. Empty input
   returns a new empty list. Iterator errors and unhashable-key TypeError propagate even
   when a default is supplied. Never swallow arbitrary exceptions as a cache miss.
3. The list is detached, values are shared references. Later cache membership changes or
   caller edits to the result list cannot alter membership in the other container.
4. Like peek, batch inspection must not count as access or mutate cache storage/size,
   access frequency/recency/order, trigger eviction/random choice/getsizeof/TTU callbacks,
   call custom __getitem__/__missing__, or purge expired storage. Ordinary mapping APIs
   and all prior peek/peekitems guarantees remain unchanged.
5. TTLCache/TLRUCache sample the underlying timer at most once per whole batch. All keys
   are evaluated at that same instant, strictly before expiry (equality means expired).
   Support existing numeric and datetime/timedelta configurations. Expired items inspected
   in a batch must still be reported by a later explicit expire(time). This applies to
   successful batches and to a batch that raises KeyError. Empty batches need no timer.
6. Arbitrary user callbacks that mutate the cache/time externally, concurrent writers,
   serialization and new dependencies/storage redesign are outside this task.

## Scope and checks

Edit only src/cachetools/__init__.py, optional src/cachetools/_inspection.py,
docs/index.rst and a NEW tests/test_peekmany_s117.py. Preserve all existing tests, including
tests/test_peek_s116.py; preserve config, other source, LICENSE, AGENTS.md and both public
contracts. Document the signature, ordering/defaults/iterator/time/no-side-effect behavior.

Run the existing interpreter and all old/new tests:
`/home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o pythonpath=src tests -q`.
This is a src-layout repo. For direct import binding, insert local src into sys.path before
importing cachetools; print __file__ and verify it belongs to this workspace's src/cachetools.
Sphinx/Ruff/mypy/coverage are unavailable here; do not install or claim those checks.

Choose normal permitted file/search/shell navigation. No mandated read_file strategy,
artificial delay, repeated unchanged verification or controller hints. Keep work durable,
finish when verified, report checks honestly. Work only in this target; no network/Git/
subagents/installs/credentials, parent/sibling or other-experiment scans, reference solutions,
hidden checks/controllers, executing-runtime or installed-package source introspection.
Normal Python/pytest invocation and the declared import-binding check are allowed.
