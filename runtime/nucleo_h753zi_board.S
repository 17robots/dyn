// NUCLEO-H753ZI (MB1364). Reset clock: HSI 64 MHz, no PLL or cache changes.
// USART3 TX on PD8/AF7 reaches STLINK's virtual COM port, 115200 baud, 8N1.
// Register definitions: STM32H753 RM0433 and ST CMSIS stm32h753xx.h.
dyn_board_initialize:
    // Select LDO supply, clearing SCUEN/BYPASS, before any RAM writes.
    movw r0, #0x480C
    movt r0, #0x5802
    ldr.w r1, [r0]
    bic.w r1, r1, #7
    orr.w r1, r1, #2
    str.w r1, [r0]
.Lnucleo_supply:
    ldr.w r1, [r0, #-8]
    tst.w r1, #0x2000
    beq.w .Lnucleo_supply
    // Relocate vectors to flash, then initialize writable data from its LMA.
    movw r0, #0xED08
    movt r0, #0xE000
    mov.w r1, #0x08000000
    str.w r1, [r0]
    dsb sy
    isb sy
    movw r0, #:lower16:__data_start
    movt r0, #:upper16:__data_start
    movw r1, #:lower16:_edata
    movt r1, #:upper16:_edata
    movw r2, #:lower16:__data_load
    movt r2, #:upper16:__data_load
.Lnucleo_data:
    cmp.w r0, r1
    bhs.w .Lnucleo_uart
    ldrb.w r3, [r2], #1
    strb.w r3, [r0], #1
    b.w .Lnucleo_data
.Lnucleo_uart:
    // RCC AHB4ENR: GPIODEN; APB1LENR: USART3EN.
    movw r0, #0x44E0
    movt r0, #0x5802
    ldr.w r1, [r0]
    orr.w r1, r1, #8
    str.w r1, [r0]
    ldr.w r1, [r0]
    ldr.w r1, [r0, #8]
    orr.w r1, r1, #0x40000
    str.w r1, [r0, #8]
    ldr.w r1, [r0, #8]
    // USART234578SEL = HSI. HSI is enabled and undivided after system reset.
    movw r0, #0x4454
    movt r0, #0x5802
    ldr.w r1, [r0]
    bic.w r1, r1, #7
    orr.w r1, r1, #3
    str.w r1, [r0]
    // GPIOD MODER8 = alternate function; AFRH8 = AF7, push-pull, no pull.
    movw r0, #0x0C00
    movt r0, #0x5802
    ldr.w r1, [r0]
    bic.w r1, r1, #0x30000
    orr.w r1, r1, #0x20000
    str.w r1, [r0]
    ldr.w r1, [r0, #0x24]
    bic.w r1, r1, #15
    orr.w r1, r1, #7
    str.w r1, [r0, #0x24]
    // BRR = round(64000000 / 115200), oversampling by 16, TE | UE.
    movw r0, #0x4800
    movt r0, #0x4000
    movw r1, #556
    str.w r1, [r0, #12]
    mov.w r1, #9
    str.w r1, [r0]
    bx lr
.global dyn_console_write
dyn_console_write:
    movw r12, #0x4800
    movt r12, #0x4000
    add.w r2, r0, r2
.Lnucleo_next:
    cmp.w r0, r2
    bhs.w .Lnucleo_done
.Lnucleo_busy:
    ldr.w r1, [r12, #0x1C]
    tst.w r1, #0x80
    beq.w .Lnucleo_busy
    ldrb.w r1, [r0], #1
    str.w r1, [r12, #0x28]
    b.w .Lnucleo_next
.Lnucleo_done:
    bx lr
.global dyn_memory_start
dyn_memory_start:
    movw r0, #:lower16:_end
    movt r0, #:upper16:_end
    add.w r0, r0, #15
    bic.w r0, r0, #15
    bx lr
.global dyn_memory_end
dyn_memory_end:
    movw r0, #0
    movt r0, #0x2408
    bx lr
// No semihosting dependency: retain status for the debugger, then sleep.
.global dyn_exit
dyn_exit:
    movw r1, #:lower16:dyn_exit_status
    movt r1, #:upper16:dyn_exit_status
    str.w r0, [r1]
.Lnucleo_halt:
    wfi
    b.w .Lnucleo_halt
.bss
.p2align 2
.global dyn_exit_status
dyn_exit_status:
    .long 0
.text
