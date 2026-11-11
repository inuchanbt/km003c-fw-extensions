/* SPDX-License-Identifier: MIT */
#include "screen_codec.h"
#include <string.h>

static unsigned hash(uint16_t p) {
    return (((p >> 11) * 3u) + (((p >> 5) & 63u) * 5u) + ((p & 31u) * 7u)) & 63u;
}
static bool packed(struct ksc_encoder *e, const uint8_t *p, size_t n) {
    if (n > e->capacity - e->used) { e->used = e->capacity; e->failed = true; return false; }
    if (e->sink) {
        if (!e->sink(e->sink_context, p, n)) { e->failed = true; return false; }
    } else if (e->out) memcpy(e->out + e->used, p, n);
    e->used += n;
    return true;
}
static bool packed_byte(struct ksc_encoder *e, unsigned b) {
    uint8_t byte = (uint8_t)b; return !e->failed && packed(e, &byte, 1);
}
static void literals(struct ksc_encoder *e, unsigned at, unsigned n) {
    if (n && packed_byte(e, n - 1)) (void)packed(e, e->pending + at, n);
}
static unsigned lz_hash(const uint8_t *p) { return (p[0] * 3u + p[1] * 5u + p[2] * 7u) & 127u; }
static void pack_pending(struct ksc_encoder *e) {
    unsigned i = 0, literal_count = 0, literal_at = 0;
    while (i < e->pending_size && !e->failed) {
        unsigned best = 0, distance = 0, saving = 0;
        uint32_t current = e->total + i;
        if (i + 3 <= e->pending_size) {
            uint32_t prior = e->positions[lz_hash(e->pending + i)];
            /* Bounded hash chains find repeated glyphs beyond the most recent
             * hash collision. All history stays in the allocated encoder. */
            for (unsigned tries = 0; prior && tries < 16; ++tries) {
                uint32_t source_at = prior - 1;
                if (source_at >= current || current - source_at > 1024) break;
                unsigned d = current - source_at, match = 0, cost = d <= 256 ? 2 : 3;
                unsigned limit = d <= 256 ? 130 : 67;
                while (match < limit && i + match < e->pending_size) {
                    uint32_t source = source_at + match;
                    uint8_t b = source >= e->total ? e->pending[source - e->total] : e->history[source & 1023];
                    if (e->pending[i + match] != b) break;
                    ++match;
                }
                if (match > cost && match - cost > saving) {
                    saving = match - cost; best = match; distance = d;
                }
                unsigned link = e->links[source_at & 1023];
                if (!link || link > source_at) break;
                prior -= link;
            }
        }
        unsigned step = best ? best : 1;
        if (best) {
            literals(e, literal_at, literal_count); literal_count = 0;
            if (distance <= 256) {
                packed_byte(e, 0x80u + best - 3); packed_byte(e, distance - 1);
            } else {
                /* KL2 reserves literal tag 127 for a three-byte long match:
                 * 257..1024 bytes back, 4..67 bytes copied. */
                packed_byte(e, 127); packed_byte(e, distance - 1);
                packed_byte(e, ((best - 4) << 2) | ((distance - 1) >> 8));
            }
        } else {
            if (!literal_count) literal_at = i;
            if (++literal_count == 127) { literals(e, literal_at, literal_count); literal_count = 0; }
        }
        for (unsigned n = 0; n < step; ++n) {
            uint32_t at = e->total + i;
            e->links[at & 1023] = 0;
            if (i + 3 <= e->pending_size) {
                unsigned h = lz_hash(e->pending + i); uint32_t prior = e->positions[h];
                if (prior && at >= prior && at - (prior - 1) <= 1024)
                    e->links[at & 1023] = (uint16_t)(at - (prior - 1));
                e->positions[h] = at + 1;
            }
            e->history[at & 1023] = e->pending[i]; ++i;
        }
    }
    if (!e->failed) literals(e, literal_at, literal_count);
    e->total += e->pending_size; e->pending_size = 0;
}
static bool emit(struct ksc_encoder *e, unsigned b) {
    if (e->failed) return false;
    e->pending[e->pending_size++] = (uint8_t)b;
    if (e->pending_size == sizeof(e->pending)) pack_pending(e);
    return !e->failed;
}
static void flush(struct ksc_encoder *e) {
    if (!e->run) return;
    if (e->kind == 1) emit(e, 0x40u + e->run - 1);
    else { emit(e, 0xc1); emit(e, e->run); }
    e->run = 0;
}
void ksc_encode_init(struct ksc_encoder *e, uint8_t *out, size_t capacity) {
    memset(e, 0, sizeof(*e)); e->out = out; e->capacity = capacity; e->pixels = KSC_PIXELS;
    packed_byte(e, 'K'); packed_byte(e, 'L'); packed_byte(e, 2);
}
void ksc_encode_sink(struct ksc_encoder *e, bool (*sink)(void *, const uint8_t *, size_t), void *context, size_t capacity) {
    memset(e, 0, sizeof(*e)); e->sink = sink; e->sink_context = context; e->capacity = capacity; e->pixels = KSC_PIXELS;
    packed_byte(e, 'K'); packed_byte(e, 'L'); packed_byte(e, 2);
}
bool ksc_encode_pixels(struct ksc_encoder *e, const uint16_t *pixels, size_t n) {
    if (e->failed || e->count > e->pixels || n > e->pixels - e->count) return false;
    while (n--) {
        uint16_t p = *pixels++;
        unsigned x = e->count % KSC_WIDTH;
        /* Keep a same-color run on ties; otherwise extend a row copy across
         * repeated backgrounds and glyph interiors. */
        unsigned kind = e->count >= KSC_WIDTH && p == e->above[x] ?
            (p == e->previous && e->run && e->kind == 1 ? 1 : 2) : p == e->previous ? 1 : 0;
        if (e->run && (kind != e->kind || e->run == (kind == 1 ? 64u : 255u))) flush(e);
        if (kind) { e->kind = (uint8_t)kind; ++e->run; }
        else {
            unsigned h = hash(p);
            int r = (p >> 11) - (e->previous >> 11);
            int g = ((p >> 5) & 63) - ((e->previous >> 5) & 63);
            int b = (p & 31) - (e->previous & 31);
            if (e->colors[h] == p) emit(e, h);
            else if (r >= -2 && r <= 1 && g >= -2 && g <= 1 && b >= -2 && b <= 1)
                emit(e, 0x80u | (unsigned)((r + 2) * 16 + (g + 2) * 4 + b + 2));
            else { emit(e, 0xc0); emit(e, p); emit(e, p >> 8); }
        }
        e->colors[hash(p)] = p; e->above[x] = p; e->previous = p; ++e->count;
        if (e->failed) return false;
    }
    return true;
}
size_t ksc_encode_finish(struct ksc_encoder *e) {
    flush(e);
    pack_pending(e);
    return !e->failed && e->count == e->pixels ? e->used : 0;
}
unsigned ksc_file_height(const struct ksc_file *f) {
    if (f->size < 4 || memcmp(f->data, "KSN1", 4)) return KSC_HEIGHT;
    if (f->size < KSC_META_BYTES + 3) return 0;
    unsigned h = f->data[4] | (unsigned)f->data[5] << 8;
    return h >= KSC_HEIGHT && h <= KSC_MAX_HEIGHT && f->data[6] == 240 && !f->data[7] ? h : 0;
}
uint32_t ksc_file_sequence(const struct ksc_file *f) {
    uint32_t sequence; memcpy(&sequence, f->data - 16, sizeof(sequence)); return sequence;
}
void ksc_file_name(const struct ksc_file *f, char out[36]) {
    unsigned n = 0;
    bool named = f->size >= KSC_META_BYTES && !memcmp(f->data, "KSN1", 4);
    if (named) {
        for (unsigned i = 8; i < KSC_META_BYTES && f->data[i]; ++i) {
            unsigned c = f->data[i];
            if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) out[n++] = (char)c;
        }
    }
    if (!n) { memcpy(out, named ? "SCREEN" : "SC", named ? 6 : 2); n = named ? 6 : 2; }
    char digits[6]; unsigned count = 0, seq = ksc_file_sequence(f);
    do { digits[count++] = (char)('0' + seq % 10); seq /= 10; } while (seq && count < 6);
    while (count < (named ? 2u : 6u)) digits[count++] = '0';
    while (count) out[n++] = digits[--count];
    memcpy(out + n, ".BMP", 5);
}
void ksc_decode_init(struct ksc_decoder *d, const uint8_t *data, size_t size) {
    memset(d, 0, sizeof(*d));
    struct ksc_file f = {data, (uint32_t)size};
    unsigned height = ksc_file_height(&f);
    if (!height) { d->failed = true; return; }
    if (size >= KSC_META_BYTES && !memcmp(data, "KSN1", 4)) { data += KSC_META_BYTES; size -= KSC_META_BYTES; }
    d->pixels = KSC_WIDTH * height; d->data = data; d->size = size;
    d->version = size >= 3 ? data[2] : 0;
    d->failed = size < 3 || data[0] != 'K' || data[1] != 'L' || (data[2] != 1 && data[2] != 2);
    d->offset = d->failed ? 0 : 3;
}
static bool unpack_byte(struct ksc_decoder *d, unsigned *b) {
    if (d->failed) return false;
    if (!d->packet_left) {
        if (d->offset >= d->size) goto bad;
        unsigned tag = d->data[d->offset++];
        d->distance = 0;
        if (d->version == 2 && tag == 127) {
            if (d->size - d->offset < 2) goto bad;
            unsigned low = d->data[d->offset++], high = d->data[d->offset++];
            d->packet_left = (high >> 2) + 4;
            d->distance = (((high & 3) << 8) | low) + 1;
            if (d->distance > d->total) goto bad;
        } else if (tag < 128) {
            d->packet_left = tag + 1;
            if (d->packet_left > d->size - d->offset) goto bad;
        } else {
            d->packet_left = tag - 128 + 3;
            if (d->offset >= d->size) goto bad;
            d->distance = d->data[d->offset++] + 1;
            if (d->distance > d->total) goto bad;
        }
    }
    *b = d->distance ? d->history[(d->total - d->distance) & 1023] : d->data[d->offset++];
    d->history[d->total++ & 1023] = (uint8_t)*b; --d->packet_left; return true;
bad:
    d->failed = true; return false;
}
bool ksc_decode_pixel(struct ksc_decoder *d, uint16_t *pixel) {
    if (d->failed || d->count >= d->pixels) return false;
    uint16_t p = d->previous;
    if (!d->run) {
        unsigned tag;
        if (!unpack_byte(d, &tag)) goto bad;
        d->kind = 0;
        if (tag < 0x40) p = d->colors[tag];
        else if (tag < 0x80) { d->run = tag - 0x40 + 1; d->kind = 1; }
        else if (tag < 0xc0) {
            int r = (p >> 11) + (int)((tag >> 4) & 3) - 2;
            int g = ((p >> 5) & 63) + (int)((tag >> 2) & 3) - 2;
            int b = (p & 31) + (int)(tag & 3) - 2;
            if (r < 0 || r > 31 || g < 0 || g > 63 || b < 0 || b > 31) goto bad;
            p = (uint16_t)((r << 11) | (g << 5) | b);
        } else if (tag == 0xc0) {
            unsigned a, b;
            if (!unpack_byte(d, &a) || !unpack_byte(d, &b)) goto bad;
            p = (uint16_t)(a | b << 8);
        } else if (tag == 0xc1) {
            unsigned run;
            if (d->count < KSC_WIDTH || !unpack_byte(d, &run)) goto bad;
            d->run = run; d->kind = 2;
            if (!d->run) goto bad;
        } else goto bad;
        if (d->run > d->pixels - d->count) goto bad;
    }
    if (d->kind == 2) p = d->above[d->count % KSC_WIDTH];
    if (d->run) --d->run;
    d->above[d->count % KSC_WIDTH] = p; d->colors[hash(p)] = p;
    d->previous = p; ++d->count; *pixel = p; return true;
bad:
    d->failed = true; return false;
}
bool ksc_decode_finish(const struct ksc_decoder *d) {
    return !d->failed && d->count == d->pixels && !d->run && !d->packet_left && d->offset == d->size;
}
uint32_t ksc_crc_update(uint32_t crc, const uint8_t *data, size_t size) {
    while (size--) {
        crc ^= *data++;
        for (unsigned i = 0; i < 8; ++i) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return crc;
}
uint32_t ksc_crc(const uint8_t *data, size_t size) { return ~ksc_crc_update(~0u, data, size); }
static uint32_t word(const uint8_t *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static bool owned_marker(const uint8_t *p, uint32_t owner) {
    return word(p) == owner && word(p + 4) == ~owner &&
        word(p + 8) == KSC_GEOMETRY && word(p + 12) == ~KSC_GEOMETRY;
}
bool ksc_owned(const uint8_t *p) { return owned_marker(p, KSC_OWNER); }
bool ksc_wide_owned(const uint8_t *p) { return owned_marker(p, KSC_WIDE_OWNER); }
bool ksc_storage_owned_sector(const uint8_t *p, unsigned sector) {
    if (sector >= KSC_SECTORS) return false;
    const uint8_t *base = p + sector * KSC_SECTOR;
    return ksc_owned(base) || ksc_wide_owned(base + (sector ? KSC_SECTOR - KSC_OWNER_BYTES : 0));
}
size_t ksc_scan_sector(const uint8_t *p, struct ksc_catalog *c, uint32_t *next_sequence) {
    if (!ksc_owned(p)) return 0;
    size_t at = KSC_OWNER_BYTES;
    while (at + KSC_RECORD_BYTES <= KSC_SECTOR) {
        uint32_t n = word(p + at);
        if (n == ~0u) {
            for (size_t i = at; i < KSC_SECTOR; ++i) if (p[i] != 255) return 0;
            return at;
        }
        if (!n || n > KSC_MAX_BYTES || word(p + at + 4) != ~n ||
            ((n + 3u) & ~3u) > KSC_SECTOR - at - KSC_RECORD_BYTES) return 0;
        uint32_t seq = word(p + at + 8);
        if (word(p + at + 12) == ~seq) {
            if (!seq || seq > 999999) return 0;
            if (seq >= *next_sequence) *next_sequence = seq + 1;
            if (word(p + at + 20) == KSC_COMMIT &&
                ksc_crc(p + at + KSC_RECORD_BYTES, n) == word(p + at + 16) && c->count < KSC_FILES)
                c->files[c->count++] = (struct ksc_file){p + at + KSC_RECORD_BYTES, n};
        }
        at += KSC_RECORD_BYTES + ((n + 3u) & ~3u);
    }
    return 0;
}
void ksc_catalog_add_pair(struct ksc_catalog *c, const uint8_t *flash, uint32_t *seq) {
    if (ksc_wide_owned(flash)) {
        const uint8_t *p = flash + KSC_OWNER_BYTES;
        uint32_t n = word(p), sequence = word(p + 8);
        if (sequence && sequence <= 999999 && word(p + 12) == ~sequence && sequence >= *seq)
            *seq = sequence + 1;
        if (ksc_wide_owned(flash + KSC_SECTOR * KSC_SECTORS - KSC_OWNER_BYTES) &&
            n && n <= KSC_MAX_WIDE_BYTES && word(p + 4) == ~n &&
            sequence && sequence <= 999999 && word(p + 12) == ~sequence &&
            word(p + 20) == KSC_COMMIT && ksc_crc(p + KSC_RECORD_BYTES, n) == word(p + 16) &&
            c->count < KSC_FILES) {
            c->files[c->count++] = (struct ksc_file){p + KSC_RECORD_BYTES, n};
        }
        return;
    }
    for (unsigned s = 0; s < KSC_SECTORS; ++s) (void)ksc_scan_sector(flash + s * KSC_SECTOR, c, seq);
}
void ksc_catalog_sort(struct ksc_catalog *c) {
    for (unsigned i = 1; i < c->count; ++i) {
        struct ksc_file f = c->files[i]; unsigned j = i;
        while (j && ksc_file_sequence(&c->files[j - 1]) > ksc_file_sequence(&f)) { c->files[j] = c->files[j - 1]; --j; }
        c->files[j] = f;
    }
}
void ksc_catalog_init(struct ksc_catalog *c, const uint8_t *flash) {
    memset(c, 0, sizeof(*c)); uint32_t seq = 1;
    ksc_catalog_add_pair(c, flash, &seq); ksc_catalog_sort(c);
}
