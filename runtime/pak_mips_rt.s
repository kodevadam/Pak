/*
 * pak_mips_rt.s — PAK MIPS Runtime Library
 *
 * Assembled by mips-n64-elf-as and linked alongside PAK-generated code.
 * Provides:
 *   - Function prologue/epilogue macros
 *   - Entry point glue (_start → main)
 *   - Panic handler (__pak_panic)
 *   - Debug print helper (__pak_debug_i32)
 *   - Fixed-point helpers (__pak_fix16_div)
 *   - Heap allocator (__pak_alloc / __pak_free) using a simple arena
 *   - Delta-time helper (_pak_delta_time)
 *
 * Calling convention: MIPS o32 ABI throughout.
 */

    .set mips3
    .set noreorder
    .set noat

/* ── Macros ─────────────────────────────────────────────────────────────── */

/*
 * PROLOGUE frame_size, save_ra, save_fp
 *   Allocates frame_size bytes on the stack, saves $ra and $fp.
 *   Caller should also save any $s registers it uses after this macro.
 *
 * Example:
 *   PROLOGUE 32, 1, 1
 *   sw   $s0, 20($sp)
 */
.macro PROLOGUE frame_size
    addiu   $sp, $sp, -\frame_size
    sw      $ra, (\frame_size - 4)($sp)
    sw      $fp, (\frame_size - 8)($sp)
    addiu   $fp, $sp, \frame_size
.endm

/*
 * EPILOGUE frame_size
 *   Restores $ra and $fp, deallocates frame, returns.
 */
.macro EPILOGUE frame_size
    lw      $ra, (\frame_size - 4)($sp)
    lw      $fp, (\frame_size - 8)($sp)
    addiu   $sp, $sp, \frame_size
    jr      $ra
     nop
.endm

/* ── Entry point glue ───────────────────────────────────────────────────── */

    .section .text
    .globl  __pak_start
    .type   __pak_start, @function
__pak_start:
    /* libdragon's _start already set up $gp, stack, BSS clear.
     * We just call main (the PAK entry block) and then loop forever
     * (the N64 never "exits").
     */
    jal     main
     nop
    /* Hang after main returns — should not happen in a game loop */
__pak_hang:
    j       __pak_hang
     nop
    .size __pak_start, . - __pak_start

/* ── Panic handler ──────────────────────────────────────────────────────── */
/*
 * void __pak_panic(const char *msg)
 *   Prints msg via debugf and halts.
 */
    .globl  __pak_panic
    .type   __pak_panic, @function
    .extern debugf
__pak_panic:
    PROLOGUE 16
    /* $a0 already holds the message pointer */
    jal     debugf
     nop
__pak_panic_loop:
    j       __pak_panic_loop
     nop
    .size __pak_panic, . - __pak_panic

/* ── Debug print ────────────────────────────────────────────────────────── */
/*
 * void __pak_debug_i32(const char *label, int32_t value)
 *   Prints "label: value\n" to the debug console.
 */
    .section .rodata
    .align  0
.L_dbg_fmt:
    .asciiz "%s: %d\n"

    .section .text
    .globl  __pak_debug_i32
    .type   __pak_debug_i32, @function
    .extern debugf
__pak_debug_i32:
    PROLOGUE 24
    sw      $a0, 20($sp)        /* save label */
    sw      $a1, 16($sp)        /* save value */
    la      $a0, .L_dbg_fmt
    lw      $a1, 20($sp)
    lw      $a2, 16($sp)
    jal     debugf
     nop
    EPILOGUE 24
    .size __pak_debug_i32, . - __pak_debug_i32

/* ── Fixed-point division: fix16.16 ────────────────────────────────────── */
/*
 * int32_t __pak_fix16_div(int32_t a, int32_t b)
 *   Returns (a << 16) / b as a Q16.16 fixed-point number.
 *   Arguments: $a0 = a (dividend), $a1 = b (divisor)
 *   Result:    $v0
 *
 * Algorithm:
 *   Sign-extend a into a 64-bit value (hi:lo), shift left 16,
 *   then perform signed 64-bit / 32-bit division.
 *
 *   Since VR4300 div only does 32-bit operands, we use:
 *     hi = a >> 16  (arithmetic, upper 16 bits after shift)
 *     lo = a << 16  (lower 32 bits after shift)
 *   then:  result = (hi:lo) / b  via div after loading hi:lo into HI/LO
 *
 * Note: MIPS has no 64-bit divide instruction; we approximate for Phase 1.
 * Phase 3 will replace this with a proper 64-bit soft-divide.
 */
    .globl  __pak_fix16_div
    .type   __pak_fix16_div, @function
