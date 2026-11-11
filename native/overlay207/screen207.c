/* SPDX-License-Identifier: MIT. Opt-in capture-only stock-2.0.7 overlay.
 * All mutable state and executable flash primitives use the native heap.
 */
#include "screen_usb.h"
#include "screen_nor.h"
#include <string.h>
#define FN(a, r, ...) ((r (*)(__VA_ARGS__))(uintptr_t)((a) | 1u))
#define alloc FN(0x32a94, void *, size_t)
#define release FN(0x32b80, void, void *)
#define layer_sys FN(0x2a6fe, void *, void *)
#define display_default FN(0x2a6a4, uint8_t *, void)
#define refresh FN(0x13e64, void, void *)
#define delete_obj FN(0x34a0a, int, void *)
#define signal_get FN(0x3501a, signal_cb, void *)
#define signal_set FN(0x35bfe, void, void *, signal_cb)
#define invalidate FN(0x35658, void, void *)
#define create_image FN(0x2f728, void *, void *, void *)
#define image_src FN(0x3057e, void, void *, const void *)
#define input_next FN(0x30ab4, void *, void *)
#define tick FN(0x3c0d0, uint32_t, void)
#define child_next FN(0x34cd0, void *, void *, void *)
#define set_y FN(0x362cc, void, void *, int16_t)
typedef uint8_t (*signal_cb)(void *, uint8_t, void *);
typedef bool (*key_cb)(void *, void *);
typedef void (*flush_cb)(void *, const int16_t *, const uint16_t *);
typedef bool (*flash_cb)(uint32_t, uint32_t, unsigned);
extern const uint8_t ksc207_flash_start[], ksc207_flash_end[];
enum { BACK = 1, OK = 2, LEFT = 4, RIGHT = 8, CAPTURE_CHORD = LEFT | RIGHT,
       NOTICE_H = 72, NOTICE_BYTES = 8 + 30 * NOTICE_H };
