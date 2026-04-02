# Claude Code Instructions for Pak

This file is automatically read by Claude Code at session startup.
Follow these instructions when working in this repository.

---

## Before Generating Any Pak Code

Read these files **in order** before writing or modifying `.pak` files:

1. **`LANGUAGE.md`** — the canonical syntax reference. Every construct you write must appear here.
2. **`NOT_SUPPORTED.md`** — hard list of things Pak does not have. If something is on this list, do not use it.
3. **`STDLIB.md`** — all builtin functions and N64 API modules. Do not invent function signatures.
4. **`examples/canonical/`** — small, correct reference examples. Prefer patterns shown here.

If a language feature is not documented in `LANGUAGE.md` and not demonstrated in `examples/canonical/`, do not use it. State uncertainty instead of guessing.

---

## Rules

- **Use only documented syntax.** No inventing keywords, operators, or constructs.
- **Use only documented APIs.** No inventing module names, function names, or signatures.
- **Prefer canonical examples** as templates for structure and style.
- **Mark implementation status.** `LANGUAGE.md` labels each feature `[IMPLEMENTED]`, `[PARTIAL]`, or `[PLANNED]`. Do not use `[PLANNED]` features in generated code.
- **Comments** use `--` (preferred) or `//`.
- **No semicolons** except where shown — Pak is mostly newline-delimited.
- **Entry point** is `entry { ... }`, not `main()` or `fn main`.

## When in Doubt

- Do not guess. Say "I'm not sure if Pak supports X — it's not in LANGUAGE.md."
- Do not use Rust, Zig, or C idioms unless they appear verbatim in Pak docs.
- If you need a feature that is `[PLANNED]`, say so and ask whether to implement a workaround.

---

## Quick Reference

```
-- comment syntax
use n64.display          -- import N64 module
asset bg: Sprite from "bg.png"  -- load asset

const MAX: i32 = 100

struct Foo { x: i32, y: f32 }

enum Dir { north, south, east, west }

variant Shape {
    circle(f32)
    rect(f32, f32)
}

fn add(a: i32, b: i32) -> i32 { return a + b }

impl Foo {
    fn new(self: *Foo) { self.x = 0 }
}

entry {
    let x: i32 = 42
    loop { ... }
}
```

See `LANGUAGE.md` for the full grammar.
