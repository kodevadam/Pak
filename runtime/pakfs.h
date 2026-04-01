/**
 * pakfs.h - PakFS runtime for Nintendo 64 (libdragon)
 *
 * PakFS is the asset filesystem for Pak language projects.
 * It registers a "pak:/" URI scheme with libdragon's filesystem,
 * serving files out of the PAKFS archive embedded in the ROM.
 *
 * Usage:
 *   1. Pack assets:   pak build  (produces build/mygame.pakfs)
 *   2. In your main:  pakfs_init("rom:/mygame.pakfs");
 *   3. Load assets:   sprite_load("pak:/hero.sprite");
 *
 * The archive is loaded into RAM once on startup; all subsequent
 * pak:/ opens are zero-copy reads directly from that buffer.
 */

#ifndef PAKFS_H
#define PAKFS_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Initialize PakFS from an archive on the ROM filesystem.
 *  Call once in main(), before loading any pak:/ assets.
 *  Returns true on success, false if the archive could not be loaded. */
bool pakfs_init(const char *rom_path);

/** Shut down PakFS and free the archive buffer. */
void pakfs_close(void);

/** Lookup a file in the archive. Returns a pointer to the file data
 *  and sets *size to its length. Returns NULL if not found.
 *  The pointer is valid until pakfs_close() is called. */
const void *pakfs_get(const char *name, uint32_t *size);

#ifdef __cplusplus
}
#endif

#endif /* PAKFS_H */
