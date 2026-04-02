# Phase 1: Core Type & Declaration Mapping

Goal: transpile C type declarations, struct definitions, enums, and function signatures
into valid PAK.

## 1.1 — Primitive Type Mapping

| C Type | PAK Type | Notes |
|--------|----------|-------|
| `char` / `signed char` | `i8` | |
| `unsigned char` / `uint8_t` / `u8` | `u8` | |
| `short` / `int16_t` / `s16` | `i16` | |
| `unsigned short` / `uint16_t` / `u16` | `u16` | |
| `int` / `int32_t` / `s32` | `i32` | |
| `unsigned int` / `uint32_t` / `u32` | `u32` | |
| `long long` / `int64_t` / `s64` | `i64` | |
| `unsigned long long` / `uint64_t` / `u64` | `u64` | |
| `float` | `f32` | |
| `double` | `f64` | |
| `_Bool` / `bool` | `bool` | |
| `void` | `void` | |
| `T *` | `*T` or `*mut T` | Mutability inferred from usage |
| `const T *` | `*T` (immutable pointer) | |
| `T[N]` | `[N]T` | PAK arrays use `[size]type` syntax |
| `void *` | `*u8` | Generic pointer → byte pointer |

Implementation in `type_mapper.py`:
- Resolve `typedef` chains first (e.g., `s32` → `int` → `i32`).
- Handle `const` qualifier: `const int *` → `*i32`, `int *const` → `*mut i32` (rare).
- Handle `volatile`: `volatile int *` → `*volatile i32` → PAK `TypeVolatile`.
- Decomp-specific types: `s8`/`s16`/`s32`/`s64`/`u8`/`u16`/`u32`/`u64`/`f32`/`f64` are
  standard in N64 decomps — map directly.

## 1.2 — Struct Mapping

```c
// C input
typedef struct {
    float x, y;
} Vec2;

typedef struct {
    Vec2 pos;
    int hp;
    unsigned char level;
} Player;
```

→

```pak
// PAK output
struct Vec2 { x: f32, y: f32 }

struct Player {
    pos: Vec2,
    hp: i32,
    level: u8,
}
```

### Rules

- `typedef struct { ... } Name;` → `struct Name { ... }`
- `struct Name { ... };` → `struct Name { ... }`
- Anonymous structs: generate a name from context (field name, parent struct, or `_AnonN`).
- Multi-declarator fields: `float x, y;` → two separate fields `x: f32, y: f32`.
- Bit-fields: expand to the next-larger integer type + emit a comment noting the original
  bit-width. PAK has no bit-fields; manual bit-masking helpers can be generated.
- `__attribute__((aligned(N)))` → `@aligned(N)`.
- `__attribute__((packed))` → `@packed` annotation.
- Flexible array members (`T data[];` at end of struct) → slice field or fixed-size array
  with a comment.

## 1.3 — Enum Mapping

```c
// C input
typedef enum {
    DIR_UP,
    DIR_DOWN,
    DIR_LEFT,
    DIR_RIGHT
} Direction;

typedef enum {
    STATE_IDLE = 0,
    STATE_ACTIVE = 1,
    STATE_DEAD = 2,
} State;
```

→

```pak
// PAK output
enum Direction { up, down, left, right }

enum State { idle, active, dead }
```

### Rules

- Strip common prefixes (`DIR_`, `STATE_`) and convert to snake_case.
- Explicit values: preserve if non-sequential; omit if they match auto-increment (0, 1, 2...).
- Enums used as bitflags (values are powers of 2): keep explicit values, add `// bitflags` comment.
- Typed enums (GCC `enum : uint8_t`): map base type → `enum Name: u8 { ... }`.
- Enum values used in arithmetic: leave as integer constants, don't map to PAK enum.

## 1.4 — Union Mapping

### Tagged Union Pattern (→ variant)

