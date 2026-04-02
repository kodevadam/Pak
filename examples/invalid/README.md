# Invalid Pak Examples — Documentation Only

> **IMPORTANT**: These files are **documentation only**. The bad code is
> commented out so the files can explain the mistake without actually failing
> to compile. Do NOT treat them as test cases.
>
> For **mechanically verified** failing examples with enforced error codes,
> see [`tests/invalid/`](../../tests/invalid/). Those files contain actual
> broken code and are tested by `pytest tests/test_invalid.py`.

---

These files show common mistakes when writing Pak, and explain the correct
alternatives. Each file passes `pak check` (because the wrong code is
commented out), but documents patterns that will fail.

| File | What it demonstrates |
|------|---------------------|
| `no_main.pak` | `fn main()` instead of `entry {}` |
| `wrong_operators.pak` | C-style `&&`, `\|\|`, `!` |
| `implicit_cast.pak` | Implicit numeric conversion |
| `wrong_result.pak` | Wrong Result syntax |
| `int_match.pak` | Matching on integer values |
| `exceptions.pak` | Exception-style error handling |
| `semicolons.pak` | Rust/C-style semicolons on every line |
| `null_keyword.pak` | Using `null` instead of `none` |
| `void_return.pak` | Declaring `-> void` return type |
| `wrong_containers.pak` | Invented container APIs |

## Enforced Tests (tests/invalid/)

| File | Error Code | What it tests |
|------|-----------|--------------|
| `e001_lex_error.pak` | E001 | Unterminated string literal |
| `e002_if_let.pak` | E002 | Rust-style `if let` not supported |
| `e002_let_underscore.pak` | E002 | `let _ = x` — `_` is not a valid identifier |
| `e010_undefined_var.pak` | E010 | Using an undeclared variable |
| `e103_no_entry.pak` | E103 | Function but no `entry {}` block |
| `e201_dma_no_writeback.pak` | E201 | DMA without `cache.writeback` |
| `e202_dma_unaligned.pak` | E202 | DMA buffer not `@aligned(16)` |
| `e301_nonexhaustive_match.pak` | E301 | Non-exhaustive match on enum |
| `e401_use_after_move.pak` | E401 | Use of pointer variable after move |
