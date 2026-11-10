# S111 real-repository task: read-only TinyDB handles

Use clean upstream TinyDB (MIT), commit `edff96aeb2616402e9489d46e90a592c05565621`,
archive SHA256 `99f6de856e39a5832a3e82fa75ec68150b4d20fb255dcffe82ede8597d725b6e`.
Do not import a previous experiment's solution or broaden unrelated batch semantics.

Add the public option `TinyDB(..., read_only=True)`. Default `read_only=False` preserves
current behavior. Export `ReadOnlyError` from `tinydb`, subclassing `PermissionError`.
Expose `db.read_only` as a boolean read-only property; no setter or runtime mode toggle.

Allowed production files: `tinydb/database.py`, `tinydb/table.py`, `tinydb/storages.py`,
`tinydb/__init__.py`, optional new `tinydb/errors.py`. New regressions only
`tests/test_readonly_s111.py`. Original tests, other source/config/dependencies and upstream
license remain unchanged. Internal representation, helper names and module placement
inside that scope are not prescribed. Do not add a transaction or concurrency framework.

Public acceptance:

1. Read-only JSON handles open existing data for reading and close normally. Opening a
   missing database in this mode raises FileNotFoundError and creates neither file nor
   missing parent directories, even with create_dirs=True. A conflicting writable
   access_mode must be safely overridden or rejected before changing bytes; never
   truncate/create data. Preserve writable defaults and ordinary storage kwargs.
2. Work with custom storage factories, including `storage=lambda: existing_memory_storage`.
   Consume the new database option at the appropriate boundary, rather than accidentally
   forwarding it as an unknown custom-storage argument or a JSON serialization option.
3. On the default and named tables, reject insert, insert_multiple, update, update_multiple,
   upsert, remove and truncate; also reject database drop_table and drop_tables. Always
   raise ReadOnlyError before consuming a supplied iterator or invoking a condition/update
   callback, including empty/no-match calls. No storage write, byte change, document/ID
   mutation or effect on other tables is permitted on refusal. Creating an absent table
   with persist_empty=True is a write attempt and must be refused before a storage write.
4. All tables obtained through a read-only database remain read-only. Attempting
   db.table(name, read_only=False) may raise ReadOnlyError or return a still-read-only
   handle; it must never provide a writable bypass. Do not weaken the flag after a table
   has been cached. Ordinary writable database table behavior remains compatible.
5. all, get, search, iteration, contains, count, tables, len and context-manager use remain
   functional. Editing returned documents (including nested objects) must not alter stored
   data or subsequent reads, including a repeated cached search. Query callback input must
   be detached from storage: its mutation may affect that invocation's transient result,
   but cannot alter storage or unrelated subsequent reads. Query cache behavior may differ
   internally in this mode; writable default caching is unchanged.
6. This is a logical guarantee through TinyDB/Table APIs. Direct access to a caller-owned
   raw Storage, closures that deliberately mutate external state, file permissions,
   operating-system isolation, arbitrary failing I/O rollback, concurrent writers and
   protection from another handle are outside this task. A custom table implementation
   that overrides mutation methods is outside the guarantee; keep original customization
   tests working for writable databases.

Read AGENTS.md and this contract, inspect original implementation/tests, plan and implement,
then run meaningful new regressions and the full unchanged original suite:
`/home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o addopts= tests -q`.
The override only disables unavailable coverage-plugin flags. Confirm imports bind to this
workspace. Ruff/mypy/coverage plugins are unavailable in that Linux venv; do not install or
claim them. No network, Git, subagents, credentials, reference solutions, parent/other-experiment
scans, executing-runtime or installed-package implementation introspection, or hidden checks.
Normal Python/pytest use is allowed. Work only in the target; finish when verified.

The controller will request one ordinary pause after a source edit and resume the same
persisted session in a fresh process. Keep partial work durable and follow the same goal;
no new task, implementation hint or scope change is implied by that control action.
