/* SPDX-License-Identifier: MIT. Exact qualified HW2.3 / APP 2.0.7 partition. */
#ifndef KPD207_SCREEN_NOR_H
#define KPD207_SCREEN_NOR_H
#include "screen_store.h"
/* Native records: 0x100000..0x300000; update writer: 0x300000..0x380000;
 * native settings: 0x3ff000..0x400000. This 1 MiB bank is outside each.
 * A foreign or damaged ownership marker disables all NOR mutations. */
#define KSC_NOR_BEGIN 0u
#define KSC_NOR_END 0x100000u
#define KSC_NOR_MAP 0x98000000u
extern const struct ksc_store ksc207_nor;
void ksc207_nor_lock(void);
void ksc207_nor_unlock(void);
bool ksc207_nor_doom(void);
bool ksc207_nor_reclaim_doom(void);
#endif
