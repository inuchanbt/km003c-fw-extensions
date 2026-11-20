/* SPDX-License-Identifier: MIT. Exact stock 2.0.7 CherryUSB ABI only.
 * Re-enumeration replaces the registered classes, not the interrupt vector.
 * ISR callbacks publish events; FAT decoding runs only in the GUI task.
 */
#include "screen_usb.h"
#include "screen_nor.h"
#include <string.h>
#define FN(a, r, ...) ((r (*)(__VA_ARGS__))(uintptr_t)((a) | 1u))
#define ep_read FN(0x510ee, int, uint8_t, uint8_t, void *, uint32_t)
#define ep_write FN(0x5120c, int, uint8_t, uint8_t, const void *, uint32_t)
#define ep_stall FN(0x5109a, int, uint8_t, uint8_t)
#define desc_register FN(0x50d5e, void, uint8_t, const void *)
#define add_interface FN(0x50c42, void, uint8_t, void *)
#define add_endpoint FN(0x50be0, void, uint8_t, const void *)
#define CORE ((volatile uint32_t *)0x20008df0u)
#define DCTL (*(volatile uint32_t *)0x400c0804u)
static const uint8_t descriptors[] = {
    /* Private capture identity, separate from factory APP/DFU PID 0x0063. */
    18,1,0,2,0,0,0,32,0xc9,0x5f,0x07,0xd2,0,2,1,2,0,1,
    9,2,32,0,1,1,0,0x80,50,
    9,4,0,0,2,8,6,0x50,0,
    7,5,0x01,2,64,0,0, 7,5,0x81,2,64,0,0,
    4,3,9,4,
    14,3,'K',0,'M',0,'0',0,'0',0,'3',0,'C',0,
    26,3,'K',0,'M',0,'0',0,'0',0,'3',0,'C',0,' ',0,'S',0,'H',0,'O',0,'T',0,'S',0,
    0
};
static struct ksc_usb *state(void) {
    struct ksc_usb *s = (struct ksc_usb *)(uintptr_t)CORE[0x234 / 4];
    return s && CORE[0x18 / 4] == (uintptr_t)descriptors ? s : NULL;
}
static void out_done(uint8_t bus, uint8_t ep, uint32_t n) {
    (void)bus; (void)ep; struct ksc_usb *s = state();
    if (s) { ++s->rx_events; s->received = n; s->out_done = 1; }
}
static void in_done(uint8_t bus, uint8_t ep, uint32_t n) {
    (void)bus; (void)ep; (void)n; struct ksc_usb *s = state();
    if (s) { ++s->tx_events; s->in_done = 1; }
}
static void event(uint8_t bus, uint8_t e) {
    (void)bus; struct ksc_usb *s = state();
    if (s) {
        ++s->bus_events; s->last_event = e;
        if (e == 1 || e == 4 || e == 7) s->event = e;
    }
}
static int class_request(uint8_t bus, const uint8_t *setup, uint8_t **data, uint32_t *length) {
    (void)bus; struct ksc_usb *s = state(); if (!s) return -1;
    if (setup[2] || setup[3] || setup[4] || setup[5] || setup[7]) return -1;
    if (setup[0] == 0xa1 && setup[1] == 0xfe && setup[6] == 1) {
        *data = &s->lun; *length = 1; return 0;
    }
    if (setup[0] == 0x21 && setup[1] == 0xff && !setup[6]) {
        s->reset = 1; *length = 0; return 0;
    }
    return -1;
}
static uint32_t irq_off(void) {
    uint32_t old; __asm__ volatile("mrs %0, primask\ncpsid i" : "=r"(old) :: "memory"); return old;
}
static void irq_restore(uint32_t old) { __asm__ volatile("msr primask, %0" :: "r"(old) : "memory"); }
bool ksc_usb_begin(struct ksc_usb *s, const struct ksc_catalog *c, uint32_t now) {
    /* Never reinterpret an unexpected native USB instance. */
    if (CORE[0x18 / 4] != 0x1fff8b34u || *(volatile uint32_t *)0x1fffb19cu != 0x400c0000u) return false;
    memset(s, 0, sizeof(*s)); ksc_msc_init(&s->msc, c); s->since = now;
    DCTL |= 2u; /* Native DWC2 soft disconnect; reconnect after 250 ms. */
    return true;
}
void ksc_usb_disconnect(struct ksc_usb *s) {
    DCTL |= 2u;
    s->configured = false;
    /* Keep the registered callback state alive until power-off. No sector
     * may change until disconnect has settled and the user confirms clear. */
}
static void halt(struct ksc_usb *s) {
    (void)ep_stall(0, 1); (void)ep_stall(0, 0x81);
    s->rx_armed = s->tx_armed = false;
}
void ksc_usb_poll(struct ksc_usb *s, uint32_t now) {
    if (s->failed) return;
    if (!s->connected) {
        if ((uint32_t)(now - s->since) < 250) return;
        s->interface[0] = (uintptr_t)class_request;
        s->endpoints[0].address = 1; s->endpoints[0].callback = out_done;
        s->endpoints[1].address = 0x81; s->endpoints[1].callback = in_done;
        uint32_t irq = irq_off();
        desc_register(0, descriptors); add_interface(0, s);
        add_endpoint(0, &s->endpoints[0]); add_endpoint(0, &s->endpoints[1]);
        CORE[0x308 / 4] = (uintptr_t)event;
        s->connected = true; DCTL &= ~2u;
        irq_restore(irq); return;
    }
    uint32_t irq = irq_off();
    unsigned e = s->event; s->event = 0;
    bool reset = s->reset != 0; s->reset = 0;
    bool rx = s->out_done != 0, tx = s->in_done != 0;
    uint32_t n = s->received; s->out_done = s->in_done = 0;
    irq_restore(irq);
    if (e || reset) {
        ksc_msc_reset(&s->msc); s->rx_armed = s->tx_armed = false; rx = tx = false;
        if (e) s->configured = e == 7;
    }
    if (!s->configured) return;
    if (rx) {
        s->rx_armed = false;
        bool ok = false;
        if (n <= sizeof(s->rx)) {
            ksc207_nor_lock(); ok = ksc_msc_out(&s->msc, (const uint8_t *)s->rx, n); ksc207_nor_unlock();
        }
        if (!ok) { halt(s); return; }
    }
    if (tx) {
        s->tx_armed = false;
        ksc207_nor_lock(); bool ok = ksc_msc_in_done(&s->msc); ksc207_nor_unlock();
        if (!ok) { halt(s); return; }
    }
    enum ksc_phase p = s->msc.phase;
    if ((p == KSC_CBW || p == KSC_DRAIN) && !s->rx_armed) {
        uint32_t bytes = p == KSC_CBW ? 64 : s->msc.remaining < 512 ? s->msc.remaining : 512;
        if (ep_read(0, 1, s->rx, bytes) < 0) { s->failed = true; halt(s); return; }
        s->rx_armed = true;
    } else if ((p == KSC_DATA || p == KSC_CSW || p == KSC_ZLP) && !s->tx_armed) {
        if (ep_write(0, 0x81, s->msc.tx, s->msc.tx_size) < 0) { s->failed = true; halt(s); return; }
        s->tx_armed = true;
    }
}
