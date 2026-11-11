/* SPDX-License-Identifier: MIT. Synthetic, read-only FAT16/BMP volume. */
#include "screen_codec.h"
#include <string.h>
enum { FAT_BLOCKS = 64, ROOT_BLOCK = 129, DATA_BLOCK = 153,
       CLUSTER_BLOCKS = 16, FILE_CLUSTERS = 128 };
static void put16(uint8_t *p, unsigned v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }
void ksc_disk_init(struct ksc_disk *d, const struct ksc_catalog *c) {
    memset(d, 0, sizeof(*d)); d->catalog = c;
}
static unsigned fat_entry(const struct ksc_disk *d, unsigned cluster) {
    if (cluster == 0) return 0xfff8;
    if (cluster == 1) return 0xffff;
    unsigned relative = cluster - 2;
    if (relative / FILE_CLUSTERS >= d->catalog->count) return 0;
    unsigned bytes = 66 + KSC_WIDTH * ksc_file_height(&d->catalog->files[relative / FILE_CLUSTERS]) * 2;
    unsigned used = (bytes + 8191) / 8192, part = relative % FILE_CLUSTERS;
    return part >= used ? 0 : part == used - 1 ? 0xffff : cluster + 1;
}
static void bmp_header(uint8_t *p, unsigned height) {
    unsigned pixels = KSC_WIDTH * height;
    memset(p, 0, 66); p[0] = 'B'; p[1] = 'M'; put32(p + 2, 66 + pixels * 2);
    put32(p + 10, 66); put32(p + 14, 40); put32(p + 18, KSC_WIDTH);
    put32(p + 22, (uint32_t)(-(int32_t)height)); put16(p + 26, 1);
    put16(p + 28, 16); put32(p + 30, 3); put32(p + 34, pixels * 2);
    put32(p + 54, 0xf800); put32(p + 58, 0x07e0); put32(p + 62, 0x001f);
}
static bool bmp_read(struct ksc_disk *d, unsigned file, unsigned offset, uint8_t *out) {
    const struct ksc_file *f = &d->catalog->files[file];
    unsigned height = ksc_file_height(f), bytes = 66 + KSC_WIDTH * height * 2;
    if (!height) return false;
    unsigned i = 0;
    if (offset == 0) { bmp_header(out, height); i = 66; }
    if (offset + i >= bytes) return true;
    unsigned pixel = (offset + i - 66) / 2;
    if (!d->cached || d->file != file || d->decoder.count > pixel) {
        ksc_decode_init(&d->decoder, f->data, f->size); d->cached = true; d->file = file;
    }
    uint16_t p;
    while (d->decoder.count < pixel) if (!ksc_decode_pixel(&d->decoder, &p)) return false;
    while (i < 512 && offset + i < bytes) {
        if (!ksc_decode_pixel(&d->decoder, &p)) return false;
        put16(out + i, p); i += 2;
    }
    return d->decoder.count != d->decoder.pixels || ksc_decode_finish(&d->decoder);
}
bool ksc_disk_read(struct ksc_disk *d, uint32_t block, uint8_t out[512]) {
    if (block >= KSC_BLOCKS) return false;
    memset(out, 0, 512);
    if (block == KSC_BLOCKS - 1 && d->catalog->diagnostic) {
        d->catalog->diagnostic(d->catalog, out); return true;
    }
    if (!block) {
        out[0] = 0xeb; out[1] = 0x3c; out[2] = 0x90; memcpy(out + 3, "KM003C  ", 8);
        put16(out + 11, 512); out[13] = CLUSTER_BLOCKS; put16(out + 14, 1); out[16] = 2;
        put16(out + 17, KSC_FILES * 4); put32(out + 32, KSC_BLOCKS); out[21] = 0xf8;
        put16(out + 22, FAT_BLOCKS); put16(out + 24, 32); put16(out + 26, 64);
        out[36] = 0x80; out[38] = 0x29; put32(out + 39, KSC_OWNER);
        memcpy(out + 43, "KM003C     FAT16   ", 19); out[510] = 0x55; out[511] = 0xaa;
    } else if (block < ROOT_BLOCK) {
        unsigned first = ((block - 1) % FAT_BLOCKS) * 512;
        for (unsigned i = 0; i < 512; i += 2) put16(out + i, fat_entry(d, (first + i) / 2));
    } else if (block < DATA_BLOCK) {
        for (unsigned i = 0; i < 16; ++i) {
            unsigned entry = (block - ROOT_BLOCK) * 16 + i, file = entry / 4, slot = entry % 4;
            if (file >= d->catalog->count) break;
            uint8_t *p = out + i * 32, alias[11]; memcpy(alias, "SC000000BMP", 11);
            uint32_t sequence = ksc_file_sequence(&d->catalog->files[file]);
            for (unsigned k = 8; k-- > 2;) { alias[k] = (uint8_t)('0' + sequence % 10); sequence /= 10; }
            if (slot != 3) {
                char name[36]; ksc_file_name(&d->catalog->files[file], name);
                unsigned len = 0; while (name[len]) ++len;
                unsigned chunks = (len + 12) / 13, part = 3 - slot;
                if (part > chunks) { p[0] = 0xe5; continue; }
                p[0] = (uint8_t)(part | (part == chunks ? 0x40 : 0)); p[11] = 0x0f;
                unsigned sum = 0;
                for (unsigned j = 0; j < 11; ++j) sum = (((sum & 1) << 7) + (sum >> 1) + alias[j]) & 255;
                p[13] = (uint8_t)sum;
                static const uint8_t positions[] = {1,3,5,7,9,14,16,18,20,22,24,28,30};
                for (unsigned j = 0; j < 13; ++j) {
                    unsigned at = (part - 1) * 13 + j;
                    put16(p + positions[j], at < len ? (uint8_t)name[at] : at == len ? 0 : 0xffff);
                }
                continue;
            }
            memcpy(p, alias, 11);
            p[11] = 1; /* Read-only. A fixed FAT date is not a capture timestamp. */
            put16(p + 24, 0x21); put16(p + 26, 2 + file * FILE_CLUSTERS);
            put32(p + 28, 66 + KSC_WIDTH * ksc_file_height(&d->catalog->files[file]) * 2);
        }
    } else {
        unsigned relative = block - DATA_BLOCK;
        unsigned file = relative / (FILE_CLUSTERS * CLUSTER_BLOCKS);
        if (file < d->catalog->count)
            return bmp_read(d, file, relative % (FILE_CLUSTERS * CLUSTER_BLOCKS) * 512, out);
    }
    return true;
}
