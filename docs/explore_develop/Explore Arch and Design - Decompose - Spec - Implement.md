---
url: https://chatgpt.com/c/6a8e7ff4-8128-83eb-bdbd-42301f99ff1d
---

## 📗 Problem Statement

> [!NOTE] Prompt
> 
> I need to extend SQLite ext/misc/regexp.c to get a JSON array of non-overlapping matched strings. As usual, I want the least amount of original code, which needs to be properly tested and a well testable design where original code is necessary.
> 
> This extension aims to be built solely as auto extension in amalgamation, so it can and should use private functions of regexp, json, or other SQLite components to minimize the amount of new code to be tested and friction. My objective is SQL regexp_matches and regexpi_matches functions with no public C interface.

The right design is to extend the existing NFA with one internal match-span primitive, then keep JSON construction and both SQL wrappers extremely thin.

### Proposed SQL interface

```sql
regexp_matches(pattern, string)  -> JSON_TEXT
regexpi_matches(pattern, string) -> JSON_TEXT
```

Examples:

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

The argument order should remain consistent with the existing functions:

```sql
regexp(pattern, string)
regexpi(pattern, string)
```

Parentheses remain non-capturing, as they already are in `regexp.c`. The result contains complete matches only.

### Match semantics

I recommend defining the result as:

> All leftmost, longest, mutually non-overlapping matches, in input order.

“Longest” is essential. The existing `re_match()` stops as soon as the NFA reaches `RE_OP_ACCEPT`, because a boolean result does not need the match extent. Reusing that stopping point directly would produce incorrect extraction behavior:

```sql
regexp_matches('a+', 'aaa')
```

must return:

```json
["aaa"]
```

not:

```json
["a","a","a"]
```

Alternation should likewise use leftmost-longest semantics:

```sql
regexp_matches('a|aa', 'aa')
-- ["aa"]
```

That is a natural fit for an engine described as implementing POSIX extended regular expressions.

#### Empty matches

This needs an explicit rule. My recommended behavior is conventional global-matching behavior:

* include zero-length matches;
* after a zero-length match, advance by one UTF-8 character;
* allow one zero-length match at end-of-input;
* never loop indefinitely.

Thus:

```sql
regexp_matches('a*', 'bbb')
-- ["","","",""]

regexp_matches('^', 'abc')
-- [""]

regexp_matches('$', 'abc')
-- [""]

regexp_matches('', '')
-- [""]
```

If you would rather exclude empty matches entirely, that is simpler for callers, but it makes valid patterns such as `^` and `$` return no matches. I would not choose that unless your actual text-processing use cases demand it.

### Internal decomposition

#### 1. Shared compilation helper

Extract the compilation and auxiliary-data handling currently embedded in `re_sql_func()` into a static helper:

```c
static ReCompiled *re_sql_compile(
  sqlite3_context *context,
  sqlite3_value *pPattern
);
```

Responsibilities:

* retrieve the compiled pattern using `sqlite3_get_auxdata()`;
* enforce `SQLITE_LIMIT_LIKE_PATTERN_LENGTH`;
* call `re_compile()`;
* select case sensitivity from `sqlite3_user_data(context)`;
* report compilation and allocation errors;
* cache the compiled expression with `sqlite3_set_auxdata()`.

Then:

* existing `re_sql_func()` calls the helper and `re_match()`;
* new `re_matches_sql_func()` calls the same helper and the span iterator.

This removes duplicated error handling while preserving the existing compiled-pattern cache.

#### 2. Match-span primitive

Add one static primitive:

```c
static int re_match_span(
  ReCompiled *pRe,
  const unsigned char *zIn,
  int nIn,
  int iFrom,
  int *piStart,
  int *piEnd
);
```

Return convention:

```text
 1  match found
 0  no match
-1  allocation failure
```

Offsets are byte offsets into the original UTF-8 input. This allows the SQL layer to pass the exact byte slice directly to SQLite’s JSON encoder.

The primitive should:

* begin searching at `iFrom`;
* preserve absolute `^`, `$`, and `\b` semantics;
* select the earliest viable start;
* continue the NFA after its first acceptance;
* retain the greatest accepting end offset for that earliest start;
* stop once no active NFA path belonging to that start remains.

