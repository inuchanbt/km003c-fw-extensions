/* SPDX-License-Identifier: MIT. Capture-only variant; QR remains a separate build. */
#include "kpd.h"
#include "profile.h"
void ksc207_gui_tick(void);
static void unavailable(void) {}
__attribute__((used, section(".kpd207.header")))
const struct {
    uint8_t magic[8]; uint32_t abi, length, crc;
    void (*tick)(void); void (*unused[5])(void);
    uint8_t stock_hash[16]; uint32_t reserved;
} kpd207_header = {
    {'K','P','D','X','2','0','7',0},1,0,0,ksc207_gui_tick,
    {unavailable,unavailable,unavailable,unavailable,unavailable}, KPD207_HASH_PREFIX,0
};
/* Fixed capability marker immediately after the common 64-byte header. */
__attribute__((used, section(".kpd207.capabilities")))
const uint8_t kpd207_screen_capability[16] = "KMSC207-SCREEN1";
