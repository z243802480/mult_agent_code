# Public contract: non-touching partition

Add `Cache.partition_items(predicate)`, supported by Cache, FIFOCache, LFUCache,
LRUCache, RRCache, TTLCache and TLRUCache. Starting source is the accepted S116
peek/peekitems artifact, not the unaccepted S121 workspace.

Take one live item snapshot as represented by public peekitems(). Visit each
(key, value) exactly once in that snapshot's order, calling predicate(key, value).
Return a tuple `(matched, rejected)` of two distinct new lists. Truthy results go
to matched, falsey results go to rejected; each list preserves snapshot order.
Values retain their original identity. Empty input gives two distinct empty lists.
Results from separate calls are independent. Propagate callback exceptions unchanged,
stopping traversal. If callbacks change the cache, keep traversing original snapshot
entries/object references and exclude new entries. Callback effects are allowed.

The API itself must not call __getitem__, count accesses, affect eviction policy,
delete entries or purge expired storage. Exclude expired TTL/TLRU items without
removing them. Preserve all existing behavior. Private implementation layouts are
not prescribed.

Required deliverables: modify src/cachetools/__init__.py and docs/index.rst;
create docs/分组（只读）.rst and tests/test_partition_items_s122.py. Both docs must
describe the semantics and include an example. Add meaningful regression tests.
Allowed but not required: edit src/cachetools/keys.py if necessary. Optional:
create src/cachetools/_partition.py only if the chosen design needs it. These two
entries are permissions/choices, not mandatory outputs. Keep literal names exact,
including the genuine punctuation in the Chinese guide name; do not append conditions.

All other source/tests/config/LICENSE/AGENTS.md/TASK_CONTRACT.md and this contract
are immutable. The older task's edit set is historical; this contract is current.
Read necessary project context with ordinary permitted tools. Do not install tools,
use network/Git/subagents/credentials, scan outside this workspace or other experiments,
read reference answers, or introspect the executing runtime/installed package code.

The project uses src layout and is not installed. Declare source imports explicitly.
Run this verified command:

    /home/administrator/.cache/asteria-s101/venv/bin/python -m pytest -o pythonpath=src -o addopts= tests -q

Print and verify source binding with this verified command:

    /home/administrator/.cache/asteria-s101/venv/bin/python -c "import sys,pathlib; sys.path.insert(0,'src'); import cachetools; print(cachetools.__file__); assert pathlib.Path(cachetools.__file__).resolve().is_relative_to(pathlib.Path.cwd()/'src/cachetools')"

Do not rely on an inherited project PYTHONPATH. Sphinx/Ruff/mypy are absent, not required;
do not install or claim them. No artificial pauses/time padding; finish when verified.