This retains the existing NFA approach and avoids repeatedly testing every possible substring.

#### 3. NFA origin tracking

The smallest efficient extension is to associate an input-origin offset with each active state.

Conceptually:

```c
typedef struct ReStateSet {
  unsigned nState;
  ReStateNumber *aState;
  int *aStart;
} ReStateSet;
```

`re_add_state()` then accepts an origin:

```c
static void re_add_state(
  ReStateSet *pSet,
  int newState,
  int iStart
);
```

When two paths reach the same NFA state, retain the earlier origin. The later path can safely be discarded because both paths have identical future behavior, while the earlier one always has match priority.

The artificial leading `RE_OP_ANYSTAR` inserted by `re_compile()` must be distinguished from an actual `.*` in the pattern. Add a flag to `ReCompiled`, for example:

```c
unsigned bUnanchored : 1;
```

When that artificial state starts the real expression, assign the current input boundary as the candidate match origin. An actual `.*` continues to propagate its existing origin.

This is substantially better than an outer “try every UTF-8 boundary” loop, which could degrade extraction to quadratic time.

#### 4. Global iterator

The SQL wrapper repeatedly calls `re_match_span()`:

```text
position = 0

while a match exists:
    append input[start:end]

    if end > start:
        position = end
    else if end < input_length:
        position = next UTF-8 boundary after end
    else:
        stop
```

Because every subsequent search starts at the previous match’s end, returned matches cannot overlap.

### JSON generation

Since this code will exist only inside the amalgamation, reuse the private JSON string builder:

```c
JsonString json;

jsonStringInit(&json, context);
jsonAppendChar(&json, '[');

for each match:
    jsonAppendSeparator(&json);
    jsonAppendString(
        &json,
        (const char *)&zStr[iStart],
        (u32)(iEnd - iStart)
    );

jsonAppendChar(&json, ']');
jsonReturnString(&json, 0, 0);
sqlite3_result_subtype(context, JSON_SUBTYPE);
```

This gives you, without new serialization code:

* correct escaping of quotes and backslashes;
* escaping of JSON control characters;
* SQLite-native allocation and OOM handling;
* correct ownership transfer;
* JSON subtype propagation.

