#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check the syscon-semaphore grant gate and the vdump failure output.

Synthetic A53 program only: the fixture copies load instructions into the
low service RAM window so one load sits exactly at the measured acquire
pc 0x082013d4, then calls it with controlled registers. No firmware.

- Grant gate (syscon-semaphore-model on): the acquire-pc load of
  0x0d151404 reads retained|1 and logs exactly one Z8_SEMAPHORE_GRANT;
  the same load at another pc, the neighbor word 0x0d151408 at the
  acquire pc, and a byte-wide read at the acquire pc do not grant.
- Disabled behavior (property unset): the acquire-pc load reads the
  retained word unchanged and no grant line appears.
- vdump failures (syscon-semaphore-trace on, lr pointed into the module
  window): the fixture enables the EL3 MMU with identity tables that
  leave two 4KiB translation holes, so one dump contains both failure
  shapes: the module window fails mid-dump (a success followed by a
  failure) and the taskstack starts in a hole (an initial failure). No
  FAIL line carries payload bytes (the stale/uninitialized-chunk bug).
"""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from check_mcu_reset import elf_text
from qemu_control import QMP, stop_child, wait_for_sockets

MAGIC = 0x5A85F1D0

PROLOGUE = r'''
.section .text
.global _start
_start:
    ldr x9, =0xa00010000
    ldr x10, =0xa00010800
    mov sp, x10
    /* Install the gated stub at the acquire pc: instruction under test
     * at 0x082013d4, then str w2,[x20]; br x4. Word installs only:
     * the CPU resets into EL3 where 8-byte stores fault unaligned. */
    ldr x0, =0x082013d4
    ldr x1, =tpl_ldr
    ldr w2, [x1]
    str w2, [x0]
    ldr x1, =tpl_tail_str
    ldr w2, [x1]
    str w2, [x0, #4]
    ldr x1, =tpl_tail_br
    ldr w2, [x1]
    str w2, [x0, #8]
    /* Install the identical stub at an un-gated pc. */
    ldr x0, =0x08201400
    ldr x1, =tpl_ldr
    ldr w2, [x1]
    str w2, [x0]
    ldr x1, =tpl_tail_str
    ldr w2, [x1]
    str w2, [x0, #4]
    ldr x1, =tpl_tail_br
    ldr w2, [x1]
    str w2, [x0, #8]
'''

GATED_CALL = r'''
    ldr x1, ={addr:#x}
    add x20, x9, #{slot}
    ldr x4, ={label}_ret
    ldr x30, =0xa02ab0010
    ldr x0, ={pc:#x}
    br x0
{label}_ret:
'''

PHASES_GATES = ''.join([
    GATED_CALL.format(addr=0x0d151404, slot=0, label='p0', pc=0x08201400),
    GATED_CALL.format(addr=0x0d151404, slot=4, label='p1', pc=0x082013d4),
    GATED_CALL.format(addr=0x0d151408, slot=8, label='p2', pc=0x08201400),
    GATED_CALL.format(addr=0x0d151408, slot=12, label='p3', pc=0x082013d4),
    r'''
    /* Rewrite the acquire pc to a byte-wide load: the size gate. */
    ldr x0, =tpl_ldrb
    ldr w2, [x0]
    ldr x0, =0x082013d4
    str w2, [x0]
''' + GATED_CALL.format(addr=0x0d151404, slot=16, label='p4', pc=0x082013d4),
])

PHASES_DISABLED = ''.join([
    GATED_CALL.format(addr=0x0d151404, slot=0, label='p0', pc=0x08201400),
    GATED_CALL.format(addr=0x0d151404, slot=4, label='p1', pc=0x082013d4),
])

PHASES_VDUMP = r'''
    /* Stage-1 tables in work-ram (identity map with two 4KiB translation
     * holes): page tables at 0xa00020000..0xa00023fff, L3 window covering
     * [0xa02a00000, 0xa02c00000). Holes: page 0 (taskstack base) and
     * page 0xc (module dump +0x1000). */
    ldr x0, =0xa00023000
    ldr x1, =0x703
    mov x2, #0
    ldr x3, =0xa02a00000
l3fill:
    orr x4, x3, x1
    str x4, [x0, x2, lsl #3]
    add x3, x3, #0x1000
    add x2, x2, #1
    cmp x2, #512
    b.lt l3fill
    str xzr, [x0]
    str xzr, [x0, #0x588]
    ldr x0, =0xa00022000
    ldr x1, =0xa00000000
    orr x1, x1, #0x700
    orr x1, x1, #1
    str x1, [x0]
    ldr x1, =0xa00023000
    orr x1, x1, #3
    str x1, [x0, #0xa8]
    ldr x0, =0xa00021000
    ldr x1, =0x701
    str x1, [x0]
    ldr x1, =0x40000000
    orr x1, x1, #0x700
    orr x1, x1, #1
    str x1, [x0, #8]
    ldr x1, =0xa00022000
    orr x1, x1, #3
    str x1, [x0, #0x140]
    ldr x0, =0xa00020000
    ldr x1, =0xa00021000
    orr x1, x1, #3
    str x1, [x0]
    ldr x1, =0xff
    msr mair_el3, x1
    ldr x1, =0x20018
    msr tcr_el3, x1
    ldr x1, =0xa00020000
    msr ttbr0_el3, x1
    dsb sy
    isb
    mrs x1, sctlr_el3
    orr x1, x1, #1
    msr sctlr_el3, x1
    isb
    ldr x1, =0x0d151404
    mov x20, x9
    ldr x4, =v_ret
    ldr x30, =0xa02ab0010
    ldr x10, =0xa02a01800
    mov sp, x10
    ldr x0, =0x082013d4
    br x0
v_ret:
'''

EPILOGUE = r'''
    ldr x10, =0x5a85f1d0
    str x10, [x9, #0x20]
    mov x11, #0
loop:
    add x11, x11, #1
    str x11, [x9, #0x28]
    b loop
.balign 8
tpl_tail_str:
    str w2, [x20]
tpl_tail_br:
    br  x4
tpl_ldr:
    ldr  w2, [x1]
tpl_ldrb:
    ldrb w2, [x1]
.ltorg
'''


def fixture_source(phases):
    return PROLOGUE + phases + EPILOGUE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default=os.environ.get('CLANG', 'clang'))
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(original_firmware_loaded=False,
                  qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),
                  checks=[], boots=[])
    proc = qmp = None

    def check(name, passed):
        report['checks'].append(dict(name=name, passed=bool(passed)))
        if not passed:
            raise AssertionError(name)

    def compile_fixture(name, source):
        text = out / (name + '.S')
        text.write_text(source)
        obj = out / (name + '.o')
        exe = out / (name + '.elf')
        subprocess.run([args.clang, '--target=aarch64-none-elf', '-c',
                        str(text), '-o', str(obj)], check=True, capture_output=True)
        # Link at the kernel base so label literals (return addresses) are
        # resolved; elf_text rejects .text with remaining relocations.
        subprocess.run([args.clang, '--target=aarch64-none-elf', '-fuse-ld=lld',
                        '-nostdlib', '-Wl,--build-id=none',
                        '-Wl,-Ttext=0x40160000', str(obj), '-o', str(exe)],
                       check=True, capture_output=True)
        binary = out / (name + '.bin')
        binary.write_bytes(elf_text(exe.read_bytes()))
        return binary

    def boot(name, machine, kernel, temp, extra=()):
        endpoint = Path(temp) / ('qmp-' + name)
        command = [str(args.qemu.resolve()), '-M', machine,
                   '-cpu', 'cortex-a53', '-smp', '4,maxcpus=5',
                   '-kernel', str(kernel), '-accel', 'tcg,thread=single',
                   '-display', 'none', '-serial', 'none', '-monitor', 'none',
                   '-nic', 'none', '-S', '-no-reboot', *extra,
                   '-qmp', f'unix:{endpoint},server=on,wait=off']
        log = (out / ('stderr-' + name + '.log')).open('wb')
        child = subprocess.Popen(command, stdout=log, stderr=log)
        wait_for_sockets(child, endpoint)
        for attempt in range(50):  # the socket file can precede listen()
            try:
                return child, QMP(endpoint)
            except ConnectionRefusedError:
                if child.poll() is not None:
                    break
                time.sleep(.05)
        return child, QMP(endpoint)

    def scratch(qmp, temp, size=64):
        dump = Path(temp) / 'scratch.bin'
        qmp.command('pmemsave', val=0xa00010000, size=size, filename=str(dump))
        return dump.read_bytes()

    def run_until(qmp, temp, deadline_seconds=10):
        deadline = time.monotonic() + deadline_seconds
        data = b'\0' * 64
        while time.monotonic() < deadline:
            qmp.command('cont')
            time.sleep(.15)
            qmp.command('stop')
            data = scratch(qmp, temp)
            if struct.unpack_from('<I', data, 0x20)[0] == MAGIC:
                return data, True
        return data, False

    base = 'nikon-z8-lab,bootstrap-fixtures=on,bus-window-fixture=on,' \
           'serial-fixture=on,image-bank-model=on,low-service-ram-model=on'
    try:
        gates = compile_fixture('gates', fixture_source(PHASES_GATES))
        disabled = compile_fixture('disabled', fixture_source(PHASES_DISABLED))
        vdump = compile_fixture('vdump', fixture_source(PHASES_VDUMP))

        with tempfile.TemporaryDirectory(prefix='z8-sem-') as temp:
            # Boot 1: the exact pc/address/size grant gate, model on.
            machine = base + ',syscon-semaphore-model=on'
            report['boots'].append(machine)
            proc, qmp = boot('gates', machine, gates, temp)
            data, done = run_until(qmp, temp)
            stderr = (out / 'stderr-gates.log').read_text(errors='replace')
            grants = [line for line in stderr.splitlines()
                      if line.startswith('Z8_SEMAPHORE_GRANT ns=')]
            unknown = [line for line in stderr.splitlines()
                       if line.startswith('Z8_UNKNOWN')]
            words = struct.unpack_from('<8I', data, 0)
            check('gates fixture completed or stopped on the byte read',
                  done or unknown)
            check('baseline retained word has bit0 clear', (words[0] & 1) == 0)
            check('acquire-pc load reads retained|1',
                  words[1] == (words[0] | 1))
            check('neighbor word at the acquire pc is not granted',
                  words[3] == words[2])
            check('exactly one grant, at the acquire pc',
                  len(grants) == 1 and 'pc=82013d4' in grants[0])
            check('the only unmodeled stop, if any, is the byte read',
                  all('addr=0xd151404 size=1' in line for line in unknown))
            stop_child(proc, qmp)
            qmp = None

            # Boot 2: the disabled (default-off) behavior.
            report['boots'].append(base)
            proc, qmp = boot('disabled', base, disabled, temp)
            data, done = run_until(qmp, temp)
            stderr = (out / 'stderr-disabled.log').read_text(errors='replace')
            words = struct.unpack_from('<8I', data, 0)
            check('disabled fixture completed', done)
            check('disabled: acquire-pc load reads the retained word',
                  words[1] == words[0] and (words[0] & 1) == 0)
            check('disabled: no grant line',
                  'Z8_SEMAPHORE_GRANT' not in stderr)
            stop_child(proc, qmp)
            qmp = None

            # Boot 3: vdump FAIL lines never carry payload bytes. The MMU-on
            # fixture builds one dump containing both failure shapes: the
            # module window fails mid-dump (success followed by failure) and
            # the taskstack starts in a translation hole (initial failure).
            machine = base + ',syscon-semaphore-trace=on'
            report['boots'].append(machine)
            proc, qmp = boot('vdump', machine, vdump, temp)
            data, done = run_until(qmp, temp)
            stderr = (out / 'stderr-vdump.log').read_text(errors='replace')
            lines = stderr.splitlines()

            def line_is(line, label, offset, kind):
                if kind == 'FAIL':
                    return line == 'Z8_VDUMP %s +0x%x FAIL' % (label, offset)
                return line.startswith('Z8_VDUMP %s +0x%x ok ' % (label, offset))

            stacks = [line for line in lines
                      if line.startswith('Z8_VDUMP taskstack +')]
            modules = [line for line in lines
                       if line.startswith('Z8_VDUMP module +')]
            check('vdump fixture completed', done)
            check('vdump dump fired at the acquire pc',
                  any(line.startswith('Z8_SEM1404_DUMP') and
                      'lr=0xa02ab0010' in line and 'sp=0xa02a01800' in line
                      for line in lines))
            check('module dump reads ok before the mid-window hole',
                  any(line_is(line, 'module', 0, 'ok') for line in modules))
            check('module dump fails inside the window without payload bytes',
                  any(line_is(line, 'module', 0x1000, 'FAIL') for line in modules))
            check('module dump reads ok again after the hole',
                  any(line_is(line, 'module', 0x2000, 'ok') for line in modules))
            check('taskstack starts with a bare FAIL line',
                  stacks and line_is(stacks[0], 'taskstack', 0, 'FAIL'))
            check('taskstack reads ok after the initial failure',
                  any(line_is(line, 'taskstack', 0x1000, 'ok') for line in stacks))
            check('no FAIL line carries payload bytes',
                  not re.search(r'FAIL [0-9a-f]+', stderr))
            stop_child(proc, qmp)
            qmp = None
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        stop_child(proc, qmp)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Passed', len(report['checks']),
          'syscon-semaphore checks; synthetic programs only')


if __name__ == '__main__':
    main()
