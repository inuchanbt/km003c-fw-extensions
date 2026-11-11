/* SPDX-License-Identifier: MIT */
#ifndef KPD_SCREEN_CODEC_H
#define KPD_SCREEN_CODEC_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { KSC_WIDTH = 240, KSC_HEIGHT = 240, KSC_PIXELS = 57600,
       KSC_SECTOR = 8192, KSC_SECTORS = 2, KSC_OWNER_BYTES = 16,
       KSC_RECORD_BYTES = 24, KSC_MAX_BYTES = KSC_SECTOR - KSC_OWNER_BYTES - KSC_RECORD_BYTES,
       KSC_MAX_WIDE_BYTES = KSC_SECTOR * KSC_SECTORS - KSC_OWNER_BYTES * 2 - KSC_RECORD_BYTES,
       KSC_FILES = 96, KSC_BLOCKS = 262144, KSC_BMP_BYTES = 66 + KSC_PIXELS * 2,
       KSC_MAX_HEIGHT = 2048, KSC_META_BYTES = 32, KSC_MAX_SPAN = 131072,
       KSC_MAX_CAPTURE_BYTES = KSC_MAX_SPAN - KSC_OWNER_BYTES * 2 - KSC_RECORD_BYTES };
#define KSC_FLASH_BASE 0x78000u
#define KSC_FLASH_END 0x7c000u
#define KSC_OWNER 0x3143534bu
#define KSC_WIDE_OWNER 0x3243534bu
#define KSC_SPAN_OWNER 0x3343534bu
#define KSC_GEOMETRY (240u | (240u << 16))
#define KSC_COMMIT 0x31564d43u

/* Streaming, lossless RGB565: 64-entry color cache, runs, small RGB deltas,
 * and runs copied from the preceding row. No color-count restriction. */
struct ksc_encoder {
    uint16_t above[KSC_WIDTH], colors[64], previous;
    uint8_t *out;
    uint32_t count, pixels;
    size_t used, capacity;
    unsigned run;
    uint8_t kind;
    bool failed;
    uint8_t history[1024], pending[130];
    uint32_t positions[128], total;
    uint16_t links[1024];
    unsigned pending_size;
    bool (*sink)(void *, const uint8_t *, size_t);
    void *sink_context;
};
struct ksc_decoder {
    uint16_t above[KSC_WIDTH], colors[64], previous;
    const uint8_t *data;
    size_t size, offset;
    uint32_t count, pixels;
    unsigned run;
    uint8_t kind;
    bool failed;
    uint8_t history[1024];
    uint32_t total;
    unsigned packet_left, distance;
    uint8_t version;
};
/* Sequence is immutable in the journal header immediately before data.
 * Avoid duplicating it in RAM: 96 entries use the same ARM RAM as the old 64. */
struct ksc_file { const uint8_t *data; uint32_t size; };
struct ksc_catalog {
    struct ksc_file files[KSC_FILES]; unsigned count;
    /* Optional private live diagnostics in an otherwise unused disk sector. */
    void (*diagnostic)(const struct ksc_catalog *, uint8_t [512]);
};
void ksc_encode_init(struct ksc_encoder *, uint8_t *, size_t);
void ksc_encode_sink(struct ksc_encoder *, bool (*)(void *, const uint8_t *, size_t), void *, size_t);
bool ksc_encode_pixels(struct ksc_encoder *, const uint16_t *, size_t);
size_t ksc_encode_finish(struct ksc_encoder *);
void ksc_decode_init(struct ksc_decoder *, const uint8_t *, size_t);
unsigned ksc_file_height(const struct ksc_file *);
uint32_t ksc_file_sequence(const struct ksc_file *);
void ksc_file_name(const struct ksc_file *, char [36]);
bool ksc_decode_pixel(struct ksc_decoder *, uint16_t *);
bool ksc_decode_finish(const struct ksc_decoder *);
uint32_t ksc_crc(const uint8_t *, size_t);
uint32_t ksc_crc_update(uint32_t, const uint8_t *, size_t);
bool ksc_owned(const uint8_t *);
bool ksc_wide_owned(const uint8_t *);
bool ksc_storage_owned_sector(const uint8_t *, unsigned);
/* Unknown, damaged and torn reservations are never writable. Valid committed
 * records before a torn append remain exportable. No erase is performed. */
size_t ksc_scan_sector(const uint8_t *, struct ksc_catalog *, uint32_t *);
void ksc_catalog_init(struct ksc_catalog *, const uint8_t *);
/* Append one independent 16 KiB pair without discarding earlier files. */
void ksc_catalog_add_pair(struct ksc_catalog *, const uint8_t *, uint32_t *);
void ksc_catalog_sort(struct ksc_catalog *);
struct ksc_disk {
    const struct ksc_catalog *catalog;
    struct ksc_decoder decoder;
    unsigned file;
    bool cached;
};
void ksc_disk_init(struct ksc_disk *, const struct ksc_catalog *);
bool ksc_disk_read(struct ksc_disk *, uint32_t, uint8_t [512]);
#endif