```c
// C input — tagged union
typedef enum { ENTITY_PLAYER, ENTITY_ENEMY, ENTITY_NONE } EntityType;
typedef struct {
    EntityType type;
    union {
        struct { Vec2 pos; int hp; } player;
        struct { uint8_t ai_state; } enemy;
    };
} Entity;
```

→

```pak
// PAK output
variant Entity {
    player { pos: Vec2, hp: i32 }
    enemy { ai_state: u8 }
    none
}
```

This is handled by `idiom_detector.py` (Phase 3) but the structural mapping lives here.
Detection criteria:
- A struct contains an enum field used as a discriminant (tag).
- The struct contains a union of structs as payload.
- Switch statements on the tag field → `match` on the variant.

### Raw Union (no tag)

```c
union { int i; float f; } val;
```

→

```pak
union IntFloat { i: i32, f: f32 }
```

PAK supports raw `union` types for this case.

## 1.5 — Typedef Handling

| C Pattern | PAK Mapping |
|-----------|-------------|
| `typedef int s32;` | Inline — replace all `s32` with `i32` |
| `typedef struct { ... } Name;` | `struct Name { ... }` |
| `typedef enum { ... } Name;` | `enum Name { ... }` |
| `typedef void (*Callback)(int);` | `type Callback = fn(i32)` or inline at use sites |
| `typedef T Name;` (simple alias) | Inline — replace `Name` with the mapped PAK type |
| `typedef struct Name Name;` (forward decl) | Drop — PAK doesn't need forward declarations |

Build a typedef resolution table during the first pass over declarations. All subsequent
mapping uses resolved types.

## 1.6 — Function Signature Mapping

```c
// C input
int factorial(int n);
void player_take_damage(Player *self, int dmg);
Vec2 vec2_add(Vec2 a, Vec2 b);
static int helper(int x) { return x * 2; }
```

→

```pak
// PAK output
fn factorial(n: i32) -> i32

// inside impl Player:
fn take_damage(self: *mut Player, dmg: i32)

// inside impl Vec2:
fn add(a: Vec2, b: Vec2) -> Vec2

fn helper(x: i32) -> i32   // static → module-private (no pub)
```

### Rules

- `void` return → omit return type in PAK.
- Pointer params: `T *` → `*mut T` if the function writes through it, `*T` otherwise.
  (Determined by const-qualifier or by write-analysis in Phase 2.)
- Detect method patterns: if first param is `StructName *` with name `self`/`this`/matching
  the struct name, hoist into an `impl StructName {}` block and strip the prefix from the
  function name (`player_take_damage` → `Player.take_damage`).
- `static` functions: emit without `pub` marker (module-private).
- Variadic functions (`...`): emit as `extern fn` declarations.
- `inline` functions: emit as normal `fn` (PAK has no inline keyword; the MIPS backend
  can inline at its discretion).

## 1.7 — Global & Static Variable Mapping

```c
// C input
int counter = 0;
static float speed = 1.5f;
const int MAX_ENTITIES = 64;
#define SCREEN_WIDTH 320
```

→

```pak
// PAK output
static mut counter: i32 = 0
static speed: f32 = 1.5
const MAX_ENTITIES: i32 = 64
const SCREEN_WIDTH: i32 = 320
```

### Rules

- `const` globals → PAK `const`.
- `#define` integer/float constants → PAK `const` (handled in Phase 4, listed here for context).
- Non-const globals → `static mut`.
- `static` globals (file-scope) → `static` (module-private).
- `extern` globals → `extern const` or `extern static` declaration.

## 1.8 — Milestone Test

```c
typedef struct { float x, y; } Vec2;
typedef enum { DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT } Direction;

Vec2 vec2_add(Vec2 a, Vec2 b) {
    Vec2 result;
    result.x = a.x + b.x;
    result.y = a.y + b.y;
    return result;
}

int main(void) {
    Vec2 pos = {1.0f, 2.0f};
    Vec2 vel = {0.5f, -0.3f};
    Vec2 new_pos = vec2_add(pos, vel);
    return 0;
}
```

Must produce valid, compilable PAK that passes the existing PAK parser and type checker.
