/* SPDX-License-Identifier: MIT */
#ifndef KPD207_SCREEN_USB_H
#define KPD207_SCREEN_USB_H
#include "screen_msc.h"
struct ksc_usb {
    /* Native CherryUSB interface ABI; must stay first. */
    uintptr_t interface[7];
    struct { uint32_t address; void (*callback)(uint8_t, uint8_t, uint32_t); } endpoints[2];
    struct ksc_msc msc;
    uint32_t rx[128];
    volatile uint32_t received;
    volatile uint32_t rx_events, tx_events, bus_events, last_event;
    volatile uint8_t event, in_done, out_done, reset;
    uint32_t since;
    bool connected, configured, rx_armed, tx_armed, failed;
    uint8_t lun;
};
bool ksc_usb_begin(struct ksc_usb *, const struct ksc_catalog *, uint32_t);
void ksc_usb_disconnect(struct ksc_usb *);
void ksc_usb_poll(struct ksc_usb *, uint32_t);
#endif
