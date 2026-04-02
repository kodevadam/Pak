# Phase 2: Expression & Statement Transpilation

Goal: transpile C function bodies — expressions, assignments, control flow, and local
variables — into valid PAK statements.

## 2.1 — Expression Mapping

### Arithmetic & Bitwise

| C Expression | PAK Expression | Notes |
|-------------|----------------|-------|
| `a + b` | `a + b` | Direct |
| `a - b` | `a - b` | Direct |
| `a * b` | `a * b` | Direct |
| `a / b` | `a / b` | Direct |
| `a % b` | `a % b` | Direct |
| `a & b` | `a & b` | Direct |
| `a \| b` | `a \| b` | Direct |
| `a ^ b` | `a ^ b` | Direct |
| `a << b` | `a << b` | Direct |
| `a >> b` | `a >> b` | Arithmetic vs logical depends on signedness |
| `~a` | `~a` | Direct |
| `-a` | `-a` | Direct |

### Comparison & Logical

| C Expression | PAK Expression |
|-------------|----------------|
| `a == b` | `a == b` |
| `a != b` | `a != b` |
| `a < b` | `a < b` |
| `a > b` | `a > b` |
| `a <= b` | `a <= b` |
| `a >= b` | `a >= b` |
| `a && b` | `a && b` |
| `a \|\| b` | `a \|\| b` |
| `!a` | `!a` |

### Assignment

| C Expression | PAK Statement | Notes |
|-------------|---------------|-------|
| `a = b` | `a = b` | Direct |
| `a += b` | `a += b` | Direct (PAK supports compound assignment) |
| `a -= b` | `a -= b` | Direct |
| `a *= b` | `a *= b` | Direct |
| `a++` | `a += 1` | PAK has no `++`/`--` operators |
| `++a` | `a += 1` | Pre-increment: emit as separate statement |
| `a--` | `a -= 1` | |
| `a = b = c` | `b = c; a = b` | Split chained assignment |

**Increment/Decrement in expressions** is the hardest case. `arr[i++]` must become:
```pak
let _tmp = i
i += 1
arr[_tmp]
```
The transpiler must detect when `++`/`--` is used as a sub-expression and extract it.

### Pointers & Memory

| C Expression | PAK Expression | Notes |
|-------------|----------------|-------|
| `*ptr` | `*ptr` | Direct |
| `&x` | `&x` or `&mut x` | Mutability from context |
| `ptr->field` | `(*ptr).field` or `ptr.field` | PAK auto-derefs for dot access on pointers |
| `ptr[i]` | `ptr[i]` | Direct (pointer arithmetic = indexing) |
| `(T *)ptr` | `ptr as *T` | Pointer cast |
| `sizeof(T)` | `sizeof(T)` | Direct — PAK has `sizeof` |
| `offsetof(S, f)` | `offsetof(S, f)` | Direct — PAK has `offsetof` |
| `NULL` | `none` | Null literal |
| `malloc(sizeof(T))` | `alloc(T)` | PAK's allocation primitive |
| `free(ptr)` | `free(ptr)` | Direct |

### Casts

| C Cast | PAK Cast | Notes |
|--------|----------|-------|
| `(int)f` | `f as i32` | |
| `(float)i` | `i as f32` | |
| `(uint8_t)x` | `x as u8` | Truncation |
| `(T *)ptr` | `ptr as *T` | Pointer reinterpret |
| `(void)expr` | `expr` | Discard — just emit as expression statement |

### Ternary Operator

```c
int x = cond ? a : b;
```

→

```pak
let x: i32 = if cond { a } else { b }
```

PAK's `if` is an expression when used in a `let` binding context. The transpiler converts
C ternary `?:` into PAK `if/else` expression blocks.

### Comma Operator

```c
x = (a++, b++, a + b);
```

→

```pak
a += 1
b += 1
x = a + b
```

Flatten comma expressions into sequential statements. Only the last value is used.

## 2.2 — Statement Mapping

### Local Variables

```c
int x = 5;
float y;
const char *name = "hello";
Vec2 pos = {1.0f, 2.0f};
int arr[10] = {0};
```

→

```pak
let x: i32 = 5
let y: f32 = 0.0          // PAK requires initialization (or use undefined)
let name: *i8 = "hello"
let pos: Vec2 = Vec2 { x: 1.0, y: 2.0 }
let arr: [10]i32 = [0; 10]
```

