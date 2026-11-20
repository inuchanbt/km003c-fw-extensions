/* SPDX-License-Identifier: MIT. GUI-task boot intent is consumed once. */
.syntax unified
.cpu cortex-m4
.thumb
.section .text.ksc207_gui_tick,"ax",%progbits
.global ksc207_gui_tick
.type ksc207_gui_tick,%function
.thumb_func
ksc207_gui_tick:
    push {r4,lr}
    ldr r4, =0x39a19
    blx r4
    mov r0, r9
    movs r4, #0
    mov r9, r4
    bl kpd207_gui_screen_tick
    pop {r4,pc}
.size ksc207_gui_tick, .-ksc207_gui_tick
.ltorg
