# Pak Standard Library and Builtin Reference

This is the canonical reference for everything that exists in Pak outside of
user-defined code. Do not invent functions, modules, or types not listed here.

---

## Built-in Keywords / Expressions

These are built into the language — not imported, not from a module.

### Memory

```pak
alloc(T)          -- allocate one T on the heap, returns *T
alloc(T, n)       -- allocate n T's on the heap (array), returns *T
free(ptr)         -- free a heap-allocated pointer
```

### Type Introspection

```pak
sizeof(Type)             -- byte size of a type (compile-time constant)
sizeof(expr)             -- byte size of expression's type
offsetof(StructName, field)  -- byte offset of struct field (compile-time)
alignof(Type)            -- alignment requirement of a type
align_of(Type)           -- alias for alignof
size_of(Type)            -- alias for sizeof
```

### Result Constructors

```pak
ok(value)          -- construct Result in Ok state
err(value)         -- construct Result in Err state
```

These are keywords, not function calls. They cannot be overloaded.

---

## Built-in Types (not imported)

```pak
i8 u8 i16 u16 i32 u32 i64 u64   -- integers
f32 f64                           -- floats
bool                              -- boolean
byte                              -- alias for u8
c_char                            -- C char, for FFI strings
fix16.16  fix10.5  fix1.15        -- fixed-point numbers
```

Generic containers (parameterized, no import needed):

```pak
Result(OkType, ErrType)   -- error-or-value type
Option(T)                  -- nullable value
Vec(T)                     -- growable heap array      [PARTIAL]
FixedList(T, N)            -- fixed-capacity list      [PARTIAL]
RingBuffer(T, N)           -- ring buffer              [PARTIAL]
FixedMap(K, V, N)          -- fixed-capacity hash map  [PARTIAL]
Pool(T, N)                 -- object pool              [PARTIAL]
```

---

## N64 Modules

Import with `use n64.module_name` before use.
Call functions as `module_name.function(args)`.

---

### `n64.display` — Framebuffer Output

```pak
use n64.display
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `display.init` | `(resolution: u32, bit_depth: u32, num_buffers: i32, gamma: u32, filters: u32)` | Initialize display subsystem |
| `display.get` | `() -> *surface_t` | Get the next available framebuffer surface |
| `display.show` | `(surface: *surface_t)` | Show/flip a surface to screen |
| `display.close` | `()` | Shut down display |

Common constants (declare as `extern const` or use raw values):
- Resolution: `RESOLUTION_320x240`, `RESOLUTION_256x240`, `RESOLUTION_640x480`
- Depth: `DEPTH_16_BPP`, `DEPTH_32_BPP`
- Gamma: `GAMMA_NONE`
- Filters: `FILTERS_RESAMPLE`, `FILTERS_DISABLED`

---

### `n64.controller` — Joypad Input

```pak
use n64.controller
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `controller.init` | `()` | Initialize joypad subsystem |
| `controller.poll` | `()` | Poll joypad state (call once per frame) |
| `controller.read` | `(port: i32) -> joypad_status_t` | Read current state for port 0–3 |

The returned `joypad_status_t` struct has fields:
```pak
-- accessed as: let input = controller.read(0)
input.held.a        -- bool: A button held
input.held.b        -- bool: B button held
input.held.start    -- bool: Start held
input.held.up       -- bool: D-pad up held
input.held.down     -- bool: D-pad down held
input.held.left     -- bool: D-pad left held
input.held.right    -- bool: D-pad right held
input.held.z        -- bool: Z trigger held
input.held.l        -- bool: L trigger held
input.held.r        -- bool: R trigger held
input.held.c_up     -- bool: C-up held
input.held.c_down   -- bool: C-down held
input.held.c_left   -- bool: C-left held
input.held.c_right  -- bool: C-right held
input.pressed.*     -- same fields but only true on the frame pressed
input.released.*    -- same fields but only true on the frame released
input.stick_x       -- i8: analog stick X (-128 to 127)
input.stick_y       -- i8: analog stick Y (-128 to 127)
```

---

### `n64.rdpq` — RDP Graphics (2D Rendering)

