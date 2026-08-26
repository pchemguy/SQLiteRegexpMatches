# SQLite `regexpmatches`

`regexpmatches.c` is an amalgamation-only companion to SQLite's stock [`ext/misc/regexp.c`](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c). It adds `regexp_matches()` and `regexpi_matches()`, which return successive non-overlapping complete matches as a JSON array. The module leaves
`regexp.c` unchanged and reuses SQLite's private regexp compiler, NFA representation, UTF-8 routines, limits, allocators, auxiliary-data cache mechanism, and JSON builder. It is intentionally not a separately compiled or loadable extension.

## SQL interface

```sql
regexp_matches(pattern, input)
regexpi_matches(pattern, input)
```

Both functions return JSON text with SQLite's JSON subtype. `regexpi_matches()` follows stock `regexpi()` and performs ASCII-only case-insensitive matching.

```sql
SELECT regexp_matches('[0-9]+', 'A12 B345');
-- ["12","345"]

SELECT regexpi_matches('ab+', 'ABb ab');
-- ["ABb","ab"]

SELECT regexp_matches('xyz', 'abc');
-- []

SELECT regexp_matches('x', NULL);
-- NULL
```

The pattern is the first argument, matching the direct-call convention of SQLite's existing `regexp(pattern, input)` and `regexpi(pattern, input)` functions.

## Match semantics

Matches are selected using:

- leftmost-first search;
- ordered alternation;
- greedy, non-possessive quantifiers;
- successive non-overlapping global iteration;
- no recursive backtracking or combinatorial path enumeration.

Ordered alternatives are significant:

```sql
SELECT regexp_matches('a|aa', 'aa');
-- ["a","a"]

SELECT regexp_matches('aa|a', 'aa');
-- ["aa"]
```

Greedy repetition still permits the remaining pattern to match:

```sql
SELECT regexp_matches('a+', 'aaa');
-- ["aaa"]

SELECT regexp_matches('.*a', 'a 1 a 2');
-- ["a 1 a"]
```

This behavior is implemented by a prioritized Thompson/Pike VM over the NFA compiled by stock `regexp.c`. Earlier alternatives outrank later alternatives; continuing a greedy quantifier outranks exiting it; and a lower-priority acceptance remains available while a higher-priority path is still viable.

Zero-length matches are returned. After one is selected, iteration advances by one complete UTF-8 code point so matching cannot loop indefinitely. An empty match at the exact end of the preceding non-empty match is suppressed.

Parentheses retain the stock engine's non-capturing behavior. Returned array members are complete matched substrings, not capture groups.

## Integration

`regexpmatches.c` depends deliberately on private static definitions from SQLite's regexp and JSON implementations. All components must therefore be part of one C translation unit in this order:

```text
SQLite amalgamation, including JSON
stock ext/misc/regexp.c
src/regexpmatches.c
```

On Windows, a custom build can be obtained using the [sqlite_MSVC_Cpp_Build_Tools.ext.bat](sqlite_MSVC_Cpp_Build_Tools.ext.bat) script (see this [note](https://github.com/pchemguy/Field-Notes/tree/main/11-sqlite-msvc-build) for details).

The match-array initializer is translation-unit private and registers only `regexp_matches()` and `regexpi_matches()`. The stock initializer continues to own `regexp()`, `regexpi()`, and the `REGEXP` operator.

## Supported pattern language

The module accepts exactly the language compiled by the included stock `regexp.c`, including:

- `*`, `+`, `?`, and `{m,n}` repetition;
- grouping and alternation;
- `^` and `$` anchors;
- `.`, bracket character classes, and negated classes;
- `\b`, `\w`, `\W`, `\d`, `\D`, `\s`, and `\S`;
- the escapes supported by the stock compiler.

It does not add capture extraction, replacement, splitting, overlap mode, flags argument, lazy or possessive quantifiers, lookaround, backreferences, named groups, Unicode case folding, or PCRE syntax.

## Complexity

The span executor is a prioritized Pike VM. At each input boundary, the first thread reaching a compiled program counter wins and duplicate threads are discarded. One span search is bounded by `O(P × I)` time and `O(P)` active-state memory, where `P` is the compiled NFA size and `I` is the examined input length.

Global extraction restarts at the end of each selected match. A higher-priority path may inspect text beyond the fallback match ultimately returned, so the aggregate worst case for `K` results is `O(K × P × I)`. The implementation does not claim whole-call linearity.

## Testing

Tests exercise only the public SQL surface through Python's standard `sqlite3` module under `pytest`. They do not substitute Python regexp or JSON implementations and do not expose test-only C helpers. 

```batch
pytest -vv
```

The suite covers registration, stock-function regressions, ordered alternation, greedy fallback, non-overlap, zero-length progress, anchors, boundaries, UTF-8 slicing, JSON escaping and subtype propagation, errors, connection limits, and adversarial ambiguity.

The current implementation passes 163 SQL-surface tests under normal, AddressSanitizer, and UndefinedBehaviorSanitizer builds. Public-SQL execution covers 92.01% of executable lines and reaches every branch site in `regexp_matches.c`; the remaining lines are defensive allocation-failure and generation-wrap paths that Python's public SQLite API cannot inject
deterministically.

## Repository layout

```text
src/regexpmatches.c                   amalgamation-only production module
regexpmatches/tests/                  structured public-SQL pytest suite
SPECIFICATION.md                      normative implementation specification
sqlite_MSVC_Cpp_Build_Tools.ext.bat   Windows/MSVC build script
```

The detailed semantic, architectural, security, and acceptance requirements are defined in
[SPECIFICATION.md](SPECIFICATION.md).
