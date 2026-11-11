/* SPDX-License-Identifier: MIT. Reuse stock bus arbitration and single-page
 * commands. No bus initialization, chip erase, or native multi-page wrapper.
 */
#include "screen_nor.h"
#include <string.h>
#define FN(a, r, ...) ((r (*)(__VA_ARGS__))(uintptr_t)((a) | 1u))
void ksc207_nor_lock(void) { FN(0x4cbe6, void, void *)((void *)0x1fffb4c4u); }
void ksc207_nor_unlock(void) { FN(0x4ccec, void, void *)((void *)0x1fffb4c4u); }
static bool range(uint32_t offset, size_t n, uint32_t bytes) {
    return offset <= bytes && n <= bytes - offset;
}
static bool program_at(uint32_t begin, uint32_t end, uint32_t offset, const uint8_t *data, size_t n) {
    if (!data || !n || !range(offset, n, end - begin)) return false;
    uint32_t at = begin + offset;
    while (n) {
        size_t chunk = 256 - (at & 255); if (chunk > n) chunk = n;
        const uint8_t *mapped = (const uint8_t *)(uintptr_t)(KSC_NOR_MAP + at);
        for (size_t i = 0; i < chunk; ++i) if (mapped[i] != 255) return false;
        if (FN(0xce84, int, const uint8_t *, uint32_t, uint32_t)(data, at, (uint32_t)chunk) != 0 ||
            memcmp(mapped, data, chunk)) return false;
        data += chunk; at += (uint32_t)chunk; n -= chunk;
    }
    return true;
}
static bool erase_at(uint32_t begin, uint32_t end, uint32_t offset) {
    if ((offset & 4095) || !range(offset, 4096, end - begin)) return false;
    /* A full 1 MiB clear may outlast one watchdog period on a slow/failing
     * chip. Preserve the same ordered native feed between bounded commands. */
    *(volatile uint32_t *)0x40049008u = 0x0123u;
    *(volatile uint32_t *)0x40049008u = 0x3210u;
    return FN(0xccb6, int, uint32_t)(begin + offset) == 0;
}
static bool program(uint32_t o, const uint8_t *p, size_t n) { return program_at(KSC_NOR_BEGIN,KSC_NOR_END,o,p,n); }
static bool erase(uint32_t o) { return erase_at(KSC_NOR_BEGIN,KSC_NOR_END,o); }
static bool extra_program(uint32_t o, const uint8_t *p, size_t n) { return program_at(KSC_EXTRA_BEGIN,KSC_EXTRA_END,o,p,n); }
static bool extra_erase(uint32_t o) { return erase_at(KSC_EXTRA_BEGIN,KSC_EXTRA_END,o); }
const struct ksc_store ksc207_nor = {
    (const uint8_t *)(uintptr_t)(KSC_NOR_MAP + KSC_NOR_BEGIN),
    KSC_NOR_END - KSC_NOR_BEGIN, program, erase
};
const struct ksc_store ksc207_extra = {
    (const uint8_t *)(uintptr_t)(KSC_NOR_MAP + KSC_EXTRA_BEGIN),
    KSC_EXTRA_END - KSC_EXTRA_BEGIN, extra_program, extra_erase
};
enum { DOOM_CLAIM = 0x3144524bu, LAST_BLOCK = KSC_NOR_END - 4096 };
static const uint32_t claim[] = {DOOM_CLAIM, ~DOOM_CLAIM, KSC_NOR_END, ~KSC_NOR_END};
static bool claimed(void) {
    return !memcmp((const void *)(KSC_NOR_MAP + KSC_NOR_END - sizeof(claim)), claim, sizeof(claim));
}
static bool erased(uint32_t at, size_t n) {
    const uint8_t *p = (const uint8_t *)(uintptr_t)(KSC_NOR_MAP + at);
    while (n--) if (*p++ != 255) return false;
    return true;
}
__attribute__((noinline)) bool ksc207_nor_doom(void) {
    if (claimed()) return true;
    /* Only the asset pack whose first MiB was read twice and explicitly
     * approved for deletion. These are game-data fingerprints, not device
     * identity. Ignore the final block so an interrupted claim can retry. */
    static const uint8_t header[] = {
        0x44,0x4d,0x43,0x44,0x4f,0x4f,0x4d,0,1,0,0,0,0x50,0xc1,0x2a,0,
        0x50,0xc1,0x2a,0,0xed,0xe4,0x4f,0xf9,0x2e,0x13,7,0xaf,0x98,0,0x96,0xf1
    };
    return !memcmp((const void *)KSC_NOR_MAP, header, sizeof(header)) &&
        ksc_crc((const uint8_t *)KSC_NOR_MAP, LAST_BLOCK) == 0x23ed291fu;
}
__attribute__((noinline)) bool ksc207_nor_reclaim_doom(void) {
    if (!ksc207_nor_doom()) return false;
    /* Publish an ownership marker before touching the rest of the approved
     * pack. Preserve it until every other block has been erased and checked. */
    if (!claimed()) {
        if (!erase(LAST_BLOCK) || !erased(LAST_BLOCK, 4096) ||
            !program(KSC_NOR_END - sizeof(claim), (const uint8_t *)claim, sizeof(claim))) return false;
    }
    for (uint32_t at = 0; at < LAST_BLOCK; at += 4096) {
        if (erased(at, 4096)) continue;
        if (!erase(at) || !erased(at, 4096)) return false;
    }
    return erase(LAST_BLOCK) && erased(LAST_BLOCK, 4096);
}
