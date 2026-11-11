/* SPDX-License-Identifier: MIT */
#ifndef KPD_SCREEN_MSC_H
#define KPD_SCREEN_MSC_H
#include "screen_codec.h"
enum ksc_phase { KSC_CBW, KSC_DATA, KSC_CSW, KSC_ZLP, KSC_DRAIN, KSC_HALT };
struct ksc_msc {
    struct ksc_disk disk;
    uint8_t tx[512];
    uint32_t tag, residue, remaining, lba, blocks;
    unsigned tx_size;
    enum ksc_phase phase;
    uint8_t status, sense, asc;
    uint8_t last_nonread;
    bool short_zlp;
};
void ksc_msc_init(struct ksc_msc *, const struct ksc_catalog *);
void ksc_msc_reset(struct ksc_msc *);
bool ksc_msc_out(struct ksc_msc *, const uint8_t *, size_t);
bool ksc_msc_in_done(struct ksc_msc *);
#endif