```pak
use n64.rdpq
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `rdpq.init` | `()` | Initialize RDP queue |
| `rdpq.close` | `()` | Shut down RDP queue |
| `rdpq.attach` | `(surface: *surface_t)` | Attach RDP output to surface |
| `rdpq.attach_clear` | `(surface: *surface_t)` | Attach and clear surface |
| `rdpq.detach` | `()` | Detach current surface |
| `rdpq.detach_show` | `()` | Detach and show surface (flip) |
| `rdpq.set_mode_standard` | `()` | Set standard rendering mode |
| `rdpq.set_mode_copy` | `()` | Set fast copy rendering mode |
| `rdpq.set_mode_fill` | `(color: u32)` | Set fill mode with color |
| `rdpq.fill_rectangle` | `(x0: i32, y0: i32, x1: i32, y1: i32)` | Draw filled rectangle |
| `rdpq.set_scissor` | `(x0: i32, y0: i32, x1: i32, y1: i32)` | Set scissor rectangle |
| `rdpq.sync_full` | `()` | Wait for RDP to finish all commands |
| `rdpq.sync_pipe` | `()` | Sync RDP pipeline state |
| `rdpq.sync_tile` | `()` | Sync RDP tile state |
| `rdpq.sync_load` | `()` | Sync RDP texture load |

---

### `n64.sprite` — 2D Sprite Rendering

```pak
use n64.sprite
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `sprite.load` | `(path: *c_char) -> *sprite_t` | Load a sprite from filesystem |
| `sprite.blit` | `(sprite: *sprite_t, x: i32, y: i32, flags: u32)` | Draw sprite at (x, y) |

---

### `n64.timer` — Timing

```pak
use n64.timer
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `timer.init` | `()` | Initialize timer subsystem |
| `timer.delta` | `() -> f32` | Delta time in seconds since last call |
| `timer.get_ticks` | `() -> u64` | Get raw timer tick count |

---

### `n64.audio` — Audio Playback

```pak
use n64.audio
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `audio.init` | `(frequency: i32, buffers: i32)` | Initialize audio |
| `audio.close` | `()` | Shut down audio |
| `audio.get_buffer` | `() -> *i16` | Get pointer to audio output buffer |

---

### `n64.debug` — Debug Output

```pak
use n64.debug
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `debug.log` | `(msg: *c_char)` | Print debug string (via USB/IS-Viewer) |
| `debug.assert` | `(cond: bool)` | Halt if condition is false |
| `debug.log_value` | `(fmt: *c_char, val: i32)` | Print formatted value |

These output to the libdragon debug channel. No output on retail hardware unless
connected to development hardware.

---

### `n64.dma` — Direct Memory Access

```pak
use n64.dma
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `dma.read` | `(dst: *u8, src: u32, len: u32)` | DMA from ROM/PI to RAM |
| `dma.write` | `(src: *u8, dst: u32, len: u32)` | DMA from RAM to peripheral |
| `dma.wait` | `()` | Wait for DMA to complete |

**Safety requirements (enforced by typechecker):**
- `dst` must be `@aligned(16)` (E202)
- `cache.writeback(dst, len)` must be called before DMA write (E201)

---

### `n64.cache` — Cache Management

```pak
use n64.cache
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `cache.writeback` | `(ptr: *u8, len: u32)` | Writeback cache lines |
| `cache.invalidate` | `(ptr: *u8, len: u32)` | Invalidate cache lines |
| `cache.writeback_inv` | `(ptr: *u8, len: u32)` | Writeback and invalidate |

---

### `n64.eeprom` — EEPROM Save Storage

```pak
use n64.eeprom
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `eeprom.present` | `() -> bool` | Check if EEPROM is present |
| `eeprom.type_detect` | `() -> i32` | Detect EEPROM type |
| `eeprom.read` | `(block: i32, dst: *u8) -> i32` | Read EEPROM block |
| `eeprom.write` | `(block: i32, src: *u8) -> i32` | Write EEPROM block |

---

### `n64.rumble` — Rumble Pak

```pak
use n64.rumble
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `rumble.init` | `()` | Initialize rumble |
| `rumble.start` | `(port: i32)` | Start rumble on port |
| `rumble.stop` | `(port: i32)` | Stop rumble on port |

---

### `n64.cpak` — Controller Pak (Memory Card)

```pak
use n64.cpak
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `cpak.init` | `()` | Initialize controller pak |
| `cpak.is_plugged` | `(port: i32) -> bool` | Check if pak is plugged in |
| `cpak.is_formatted` | `(port: i32) -> bool` | Check if pak is formatted |
| `cpak.format` | `(port: i32)` | Format controller pak |
| `cpak.read_sector` | `(port: i32, sector: i32, dst: *u8) -> i32` | Read sector |
| `cpak.write_sector` | `(port: i32, sector: i32, src: *u8) -> i32` | Write sector |
| `cpak.get_free_space` | `(port: i32) -> i32` | Get free space in pages |

---

### `n64.tpak` — Transfer Pak

