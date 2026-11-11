/* SPDX-License-Identifier: MIT. Read-only USB Mass Storage Bulk-Only Transport. */
#include "screen_msc.h"
#include <string.h>
static uint32_t le32(const uint8_t *p) { return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static void putle(uint8_t *p, uint32_t v) { for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i)); }
static void putbe(uint8_t *p, uint32_t v) { for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (24 - 8 * i)); }
void ksc_msc_reset(struct ksc_msc *m) { m->phase = KSC_CBW; m->tx_size = 0; m->blocks = 0; m->disk.cached = false; }
void ksc_msc_init(struct ksc_msc *m, const struct ksc_catalog *c) { memset(m, 0, sizeof(*m)); ksc_disk_init(&m->disk, c); ksc_msc_reset(m); }
static bool csw(struct ksc_msc *m) {
    putle(m->tx, 0x53425355); putle(m->tx + 4, m->tag); putle(m->tx + 8, m->residue);
    m->tx[12] = m->status; m->tx_size = 13; m->phase = KSC_CSW; return true;
}
static bool fail(struct ksc_msc *m, bool input, uint8_t key, uint8_t asc) {
    m->status = 1; m->sense = key; m->asc = asc; m->blocks = 0;
    if (m->residue && !input) { m->remaining = m->residue; m->phase = KSC_DRAIN; m->tx_size = 0; return true; }
    if (m->residue) { m->phase = KSC_ZLP; m->tx_size = 0; return true; }
    return csw(m);
}
static bool data(struct ksc_msc *m, unsigned n) {
    if (n > m->residue) n = m->residue;
    m->short_zlp = n < m->residue && n % 64 == 0;
    m->residue -= n; m->tx_size = n; m->phase = KSC_DATA;
    return true;
}
bool ksc_msc_out(struct ksc_msc *m, const uint8_t *p, size_t n) {
    if (m->phase == KSC_DRAIN) {
        if (!n || n > m->remaining) goto halt;
        m->remaining -= (uint32_t)n;
        return m->remaining ? true : csw(m);
    }
    if (m->phase != KSC_CBW || n != 31 || le32(p) != 0x43425355 || p[12] & 0x7f ||
        p[13] || !p[14] || p[14] > 16) goto halt;
    m->tag = le32(p + 4); m->residue = le32(p + 8); m->status = 0; m->blocks = 0;
    m->short_zlp = false; bool input = (p[12] & 0x80) != 0;
    const uint8_t *c = p + 15;
    if (c[0] != 0x28 && c[0] != 0xa8) m->last_nonread = c[0];
    memset(m->tx, 0, sizeof(m->tx));
    unsigned length = 0;
    switch (c[0]) {
    case 0x00: case 0x1b: case 0x1e: case 0x35: /* Ready, start/stop, prevent, sync */
        if (p[14] < (c[0] == 0x35 ? 10 : 6)) goto invalid;
        if (m->residue) goto phase_error;
        return csw(m);
    case 0x03: /* REQUEST SENSE */
        if (p[14] < 6 || c[1]) goto invalid;
        m->tx[0] = 0x70; m->tx[2] = m->sense; m->tx[7] = 10; m->tx[12] = m->asc;
        m->sense = m->asc = 0; length = c[4] < 18 ? c[4] : 18; break;
    case 0x12: /* INQUIRY */
        if (p[14] < 6 || c[1] || c[2]) goto invalid;
        m->tx[1] = 0x80; m->tx[2] = 4; m->tx[3] = 2; m->tx[4] = 31;
        memcpy(m->tx + 8, "KM003C  SCREEN CAPTURES  0001", 28);
        length = c[4] < 36 ? c[4] : 36; break;
    case 0x1a: /* MODE SENSE(6): medium is write-protected */
        if (p[14] < 6 || (c[2] & 63) != 0x3f) goto invalid;
        m->tx[0] = 3; m->tx[2] = 0x80; length = c[4] < 4 ? c[4] : 4; break;
    case 0x5a: /* MODE SENSE(10) */
        if (p[14] < 10 || (c[2] & 63) != 0x3f) goto invalid;
        m->tx[1] = 6; m->tx[3] = 0x80; length = ((unsigned)c[7] << 8) | c[8];
        if (length > 8) length = 8;
        break;
    case 0x23: /* READ FORMAT CAPACITIES */
        if (p[14] < 10) goto invalid;
        m->tx[3] = 8; putbe(m->tx + 4, KSC_BLOCKS); m->tx[8] = 2; m->tx[10] = 2;
        length = ((unsigned)c[7] << 8) | c[8]; if (length > 12) length = 12; break;
    case 0x25: /* READ CAPACITY(10) */
        if (p[14] < 10 || be32(c + 2) || c[8]) goto invalid;
        putbe(m->tx, KSC_BLOCKS - 1); putbe(m->tx + 4, 512); length = 8; break;
    case 0x28: case 0xa8: /* READ(10/12) */
        if (p[14] < (c[0] == 0x28 ? 10 : 12)) goto invalid;
        m->lba = be32(c + 2);
        m->blocks = c[0] == 0x28 ? ((unsigned)c[7] << 8) | c[8] : be32(c + 6);
        if (m->lba >= KSC_BLOCKS || m->blocks > KSC_BLOCKS - m->lba)
            return fail(m, input, 5, 0x21);
        if ((m->blocks && !input) || m->residue != m->blocks * 512) goto phase_error;
        if (!m->blocks) return csw(m);
        if (!ksc_disk_read(&m->disk, m->lba++, m->tx)) return fail(m, input, 3, 0x11);
        --m->blocks; m->residue -= 512; m->tx_size = 512; m->phase = KSC_DATA; return true;
    case 0x2a: case 0xaa: case 0x15: case 0x55: case 0x04: /* All modifying commands */
        return fail(m, input, 7, 0x27);
    default: return fail(m, input, 5, 0x20);
    }
    if (m->residue && !input) goto phase_error;
    return data(m, length);
invalid:
    return fail(m, input, 5, 0x24);
phase_error:
    m->status = 2; m->blocks = 0; return csw(m);
halt:
    m->phase = KSC_HALT; m->tx_size = 0; return false;
}
bool ksc_msc_in_done(struct ksc_msc *m) {
    switch (m->phase) {
    case KSC_DATA:
        if (m->blocks) {
            if (!ksc_disk_read(&m->disk, m->lba++, m->tx)) return fail(m, true, 3, 0x11);
            --m->blocks; m->residue -= 512; m->tx_size = 512; return true;
        }
        if (m->short_zlp) { m->phase = KSC_ZLP; m->tx_size = 0; m->short_zlp = false; return true; }
        return csw(m);
    case KSC_ZLP: return csw(m);
    case KSC_CSW:
        if (m->status == 2) { m->phase = KSC_HALT; return false; }
        m->phase = KSC_CBW; m->tx_size = 0; return true;
    default: return false;
    }
}
