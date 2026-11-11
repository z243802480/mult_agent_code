# S118 new public follow-up: stable inspection snapshots

This is the accepted S116 peek/peekitems implementation on cachetools v6.2.1,
MIT, commit ca7508fd56103a1b6d6f17c8e93e36c60b44ca25. Preserve TASK_CONTRACT.md.
Add `cache.snapshot(deep=False)` to Cache, FIFOCache, LFUCache, LRUCache, RRCache,
TTLCache and TLRUCache for diagnostic consumers needing stable read-only membership.
This is a new requested API, not an upstream feature claim or the S117 batch lookup task.

## Public behavior

1. Return a fresh `collections.abc.Mapping` with every currently available key/value
   exactly once. No ordering or private representation is required. The mapping cannot
   be used to insert/delete/replace members. Item assignment/deletion must raise TypeError;
   dictionary-specific mutation methods may be absent or refuse without changing members.
2. Membership is detached from the live cache and other snapshots: later cache insertion,
   deletion, eviction or expiry does not change an earlier snapshot's members or values.
   Without deep=True, normal object references are shared: stored mutable values remain
   the exact same objects, and mutating such a value is visible through other references.
3. deep=True deep-copies the values. Nested mutation of the result cannot change cache
   values, and later nested cache mutation cannot change the snapshot. Preserve shared
   references and cycles WITHIN the copied value graph (including between different
   cached values). Keys are always retained by identity, never deep-copied. Assume values
   support normal deepcopy; its exceptions must propagate without changing the cache.
4. Snapshot construction is inspection: no access frequency/recency/insertion-order or
   storage/size changes, no eviction/random-choice/getsizeof/TTU callbacks, overridden
   __getitem__/__missing__ hooks or eager expired-entry purge. Existing ordinary mapping
   APIs and peek/peekitems retain their behavior. Never leak expired values in a snapshot.
5. TTLCache/TLRUCache use at most one underlying timer sample for the entire snapshot,
   with one consistent instant, strictly before expiry; equality is expired. Numeric and
   datetime/timedelta timers work. A later public expire(time) still reports expired items
   inspected during snapshot creation. Old snapshots remain stable after future expiry.
6. Concurrent writers, callbacks deliberately mutating external state, serialization,
   arbitrary custom cache subclasses and dependencies/storage redesign are out of scope.

## Scope, verification and boundary

Edit only src/cachetools/__init__.py, optional new src/cachetools/_snapshot.py,
docs/index.rst and NEW tests/test_snapshot_s118.py. Preserve all existing tests including
tests/test_peek_s116.py, every other source/config/LICENSE, AGENTS.md and both contracts.
Document the signature, read-only membership versus referenced/deep-copied values, shared
graph/key semantics and timed/no-access-side-effect behavior.

The earlier AGENTS edit list described the old task; this contract supplies the additional
edit set above. Choose normal permitted file/search/shell navigation, no mandated strategy,
controller hints, artificial pause, delay or repeated unchanged checks. Finish when verified.

Run all original and new tests:
`/home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o pythonpath=src tests -q`.
For direct source binding insert local src into sys.path first, print cachetools.__file__
and verify it lies inside this workspace's src/cachetools. Sphinx/Ruff/mypy/coverage are
unavailable here; do not install or claim them. Work only here: no network/Git/subagents/
credentials, parent/sibling or other-experiment scans, reference solutions, hidden checks/
controllers, executing-runtime or installed-package implementation introspection. Normal
declared Python/pytest and source-binding checks are allowed. Report actual checks honestly.
