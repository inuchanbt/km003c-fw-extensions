/* SPDX-License-Identifier: MIT */
#include "screen_store.h"
#include <string.h>
enum { PAIR = KSC_SECTOR * 2, ERASE = 4096 };
static bool geometry(const struct ksc_store *s) {
    return s && s->base && s->bytes && s->bytes <= 0x400000 && s->bytes % PAIR == 0;
}
static bool blank(const uint8_t *p, size_t n) {
    while (n--) if (*p++ != 255) return false;
    return true;
}
static uint32_t word(const uint8_t *p) { uint32_t n; memcpy(&n, p, 4); return n; }
/* A complete complemented head claims an entire bounded reservation, even
 * if power failed before its footer/commit. Clear erases this head last. */
static uint32_t span(const uint8_t *p, uint32_t available) {
    uint32_t n = word(p + 8);
    return word(p) == KSC_SPAN_OWNER && word(p + 4) == ~KSC_SPAN_OWNER &&
        n >= PAIR && n <= KSC_MAX_SPAN && n <= available && n % PAIR == 0 &&
        word(p + 12) == ~n ? n : 0;
}
bool ksc_store_safe(const struct ksc_store *s) {
    if (!geometry(s)) return false;
    for (uint32_t pair = 0; pair < s->bytes; pair += PAIR) {
        uint32_t n = span(s->base + pair, s->bytes - pair);
        if (n) { pair += n - PAIR; continue; }
        for (unsigned sector = 0; sector < 2; ++sector)
            if (!blank(s->base + pair + sector * KSC_SECTOR, KSC_SECTOR) &&
                !ksc_storage_owned_sector(s->base + pair, sector)) return false;
    }
    return true;
}
void ksc_store_mount(const struct ksc_store *s, struct ksc_catalog *c, uint32_t *seq) {
    if (!geometry(s)) return;
    for (uint32_t at = 0; at < s->bytes; at += PAIR) {
        const uint8_t *p = s->base + at;
        uint32_t n = span(p, s->bytes - at);
        if (!n) { ksc_catalog_add_pair(c, p, seq); continue; }
        uint32_t size = word(p + 16), sequence = word(p + 24);
        if (sequence && sequence <= 999999 && word(p + 28) == ~sequence && sequence >= *seq) *seq = sequence + 1;
        if (!memcmp(p, p + n - KSC_OWNER_BYTES, KSC_OWNER_BYTES) &&
            size && size <= n - KSC_OWNER_BYTES * 2 - KSC_RECORD_BYTES && word(p + 20) == ~size &&
            sequence && sequence <= 999999 && word(p + 28) == ~sequence &&
            word(p + 36) == KSC_COMMIT && ksc_crc(p + 40, size) == word(p + 32) && c->count < KSC_FILES)
            c->files[c->count++] = (struct ksc_file){p + 40, size};
        at += n - PAIR;
    }
    ksc_catalog_sort(c);
}
static bool write(const struct ksc_store *s, uint32_t at, const uint8_t *data, size_t n) {
    if (!s->program || at > s->bytes || n > s->bytes - at || !blank(s->base + at, n)) return false;
    if (!s->program(at, data, n)) return false;
    return memcmp(s->base + at, data, n) == 0;
}
bool ksc_store_begin(const struct ksc_store *s, size_t n, uint32_t seq, struct ksc_store_txn *t) {
    if (!t) return false;
    memset(t, 0, sizeof(*t));
    if (!n || n > KSC_MAX_CAPTURE_BYTES || !seq || seq > 999999 || !ksc_store_safe(s)) return false;
    bool wide = n > KSC_MAX_BYTES, found = false;
    uint32_t extent = n > KSC_MAX_WIDE_BYTES ? (uint32_t)((n + 56 + PAIR - 1) / PAIR * PAIR) : PAIR;
    uint32_t chosen = 0, at = 0;
    struct ksc_catalog ignored = {0}; uint32_t next = 1;
    ksc_store_mount(s, &ignored, &next);
    if (ignored.count >= KSC_FILES || seq < next) return false;
    for (uint32_t pair = 0; pair < s->bytes; pair += PAIR) {
        const uint8_t *p = s->base + pair;
        uint32_t reserved = span(p, s->bytes - pair);
        if (reserved) { pair += reserved - PAIR; continue; }
        if (wide) {
            if (extent <= s->bytes - pair && blank(p, extent)) { chosen = pair; at = KSC_OWNER_BYTES; found = true; break; }
        } else {
            if (ksc_wide_owned(p) || ksc_wide_owned(p + PAIR - KSC_OWNER_BYTES)) continue;
            for (unsigned sector = 0; sector < 2; ++sector) {
                uint32_t base = pair + sector * KSC_SECTOR;
                size_t offset = ksc_scan_sector(s->base + base, &ignored, &next);
                if (!offset && blank(s->base + base, KSC_SECTOR)) offset = KSC_OWNER_BYTES;
                if (offset && ((n + 3u) & ~3u) + KSC_RECORD_BYTES <= KSC_SECTOR - offset) {
                    chosen = base; at = (uint32_t)offset; found = true; break;
                }
            }
            if (found) break;
        }
    }
    if (!found) return false;
    if (wide || !ksc_owned(s->base + chosen)) {
        uint32_t tag = extent > PAIR ? KSC_SPAN_OWNER : wide ? KSC_WIDE_OWNER : KSC_OWNER;
        uint32_t info = extent > PAIR ? extent : KSC_GEOMETRY;
        const uint32_t owner[] = {tag, ~tag, info, ~info};
        if (!write(s, chosen, (const uint8_t *)owner, sizeof(owner))) return false;
        if (wide && !write(s, chosen + extent - KSC_OWNER_BYTES, (const uint8_t *)owner, sizeof(owner))) return false;
    }
    at += chosen;
    const uint32_t header[] = {(uint32_t)n, ~(uint32_t)n, seq, ~seq};
    if (!write(s, at, (const uint8_t *)header, sizeof(header))) return false;
    *t = (struct ksc_store_txn){s, at, (uint32_t)n, 0, false};
    return true;
}
bool ksc_store_put(struct ksc_store_txn *t, const uint8_t *data, size_t n) {
    if (!t || !t->store || t->failed) return false;
    if (!data || !n || t->written > t->size || n > t->size - t->written ||
        !write(t->store, t->at + KSC_RECORD_BYTES + t->written, data, n)) {
        t->failed = true; return false;
    }
    t->written += (uint32_t)n; return true;
}
bool ksc_store_commit(struct ksc_store_txn *t, uint32_t crc) {
    if (!t || !t->store || t->failed) return false;
    t->failed = true; /* No retry or second commit on a used transaction. */
    const struct ksc_store *s = t->store;
    if (t->written != t->size || ksc_crc(s->base + t->at + KSC_RECORD_BYTES, t->size) != crc ||
        !write(s, t->at + 16, (const uint8_t *)&crc, 4)) return false;
    const uint32_t commit = KSC_COMMIT;
    return write(s, t->at + 20, (const uint8_t *)&commit, 4);
}
bool ksc_store_append(const struct ksc_store *s, const uint8_t *data, size_t n, uint32_t seq) {
    struct ksc_store_txn t;
    return data && ksc_store_begin(s, n, seq, &t) && ksc_store_put(&t, data, n) &&
        ksc_store_commit(&t, ksc_crc(data, n));
}
bool ksc_store_clear(const struct ksc_store *s) {
    if (!s || !s->erase4k || !ksc_store_safe(s)) return false;
    for (uint32_t at = 0; at < s->bytes; at += KSC_SECTOR) {
        uint32_t extent = at % PAIR == 0 ? span(s->base + at, s->bytes - at) : 0;
        if (extent) {
            for (uint32_t end = extent; end; end -= ERASE) {
                uint32_t block = at + end - ERASE;
                if (blank(s->base + block, ERASE)) continue;
                if (!s->erase4k(block) || !blank(s->base + block, ERASE)) return false;
            }
            at += extent - KSC_SECTOR; continue;
        }
        if (blank(s->base + at, KSC_SECTOR)) continue;
        /* Erase the ownership-bearing 4 KiB last so a failed first erase can
         * be retried. Wide companions have their marker at the high end. */
        unsigned first = ksc_wide_owned(s->base + at + KSC_SECTOR - KSC_OWNER_BYTES) ? 0 : ERASE;
        for (unsigned i = 0; i < 2; ++i) {
            uint32_t block = at + (i ? ERASE - first : first);
            if (blank(s->base + block, ERASE)) continue;
            if (!s->erase4k(block) || !blank(s->base + block, ERASE)) return false;
        }
    }
    return true;
}
