# S118 public follow-up: detached database snapshots

This is the accepted S113 read-only TinyDB implementation on upstream MIT commit
edff96aeb2616402e9489d46e90a592c05565621. Preserve its full TASK_CONTRACT.md behavior.
Add a database-level `TinyDB.snapshot(table_names=None)` API for inspection/export.
This is a new requested API, not a claim about upstream TinyDB.

## Public behavior

1. With no selection, return a fresh dict mapping every stored table name to a fresh list
   of `tinydb.table.Document` objects. Their public doc_id integers and document contents
   match stored data. Include persisted empty tables; exclude handles that have never been
   persisted. A storage read returning None means an empty database. No table/document
   ordering is prescribed. Document subclasses are allowed.
2. table_names=None selects all; a string selects that one table; any finite iterable of
   names is consumed once and selects those tables. Repeated names appear once. An empty
   iterable returns {}. A requested name absent from stored data raises KeyError(name),
   including a handle that exists only in memory. Iterator exceptions must propagate.
3. One snapshot observes exactly one underlying storage.read call, including an empty
   selection. Do not call storage.write, create/drop tables, instantiate Table handles,
   run query callbacks or populate query caches. Work with normal JSON storage and custom
   factories such as storage=lambda: existing_memory_storage. Never assume a wrapper
   exposes custom instrumentation attributes. A storage.read exception propagates.
4. The returned dict, lists, Documents and nested mutable document values are detached
   from storage and future snapshots. Editing a returned doc, its doc_id, nested values,
   table membership or lists must not alter storage or later reads. Later normal writes
   cannot retroactively change an old snapshot. Deep-copy compatible values are assumed.
5. Both writable and read_only=True handles support snapshots. Keep db.read_only and
   existing mutation/refusal semantics. JSON file bytes must not change on inspection;
   taking a snapshot cannot close the handle or make a writable handle read-only.
6. Preserve all existing APIs/tests/config/license. Concurrent writers, transaction
   guarantees across handles, arbitrary failing I/O rollback, custom document ID classes,
   custom Document constructors, and callbacks deliberately mutating external state are
   out of scope. Do not introduce dependencies or redesign storage.

## Scope, checks and experiment boundaries

Edit only tinydb/database.py, tinydb/table.py, tinydb/__init__.py, optional new
tinydb/_snapshot.py, docs/usage.rst, docs/api.rst and NEW tests/test_snapshot_s118.py.
Update both documentation files for the signature, selection, isolation, single-read and
read-only semantics. Preserve every existing test including tests/test_readonly_s111.py,
all other source/config, LICENSE, AGENTS.md and both public contracts.

Run all existing and new tests with the available interpreter:
`/home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o addopts= tests -q`.
The override only disables unavailable coverage-plugin flags. Confirm tinydb.__file__ binds
this workspace before interpreting results. Sphinx/Ruff/mypy/coverage plugins are unavailable
here; do not install or claim them. Choose normal permitted file/search/shell tools; no special
navigation strategy, controller hints or planned pauses. Keep work durable, finish when verified.

The old AGENTS/TASK contract edit list described the earlier task; this follow-up contract
supplies the additional edit list above. The earlier pause/resume experiment has ended; no
new artificial pause is planned. No network/Git/subagents/installs/credentials, parent/sibling
or other-experiment scans, reference solutions, hidden checks/controllers, executing-runtime
or installed-package implementation introspection. Normal Python/pytest and source-binding
checks are allowed. Work only in this target and report actual checks honestly.