Rules:
- Uninitialized variables: emit `= undefined` or zero-initialize with a comment.
- Struct initializers `{.field = val}` → PAK struct literals `StructName { field: val }`.
- Array initializers: map to PAK array literals.
- Multiple declarations on one line: `int a, b, c;` → three separate `let` statements.

### If / Else

```c
if (x > 0) {
    do_thing();
} else if (x == 0) {
    do_other();
} else {
    fallback();
}
```

→

```pak
if x > 0 {
    do_thing()
} elif x == 0 {
    do_other()
} else {
    fallback()
}
```

Rules:
- Strip parentheses from condition (PAK doesn't use them).
- `else if` → `elif`.
- Single-statement bodies: always wrap in braces (PAK requires them).
- Truthiness: `if (ptr)` → `if ptr != none`; `if (n)` → `if n != 0`.

### While / Do-While

```c
while (running) { update(); }
do { step(); } while (has_more);
```

→

```pak
while running { update() }
loop { step(); if !has_more { break } }
```

PAK has no `do-while`. Convert to `loop` + `if !cond { break }` at the end.

### For Loops

```c
// Counting for
for (int i = 0; i < n; i++) { body(); }

// Pointer iteration
for (T *p = arr; p < arr + len; p++) { use(*p); }

// Complex for (arbitrary init/step)
for (x = start; x != end; x = next(x)) { body(); }
```

→

```pak
// Counting for → range-based
for i in 0..n { body() }

// Pointer iteration → slice for-each
for item in arr { use(item) }

// Complex for → while
let x = start
while x != end {
    body()
    x = next(x)
}
```

Rules:
- Detect the common `for (int i = 0; i < N; i++)` pattern → PAK `for i in 0..N`.
- Detect pointer walks → PAK `for item in slice`.
- All other `for` loops → `while` with init before, step at end of body.
- `for (;;)` → `loop`.

### Switch / Case

```c
switch (dir) {
    case DIR_UP:    y -= 1; break;
    case DIR_DOWN:  y += 1; break;
    case DIR_LEFT:  x -= 1; break;
    case DIR_RIGHT: x += 1; break;
    default:        break;
}
```

→

```pak
match dir {
    .up => { y -= 1 }
    .down => { y += 1 }
    .left => { x -= 1 }
    .right => { x += 1 }
}
```

Rules:
- `switch` on enum → `match` with dot-prefixed cases.
- `switch` on integer → `match` with value patterns.
- Fall-through (no `break`): merge case bodies. Warn if intentional fall-through is detected.
- `default` → `_` wildcard pattern (if not exhaustive).
- Complex fall-through patterns: convert to if/elif chains with a comment.

### Goto / Labels

```c
    goto cleanup;
    // ...
cleanup:
    free(buf);
    return -1;
```

→

```pak
    goto cleanup
    // ...
    label cleanup
    free(buf)
    return -1
```

PAK supports `goto` and `label` for direct mapping. No transformation needed.
Many `goto cleanup` patterns should be detected and converted to `defer` in Phase 3.

### Return

```c
return expr;
return;
```

→

```pak
return expr
return
```

Direct mapping. Note: C's `return expr` where `expr` has side effects may need extraction.

## 2.3 — Function Body Transpilation

The overall strategy for function bodies:

1. **Pass 1 — Variable extraction**: Scan for all local declarations, determine types.
2. **Pass 2 — Statement mapping**: Walk the C AST, emit PAK statements.
3. **Pass 3 — Expression rewriting**: Flatten complex expressions (comma, pre/post-increment
   in sub-expressions, nested assignments).

### Handling C's Expression-Heavy Style

C loves embedding side effects in expressions. PAK is more statement-oriented. Key
transformations:

```c
// C: assignment in condition
while ((ch = getchar()) != EOF) { ... }

// PAK:
loop {
    let ch = getchar()
    if ch == EOF { break }
    ...
}
```

```c
// C: increment in array index
arr[idx++] = val;

// PAK:
arr[idx] = val
idx += 1
```

```c
// C: multiple side effects in one expression
result = (a = compute(), b = transform(a), combine(a, b));

// PAK:
a = compute()
b = transform(a)
result = combine(a, b)
```

## 2.4 — Milestone Test

```c
int gcd(int a, int b) {
    while (b != 0) {
        int temp = b;
        b = a % b;
        a = temp;
    }
    return a;
}

void bubble_sort(int *arr, int n) {
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int tmp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = tmp;
            }
        }
    }
}
```

Must produce valid, compilable PAK with correct runtime behavior matching the C version.
