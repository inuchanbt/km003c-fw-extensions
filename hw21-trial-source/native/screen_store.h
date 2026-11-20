/* SPDX-License-Identifier: MIT. Bounded append-only mapped-NOR journal. */
#ifndef KPD_SCREEN_STORE_H
#define KPD_SCREEN_STORE_H
#include "screen_codec.h"
struct ksc_store {
    const uint8_t *base;
    uint32_t bytes;
    bool (*program)(uint32_t, const uint8_t *, size_t);
    bool (*erase4k)(uint32_t);
};
struct ksc_store_txn {
    const struct ksc_store *store;
    uint32_t at, size, written;
    bool failed;
};
bool ksc_store_begin(const struct ksc_store *, size_t, uint32_t, struct ksc_store_txn *);
bool ksc_store_put(struct ksc_store_txn *, const uint8_t *, size_t);
bool ksc_store_commit(struct ksc_store_txn *, uint32_t);
bool ksc_store_safe(const struct ksc_store *);
void ksc_store_mount(const struct ksc_store *, struct ksc_catalog *, uint32_t *);
bool ksc_store_append(const struct ksc_store *, const uint8_t *, size_t, uint32_t);
bool ksc_store_clear(const struct ksc_store *);
#endif