#define STATE_MAGIC 0x3253434bu
#define RAW_KEYS ((volatile uint32_t *)0x1fffb4fcu)
struct notice { uint32_t header, size; const uint8_t *pixels; };
struct capture_stream {
    struct ksc_store_txn transaction;
    uint8_t page[256];
    unsigned used;
    uint32_t crc;
};
struct capture_plan {
    uint8_t metadata[KSC_META_BYTES];
    uint8_t *page, *scroll;
    int16_t original_y, top, height, first, last, next;
    uint8_t bars;
    unsigned base;
};
_Static_assert(sizeof(struct capture_stream) <= sizeof(struct ksc_catalog), "Capture workspace must fit the existing catalog");
_Static_assert(sizeof(struct ksc_catalog) == 776, "Keep the qualified ARM catalog and state ABI unchanged");
struct screen207 {
    uint32_t magic;
    void *input;
    key_cb reader;
    struct ksc_encoder *encoder;
    flush_cb flush;
    uint8_t *flash_code;
    union { struct ksc_catalog catalog; struct capture_stream stream; };
    struct ksc_usb *usb;
    void *notice_obj;
    struct notice descriptor;
    uint8_t *notice_data;
    uint32_t since, notice_since, single_since;
    uint8_t mode, request, single;
    bool chord, fired, forwarded, released;
    signal_cb notice_signal;
    uint32_t raw_since;
    uint8_t raw_single;
    bool raw_latched;
    uint32_t boot_ms, boot_keys, boot_token, boot_reset;
    uint32_t captures, encoded_bytes;
    volatile uint32_t capture_stage;
    uint32_t watchdog_refreshes, watchdog_ms;
    uint32_t capture_pixels, capture_bytes, capture_flags, capture_flushes;
    int16_t bad_area[4];
    uint32_t capture_ms, render_crc;
    struct capture_plan *plan;
    uint32_t extra_status, extra_crc, guard_crc;
};
static bool read_keys(void *, void *);
static struct screen207 *state(void) {
    /* The registered keypad outlives native screen/system-layer cleanups.
     * Its qualified, initially NULL user_data field is at +12 (display +16).
     * Never discover ownership through a disposable screen child. */
    for (uint8_t *input = input_next(NULL); input; input = input_next(input)) {
        if (*(key_cb *)(input + 4) != read_keys) continue;
        uintptr_t p = *(const uintptr_t *)(input + 12);
        if (p < 0x200091e4u || p > 0x200111e0u - sizeof(struct screen207)) continue;
        struct screen207 *s = (struct screen207 *)p;
        if (s->magic == STATE_MAGIC && s->input == input) return s;
    }
    return NULL;
}
static unsigned buttons(void) {
    unsigned b = 0;
    if (!*(volatile const uint32_t *)0x42a7021cu) b |= BACK;
    if (!*(volatile const uint32_t *)0x42a7022cu) b |= OK;
    if (!*(volatile const uint32_t *)0x42a70220u) b |= LEFT;
    if (!*(volatile const uint32_t *)0x42a70224u) b |= RIGHT;
    return b;
}
static void diagnostic_word(uint8_t *out, unsigned at, uint32_t value) {
    memcpy(out + at, &value, 4);
}
static void diagnostic(const struct ksc_catalog *catalog, uint8_t out[512]) {
    const struct screen207 *s = (const struct screen207 *)((const uint8_t *)catalog -
                                                        offsetof(struct screen207, catalog));
    memcpy(out, "KSC207D2", 8);
    const uint32_t values[] = {18, tick(), s->boot_ms, s->boot_keys, s->boot_token,
        s->boot_reset, s->mode, s->capture_stage, s->captures, s->encoded_bytes,
        (uintptr_t)s, (uintptr_t)s->input, *(const uintptr_t *)((const uint8_t *)s->input + 12),
        *(const uintptr_t *)((const uint8_t *)s->input + 4), catalog->count,
        *(volatile const uint32_t *)0x40010410u, *(volatile const uint32_t *)0xe000ed28u,
        *(volatile const uint32_t *)0xe000ed2cu, buttons(), *(const uint32_t *)0x74010u,
        *(volatile const uint32_t *)0x1fffbf2cu};
    for (unsigned n = 0; n < sizeof(values) / sizeof(values[0]); ++n)
        diagnostic_word(out, 8 + n * 4, values[n]);
    memcpy(out + 96, (const void *)0x1fffb4fcu, 96);
    memcpy(out + 192, s->input, 32);
    memcpy(out + 224, (const void *)0x1fffbf2cu, 48);
    /* Enumerate only tagged allocated state blocks, not foreign payloads. */
    unsigned found = 0, free_bytes = 0, largest = 0, blocks = 0;
    for (uintptr_t p = 0x200091e0u; p < 0x200111dcu;) {
        uint32_t header = *(const uint32_t *)p, size = header >> 1;
        if (!size || size > 0x200111e0u - p - 4) break;
        ++blocks;
        if (!(header & 1)) { free_bytes += size; if (size > largest) largest = size; }
        const struct screen207 *old = (const struct screen207 *)(p + 4);
        if (found < 3 && (header & 1) && size >= sizeof(*old) && old->magic == STATE_MAGIC) {
            unsigned at = 272 + found++ * 40;
            const uint32_t entry[] = {(uintptr_t)old, size, (uintptr_t)old->input,
                old->boot_ms, old->boot_keys, old->boot_token, old->mode,
                old->capture_stage, old->captures, old->encoded_bytes};
            memcpy(out + at, entry, sizeof(entry));
        }
        p += 4 + size;
    }
    diagnostic_word(out, 472, found);
    if (found == 1) {
        const uint32_t extra_bank[] = {0x3845584bu,KSC_EXTRA_BEGIN,KSC_EXTRA_END,s->extra_status,s->extra_crc,KSC_FILES,s->guard_crc};
        memcpy(out + 312, extra_bank, sizeof(extra_bank));
    }
    const struct ksc_usb *usb = s->usb;
    const uint32_t extra[] = {free_bytes, largest, blocks, usb ? usb->msc.phase : 0,
        usb ? usb->msc.lba : 0, usb ? usb->msc.blocks : 0, usb ? usb->msc.tx_size : 0,
        usb ? usb->msc.status | (uint32_t)usb->msc.sense << 8 | (uint32_t)usb->msc.asc << 16 : 0,
        usb ? usb->msc.last_nonread : 0, usb ? usb->rx_events : 0, usb ? usb->tx_events : 0,
        usb ? usb->bus_events : 0, usb ? usb->last_event : 0,
        usb ? usb->failed | (unsigned)usb->connected << 1 | (unsigned)usb->configured << 2 : 0,
        *(volatile const uint8_t *)0x20013f18u};
    for (unsigned n = 0; n < sizeof(extra) / sizeof(extra[0]); ++n)
        diagnostic_word(out, 392 + n * 4, extra[n]);
    const uint32_t watchdog[] = {*(volatile const uint32_t *)0x40049000u,
        *(volatile const uint32_t *)0x40049004u, s->watchdog_refreshes, s->watchdog_ms,
        *(volatile const uint16_t *)0x400540c0u};
    for (unsigned n = 0; n < sizeof(watchdog) / sizeof(watchdog[0]); ++n)
        diagnostic_word(out, 452 + n * 4, watchdog[n]);
    uint32_t bad[2]; memcpy(bad, s->bad_area, sizeof(bad));
    const uint32_t capture[] = {s->capture_pixels, s->capture_bytes, s->capture_flags,
        s->capture_flushes, bad[0], bad[1], s->capture_ms, s->render_crc};
    for (unsigned n = 0; n < sizeof(capture) / sizeof(capture[0]); ++n)
        diagnostic_word(out, 480 + n * 4, capture[n]);
}
static const uintptr_t raw_original[] = {0x90e9u, 0x90fbu, 0x910du, 0x911fu, 0x9131u, 0x9149u};
static bool raw_key(unsigned n) {
    struct screen207 *s = state();
    if (s) {
        unsigned b = buttons(); uint32_t now = tick();
        if (s->mode) return false;
        if (!b) { s->raw_latched = false; s->raw_single = 0; }
        if (b == CAPTURE_CHORD) s->raw_latched = true;
        if (s->raw_latched) return false;
        if (b == LEFT || b == RIGHT) {
            if (s->raw_single != b) { s->raw_single = (uint8_t)b; s->raw_since = now; }
            if (n >= 2 && n <= 3 && (uint32_t)(now - s->raw_since) < 150) return false;
        } else s->raw_single = 0;
    }
    return ((bool (*)(void))raw_original[n])();
}
static bool raw_back(void) { return raw_key(0); }
static bool raw_ok(void) { return raw_key(1); }
static bool raw_left(void) { return raw_key(2); }
static bool raw_right(void) { return raw_key(3); }
static bool raw_loader(void) { return raw_key(4); }
static bool raw_left_ok(void) { return raw_key(5); }
static void feed_watchdog(struct screen207 *s, uint32_t now) {
    /* The exact native reader's prologue at 0x24608..0x2461a refreshes WDT.
     * Preserve these two ordered stores when its dialog-producing body is
     * bypassed. Normal input still receives the native prologue exactly once. */
    volatile uint32_t *watchdog_register = (volatile uint32_t *)0x40049008u;
    *watchdog_register = 0x0123u; *watchdog_register = 0x3210u;
    ++s->watchdog_refreshes; s->watchdog_ms = now;
}
static bool suppress_keys(struct screen207 *s, void *data, uint32_t now) {
    feed_watchdog(s, now);
    *((uint8_t *)data + 14) = 0;
    *(uint32_t *)((uint8_t *)data + 4) = 0;
    return false;
}
static bool read_keys(void *input, void *data) {
    struct screen207 *s = state();
    key_cb original = (key_cb)(uintptr_t)0x24607u;
    if (s && s->input == input) original = s->reader;
    if (!s || s->input != input) return original(input, data);
    uint8_t *pressed = (uint8_t *)data + 14;
    uint32_t *key = (uint32_t *)((uint8_t *)data + 4);
    unsigned b = buttons(); uint32_t now = tick();
    if (s->mode) return suppress_keys(s, data, now);
    /* Exit + OK is the stock loader shortcut, handled outside LVGL too.
     * The arrow chord is filtered here and in the native raw-key callbacks. */
    if (!s->chord && b == CAPTURE_CHORD) {
        s->chord = true; s->since = now; s->fired = false; s->single = 0;
    }
    if (s->chord) {
        uint32_t held = now - s->since;
        if (!s->fired && ((b == CAPTURE_CHORD && held >= 2000) || (b != CAPTURE_CHORD && !(b & ~CAPTURE_CHORD) && held >= 500))) {
            s->request = held >= 2000 ? 2 : 1; s->fired = true;
        }
        if (b & ~CAPTURE_CHORD) s->fired = true;
        if (!(b & CAPTURE_CHORD)) s->chord = false;
        return suppress_keys(s, data, now);
    }
    /* The native reader can create dialogs before returning key data.
     * Defer its call itself, not just the returned LVGL press. */
    if (b == LEFT || b == RIGHT) {
        uint8_t arrow = b == LEFT ? 20 : 19;
        if (s->single != arrow) {
            s->single = arrow; s->single_since = now; s->forwarded = false;
        }
        if ((uint32_t)(now - s->single_since) < 150) {
            return suppress_keys(s, data, now);
        }
        s->forwarded = true;
    }
    bool more = original(input, data);
    if (!(b & CAPTURE_CHORD)) {
        if (s->single && !s->forwarded && !*pressed) { *key = s->single; *pressed = 1; }
        s->single = 0;
    }
    return more;
}
static void close_notice(struct screen207 *s) {
    if (s->notice_obj) delete_obj(s->notice_obj);
    if (s->notice_data) release(s->notice_data);
    s->notice_obj = NULL; s->notice_data = NULL;
}
static uint8_t notice_signal(void *obj, uint8_t sign, void *param) {
    struct screen207 *s = state();
    if (!s) return 1;
    uint8_t result = s->notice_signal(obj, sign, param);
    if (sign == 0 && s->notice_obj == obj) { /* Native LV_SIGNAL_CLEANUP. */
        s->notice_obj = NULL;
        if (s->notice_data) release(s->notice_data);
        s->notice_data = NULL;
    }
    return result;
}
static void text(uint8_t *pixels, const char *str, unsigned y) {
    const char chars[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /?+-";
    const uint16_t glyphs[] = {0x2bed,0x6bae,0x7927,0x6b6e,0x79a7,0x79a4,0x496f,0x5bed,0x7497,
        0x124e,0x5bad,0x4927,0x5ffd,0x7b6d,0x7b6f,0x7be4,0x7b7b,0x6bad,0x79cf,0x7492,
        0x5b6f,0x5b6a,0x5bfd,0x5aad,0x5a92,0x72a7,0x7b6f,0x2c97,0x73e7,0x73cf,0x5bc9,
        0x79cf,0x79ef,0x7292,0x7bef,0x7bcf,0,0x12a4,0x7282,0x05d0,0x01c0};
    unsigned len = 0; while (str[len]) ++len;
    if (len > 29) return;
    unsigned left = (240 - len * 8 + 2) / 2;
    for (unsigned i = 0; i < len; ++i) {
        unsigned g = 0; while (chars[g] && chars[g] != str[i]) ++g;
        if (!chars[g]) continue;
        for (unsigned yy = 0; yy < 10; ++yy) for (unsigned xx = 0; xx < 6; ++xx)
            if (glyphs[g] & (1u << (14 - yy / 2 * 3 - xx / 2))) {
                unsigned x = left + i * 8 + xx;
                pixels[8 + (y + yy) * 30 + x / 8] |= (uint8_t)(0x80u >> (x % 8));
            }
    }
}
static void notice(struct screen207 *s, const char *title, const char *detail, uint32_t now) {
    close_notice(s); s->notice_since = now;
    unsigned height = s->mode ? 240 : NOTICE_H;
    unsigned bytes = 8 + 30 * height;
    s->notice_data = alloc(bytes); if (!s->notice_data) return;
    memset(s->notice_data, 0, bytes); memset(s->notice_data, 255, 4); s->notice_data[7] = 255;
    text(s->notice_data, title, 18); text(s->notice_data, detail, 42);
    s->descriptor = (struct notice){7u | (240u << 10) | (height << 21), bytes, s->notice_data};
    s->notice_obj = create_image(layer_sys(NULL), NULL);
    if (!s->notice_obj) { close_notice(s); return; }
    s->notice_signal = signal_get(s->notice_obj);
    signal_set(s->notice_obj, notice_signal);
    image_src(s->notice_obj, &s->descriptor);
}
static bool blank(uint32_t address, size_t bytes) {
    const uint8_t *p = (const uint8_t *)(uintptr_t)address;
    while (bytes--) if (*p++ != 255) return false;
    return true;
}
static bool prepare_flash(struct screen207 *s) {
    if (s->flash_code) return true;
    size_t n = (uintptr_t)ksc207_flash_end - ((uintptr_t)ksc207_flash_start & ~1u);
    s->flash_code = alloc(n); if (!s->flash_code) return false;
    memcpy(s->flash_code, (const void *)((uintptr_t)ksc207_flash_start & ~1u), n);
    __asm__ volatile("dsb\nisb" ::: "memory"); return true;
}
static void flush_capture(void *display, const int16_t *area, const uint16_t *pixels) {
    struct screen207 *s = state(); struct ksc_encoder *e = s->encoder;
    struct capture_plan *p = s->plan;
    feed_watchdog(s, tick());
    ++s->capture_flushes;
    if (!e->failed) {
        if (area[0] != 0 || area[2] != 239 || area[1] < 0 || area[3] >= 240 || area[3] < area[1] ||
            area[1] != p->next) {
            e->failed = true; s->capture_flags |= 2; memcpy(s->bad_area, area, sizeof(s->bad_area));
        } else {
            p->next = area[3] + 1;
            int first = area[1] > p->first ? area[1] : p->first;
            int last = area[3] < p->last ? area[3] : p->last;
            if (first <= last) {
                unsigned count = (unsigned)(last - first + 1) * 240;
                const uint16_t *selected = pixels + (first - area[1]) * 240;
                (void)ksc_encode_pixels(e, selected, count);
                s->render_crc = ksc_crc_update(s->render_crc, (const uint8_t *)selected, count * 2);
            }
        }
    }
    s->flush(display, area, pixels);
}
static bool prepare_save(struct screen207 *s, size_t n) {
    uint32_t seq = 1;
    struct ksc_store_txn transaction;
    memset(&s->catalog, 0, sizeof(s->catalog));
    ksc_catalog_add_pair(&s->catalog, (const uint8_t *)KSC_FLASH_BASE, &seq);
    ksc207_nor_lock();
    ksc_store_mount(&ksc207_nor, &s->catalog, &seq);
    if (s->extra_status & 2) ksc_store_mount(&ksc207_extra, &s->catalog, &seq);
    bool ok = !ksc207_nor_doom() && s->catalog.count < KSC_FILES &&
        (((s->extra_status & 2) && ksc_store_begin(&ksc207_extra, n, seq, &transaction)) ||
         ksc_store_begin(&ksc207_nor, n, seq, &transaction));
    ksc207_nor_unlock();
    if (ok) {
        memset(&s->stream, 0, sizeof(s->stream));
        s->stream.transaction = transaction; s->stream.crc = ~0u;
    }
    return ok;
}
static bool stream_flush(struct capture_stream *w) {
    if (!w->used) return !w->transaction.failed;
    ksc207_nor_lock();
    bool ok = ksc_store_put(&w->transaction, w->page, w->used);
    ksc207_nor_unlock();
    if (ok) w->used = 0;
    return ok;
}
static bool stream_bytes(void *context, const uint8_t *data, size_t n) {
    struct capture_stream *w = context;
    w->crc = ksc_crc_update(w->crc, data, n);
    while (n) {
        unsigned target = 256 - ((w->transaction.at + KSC_RECORD_BYTES + w->transaction.written) & 255);
        unsigned bytes = target - w->used; if (bytes > n) bytes = (unsigned)n;
        memcpy(w->page + w->used, data, bytes); w->used += bytes; data += bytes; n -= bytes;
        if (w->used == target && !stream_flush(w)) return false;
    }
    return true;
}
static int coordinate(const uint8_t *o, unsigned n) { return ((const int16_t *)(o + 16))[n]; }
static bool equal(const char *a, const char *b) {
    if (!a) return false;
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}
static uint8_t *front_window(uint8_t *obj, unsigned depth, const char **fallback) {
    if (depth > 12 || (obj[0x34] & 16) || coordinate(obj, 0) > 239 || coordinate(obj, 2) < 0 ||
        coordinate(obj, 1) > 239 || coordinate(obj, 3) < 0) return NULL;
    for (uint8_t *c = child_next(obj, NULL); c; c = child_next(obj, c)) {
        uint8_t *w = front_window(c, depth + 1, fallback); if (w) return w;
    }
    if ((uintptr_t)signal_get(obj) == 0x31cd5u) {
        const char *label = **(const char ***)(obj + 36);
        if (equal(label, "Active") || equal(label, "Previous")) *fallback = "CAPACITY";
        else if (equal(label, "Application")) *fallback = "APPLICATION";
        else if (equal(label, "VBUS") && equal(*fallback, "SCREEN")) *fallback = "MEASUREMENT";
    }
    return (uintptr_t)signal_get(obj) == 0x3c9f9u ? obj : NULL;
}
static void plan_capture(struct capture_plan *p, uint8_t *display, bool tall) {
    memset(p, 0, sizeof(*p)); memcpy(p->metadata, "KSN1", 4);
    p->height = 240;
    const char *name = "SCREEN";
    uint8_t *win = front_window(*(uint8_t **)(display + 0x48), 0, &name);
    if (win) {
        uint8_t *ext = *(uint8_t **)(win + 36);
        name = *(const char **)(ext + 8);
        uint8_t *page = *(uint8_t **)ext;
        if (tall) {
            uint8_t *scroll = *(uint8_t **)(*(uint8_t **)(page + 36) + 4);
            int h = coordinate(scroll, 3) - coordinate(scroll, 1) + 1 + coordinate(page, 1);
            if (h > 240) {
                if (h > KSC_MAX_HEIGHT || coordinate(page, 0) != 0 || coordinate(page, 2) != 239 || coordinate(page, 3) != 239) {
                    p->height = -1; return;
                }
                p->page = page; p->scroll = scroll; p->height = (int16_t)h;
                p->top = (int16_t)coordinate(page, 1);
                p->original_y = (int16_t)(coordinate(scroll, 1) - p->top);
                p->bars = (*(uint8_t **)(page + 36))[32];
            }
        }
    }
    unsigned n = 8;
    if (name) for (unsigned i = 0; i < 80 && name[i] && n < KSC_META_BYTES - 1; ++i) {
        unsigned c = (uint8_t)name[i]; if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) p->metadata[n++] = (uint8_t)c;
    }
    p->metadata[4] = (uint8_t)p->height; p->metadata[5] = (uint8_t)(p->height >> 8); p->metadata[6] = 240;
}
static size_t render_capture(struct screen207 *s, uint8_t *display, bool writing, size_t capacity) {
    struct capture_plan *p = s->plan;
    s->capture_flags = 0; s->render_crc = ~0u; memset(s->bad_area, 0, sizeof(s->bad_area));
    if (writing && !stream_bytes(&s->stream, p->metadata, KSC_META_BYTES)) return 0;
    ksc_encode_sink(s->encoder, writing ? stream_bytes : NULL, &s->stream, capacity - KSC_META_BYTES);
    s->encoder->pixels = (unsigned)p->height * KSC_WIDTH;
    s->flush = *(flush_cb *)(display + 12); *(flush_cb *)(display + 12) = flush_capture;
    s->capture_stage = 3;
    if (p->scroll) { (*(uint8_t **)(p->page + 36))[32] &= (uint8_t)~31u; set_y(p->scroll, 0); }
    unsigned end = 0;
    do {
        p->first = 0; p->last = 239; p->next = 0; p->base = end * KSC_WIDTH;
        if (end) {
            set_y(p->scroll, (int16_t)(p->top - (int)end));
            int offset = p->top - coordinate(p->scroll, 1);
            int next = 240 + offset;
            if (next <= (int)end || next > p->height) { s->encoder->failed = true; break; }
            p->first = (int16_t)(240 - (next - (int)end)); end = (unsigned)next;
        } else end = 240;
        invalidate(*(void **)(display + 0x48)); refresh(*(void **)(display + 0x38));
        if (p->next != 240 || s->encoder->count != end * KSC_WIDTH) s->encoder->failed = true;
    } while (end < (unsigned)p->height && !s->encoder->failed);
    s->capture_stage = 4;
    *(flush_cb *)(display + 12) = s->flush;
    if (p->scroll) {
        set_y(p->scroll, p->original_y); (*(uint8_t **)(p->page + 36))[32] = p->bars;
        invalidate(*(void **)(display + 0x48)); refresh(*(void **)(display + 0x38));
    }
    size_t n = ksc_encode_finish(s->encoder);
    s->capture_pixels = s->encoder->count; s->capture_bytes = (uint32_t)s->encoder->used + KSC_META_BYTES;
    if (s->encoder->failed) s->capture_flags |= s->encoder->used >= capacity - KSC_META_BYTES ? 1u : 4u;
    if (s->encoder->count != s->encoder->pixels) s->capture_flags |= 8;
    return n ? n + KSC_META_BYTES : 0;
}
static void capture(struct screen207 *s, uint32_t now, bool tall) {
    struct capture_plan plan;
    ++s->captures; s->capture_stage = 1; s->encoded_bytes = 0;
    s->capture_pixels = s->capture_bytes = s->capture_flags = s->capture_flushes = 0;
    const char *title = "CAPTURE FAILED", *detail = "DRAW INCOMPLETE / RETRY";
    close_notice(s);
    uint8_t *display = display_default();
    if (!display || *(flush_cb *)(display + 12) != (flush_cb)(uintptr_t)0x1fff8001u ||
        *(const uint32_t *)display != KSC_GEOMETRY) { detail = "DISPLAY UNAVAILABLE"; goto done; }
    plan_capture(&plan, display, tall); s->plan = &plan;
    if (plan.height < 0) { detail = "LONG CAPTURE UNAVAILABLE"; goto done; }
    s->encoder = alloc(sizeof(*s->encoder));
    if (!s->encoder) { detail = "NO MEMORY"; goto done; }
    s->capture_stage = 2;
    /* Count first, then stream an uncommitted record through a page buffer.
     * A second redraw must match before CRC/readback and final commit. */
    size_t needed = render_capture(s, display, false, KSC_MAX_CAPTURE_BYTES);
    if (!needed) {
        if (s->capture_flags & 1) { title = "CAPTURE TOO LARGE"; detail = "TRY A SIMPLER SCREEN"; }
        goto done;
    }
    uint32_t crc = s->render_crc;
    if (!prepare_save(s, needed)) { title = "CAPTURE NOT SAVED"; detail = "COPY THEN CLEAR / RETRY"; goto done; }
    size_t n = render_capture(s, display, true, needed);
    s->encoded_bytes = (uint32_t)n; s->capture_stage = 5;
    if (!n || n != needed || s->render_crc != crc) { detail = "DISPLAY CHANGED / RETRY"; goto done; }
    bool saved = stream_flush(&s->stream);
    if (saved) {
        ksc207_nor_lock();
        saved = ksc_store_commit(&s->stream.transaction, ~s->stream.crc);
        ksc207_nor_unlock();
    }
    title = saved ? "CAPTURE SAVED" : "CAPTURE NOT SAVED";
    detail = saved ? "USB COPY AFTER RECONNECT" : "COPY THEN CLEAR / RETRY";
done:
    s->capture_stage = 6;
    if (s->encoder) { release(s->encoder); s->encoder = NULL; }
    s->plan = NULL;
    if (s->flash_code) { release(s->flash_code); s->flash_code = NULL; }
    s->capture_ms = tick() - now;
    notice(s, title, detail, tick());
    s->capture_stage = 7;
}
static void clear_tick(struct screen207 *s, uint32_t now) {
    unsigned b = buttons();
    if (!s->released) { if (!b) s->released = true; return; }
    if (b & BACK) { s->mode = 3; notice(s, "CLEAR CANCELLED", "UNPLUG TO RESTART", now); return; }
    if (b != OK) { s->chord = false; return; }
    if (!s->chord) { s->since = now; s->chord = true; }
    if ((uint32_t)(now - s->since) < 2000) return;
    bool ok = true;
    for (unsigned i = 0; i < KSC_SECTORS; ++i)
        if (!blank(KSC_FLASH_BASE + i * KSC_SECTOR, KSC_SECTOR) &&
            !ksc_storage_owned_sector((const uint8_t *)KSC_FLASH_BASE, i)) ok = false;
    ksc207_nor_lock();
    bool doom = ksc207_nor_doom();
    if (!doom && (!ksc_store_safe(&ksc207_nor) ||
        ((s->extra_status & 2) && !ksc_store_safe(&ksc207_extra)))) ok = false;
    if (ok) ok = prepare_flash(s);
    if (ok) ok = doom ? ksc207_nor_reclaim_doom() : ksc_store_clear(&ksc207_nor);
    if (ok && (s->extra_status & 2)) ok = ksc_store_clear(&ksc207_extra);
    ksc207_nor_unlock();
    for (uint32_t at = KSC_FLASH_BASE; ok && at < KSC_FLASH_END; at += KSC_SECTOR) {
        if (blank(at, KSC_SECTOR)) continue;
        flash_cb erase = (flash_cb)((uintptr_t)s->flash_code | 1u);
        ok = erase(at, 0, 1) && blank(at, KSC_SECTOR);
    }
    if (s->flash_code) { release(s->flash_code); s->flash_code = NULL; }
    s->mode = 3;
    notice(s, ok ? (doom ? "STORAGE READY" : "CAPTURES CLEARED") : "CLEAR FAILED", "UNPLUG TO RESTART", now);
}
void kpd207_gui_screen_tick(uint32_t boot_token) {
    void *layer = layer_sys(NULL); if (!layer) return;
    struct screen207 *s = state(); uint32_t now = tick();
    if (!s) {
        uint8_t *keypad = NULL;
        for (void *input = input_next(NULL); input; input = input_next(input)) {
            if (*(const uint8_t *)input != 2) continue;
            if (*(const uintptr_t *)((uint8_t *)input + 4) != 0x24607u ||
                *(const uintptr_t *)((uint8_t *)input + 12) != 0) return;
            keypad = input; break;
        }
        if (!keypad) return;
        for (unsigned n = 0; n < 6; ++n) if (RAW_KEYS[n * 4] != raw_original[n]) return;
        /* Sample only after native initialization has registered the keypad.
         * The task-entry gate runs before this initialization. Ownership in
         * the persistent keypad prevents a layer cleanup from sampling again. */
        unsigned boot_keys = buttons();
        bool export_boot = boot_token == 1 && now < 5000 && boot_keys == CAPTURE_CHORD;
        s = alloc(sizeof(*s)); if (!s) return;
        memset(s, 0, sizeof(*s)); s->magic = STATE_MAGIC;
        s->boot_ms = now; s->boot_keys = boot_keys; s->boot_token = boot_token;
        s->boot_reset = *(volatile const uint16_t *)0x400540c0u;
        s->input = keypad; s->reader = *(key_cb *)(keypad + 4);
        s->mode = export_boot ? 4 : 0; s->since = now;
        *(uintptr_t volatile *)(keypad + 12) = (uintptr_t)s;
        __asm__ volatile("dmb" ::: "memory");
        *(key_cb volatile *)(keypad + 4) = read_keys;
        bool (*const raw_readers[])(void) = {raw_back, raw_ok, raw_left, raw_right, raw_loader, raw_left_ok};
        for (unsigned n = 0; n < 6; ++n) RAW_KEYS[n * 4] = (uintptr_t)raw_readers[n];
        /* The APP/DFU read protocol does not expose the whole chip. Qualify
         * the extra mapped bank on-device without any erase/program command.
         * Foreign data disables that bank; the original bank remains usable. */
        feed_watchdog(s, tick());
        ksc207_nor_lock();
        s->extra_status = 1u | (ksc_store_safe(&ksc207_extra) ? 2u : 0u) |
            (blank(KSC_NOR_MAP + KSC_EXTRA_BEGIN, KSC_EXTRA_END - KSC_EXTRA_BEGIN) ? 4u : 0u);
        s->extra_crc = (s->extra_status & 2) ? ksc_crc(ksc207_extra.base, ksc207_extra.bytes) : 0;
        s->guard_crc = ksc_crc((const uint8_t *)(KSC_NOR_MAP + KSC_EXTRA_END), 0x400000 - KSC_EXTRA_END);
        ksc207_nor_unlock(); feed_watchdog(s, tick());
        if (export_boot) {
            s->mode = 4; s->since = now;
            ksc_catalog_init(&s->catalog, (const uint8_t *)KSC_FLASH_BASE);
            uint32_t seq = 1;
            for (unsigned i = 0; i < s->catalog.count; ++i)
                if (ksc_file_sequence(&s->catalog.files[i]) >= seq) seq = ksc_file_sequence(&s->catalog.files[i]) + 1;
            ksc207_nor_lock(); ksc_store_mount(&ksc207_nor, &s->catalog, &seq); ksc207_nor_unlock();
            if (s->extra_status & 2) {
                ksc207_nor_lock(); ksc_store_mount(&ksc207_extra, &s->catalog, &seq); ksc207_nor_unlock();
            }
            s->catalog.diagnostic = diagnostic;
            s->usb = alloc(sizeof(*s->usb));
            if (!s->usb) {
                s->mode = 3; notice(s, "USB EXPORT FAILED", "NO MEMORY / RECONNECT", now);
            } else notice(s, "USB SCREENSHOTS", "READ ONLY / UNPLUG TO EXIT", now);
        }
    }
    if (s->mode == 4) {
        if (ksc_usb_begin(s->usb, &s->catalog, now)) s->mode = 1;
        else if ((uint32_t)(now - s->since) >= 2500) {
            release(s->usb); s->usb = NULL; s->mode = 3;
            notice(s, "USB EXPORT FAILED", "UNPLUG TO RESTART", now);
        }
    } else if (s->mode == 1 && s->usb) {
        ksc_usb_poll(s->usb, now);
        if (buttons() != OK) s->chord = false;
        else if (!s->chord) { s->chord = true; s->since = now; }
        else if ((uint32_t)(now - s->since) >= 2000) {
            ksc_usb_disconnect(s->usb); s->mode = 5; s->since = now;
            s->chord = false; s->released = false;
            ksc207_nor_lock(); bool doom = ksc207_nor_doom(); ksc207_nor_unlock();
            notice(s, doom ? "ERASE DOOM DATA?" : "ERASE ALL CAPTURES?", "RELEASE THEN HOLD OK 2S", now);
        }
    } else if (s->mode == 5) {
        if ((uint32_t)(now - s->since) >= 250) s->mode = 2;
    }
    else if (s->mode == 2) clear_tick(s, now);
    else if (!s->mode && s->request) { bool tall = s->request == 2; s->request = 0; capture(s, now, tall); }
    else if (!s->mode && s->notice_obj && (uint32_t)(now - s->notice_since) >= 2000) close_notice(s);
}