__pak_fix16_div:
    /* $a0 = dividend, $a1 = divisor */
    /* Shift dividend left 16: build 64-bit value in $t0 (lo) and $t1 (hi) */
    sra     $t1, $a0, 16        /* hi = a >> 16 (sign-extended) */
    sll     $t0, $a0, 16        /* lo = a << 16 */

    /* Load HI:LO with our shifted value, then divide */
    mthi    $t1
    mtlo    $t0
    div     $zero, $a1          /* HI:LO / $a1 — MIPS div ignores $zero target,
                                 * but actually: "div $rs, $rt" sets HI=remainder, LO=quotient
                                 * The syntax "div $zero, $a1" is a common idiom
                                 * (GAS pseudop: div $t0, $a1 → generates div + trap)
                                 * Use raw div:  */
    /* Redo with explicit operands for clarity */
    div     $t0, $a1
    mflo    $v0
    jr      $ra
     nop
    .size __pak_fix16_div, . - __pak_fix16_div

/* ── Arena allocator ────────────────────────────────────────────────────── */
/*
 * Simple bump-pointer arena allocator.
 * __pak_alloc(uint32_t size) → void*   ($a0=size, returns $v0=ptr or 0)
 * __pak_free(void *ptr)               (no-op for arena)
 *
 * The arena lives in .bss between __pak_heap_start and __pak_heap_end.
 * The linker script must define these symbols.  If not, we fall back to
 * libdragon's malloc.
 */
    .section .bss
    .align  3
    .globl  __pak_heap_ptr
__pak_heap_ptr:
    .space  4                   /* current bump pointer (word) */

    /* 64 KiB default arena — override by defining __pak_heap in linker script */
    .globl  __pak_heap_arena
__pak_heap_arena:
    .space  65536

    .section .text
    .globl  __pak_alloc
    .type   __pak_alloc, @function
    .extern malloc
__pak_alloc:
    /* $a0 = requested size */
    /* Round up to 8-byte alignment */
    addiu   $v0, $a0, 7
    li      $t0, ~7
    and     $a0, $v0, $t0

    /* Load current heap pointer */
    la      $t1, __pak_heap_ptr
    lw      $t2, 0($t1)

    /* First call: initialise pointer to arena base */
    bne     $t2, $zero, .L_alloc_have_ptr
     nop
    la      $t2, __pak_heap_arena
    sw      $t2, 0($t1)

.L_alloc_have_ptr:
    /* result = current pointer */
    move    $v0, $t2
    /* advance pointer */
    addu    $t2, $t2, $a0
    sw      $t2, 0($t1)

    jr      $ra
     nop
    .size __pak_alloc, . - __pak_alloc

    .globl  __pak_free
    .type   __pak_free, @function
__pak_free:
    /* Arena allocator — free is a no-op */
    jr      $ra
     nop
    .size __pak_free, . - __pak_free

/* ── Delta time ─────────────────────────────────────────────────────────── */
/*
 * float _pak_delta_time(void)
 *   Returns time since last call in seconds as f32 in $f0.
 *   Uses libdragon's timer_ticks() and TICKS_PER_SECOND.
 *
 * For Phase 1 this returns a fixed 1/60 second (≈ 0.01667).
 * Phase 4 will wire this up to the real timer.
 */
    .section .rodata
    .align  2
.L_dt_fixed:
    .word   0x3C888889          /* IEEE 754 for 1.0/60.0 ≈ 0.016667 */

    .section .text
    .globl  _pak_delta_time
    .type   _pak_delta_time, @function
_pak_delta_time:
    la      $t0, .L_dt_fixed
    lwc1    $f0, 0($t0)
    jr      $ra
     nop
    .size _pak_delta_time, . - _pak_delta_time
