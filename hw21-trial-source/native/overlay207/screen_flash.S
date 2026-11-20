/* SPDX-License-Identifier: MIT. Copied to owned executable heap memory.
 * r0: aligned capture address, r1: value, r2: 0 program / 1 sector erase.
 * No flash fetches, literal pools, external calls, or interrupt handlers while
 * EFM is busy. Restores PRIMASK and the original EFM control/cache settings.
 * Mode/permission sequence matches the vendor DDL EFM_SingleProgram /
 * EFM_SectorErase (Klipper's vendored hc32f460_efm.c/.h).
 */
.syntax unified
.thumb
.section .text.ksc207_flash,"ax",%progbits
.balign 4
.global ksc207_flash_start
.global ksc207_flash_end
.type ksc207_flash_start,%function
.thumb_func
ksc207_flash_start:
    push {r4-r7,lr}
    movw r3, #0x8000
    movt r3, #7
    cmp r0, r3
    blo 9f
    movw r3, #0xc000
    movt r3, #7
    cmp r0, r3
    bhs 9f
    tst r0, #3
    bne 9f
    cmp r2, #1
    bhi 9f
    cbz r2, 1f
    ubfx r3, r0, #0, #13
    cmp r3, #0
    bne 9f
    movw r1, #0x5678
    movt r1, #0x1234
1:
    mrs r7, primask
    cpsid i
    movw r3, #0x0400
    movt r3, #0x4001
    ldr r4, [r3, #8]
    ldr r5, [r3, #12]
    ldr r6, [r3, #4]
    push {r4-r6}
    ldr r4, [r3]
    cmp r4, #0
    bne 10f
    tst r5, #0x70
    bne 10f
    ldr r4, [r3, #16]
    tst r4, #0x100
    beq 10f
    movw r4, #0x0123
    str r4, [r3]
    movw r4, #0x3210
    str r4, [r3]
    ldr r4, [r3]
    cbz r4, 7f
    movs r4, #0
    str r4, [r3, #4]
    ldr r4, [r3, #8]
    bic r4, r4, #0x10000
    str r4, [r3, #8]
    movs r4, #0x3f
    str r4, [r3, #20]
    /* Vendor DDL: single-word program=1, sector erase=4 (never sequence=3
     * or chip erase=5). PEMODE must already be enabled before PEMOD changes. */
    add r2, r2, r2, lsl #1
    adds r2, #1
    ldr r4, [r3, #12]
    orr r4, r4, #1
    str r4, [r3, #12]
    bfi r4, r2, #4, #3
    str r4, [r3, #12]
    dsb
    str r1, [r0]
    dsb
    movw r4, #0xffff
    movt r4, #0x003f
2:
    ldr r2, [r3, #16]
    /* Single program/sector erase finish at RDY. OPTEND need not be set
     * on a rejected write; errors must return safely once the bus is idle. */
    tst r2, #0x100
    bne 3f
    subs r4, #1
    bne 2b
    /* A busy flash cannot safely return to flash code. Reset from RAM. */
    movw r0, #0xed0c
    movt r0, #0xe000
    movw r1, #4
    movt r1, #0x05fa
    str r1, [r0]
    dsb
4:  b 4b
3:
    tst r2, #0x2f
    ite eq
    moveq r0, #1
    movne r0, #0
    b 8f
7:  movs r0, #0
8:
    movs r4, #0x10
    str r4, [r3, #20]
    pop {r4-r6}
    orr r2, r5, #1
    str r2, [r3, #12]
    str r5, [r3, #12]
    str r6, [r3, #4]
    orr r5, r4, #0x1000000
    str r5, [r3, #8]
    bic r5, r4, #0x1000000
    str r5, [r3, #8]
    movs r5, #0
    str r5, [r3]
    dsb
    isb
    msr primask, r7
    pop {r4-r7,pc}
10: pop {r4-r6}
    movs r0, #0
    msr primask, r7
    pop {r4-r7,pc}
9:  movs r0, #0
    pop {r4-r7,pc}
.balign 4
ksc207_flash_end:
.size ksc207_flash_start, .-ksc207_flash_start
