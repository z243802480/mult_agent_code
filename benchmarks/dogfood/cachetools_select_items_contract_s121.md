# Public contract: non-touching item selection

Starting source is the accepted S116 cachetools artifact, including public `peek` and
`peekitems`. Add `Cache.select_items(predicate)`, inherited or specialized as appropriate
for Cache, FIFOCache, LFUCache, LRUCache, RRCache, TTLCache and TLRUCache.

At call time take the live `(key, value)` snapshot represented by public `peekitems()`.
In that snapshot's order, call `predicate(key, value)` exactly once for every entry.
Return a new list of matching pairs using normal Python truth testing of the result.
The returned values retain their original identity (no deep copy). Each result list is
independent. Empty caches give an empty list and no predicate calls. Exceptions from the
predicate propagate unchanged and traversal stops at the failing callback.

If a callback changes the cache, selection must still traverse the original snapshot's
entries and object references; newly inserted entries are excluded. User callback effects
are allowed; the API itself must not call `__getitem__`, count accesses, change eviction
policy, delete entries, or purge expired storage. Expired TTL/TLRU entries are excluded
from callbacks and results without being removed. Preserve existing peek/peekitems and
all original behavior. Public behavior is judged without assuming private cache layout.

Required changed/new deliverables:

- `src/cachetools/__init__.py`: implement the public API.
- `docs/index.rst`: document/link the API and new guide.
- `docs/筛选（只读）.rst`: a new user guide with semantics and a runnable example.
- NEW `tests/test_select_items_s121.py`: meaningful regressions.

Allowed but NOT required: `src/cachetools/keys.py` may be edited if necessary.
Optional implementation choice: NEW `src/cachetools/_selection.py` only if the selected
design actually needs a helper. Do not create a placeholder just to satisfy metadata.
These permission/conditional entries are not mandatory deliverables. Descriptions in
parentheses or natural language are not suffixes to add to paths. Genuine punctuation
in the required Chinese guide path above is part of the exact name and must be kept.

Do not change any other file, original test, config, LICENSE, AGENTS.md, TASK_CONTRACT.md,
or this contract. The prior task's edit set is historical; this contract defines the
current task. Do not use Git, network, credentials, other experiments, reference solutions,
executing-runtime source, installed cachetools implementation, or scan outside this workspace.
Do not install tools or add artificial pauses/delays. Navigate with ordinary permitted tools.
Run the existing pytest suite plus the new tests; unavailable Sphinx/Ruff/mypy are not
required and must not be claimed. Report actual results and print `cachetools.__file__`
to prove imports bind to this workspace's `src/cachetools`.
