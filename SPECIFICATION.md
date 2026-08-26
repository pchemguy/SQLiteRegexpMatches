# SQLite `regexp_matches` Extension Specification

## 1. Status and normative language

This document specifies an amalgamation-only companion module for SQLite's stock `ext/misc/regexp.c`. The companion adds two scalar SQL functions returning all successive non-overlapping regular-expression matches as a JSON array of strings:

```sql
regexp_matches(pattern, input)  -> JSON text
regexpi_matches(pattern, input) -> JSON text
```

The implementation target is a customized SQLite amalgamation that textually includes stock `regexp.c`, then `regexp_matches.c`, after SQLite's stock modules (including JSON) have been included. A separately loadable extension and a public match-extraction C API are explicitly outside scope.

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** express implementation requirements.

The implementation MUST be based on the exact SQLite source checkpoint selected by the project. The coding agent MUST inspect that checkpoint rather than assume that names, structures, private JSON helpers, or amalgamation order match another SQLite release.

## 2. Purpose

SQLite's `ext/misc/regexp.c` compiles a regular expression to a compact nondeterministic finite automaton and exposes boolean SQL matching through `regexp()` and `regexpi()`. Boolean matching can stop when any accepting path is found; it does not need to identify which regex path wins or where the complete match ends.

The new functions require complete match spans while preserving the intended behavior of ordered alternatives and repetition qualifiers. The companion module shall obtain that behavior by executing SQLite's existing compiled automaton through an additional span-producing VM, not by modifying `regexp.c`, introducing another regex library, or using a recursive backtracking matcher.

The design priorities, in order, are:

1. preserve existing `regexp()` and `regexpi()` behavior;
2. guarantee non-backtracking execution with no combinatorial enumeration of regex paths;
3. reuse SQLite's compiler, VM representation, UTF-8 decoder, limits, allocation, auxiliary-data cache, JSON serializer, and error conventions;
4. keep new C code small, private, cohesive, and directly exercisable through SQL;
5. provide deterministic and precisely documented match selection;
6. make upgrades to later SQLite checkpoints straightforward to review.

## 3. Scope

The implementation shall:

- leave stock `ext/misc/regexp.c` unchanged;
- implement `regexp_matches()` and `regexpi_matches()` solely in `regexp_matches.c`;
- return complete matched substrings, not capture groups;
- return all successive non-overlapping matches in source order;
- use the same pattern language as the existing SQLite regexp extension;
- implement leftmost-first search, ordered alternation, and greedy non-possessive repetition;
- execute using a prioritized Thompson/Pike NFA simulation;
- build JSON through SQLite's private JSON implementation;
- cache compiled patterns using SQLite auxiliary data;
- register the new functions from a distinct translation-unit-private initializer;
- remain internal to the amalgamation except for the SQL interface and the pre-existing stock regexp initializer.

The implementation shall not:

- add capture-group extraction;
- add replacement, splitting, position, limit, flags, or overlap arguments;
- add lazy or possessive quantifiers;
- add lookaround, backreferences, named groups, Unicode case folding, or PCRE syntax;
- import PCRE, RE2, Oniguruma, or another regex or JSON library;
- serialize JSON manually when the required SQLite JSON helpers are available;
- expose new non-static C symbols or public C declarations;
- support compilation as an ordinary loadable extension;
- copy SQLite implementation source into project documentation or tests.

## 4. Authoritative baseline and dependencies

### 4.1 SQLite regexp implementation

The authoritative regex baseline is the target checkpoint's `ext/misc/regexp.c`. The implementation MUST reuse its:

- pattern parser and compiler;
- `ReCompiled` bytecode representation;
- opcode set and quantifier expansion;
- character-class implementation;
- UTF-8 decoding routines;
- ASCII-only case-insensitive decoder;
- NFA-size and pattern-length protection;
- memory allocator usage;
- SQLite auxiliary-data caching APIs and ownership conventions;
- compiler and matcher internals already visible in the amalgamation translation unit.

SQLite describes this matcher as an NFA whose boolean matching complexity is bounded by the product of compiled-pattern size and input size. That security property is fundamental and MUST be preserved. See [SQLite `ext/misc/regexp.c`](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c).

### 4.2 SQLite JSON implementation

The target amalgamation MUST include SQLite JSON support. The new functions MUST reuse the target checkpoint's private JSON string-building facilities, including the facilities equivalent to:

- JSON string-builder initialization;
- appending structural punctuation;
- appending a correctly quoted and escaped string slice;
- returning JSON text through a SQLite function context;
- assigning SQLite's JSON subtype.

