# Canonical Pak Examples

These are the **gold-standard reference examples** for the Pak language.
Every file here is known-correct. Use them as templates.

Each example focuses on one concept. They are intentionally small.

| File | Concept |
|------|---------|
| `01_hello.pak` | Minimal program, entry block, debug output |
| `02_variables.pak` | `let`, `const`, `static`, assignment |
| `03_functions.pak` | `fn`, parameters, return values, pointer params |
| `04_structs.pak` | `struct`, struct literals, field access, `impl` methods |
| `05_enums.pak` | `enum`, discriminant types, `match` on enum |
| `06_variants.pak` | `variant` (tagged union), payload extraction in `match` |
| `07_control_flow.pak` | `if/elif/else`, `loop`, `while`, `do-while`, `for`, `break`, `continue` |
| `08_arrays.pak` | Fixed-size arrays, indexing, passing to functions |
| `09_pointers.pak` | `*T`, `*mut T`, `?*T`, `&`, `*`, `alloc`, `free` |
| `10_result.pak` | `Result(Ok, Err)`, `ok()`, `err()`, match on result |
| `11_defer.pak` | `defer` for cleanup |
| `12_const_static.pak` | `const` vs `static`, `@aligned` |
| `13_extern.pak` | `extern "C"` FFI, `extern const` |
| `14_assets.pak` | `asset` declarations, sprite rendering |
| `15_game_loop.pak` | Canonical N64 game loop structure |
| `16_fixed_point.pak` | `fix16.16` arithmetic |
| `17_annotations.pak` | `@hot`, `@aligned`, `@cfg` |
| `18_dma.pak` | DMA with cache writeback (safety pattern) |
| `19_traits.pak` | `trait`, `impl for`, trait objects [PARTIAL] |
| `20_multifile.pak` | `module`, multi-file structure [PARTIAL] |