The current JSON implementation provides exactly these private `JsonString`, `jsonAppendString()`, and `jsonReturnString()` facilities. The amalgamation must place the incorporated `regexp.c` after `json.c`, and the build should require JSON support rather than supporting `SQLITE_OMIT_JSON`. [SQLite JSON implementation](https://github.com/sqlite/sqlite/blob/master/src/json.c)

### Registration

Register both functions through the existing `sqlite3_regexp_init()`:

```c
sqlite3_create_function(
    db,
    "regexp_matches",
    2,
    SQLITE_UTF8
      | SQLITE_INNOCUOUS
      | SQLITE_DETERMINISTIC
      | SQLITE_RESULT_SUBTYPE,
    0,
    re_matches_sql_func,
    0,
    0
);

sqlite3_create_function(
    db,
    "regexpi_matches",
    2,
    SQLITE_UTF8
      | SQLITE_INNOCUOUS
      | SQLITE_DETERMINISTIC
      | SQLITE_RESULT_SUBTYPE,
    (void *)1,
    re_matches_sql_func,
    0,
    0
);
```

All new C functions remain `static`. There is no new exported initialization function or public C API.

### Testing structure

The SQL surface is sufficient to test the internal primitive thoroughly. I would divide tests into these modules.

#### Existing-function regression

Verify unchanged behavior of:

* `regexp()`;
* `regexpi()`;
* the `REGEXP` operator;
* pattern compilation errors;
* pattern-size limits;
* NULL propagation;
* repeated execution with auxiliary-data caching.

#### Basic extraction

Test:

* no matches → `[]`;
* one match;
* several separated matches;
* adjacent matches;
* match at the beginning;
* match at the end;
* whole-input match.

#### Extent selection

These are the most important new tests:

```text
a+          against aaa
a*          against aaa
a|aa        against aa
aa|a        against aa
a?          against a
(ab|abc)    against abc
.*          against complete input
.*x         against multiple x occurrences
[0-9]{2,4}  against a long digit run
```

They verify leftmost-longest selection rather than first acceptance.

#### Non-overlap and restart

Test:

```text
aa   against aaaa
aba  against ababa
\w+  against several words
```

Expected results must never overlap.

#### Empty matches

Test:

* empty pattern and empty input;
* empty pattern and nonempty input;
* `a*` on matching and nonmatching input;
* `a?`;
* `^`;
* `$`;
* `^$`;
* empty match following a nonempty match;
* end-of-input termination.

#### Anchors and boundaries

Test:

* `^` only recognizes absolute input start, not the restart position;
* `$` recognizes absolute input end;
* `\b` after a previous match sees the character preceding the restart position;
* `\B` if later supported;
* anchors inside alternation and parentheses.

This catches the common error of treating every global-search restart as the beginning of a new string.

#### UTF-8

Test:

* one-byte ASCII;
* two-, three-, and four-byte UTF-8 characters;
* `.` returning complete characters;
* advancement after an empty match by character, not byte;
* matches returned as the original UTF-8 byte sequence;
* case-insensitive behavior remains ASCII-only, matching current `regexpi()` semantics.

#### JSON serialization

Test matched strings containing:

* `"`;
* `\`;
* newline, tab, carriage return;
* other control characters;
* Unicode text.

Validate results using `json_valid()` and inspect elements through `json_each()` rather than comparing only serialized spelling.

#### Error and limit handling

Test:

* invalid patterns;
* oversized patterns;
* NULL pattern;
* NULL input;
* allocation failures if using SQLite’s native fault-injection test fixture.

### Recommendation

Do not implement this as a second independent matcher and do not generate JSON manually. The clean boundary is:

```text
existing compiler
      ↓
extended NFA span primitive
      ↓
small global iterator
      ↓
SQLite JsonString builder
      ↓
two SQL registrations
```

Only origin tracking, longest-match termination, and zero-length progress are genuinely new behavior. Everything else can be inherited from the existing [`ext/misc/regexp.c`](https://github.com/sqlite/sqlite/blob/master/ext/misc/regexp.c) and SQLite JSON implementation.

---
---

## 📗 Target Refinement

> [!NOTE] Prompt
> 
> I am not particularly happy about a|aa. Is this standard behavior that matcher must try every combination of alternatives!? THIS IS OF COURSE UTTERLY UNACCEPTABLE. Repetition qualifiers must be greedy, but first matching alternative got to be used. Otherwise, you blow computational complexity.

You are right. My proposed leftmost-longest rule was wrong for your intended regex semantics.

The appropriate rule is:

> Select the leftmost match; at that position, respect ordered alternation and greedy repetition.

Therefore:

```sql
regexp_matches('a|aa', 'aa')
-- ["a","a"]

regexp_matches('aa|a', 'aa')
-- ["aa"]

regexp_matches('a+', 'aaa')
-- ["aaa"]
```

The engine must not try every combination or search for the longest alternative.

This does not require backtracking. It can be implemented as a prioritized Thompson/Pike NFA with bounded complexity:

* active states remain ordered by priority;
* the first alternative has priority over later alternatives;
* greedy repetition prioritizes another repetition over exiting;
* duplicate states retain the first, highest-priority thread;
* an accepting thread is kept as a fallback only while higher-priority threads remain viable;
* lower-priority threads are discarded once an earlier accepting path outranks them.

The existing `RE_OP_FORK` can express the required priority:

* positive fork argument: process fall-through first;

  * first alternative before the second;
  * optional operand before skipping it;
* negative fork argument: process the jump target first;

  * another `*` or `+` repetition before exiting.

Conceptually:

```c
case RE_OP_FORK:
  if( pRe->aArg[x] < 0 ){
    re_add_state(pSet, x + pRe->aArg[x]); /* Repeat first */
    re_add_state(pSet, x + 1);            /* Then exit */
  }else{
    re_add_state(pSet, x + 1);            /* First alternative */
    re_add_state(pSet, x + pRe->aArg[x]); /* Second alternative */
  }
  break;
```

Actual prioritized matching needs epsilon expansion and acceptance handling around this ordering, not merely this local change.

For greediness:

```text
a+?    unsupported
a+     greedy
a*     greedy
a?     greedy
a{m,n} greedy
```

So:

```sql
regexp_matches('a.*b', 'a1b2b')
-- ["a1b2b"]
```

But ordered alternatives remain decisive:

```sql
regexp_matches('a|a.*b', 'a1b')
-- ["a"]

regexp_matches('a.*b|a', 'a1b')
-- ["a1b"]
```

A prioritized NFA still has polynomial, normally `O(N×M)`, behavior. Each NFA state is retained at most once per input position; priority determines which duplicate survives. It does not enumerate alternative combinations.

The corrected contract should therefore be:

> Return successive non-overlapping matches using leftmost-first, ordered-alternation semantics and greedy repetition, without backtracking.

The critical tests become:

```text
a|aa       on aa     → ["a", "a"]
aa|a       on aa     → ["aa"]
a+         on aaa    → ["aaa"]
a?|aa      on aa     → ["a", "a"]
aa|a?      on aa     → ["aa"]
a.*b|a     on a1b    → ["a1b"]
a|a.*b     on a1b    → ["a"]
(ab|a)b    on ab     → ["ab"]
(a|ab)b    on abb    → ["ab"]
```

This gives conventional ordered regex behavior without catastrophic backtracking.

---
---

## 📗 Greedy Regexp

> [!NOTE] Prompt
> 
> Maybe greedy is not the right term? .* Captures all, but .*a must still match, if the sequence contains 'a' anywhere

“Greedy” is the correct term, but specifically **greedy and non-possessive**.

A greedy quantifier consumes as much as possible while still permitting the remainder of the pattern to match:

```text
.*       → consumes the entire remaining string
.*a      → consumes through the last reachable "a"
.*ab     → consumes through the last reachable "ab"
```

For example:

```sql
regexp_matches('.*a', 'a 1 a 2')
-- ["a 1 a"]

regexp_matches('.*a', 'xyz')
-- []
```

What you do not want is a **possessive** quantifier. Possessive `.*` would consume everything irreversibly, causing `.*a` to fail whenever `a` was not beyond what it consumed.

This still does not require combinatorial backtracking. A prioritized NFA can retain the relevant alternatives concurrently:

* one higher-priority thread continues `.*`;
* another lower-priority thread attempts the following `a`;
* whenever the following `a` succeeds, that acceptance becomes the current fallback;
* if the repetition continues and another `a` succeeds later, the later acceptance replaces it;
* each NFA state is still processed at most once per input position.

So the desired semantics are:

> Leftmost-first matching, ordered alternation, and greedy non-possessive repetition, implemented without backtracking.

The distinction is:

```text
a|aa     → first alternative wins: "a"
aa|a     → first alternative wins: "aa"
a+       → greedy repetition: "aaa"
.*a      → greedy repetition constrained by suffix: through last "a"
```

“First alternative wins” and “greedy quantifier” are compatible. Priority belongs to the regex execution paths:

* earlier alternatives outrank later alternatives;
* continuing a greedy quantifier outranks exiting it;
* a lower-priority successful exit is retained while the higher-priority repetition path remains viable.

That priority model is the correct basis for the span-producing extension.

---
---

## 📗 Regexp Reuse

> [!NOTE] Prompt
> 
> Can I still use SQLite engine?

Yes. You can retain almost the entire SQLite regexp engine:

* existing parser/compiler;
* existing NFA bytecode and opcodes;
* character classes and UTF-8 decoding;
* pattern-size limits;
* case-sensitive/case-insensitive handling;
* compiled-pattern caching;
* non-backtracking complexity.

What cannot be reused unchanged is only `re_match()`, because it answers a boolean question and discards path priority and match boundaries as soon as any path accepts.

Add a span-producing execution mode:

```c
static int re_match_span(
  ReCompiled *pRe,
  const unsigned char *zIn,
  int nIn,
  int iFrom,
  int *piStart,
  int *piEnd
);
```

It should run the same SQLite bytecode as a prioritized NFA:

* earlier alternatives have higher priority;
* continuing a quantifier has priority over exiting it;
* an accepting lower-priority path is retained as a fallback;
* higher-priority paths may continue;
* duplicate `(opcode, input-position)` states are eliminated;
* no recursive or combinatorial backtracking occurs.

Thus SQLite’s engine supplies the regex language and transition machinery; the new code supplies only:

1. ordered NFA-thread management;
2. start/end byte tracking;
3. acceptance-priority handling;
4. repeated non-overlapping iteration;
5. JSON assembly.

The compiler probably needs only one small addition: record whether the leading `RE_OP_ANYSTAR` was injected to implement unanchored search, so it can be distinguished from a real `.*`:

```c
struct ReCompiled {
  /* Existing fields... */
  unsigned bUnanchored : 1;
};
```

No regex recompilation, pattern rewriting, PCRE dependency, or alternative regex implementation is needed.

The resulting behavior remains:

```text
a|aa   on aa       → a, a
aa|a   on aa       → aa
a+     on aaa      → aaa
.*a    on a 1 a 2  → a 1 a
```

So yes: retain SQLite’s regexp compiler and VM. Extend only its execution semantics sufficiently to identify the selected match span.

---
---

## 📗 Specification

> [!NOTE] Prompt
> 
> Generate a comprehensive pro extension spec suitable for defining a full context (with references to SQLite sources being acceptable, no SQLite source in the spec) for implementation by a coding agent. Make sure to include among other things proper terminology, names of standard algos, etc. Focus testing on the public SQL surface via python/sqlite3/pytest.

Updated the specification to make Python 3.11’s `sqlite3` API under `pytest` the exclusive normative test surface.

Key changes:

* No direct C unit tests, Tcl harness, shell tests, or test-only SQL functions.
* Tests run against a Python `sqlite3` module linked to the custom amalgamation.
* Mandatory source-ID verification prevents accidental use of Python’s bundled SQLite.
* Defined pytest fixtures, test modules, parameterization, JSON assertions, errors, timeouts, and complexity testing.
* Internal VM components are tested transitively through the four public SQL functions.

---
---

## 📗 Implementation

> [!NOTE] Prompt
> 
> Proceed to full implementation per generated spec. Generate dedicated artifacts for the module source and structured pytest modules. Ensure comprehensive coverage of non-SQLite code by tests, including edge cases.

Implemented and verified.

Key outcomes:

* Added `regexp_matches(pattern, text)` and `regexpi_matches(pattern, text)`.
* Uses prioritized Pike VM semantics: first alternative wins; repetition remains greedy with required suffix fallback.
* Produces non-overlapping JSON arrays with correct empty-match and UTF-8 handling.
* Preserves the original boolean matcher.
* Uses SQLite’s private JSON builder and auto-extension registration.
* No SQLite version/source-ID pin. Optional mismatches only emit a pytest warning.
* 154 SQL-surface tests pass under normal, UBSan, and ASan builds.

---
---

## 📗 Factor out regexp_matches.c

> [!NOTE] Prompt
> 
> Now, what I actually meant is keeping SQLite regexp.c as is. The objective of this project is to make regexp_matches.c, solely implementing the missing functionality and fully relying on SQLite regexp.c and json.c for corresponding functionality. Is included into SQLite amalgamation after all stock modules have already been included. So you do not patch/extend regexp.c, but assume its functionality is available. So, the next step is to transform the patched regexp.c into regexp_matches.c.

Implemented the corrected architecture.

* Stock `regexp.c` is restored unchanged and is not bundled as project-owned code.
* New `regexp_matches.c` relies directly on SQLite’s private regexp compiler/VM structures, UTF-8 helpers, predicates, allocators, limits, and JSON builder.
* Extraction metadata lives in a separate cache wrapper; `ReCompiled` is untouched.
* A private initializer registers only `regexp_matches()` and `regexpi_matches()`.
* Build order and dual auto-extension registration are documented.
* 163 SQL-surface tests pass normally and under ASan+UBSan.
* Coverage: 92.01% of executable module lines; 100% of branch sites executed. Remaining lines are defensive allocation-failure/generation-wrap paths unavailable through deterministic Python SQL testing.