```pak
use n64.tpak
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `tpak.init` | `(port: i32)` | Initialize transfer pak |
| `tpak.set_value` | `(port: i32, address: u16, value: u8)` | Write to Game Boy memory |
| `tpak.get_value` | `(port: i32, address: u16) -> u8` | Read from Game Boy memory |

---

## 3D Library (T3D)

Import with `use t3d`.

### `t3d` — Tiny3D Core

```pak
use t3d
```

| Function | Description |
|----------|-------------|
| `t3d.init()` | Initialize T3D library |
| `t3d.destroy()` | Shut down T3D |
| `t3d.frame_start()` | Begin a 3D frame |
| `t3d.frame_end()` | End/submit a 3D frame |
| `t3d.screen_projection(...)` | Set screen projection |
| `t3d.viewport_create() -> T3DViewport` | Create viewport |
| `t3d.viewport_set_projection(vp: *T3DViewport, fov: f32, near: f32, far: f32)` | Set projection |
| `t3d.viewport_attach(vp: *T3DViewport)` | Attach viewport for rendering |
| `t3d.viewport_set_fov(vp: *T3DViewport, fov: f32)` | Set FOV |

### T3D Model

| Function | Description |
|----------|-------------|
| `t3d.model_load(path: *c_char) -> *T3DModel` | Load a `.t3dm` model |
| `t3d.model_free(model: *T3DModel)` | Free model |
| `t3d.model_draw(model: *T3DModel)` | Draw model |
| `t3d.draw_object(obj: *T3DObject)` | Draw a model object |

### T3D Math (matrix/vector — output pointer is first arg)

| Function | Description |
|----------|-------------|
| `t3d.mat4_identity(out: *T3DMat4)` | Set matrix to identity |
| `t3d.mat4_rotate_y(out: *T3DMat4, angle: f32)` | Rotation around Y |
| `t3d.mat4_rotate_x(out: *T3DMat4, angle: f32)` | Rotation around X |
| `t3d.mat4_rotate_z(out: *T3DMat4, angle: f32)` | Rotation around Z |
| `t3d.mat4_translate(out: *T3DMat4, x: f32, y: f32, z: f32)` | Translation |
| `t3d.mat4_scale(out: *T3DMat4, x: f32, y: f32, z: f32)` | Scale |
| `t3d.mat4_mul(out: *T3DMat4, a: *T3DMat4, b: *T3DMat4)` | Matrix multiply |
| `t3d.vec3_norm(out: *T3DVec3, v: *T3DVec3)` | Normalize vector |
| `t3d.vec3_cross(out: *T3DVec3, a: *T3DVec3, b: *T3DVec3)` | Cross product |
| `t3d.vec3_dot(a: *T3DVec3, b: *T3DVec3) -> f32` | Dot product |

### T3D Lighting

| Function | Description |
|----------|-------------|
| `t3d.light_set_ambient(r: u8, g: u8, b: u8)` | Set ambient light color |
| `t3d.light_set_directional(idx: i32, r: u8, g: u8, b: u8, x: f32, y: f32, z: f32)` | Set directional light |
| `t3d.light_set_count(count: i32)` | Set number of active lights |

### T3D Animation

| Function | Description |
|----------|-------------|
| `t3d.anim_create(model: *T3DModel, name: *c_char) -> T3DAnim` | Create animation |
| `t3d.anim_destroy(anim: *T3DAnim)` | Destroy animation |
| `t3d.anim_set_playing(anim: *T3DAnim, playing: bool)` | Play/pause |
| `t3d.anim_set_looping(anim: *T3DAnim, looping: bool)` | Set looping |
| `t3d.anim_set_speed(anim: *T3DAnim, speed: f32)` | Set playback speed |
| `t3d.anim_update(anim: *T3DAnim, dt: f32)` | Update animation |
| `t3d.anim_attach(anim: *T3DAnim, skel: *T3DSkeleton)` | Attach to skeleton |

### T3D Skeleton

| Function | Description |
|----------|-------------|
| `t3d.skeleton_create(model: *T3DModel) -> T3DSkeleton` | Create skeleton |
| `t3d.skeleton_destroy(skel: *T3DSkeleton)` | Destroy skeleton |
| `t3d.skeleton_update(skel: *T3DSkeleton)` | Update skeleton |
| `t3d.skeleton_draw(skel: *T3DSkeleton, model: *T3DModel)` | Draw skinned model |

---

## Runtime Helpers (Internal — Do Not Call Directly)

These are emitted by the compiler. Do not call them in Pak source:

- `__pak_fix16_div(dividend: i32, divisor: i32) -> i32` — fixed-point division
- `__pak_delta_time()` — used by `timer.delta()`

---

## What Does NOT Exist

- No `math` module — use raw arithmetic or C math via `extern "C"`
- No `string` module — use `*c_char` and C string functions via `extern "C"`
- No `io` module — no file I/O in the Pak stdlib
- No `os` module
- No `collections` module — use the built-in generic containers
- No `random` / `rand` module
- No networking
- No threading / concurrency primitives
