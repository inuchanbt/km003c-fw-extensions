/* SPDX-License-Identifier: MIT. Portable core test boundary. */
#include "screen_msc.h"
#include <string.h>
struct test_screen { struct ksc_catalog catalog; struct ksc_disk disk; struct ksc_msc msc; };
size_t screen_context_size(void) { return sizeof(struct test_screen); }
void screen_name(const uint8_t *data, unsigned size, unsigned sequence, char out[36]) {
    uint8_t record[24 + KSC_META_BYTES] = {0};
    memcpy(record + 8, &sequence, 4);
    memcpy(record + 24, data, size < KSC_META_BYTES ? size : KSC_META_BYTES);
    const struct ksc_file f = {record + 24, size}; ksc_file_name(&f, out);
}
size_t screen_encode_height(const uint16_t *pixels, unsigned height, uint8_t *out, size_t capacity) {
    if (height < KSC_HEIGHT || height > KSC_MAX_HEIGHT) return 0;
    struct ksc_encoder e; ksc_encode_init(&e, out, capacity); e.pixels = height * KSC_WIDTH;
    for (unsigned i = 0; i < e.pixels; i += KSC_WIDTH)
        if (!ksc_encode_pixels(&e, pixels + i, KSC_WIDTH)) return 0;
    return ksc_encode_finish(&e);
}
size_t screen_encode(const uint16_t *pixels, uint8_t *out, size_t capacity, unsigned chunk) {
    struct ksc_encoder e; ksc_encode_init(&e, out, capacity);
    for (unsigned i = 0; i < KSC_PIXELS;) {
        unsigned n = KSC_PIXELS - i; if (n > chunk) n = chunk;
        if (!ksc_encode_pixels(&e, pixels + i, n)) return 0;
        i += n;
    }
    return ksc_encode_finish(&e);
}
struct test_sink { uint8_t *out; size_t used, limit; };
static bool sink_bytes(void *context, const uint8_t *data, size_t n) {
    struct test_sink *s = context;
    if (n > s->limit - s->used) return false;
    memcpy(s->out + s->used, data, n); s->used += n; return true;
}
size_t screen_encode_sink(const uint16_t *pixels, uint8_t *out, size_t capacity, unsigned chunk, size_t fail_after) {
    struct test_sink sink = {out, 0, fail_after < capacity ? fail_after : capacity};
    struct ksc_encoder e; ksc_encode_sink(&e, sink_bytes, &sink, capacity);
    for (unsigned i = 0; i < KSC_PIXELS;) {
        unsigned n = KSC_PIXELS - i; if (n > chunk) n = chunk;
        if (!ksc_encode_pixels(&e, pixels + i, n)) return 0;
        i += n;
    }
    size_t n = ksc_encode_finish(&e); return n == sink.used ? n : 0;
}
int screen_decode(const uint8_t *data, size_t n, uint16_t *out) {
    struct ksc_decoder d; ksc_decode_init(&d, data, n);
    for (unsigned i = 0; i < KSC_PIXELS; ++i) if (!ksc_decode_pixel(&d, out + i)) return 0;
    return ksc_decode_finish(&d);
}
unsigned screen_mount(struct test_screen *s, const uint8_t *flash) {
    ksc_catalog_init(&s->catalog, flash); ksc_disk_init(&s->disk, &s->catalog);
    ksc_msc_init(&s->msc, &s->catalog); return s->catalog.count;
}
int screen_block(struct test_screen *s, unsigned block, uint8_t *out) { return ksc_disk_read(&s->disk, block, out); }
int screen_out(struct test_screen *s, const uint8_t *p, size_t n) { return ksc_msc_out(&s->msc, p, n); }
int screen_in(struct test_screen *s) { return ksc_msc_in_done(&s->msc); }
unsigned screen_tx(struct test_screen *s, uint8_t *out) { memcpy(out, s->msc.tx, s->msc.tx_size); return s->msc.tx_size; }
unsigned screen_phase(struct test_screen *s) { return s->msc.phase; }
void screen_reset(struct test_screen *s) { ksc_msc_reset(&s->msc); }
size_t screen_scan(const uint8_t *sector) { struct ksc_catalog c = {0}; uint32_t seq = 1; return ksc_scan_sector(sector, &c, &seq); }
unsigned screen_owned_sector(const uint8_t *storage, unsigned sector) { return ksc_storage_owned_sector(storage, sector); }