The current names may include `JsonString`, `jsonStringInit()`, `jsonAppendChar()`, `jsonAppendSeparator()`, `jsonAppendString()`, `jsonReturnString()`, and `JSON_SUBTYPE`, but the implementation MUST verify them against the SQLite sources used to build the amalgamation. See [SQLite `src/json.c`](https://github.com/sqlite/sqlite/blob/master/src/json.c).

Building with `SQLITE_OMIT_JSON` is unsupported. The amalgamation composition order MUST make the stock regexp and private JSON declarations and definitions visible to `regexp_matches.c` in the same C translation unit.

### 4.3 Auto-extension integration

The stock regexp initializer and the private match-array initializer shall both be registered with SQLite's auto-extension mechanism. SQLite invokes registered auto-extension entry points for each newly opened database connection. See [`sqlite3_auto_extension()`](https://sqlite.org/c3ref/auto_extension.html).

The project build integration, rather than either module, is responsible for placing both initializers on the automatic-extension list. The second initializer MUST register only `regexp_matches()` and `regexpi_matches()`. The implementation MUST NOT add runtime loading or shell `.load` steps.

## 5. Terminology

### 5.1 Thompson NFA

A **Thompson NFA** is a nondeterministic finite automaton produced from a regular expression using Thompson-style construction. Multiple possible regex paths are represented as simultaneously active states rather than explored recursively one after another.

### 5.2 Pike VM

A **Pike VM** is a lockstep virtual-machine simulation of a Thompson NFA, commonly attributed to Rob Pike and described by Russ Cox. It processes an ordered set of regex threads at each input position. Threads reaching the same program counter can be merged because their future instruction sequences are identical.

The required execution model is a **prioritized Pike VM**: thread order carries regex path priority so that ordered alternation and greedy quantifiers can be reproduced without recursive backtracking.

### 5.3 Thread

A **thread** is one active execution of the compiled regex program. At minimum it identifies:

- the NFA program counter or opcode index;
- the start byte offset of the candidate match;
- its priority relative to other active threads.

No capture registers are required because only the complete match is returned.

### 5.4 Epsilon transition and epsilon closure

An **epsilon transition** changes regex program state without consuming an input character. Forks, jumps, boundary assertions, start assertions, and entry into or exit from certain optimized instructions may require epsilon processing.

The **epsilon closure** of a thread is the ordered set of consuming or accepting states reachable through epsilon transitions at the same input boundary.

### 5.5 Leftmost-first matching

**Leftmost-first** means:

1. the match beginning at the earliest input position wins;
2. among paths beginning at that position, regex path priority decides the result;
3. earlier alternatives have priority over later alternatives;
4. greedy quantifiers prefer another repetition over exiting the quantifier.

Leftmost-first is not POSIX leftmost-longest disambiguation. Although SQLite's supported syntax is described as POSIX-extended-like, the new extraction functions MUST NOT select a later alternative merely because it produces a longer match.

### 5.6 Ordered alternation

For `X|Y`, **ordered alternation** tries the path for `X` before the path for `Y`. `Y` is relevant only if the higher-priority `X` path cannot complete the whole expression.

For example:

```text
pattern  input  first match
a|aa     aa     a
aa|a     aa     aa
```

The implementation MUST NOT enumerate every combination of alternatives to find the longest result.

### 5.7 Greedy non-possessive quantifier

A **greedy** quantifier prefers another repetition over exiting. **Non-possessive** means that a viable exit remains available when further repetition would prevent the remainder of the expression from matching.

Thus:

```text
.*       consumes through the end of the available input
.*a      consumes through the last reachable `a`
a.*b     consumes through the last reachable `b`
```

Greediness does not mean irreversible consumption. Irreversible consumption would be possessive behavior, which is not required or supported.

### 5.8 Accepting fallback

An **accepting fallback** is a successful lower-priority exit retained while a higher-priority greedy path remains viable. If the higher-priority path later fails, the fallback becomes the selected match. If that higher-priority path later accepts, its acceptance supersedes the fallback.

### 5.9 Match span

A **match span** is a half-open byte interval `[start, end)` into the original UTF-8 input. The returned string is the exact input byte slice in that interval. `start == end` denotes a zero-length match.

## 6. SQL interface

### 6.1 Signatures

```sql
regexp_matches(pattern, input)  -> JSON text or NULL
regexpi_matches(pattern, input) -> JSON text or NULL
```

Both functions MUST have arity two. Argument order MUST match the existing direct function forms:

```sql
regexp(pattern, input)
regexpi(pattern, input)
```

### 6.2 Case behavior

`regexp_matches()` MUST use the same case-sensitive character comparison as `regexp()`.

`regexpi_matches()` MUST use exactly the same case-insensitive behavior as `regexpi()`. At the current baseline this means ASCII case folding only. The new function MUST NOT independently add locale-dependent or general Unicode case folding.

### 6.3 Result shape

On successful non-NULL input, the result MUST be a minified JSON array of JSON strings:

```sql
SELECT regexp_matches('[0-9]+', 'A12 B345');
-- ["12","345"]

SELECT regexpi_matches('ab+', 'ABb ab');
-- ["ABb","ab"]

SELECT regexp_matches('xyz', 'abc');
-- []
```

Each element MUST be the complete match. Parenthesized subexpressions MUST NOT change the result shape and MUST NOT create nested arrays.

The result MUST carry SQLite's JSON text subtype. Function registration MUST include `SQLITE_RESULT_SUBTYPE` whenever the implementation calls `sqlite3_result_subtype()`. SQLite documents this requirement in its [function flags](https://sqlite.org/c3ref/c_deterministic.html) and [`sqlite3_result_subtype()`](https://sqlite.org/c3ref/result_subtype.html) documentation.

### 6.4 NULL handling

If either argument is SQL `NULL`, the result MUST be SQL `NULL`:

```sql
regexp_matches(NULL, 'abc') IS NULL
regexp_matches('a', NULL)   IS NULL
```

An empty array MUST mean “valid invocation with no selected match”; it MUST NOT be used in place of NULL propagation.

### 6.5 SQLite value conversion

Argument conversion MUST follow the existing regexp SQL functions. Non-NULL values are obtained through SQLite's text conversion APIs. The extension MUST NOT invent stricter SQL-type rejection rules unless the included `regexp.c` already has them.

Pattern and input text containing an embedded zero byte are outside the supported text domain. Behavior MUST remain consistent with the target checkpoint's existing C-string-based regexp behavior; the new API MUST NOT silently claim a distinct binary-safe regex contract.

Malformed UTF-8 is outside the contractual domain. For well-formed UTF-8, all offsets MUST remain on code-point boundaries and returned slices MUST reproduce the original text exactly.

## 7. Regex-language inheritance

The new functions MUST accept exactly the syntax accepted by the target checkpoint's `regexp()` and `regexpi()` implementation. The coding agent MUST derive the definitive list from that source.

The expected baseline includes:

- literal characters and concatenation;
- grouping parentheses;
- ordered alternation `|`;
- `.`, `*`, `+`, `?`, and bounded repetition `{m,n}`;
- `^` and `$`;
- inclusive and exclusive character classes and ranges;
- supported backslash escapes;
- supported word, digit, space, and boundary classes.

Grouping parentheses are structural and non-capturing. No syntax extension is authorized as part of this work.

Compiler errors, unsupported escapes, malformed classes, malformed bounds, unmatched delimiters, and pattern complexity errors MUST be reported exactly as the existing compiler reports them.

## 8. Match-selection semantics

### 8.1 Earliest start

Search begins at the current global-search cursor. The earliest input boundary at which the expression can match MUST win. A later match MUST never displace a viable earlier-start match.

### 8.2 Ordered alternatives

At a fixed start position, alternative order is semantically significant:

```sql
SELECT regexp_matches('a|aa', 'aa');
-- ["a","a"]

SELECT regexp_matches('aa|a', 'aa');
-- ["aa"]
```

An earlier alternative is abandoned only when it cannot complete the remainder of the expression. For example:

```text
(ab|a)b  against ab   -> ab
(a|ab)b  against abb  -> ab
```

In the first case, the first alternative consumes `ab` but cannot satisfy the final `b`, so the second alternative supplies the successful path. In the second case, the first alternative completes the whole expression and wins even though a later path could consume more.

### 8.3 Repetition

All supported repetition qualifiers MUST be greedy and non-possessive. Continuing the repetition has higher priority than exiting it, but the exit is retained as a fallback when necessary to satisfy the remainder.

Required examples include:

```text
a+       against aaa       -> aaa
a?       against a         -> a
a{2,4}   against aaaaa     -> aaaa
.*a      against a 1 a 2   -> a 1 a
a.*b     against a1b2b     -> a1b2b
```

### 8.4 Interaction of alternation and repetition

Path priority MUST be structural, not based on resulting length:

```text
a|a.*b   against a1b  -> a
a.*b|a   against a1b  -> a1b
```

The first expression chooses the first completed alternative. The second expression greedily extends its first alternative.

### 8.5 Anchors and boundaries

`^` and `$` refer to the absolute beginning and end of the complete SQL input, not to the beginning or end of a suffix examined during global iteration.

Word-boundary evaluation after a previous match MUST see the actual code point immediately before the restart position. A restarted search MUST NOT manufacture a start-of-input condition.

### 8.6 Non-overlapping global iteration

After selecting a non-empty match `[start,end)`, the next search begins at `end`. No later result may contain a byte before that boundary.

The matcher MUST NOT search for overlapping alternatives beginning inside a previously selected match.

### 8.7 Zero-length matches

Zero-length matching MUST be finite and deterministic. This specification adopts the established `FindAll` rule used by Go's RE2-derived regexp package:

- zero-length matches are valid;
- after selecting a zero-length match, scanning advances by one UTF-8 code point when possible;
- an empty match abutting the immediately preceding non-empty match is ignored;
- at most one terminal empty match may be considered at end-of-input;
- no execution path may repeatedly emit the same empty span.

See the Go regexp package's definition of [successive non-overlapping matches and abutting empty matches](https://pkg.go.dev/regexp).

Tests MUST pin the exact expected results for the empty pattern, `^`, `$`, `a*`, `a?`, alternations containing an empty branch, empty input, and multibyte input. The implementation MUST NOT leave zero-length behavior as an incidental consequence of loop structure.

## 9. Required algorithm

### 9.1 Execution family

The match-span implementation MUST use prioritized Thompson-NFA simulation, commonly called a prioritized Pike VM. It MUST NOT use recursive backtracking, explicit path-stack backtracking, exhaustive alternative enumeration, or substring enumeration.

Background references:

- Russ Cox, [Regular Expression Matching Can Be Simple And Fast](https://swtch.com/~rsc/regexp/regexp1.html);
- Russ Cox, [Regular Expression Matching: the Virtual Machine Approach](https://research.swtch.com/regexp2);
- the target SQLite [`regexp.c`](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c).

### 9.2 Ordered thread lists

For each input boundary, active threads MUST be maintained in priority order. Epsilon expansion MUST preserve that order. A thread arriving at a program counter already visited in the same input generation is redundant; the first arrival wins because it has higher priority and the same future program.

A per-generation visited-state mechanism SHOULD be used so clearing state does not require an avoidable full-array reset at every character.

### 9.3 Fork priority

The compiler's fork structure MUST be interpreted so that:

- the first branch of `X|Y` precedes the second branch;
- entering the operand of greedy `X?` precedes skipping it;
- repeating greedy `X*`, `X+`, and expanded bounded repetitions precedes exiting them.

The coding agent MUST inspect how positive and negative fork displacements are generated by the compiler in the target SQLite source tree and encode priority from that verified structure. It MUST NOT assume that the existing boolean matcher's current order of `re_add_state()` calls already expresses extraction priority; boolean acceptance does not require such ordering.

### 9.4 Acceptance and fallback

At an input boundary, encountering an accepting thread establishes a candidate result. Threads lower in priority than that acceptance cannot win and MUST be discarded. Higher-priority threads remain active.

The candidate acceptance is retained as a fallback while those higher-priority threads remain viable. A later acceptance reached by a surviving higher-priority path supersedes it. When no higher-priority path remains viable, the current fallback is final.

This mechanism is what permits both:

- first-alternative behavior for `a|aa`; and
- greedy non-possessive behavior for `.*a`.

### 9.5 Unanchored search state

The existing compiler may inject a leading optimized any-star instruction to implement unanchored search. The executor MUST distinguish this synthetic search prefix from an actual `.*` written by the caller.

The implementation MUST record this distinction in extraction-owned cache metadata derived from the original pattern before invoking stock `re_compile()`. It MUST NOT change `ReCompiled` or infer the distinction merely from the first opcode, because an anchored user pattern can itself begin with `.*`.

New candidate starts introduced by unanchored search MUST be ordered after still-viable earlier starts. Candidate start positions MUST be byte offsets at valid UTF-8 input boundaries.

### 9.6 Match-span primitive

The implementation SHOULD isolate matching from SQL and JSON concerns in a private primitive logically equivalent to:

```c
static int remMatchSpan(
  RemCompiled *pCompiled,
  const unsigned char *zIn,
  int nIn,
  int iFrom,
  int *piStart,
  int *piEnd
);
```

The precise name and types MAY follow SQLite style in the target amalgamation. Its logical result contract MUST distinguish:

- match found, with a valid half-open span;
- no match;
- allocation failure.

It MUST NOT allocate or construct JSON. It MUST be independently understandable as the unit that selects one regex match.

### 9.7 Global-match driver

A private global driver shall repeatedly obtain selected spans, append their source slices to the result, and enforce non-overlap and empty-match progress.

The driver MUST operate on byte offsets but advance zero-length searches using SQLite's existing UTF-8 decoder or an equivalent already present in `regexp.c`. It MUST NOT advance one raw byte through a multibyte code point.

### 9.8 Complexity requirements

For a single search beginning at a given cursor, each compiled NFA program counter MUST be admitted at most once per input generation. The search MUST therefore remain bounded by `O(P × I)` time and `O(P)` active-state memory, where:

- `P` is the compiled NFA size after bounded-repeat expansion;
- `I` is the number of input code points examined by that search.

No pattern may cause exponential path enumeration or catastrophic backtracking.

Global extraction may need to examine text beyond the span ultimately returned because a higher-priority path can fail only after lookahead. The implementation MUST document whether subsequent matching re-examines such text. If the simple restart design is used, its aggregate worst-case bound is `O(K × P × I)`, where `K` is the number of returned matches; this bound MUST be stated honestly and covered by an adversarial performance test. The implementation MUST NOT claim whole-invocation linearity unless it actually preserves sufficient state to prove it.

Patterns such as the following MUST be used to detect accidental exponential behavior:

```text
(a?){n}a{n}
(a+)+b
(a|aa)*b
```

Only syntax accepted by SQLite's compiler shall be used in executable cases. Bounded repetitions must remain within configured complexity limits.

An additional global-restart stress case MUST cover a high-priority greedy branch that scans far beyond a short accepting fallback, such as the supported equivalent of:

```text
a.*z|a
```

against a long `a`-rich input containing no `z`.

## 10. Internal code organization

### 10.1 Companion source module

All production code MUST reside in `regexp_matches.c`. Stock `ext/misc/regexp.c` MUST remain unmodified and byte-comparable with the selected SQLite source. No production header is required.

### 10.2 Extraction-owned compilation cache

`regexp_matches.c` MUST implement its own private auxiliary-data cache wrapper. The wrapper owns a stock `ReCompiled *` plus extraction-only metadata, including whether the original pattern was unanchored. Compilation MUST call stock `re_compile()` and destruction MUST call stock `re_free()`.

The refactor MUST preserve:

- auxiliary-data slot selection;
- case-mode selection without changing stock registration or wrappers;
- maximum-pattern-length lookup;
- NFA complexity-limit calculation;
- allocator and destructor behavior;
- existing error strings;
- NULL behavior.

The existing boolean wrapper and all other stock regexp source MUST remain untouched.

### 10.3 Separation of responsibilities

Production code SHOULD be decomposed into these private responsibilities:

1. compile or retrieve a cached expression;
2. add a prioritized thread and compute ordered epsilon closure;
3. execute one consuming input step;
4. select one match span;
5. iterate successive non-overlapping spans;
6. append exact slices to a JSON array;
7. implement the common SQL wrapper for both case modes.

Regex execution code MUST NOT know about `JsonString`. JSON code MUST NOT decide regex priority or matching extent.

### 10.4 Existing boolean matcher

The stock boolean executor MUST remain unchanged. `regexp_matches.c` shall add a dedicated prioritized span executor over the same compiled NFA. It MUST call stock helpers directly where corresponding functionality already exists rather than copying them.

## 11. Memory and resource management

All dynamic memory MUST use SQLite allocators and MUST follow SQLite's existing ownership conventions.

The implementation MUST:

- detect every allocation failure;
- return `SQLITE_NOMEM` through the SQL context as appropriate;
- free temporary thread storage on every exit path;
- preserve ownership of cached `ReCompiled` objects through auxiliary-data destructors;
- avoid per-character heap allocation;
- use existing small stack buffers where reasonable and fall back to SQLite heap allocation for larger NFAs;
- avoid integer overflow when sizing state, priority, or offset arrays;
- use length and result APIs appropriate for SQLite's maximum string size.

Thread storage SHOULD be allocated once per one-span search and reused across every input boundary examined by that search. The implementation MUST perform no per-character heap allocation.

## 12. JSON construction

The result builder MUST:

1. initialize SQLite's private JSON string accumulator with the SQL context;
2. append `[`;
3. append each match through SQLite's private JSON string-quoting routine, separated by commas;
4. append `]`;
5. return the accumulated JSON using the private JSON result routine;
6. mark the SQL result with SQLite's JSON subtype.

The match slice MUST be passed with an explicit byte length. It MUST NOT be copied into a temporary zero-terminated buffer solely for JSON quoting.

The extension MUST delegate escaping of quotes, reverse solidus characters, and control characters to SQLite JSON code. It MUST NOT maintain an independent JSON escaping table.

The empty successful result MUST be exactly:

```json
[]
```

Whitespace formatting is not permitted or required.

## 13. SQL-function registration

The two initializers together MUST register four scalar functions:

```text
regexp
regexpi
regexp_matches
regexpi_matches
```

The private initializer in `regexp_matches.c` MUST register the new functions with:

- arity `2`;
- preferred encoding `SQLITE_UTF8`;
- `SQLITE_DETERMINISTIC`;
- `SQLITE_INNOCUOUS`;
- `SQLITE_RESULT_SUBTYPE`;
- distinct case-sensitive and case-insensitive C wrappers, leaving function user data zero so it cannot collide with private JSON output-format flags.

Registration MUST propagate the first non-`SQLITE_OK` result and MUST not leave a partially reported successful initialization.

No `SQLITE_DIRECTONLY` flag is required because the functions are deterministic, side-effect-free, and suitable for trusted-schema-disabled use when correctly audited as innocuous.

## 14. Error behavior

The new functions MUST follow existing regexp error behavior:

- invalid pattern: SQL error with the existing compiler message;
- pattern exceeding the configured limit: existing “pattern too big” error;
- allocation failure: SQLite out-of-memory result;
- NULL input: NULL result, not an error;
- no match: `[]`, not NULL and not an error.

JSON allocation or size failures MUST be reported through the private JSON builder's established mechanisms. A partial JSON document MUST never be returned.

## 15. Compatibility requirements

### 15.1 Existing SQL behavior

All pre-existing tests for `regexp()`, `regexpi()`, and `REGEXP` MUST continue to pass without changed expected results.

The `REGEXP` operator remains boolean and retains SQLite's reversed operator-to-function argument mapping. No `REGEXP_MATCHES` operator shall be introduced.

### 15.2 Source compatibility

No new public header, public typedef, exported match routine, or application-facing C declaration shall be introduced.

The pre-existing regexp initializer may remain externally visible as required by static auto-extension registration. The match-array initializer and all new functions, structures, and helpers MUST be `static` or otherwise translation-unit private.

### 15.3 Upgrade compatibility

References to private JSON code are intentionally permitted, but they create a checkpoint dependency. The source MUST contain a concise integration comment identifying:

- that `regexp_matches.c` is amalgamation-only and must follow unmodified stock `regexp.c`;
- which private JSON facilities it relies on;
- that SQLite JSON must be enabled;
- that amalgamation order is significant.

The code SHOULD use a small, localized adapter section for private JSON calls so future SQLite changes are easy to review.

## 16. Security properties

The new functions process potentially adversarial patterns and text. The implementation MUST preserve the following properties:

- no recursive regex-path backtracking;
- no exponential enumeration of alternatives or repetition partitions;
- existing compiled-NFA complexity limit remains effective;
- existing runtime pattern-length limit remains effective;
- no unbounded C recursion proportional to input length;
- no integer overflow in allocation calculations or byte offsets;
- no out-of-bounds read at UTF-8 boundaries or end-of-input;
- no infinite loop on an empty match;
- no unescaped match text in JSON output;
- deterministic results for identical SQL values and connection limits.

SQLite permits lowering limits per connection to constrain resource use; the existing regexp extension derives its pattern bound from `SQLITE_LIMIT_LIKE_PATTERN_LENGTH`. This behavior MUST remain intact. See [SQLite limits](https://sqlite.org/limits.html).

## 17. Testing strategy

### 17.1 Principles

Tests MUST exercise the production SQL functions in an amalgamation build exclusively through Python's standard `sqlite3` API under `pytest`. A standalone mock regex or JSON implementation, a direct C unit test of static helpers, or a test-only SQL function is not an acceptable substitute.

The public SQL surface is the unit under test. Private compiler, Pike-VM, span-selection, iteration, and JSON helpers MUST be tested transitively through calls to `regexp()`, `regexpi()`, `regexp_matches()`, and `regexpi_matches()` made by Python `sqlite3.Connection` objects.

The test suite MUST be divided into:

- regression tests for existing behavior;
- semantic tests for selected spans;
- JSON correctness tests;
- error and resource tests;
- adversarial complexity tests;
- build and registration tests.

Expected results MUST be specified explicitly. Python's `re` module MUST NOT be used as the normative oracle because its syntax, case folding, empty-match behavior, and implementation differ from SQLite's regexp engine. It MAY be used only for non-normative exploratory comparison.

Tests SHOULD use `pytest.mark.parametrize` for semantic matrices and ordinary bound SQL parameters for patterns and inputs. They MUST NOT interpolate test values into SQL source.

### 17.2 Existing regexp regression module

Cover at least:

- literal match and non-match;
- `REGEXP` operator argument order;
- `regexp()` direct-call argument order;
- `regexpi()` ASCII case folding;
- anchors;
- classes and ranges;
- quantifiers and bounded repetition;
- alternation and grouping as boolean expressions;
- supported escapes;
- invalid-pattern messages;
- NULL propagation;
- repeated execution of a prepared statement with a constant pattern;
- repeated execution with a changed bound pattern, proving auxiliary-data invalidation remains correct.

### 17.3 Basic extraction module

Cover:

- no match returns `[]`;
- one match;
- several separated matches;
- adjacent matches;
- match at byte zero;
- match ending at input end;
- complete-input match;
- case-insensitive extraction preserves original input spelling;
- grouping does not create capture output.

### 17.4 Priority and disambiguation module

Pin at least these behaviors:

| Pattern | Input | Required matches |
| --- | --- | --- |
| <code>a&#124;aa</code> | `aa` | `["a","a"]` |
| <code>aa&#124;a</code> | `aa` | `["aa"]` |
| <code>a&#124;a.*b</code> | `a1b` | `["a"]` |
| <code>a.*b&#124;a</code> | `a1b` | `["a1b"]` |
| <code>(ab&#124;a)b</code> | `ab` | `["ab"]` |
| <code>(a&#124;ab)b</code> | `abb` | `["ab"]` |

Add nested alternation cases in which a high-priority path fails only after consuming substantial lookahead.

### 17.5 Greedy repetition module

Cover every supported qualifier:

| Pattern | Input | Required first match |
| --- | --- | --- |
| `a*` | `aaa` | `aaa` |
| `a+` | `aaa` | `aaa` |
| `a?` | `a` | `a` |
| `a{2,4}` | `aaaaa` | `aaaa` |
| `.*a` | `a 1 a 2` | `a 1 a` |
| `a.*b` | `a1b2b` | `a1b2b` |

Also cover repetition followed by a required suffix, nested grouping, a repetition that must fall back, and a repetition whose operand can match in more than one way.

### 17.6 Non-overlap module

Cover:

- `aa` against `aaaa` returns two matches;
- `aba` against `ababa` returns only the first overlapping possibility;
- restart at the exact end byte of a selected match;
- an anchored expression is not re-anchored at a restart cursor;
- a boundary assertion sees text preceding the cursor.

### 17.7 Zero-length module

Pin complete JSON results for:

- empty pattern against empty input;
- empty pattern against ASCII input;
- empty pattern against multibyte UTF-8 input;
- `^`, `$`, and `^$`;
- `a*` against all-matching input;
- `a*` against nonmatching input;
- `a?` against matching and nonmatching input;
- an empty alternative before and after a non-empty alternative;
- a zero-length match adjacent to a prior non-empty match;
- end-of-input.

Every case MUST have a timeout or bounded test harness so an empty-match progress regression cannot hang the suite.

### 17.8 UTF-8 module

Cover:

- two-, three-, and four-byte code points;
- `.` consuming exactly one code point;
- literal non-ASCII matching;
- matches adjacent to multibyte characters;
- zero-length advancement by code point rather than byte;
- exact preservation of the matched source spelling;
- documented ASCII-only behavior of `regexpi_matches()`.

### 17.9 JSON module

Use `json_valid()` and `json_each()` to verify content, not serialized spelling alone. Cover match text containing:

- quotation marks;
- reverse solidus characters;
- tab, newline, carriage return, backspace, and form feed where accepted as SQL text;
- other JSON control characters;
- non-ASCII UTF-8;
- multiple independently escaped matches.

Verify:

- SQL storage class is `text`;
- empty output is valid JSON;
- every array member has JSON type `text`;
- embedding the result in another JSON operation treats it as JSON rather than a quoted ordinary string, where subtype propagation is observable.

### 17.10 NULL, coercion, and errors module

Cover:

- NULL in either argument;
- numeric values converted according to existing regexp behavior;
- empty pattern;
- malformed pattern families;
- unsupported escape;
- oversized pattern under a deliberately lowered connection limit;
- no partial JSON result after an error.

### 17.11 Registration module

For a newly opened connection, verify through `pragma_function_list` or direct calls that all four functions exist with arity two.

Verify that the new functions:

- are automatically available without `.load`;
- are deterministic;
- are usable with `trusted_schema=OFF` in contexts allowed to innocuous functions;
- return JSON subtype correctly in expression-index-sensitive builds where practical.

### 17.12 Complexity and stress module

Include parameterized adversarial inputs whose length increases geometrically. Measure execution through the public SQL call with generous platform-independent thresholds. Complexity tests SHOULD use a pytest timeout facility or an equivalent outer timeout so a regression cannot hang the suite.

The tests MUST demonstrate absence of exponential growth for ambiguous nested repetitions and alternatives. They MUST separately characterize the documented aggregate behavior of global restart and the `a.*z|a` fallback case.

Performance tests MUST not require exact wall-clock ratios on shared CI hosts. Use broad upper bounds and growth checks intended to detect catastrophic behavior, not microbenchmark ordinary execution speed.

## 18. Test builds and execution

### 18.1 Required test build

The normative test artifact is a Python `sqlite3` module linked to the custom SQLite amalgamation with JSON and the regexp auto-extension enabled. The project's primary required configuration is Windows/MSVC with Python 3.11.

The build procedure MUST produce or stage the Python extension module and any associated SQLite DLL so importing `sqlite3` in the configured test environment uses the custom amalgamation. It MUST NOT rely on whatever SQLite happens to be bundled with the machine's ordinary Python installation.

Debug, sanitizer, or other compiler variants MAY be exercised additionally, but they MUST run the same public SQL pytest suite. They do not justify separate private C tests or diagnostic SQL functions.

### 18.2 Build invariant

Tests MUST execute against the produced custom SQLite artifact, not Python's bundled or system SQLite library. A session-scoped pytest fixture MUST query and verify at least:

```sql
SELECT sqlite_version(), sqlite_source_id();
SELECT compile_options FROM pragma_compile_options ORDER BY compile_options;
SELECT name, narg, flags
FROM pragma_function_list
WHERE name IN ('regexp', 'regexpi', 'regexp_matches', 'regexpi_matches')
ORDER BY name;
```

The suite MUST NOT hard-pin a SQLite version or source ID. An expected source ID MAY be supplied for diagnostics, but a mismatch shall produce at most a warning. The normative proof that the intended feature build is loaded is successful automatic discovery and execution of all four required functions, including extension-specific semantic cases that an ordinary Python-bundled SQLite cannot satisfy.

The build MUST fail clearly if:

- JSON is omitted;
- the private JSON facilities are unavailable at the selected checkpoint;
- amalgamation composition places `regexp_matches.c` before required stock regexp or JSON internals;
- either initializer is not registered as an auto-extension.

### 18.3 Pytest fixtures

`tests/conftest.py` SHOULD provide:

- a session-scoped build-identity check;
- a fresh in-memory `sqlite3.Connection` fixture for each test;
- connection cleanup after every test;
- optional helpers that execute a scalar SQL expression with bound parameters;
- optional helpers that decode returned JSON using Python's `json.loads()`.

No fixture may register Python implementations of any regexp or JSON function. Availability of the four regexp functions must come solely from SQLite auto-extension registration.

Connections SHOULD use default text handling so returned JSON and match members are Python `str` objects. Tests involving control characters MUST pass values as bound parameters.

### 18.4 Test modules

The pytest suite SHOULD use a structure equivalent to:

```text
tests/
    conftest.py
    test_registration.py
    test_regexp_regression.py
    test_matches_basic.py
    test_matches_priority.py
    test_matches_repetition.py
    test_matches_nonoverlap.py
    test_matches_empty.py
    test_matches_utf8.py
    test_matches_json.py
    test_matches_errors.py
    test_matches_complexity.py
```

Module boundaries MAY be adjusted, but registration, regression, semantics, JSON, errors, UTF-8, empty matches, and complexity MUST remain visibly separable.

### 18.5 Assertions

Most functional tests SHOULD:

1. call the SQL function with `Connection.execute()` and bound parameters;
2. fetch the single scalar result;
3. assert SQL NULL directly when expected;
4. otherwise assert that the result is a Python `str`;
5. decode it with `json.loads()`;
6. compare the decoded Python list with an explicit expected list.

Separate JSON-integration tests MUST validate the value inside SQLite with `json_valid()`, `json_each()`, and another JSON composition function so correctness does not depend only on Python's JSON parser.

Invalid patterns and size-limit failures MUST be asserted through the appropriate `sqlite3` exception class and message. Tests SHOULD match stable message content without overspecifying Python wrapper prefixes that can vary across Python patch releases.

### 18.6 Execution order

The standard pytest command shall:

1. activate or select the Python 3.11 environment containing the custom `sqlite3` module;
2. run the session feature check and optional source-ID diagnostic;
3. verify auto-registration on a fresh connection;
4. run existing regexp regression tests;
5. run functional extraction tests;
6. run JSON and error tests;
7. run UTF-8 and zero-length tests;
8. run complexity tests, preferably under a dedicated pytest marker.

The repository documentation MUST give exact commands for building the custom SQLite/Python test artifact on Windows with MSVC and for executing both the normal and complexity-marked pytest selections.

## 19. Implementation sequence

The coding agent SHOULD implement in these stages, keeping every stage buildable and tested:

1. restore and verify byte-identical stock `regexp.c`;
2. introduce `regexp_matches.c` and prove its separate auto-extension visibility;
3. implement extraction-owned pattern caching and synthetic-unanchored-search metadata;
4. implement prioritized epsilon closure and thread deduplication;
5. implement one leftmost-first match span without JSON iteration;
6. validate ordered alternation independently;
7. implement accepting fallbacks for greedy non-possessive repetition;
8. validate anchors, boundaries, and UTF-8 byte spans;
9. add global non-overlapping iteration and zero-length progress;
10. connect SQLite's private JSON builder and subtype handling;
11. add public SQL error, limit, UTF-8, JSON, and adversarial-complexity coverage;
12. complete amalgamation and MSVC integration documentation.

Each stage MUST be applied as a patch to the preceding implementation. The coding agent MUST not regenerate or patch `regexp.c`.

## 20. Acceptance criteria

The extension is complete only when all of the following are true:

- `regexp_matches()` and `regexpi_matches()` are automatically available on every new connection in the custom build;
- both functions return valid JSON arrays of complete matched strings;
- `a|aa` and `aa|a` prove ordered alternation rather than longest-alternative selection;
- `a+`, `.*a`, and suffix-constrained repetitions prove greedy non-possessive behavior;
- all results are leftmost and non-overlapping;
- zero-length matches terminate and follow the specified abutting-match rule;
- anchors and boundaries retain absolute-input semantics across restarts;
- UTF-8 matches use correct byte spans and code-point progress;
- JSON escaping and subtype propagation are correct;
- NULL, invalid-pattern, and runtime-limit behavior are correct;
- stock `regexp.c` is unchanged and existing `regexp()`, `regexpi()`, and `REGEXP` behavior is unchanged;
- no new public C API or external dependency exists;
- no regex path is explored through recursive or combinatorial backtracking;
- the implementation states and tests its honest aggregate complexity bound;
- the complete Python `sqlite3`/pytest suite passes against the primary Windows/MSVC custom build.

## 21. References

- SQLite, [`ext/misc/regexp.c`](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c).
- SQLite, [`src/json.c`](https://github.com/sqlite/sqlite/blob/master/src/json.c).
- SQLite, [Automatically Load Statically Linked Extensions](https://sqlite.org/c3ref/auto_extension.html).
- SQLite, [Function Flags](https://sqlite.org/c3ref/c_deterministic.html).
- SQLite, [Setting the Subtype of an SQL Function](https://sqlite.org/c3ref/result_subtype.html).
- SQLite, [Implementation Limits](https://sqlite.org/limits.html).
- Russ Cox, [Regular Expression Matching Can Be Simple And Fast](https://swtch.com/~rsc/regexp/regexp1.html).
- Russ Cox, [Regular Expression Matching: the Virtual Machine Approach](https://research.swtch.com/regexp2).
- Go regexp package, [successive non-overlapping and empty-match semantics](https://pkg.go.dev/regexp).
