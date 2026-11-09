#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check the default-off mcu-switch-candidate semantic alias on the native MCU.

Synthetic A53/M4 programs only: the M4 fixture configures the measured
stock-EX pull pattern (pull-up on B11/C2/F6/G2, floating C5/G14), then
the checks drive each whitelisted switch candidate through
mcu-switch-candidate / mcu-switch-candidate-pin and read the state back
through the EX IDR (native-mcu-io-state). Requires clang with
AArch64/Thumb targets.

The alias borrows the selected pin only while mcu-switch-candidate is
true: turning it off, or switching pins while on, hands the pin back --
the pin's accumulated generic mcu-pins drive when one is in effect
(runtime mcu-pins sets re-take the pins they list and never release
unlisted ones, so the effective drive is tracked per pin, not
re-derived from the last spec string), otherwise a true release to the
pull state. While the alias is off, selecting a pin changes no hardware
state. The second boot runs the same alias against an existing generic
mcu-pins drive (PB11=0:PC5=1) and checks selecting, asserting,
deasserting and switching coexist with it; the first boot additionally
walks the incremental-update review case (two separate runtime sets,
then a borrow cycle) and repeated assignments within one spec, where
the last value wins both in hardware and on hand-back.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

from check_mcu_reset import elf_text, FIXTURES
from qemu_control import QMP, stop_child, wait_for_sockets

# Dual-evidence whitelist (E1 e1-r5..r13 + E2a re-verification): pin ->
# (gpio port index, pin, idle IDR level, assert level). Stock EX idles
# B11/C2/F6/G2 pulled up and C5/G14 floating; asserting drives the pin
# away from idle (low for the pulled-up four, high for C5/G14).
PINS = {
    'PB11': (1, 11, 1, 0), 'PC2': (2, 2, 1, 0), 'PF6': (5, 6, 1, 0),
    'PG2': (6, 2, 1, 0), 'PC5': (2, 5, 0, 1), 'PG14': (6, 14, 0, 1),
}
PUPDR = {1: 1 << (2 * 11), 2: 1 << (2 * 2), 5: 1 << (2 * 6), 6: 1 << (2 * 2)}

M4='''
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000041
.org 0x40
.thumb_func
start:
ldr r0, =0x4002040C
ldr r1, =0x00400000
str r1, [r0]
ldr r0, =0x4002080C
ldr r1, =0x00000010
str r1, [r0]
ldr r0, =0x4002140C
ldr r1, =0x00001000
str r1, [r0]
ldr r0, =0x4002180C
ldr r1, =0x00000010
str r1, [r0]
ldr r0, =0x20001000
movs r1, #0
loop:
adds r1, #1
str r1, [r0]
b loop
.ltorg
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--clang',default=os.environ.get('CLANG','clang'))
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),checks=[])
    proc=qmp=None
    def check(name,passed):
        report['checks'].append(dict(name=name,passed=bool(passed)))
        if not passed:raise AssertionError(name)
    def compile(name,source,target,flags=()):
        text=out/(name+'.S');text.write_text(source);obj=out/(name+'.o');binary=out/(name+'.bin')
        subprocess.run([args.clang,'--target='+target,'-c',str(text),'-o',str(obj),*flags],check=True,capture_output=True)
        binary.write_bytes(elf_text(obj.read_bytes()));return binary
    a53=compile('a53',(FIXTURES/'a53-reset-heartbeat.S').read_text(),'aarch64-none-elf')
    mcu=compile('mcu',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    try:
        with tempfile.TemporaryDirectory(prefix='z8-switch-candidate-') as temp:
            def boot(machine,name):
                endpoint=Path(temp)/('qmp-'+name)
                command=[str(args.qemu.resolve()),'-M',machine,
                    '-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single',
                    '-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot',
                    '-qmp',f'unix:{endpoint},server=on,wait=off']
                log=(out/f'stderr-{name}.log').open('wb')
                child=subprocess.Popen(command,stdout=log,stderr=log)
                wait_for_sockets(child,endpoint)
                for attempt in range(50):  # the socket file can precede listen()
                    try:
                        return child,QMP(endpoint)
                    except ConnectionRefusedError:
                        if child.poll() is not None:
                            break
                        time.sleep(.05)
                return child,QMP(endpoint)
            report['boots']=[]
            machine=f'nikon-z8-lab,mcu-image={mcu},bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on'
            report['boots'].append(machine)
            proc,qmp=boot(machine,'native')
            def io():
                qmp.command('cont');time.sleep(.02);qmp.command('stop')
                return {g['port']:g for g in json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-io-state'))['gpio']}
            deadline=time.monotonic()+5
            while True:
                gpio=io()
                if all(gpio[p]['pull']==v for p,v in PUPDR.items()) or time.monotonic()>deadline:break
            check('M4 fixture applied the stock-EX pull pattern',all(gpio[p]['pull']==v for p,v in PUPDR.items()))
            def pin_state(gpio,name):
                port,pin,_,_=PINS[name]
                g=gpio[port]
                return bool((g['input']>>pin)&1),bool((g['driven']>>pin)&1)
            check('default off: no candidate pin is driven',all(not pin_state(gpio,n)[1] for n in PINS))
            check('default off: inputs idle at the measured levels',
                  all(pin_state(gpio,n)[0]==idle for n,(_,_,idle,_) in PINS.items()))
            check('default pin is PB11',qmp.command('qom-get',path='/machine',property='mcu-switch-candidate-pin')=='PB11')
            check('default candidate level is off',qmp.command('qom-get',path='/machine',property='mcu-switch-candidate') is False)
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io();level,driven=pin_state(gpio,'PB11')
            check('candidate on without an explicit pin borrows the default PB11',driven and level==PINS['PB11'][3])
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PC2')
            gpio=io()
            check('switching from the default hands PB11 back and asserts PC2',
                  pin_state(gpio,'PB11')==(PINS['PB11'][2],False) and pin_state(gpio,'PC2')==(PINS['PC2'][3],True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('candidate off after the switch releases PC2 to its pull state',
                  pin_state(gpio,'PC2')==(PINS['PC2'][2],False))
            for name in ('PB11','PC2','PF6','PG2','PC5','PG14'):
                qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value=name)
                qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
                gpio=io();level,driven=pin_state(gpio,name)
                check(f'{name} assert drives the measured assert level',driven and level==PINS[name][3])
                qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
                gpio=io()
                check(f'{name} release returns the pin un-driven at its pull state',
                      pin_state(gpio,name)==(PINS[name][2],False))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PC5')
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('switching pins hands the previous candidate back',
                  pin_state(gpio,'PG14')==(PINS['PG14'][2],False) and pin_state(gpio,'PC5')==(True,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='pc2')
            check('lowercase pin spelling canonicalizes',qmp.command('qom-get',path='/machine',property='mcu-switch-candidate-pin')=='PC2')
            before=io()
            for value in ('G7','A0','B16','B11=0','','PC5=1','PB9'):
                rejected=False
                try:qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value=value)
                except RuntimeError:rejected=True
                check('non-whitelisted pin rejected: '+repr(value),rejected)
            check('rejections left the pin state unchanged',io()==before)

            # Incremental generic updates: runtime mcu-pins sets accumulate
            # per pin, so a hand-back must restore the accumulated drive,
            # not what the last spec string happens to list (review case).
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PB11')
            gpio=io()
            check('selecting PB11 while off leaves the state untouched',
                  all(not pin_state(gpio,n)[1] for n in PINS))
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='B11=0')
            gpio=io()
            check('a first incremental mcu-pins set drives PB11 low',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='C5=1')
            gpio=io()
            check('a later incremental set keeps the earlier drive',
                  pin_state(gpio,'PB11')==(0,True) and pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('borrowing PB11 over accumulated drives stays driven low',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('hand-back retains the accumulated generic low drive',
                  pin_state(gpio,'PB11')==(0,True) and pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='B11=1,B11=0')
            gpio=io()
            check('repeated assignments in one spec leave the last value',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('hand-back after repeated assignments restores the last value',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PC5')
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('a borrowed PC5 hands back to its accumulated high drive',
                  pin_state(gpio,'PC5')==(1,True))

            # A runtime mcu-pins set re-takes the borrowed pin itself: the
            # generic write wins immediately and the later hand-back must
            # keep it (last writer wins), not revert to the older drive.
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PB11')
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('borrowing over the accumulated drives asserts PB11 low again',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='B11=1')
            gpio=io()
            check('a runtime mcu-pins set re-takes the borrowed pin',
                  pin_state(gpio,'PB11')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('hand-back after the re-take keeps the newer generic drive',
                  pin_state(gpio,'PB11')==(1,True) and pin_state(gpio,'PC5')==(1,True))

            # Switching the selected pin while the alias is on hands the
            # previous candidate back to its accumulated drive.
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('re-borrowing PB11 asserts low over the re-taken drive',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PC5')
            gpio=io()
            check('switching while on hands PB11 back to its accumulated drive',
                  pin_state(gpio,'PB11')==(1,True) and pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('deasserting after the switch restores the PC5 drive',
                  pin_state(gpio,'PC5')==(1,True))

            # A malformed item rejects the spec, but the items before it
            # already applied (one validate-and-apply pass); the retained
            # string keeps the last accepted write. The hand-back must use
            # what actually applied, not that string.
            rejected=False
            try:qmp.command('qom-set',path='/machine',property='mcu-pins',value='B11=0,NOTAPIN')
            except RuntimeError:rejected=True
            check('a malformed item rejects the whole spec',rejected)
            gpio=io()
            check('the valid prefix item still applied',pin_state(gpio,'PB11')==(0,True))
            check('the rejected spec does not update the retained string',
                  qmp.command('qom-get',path='/machine',property='mcu-pins')=='B11=1')
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('hand-back uses what applied, not the retained string',
                  pin_state(gpio,'PB11')==(0,True))
            stop_child(proc,qmp);qmp=None;check('native boot reaped',proc.poll() is not None)

            # Second native boot: the alias against an existing generic drive.
            machine=f'nikon-z8-lab,mcu-image={mcu},mcu-pins=B11=0:C5=1,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on'
            report['boots'].append(machine)
            proc,qmp=boot(machine,'generic')
            deadline=time.monotonic()+5
            while True:
                gpio=io()
                if all(gpio[p]['pull']==v for p,v in PUPDR.items()) or time.monotonic()>deadline:break
            check('generic boot applies the pull pattern too',all(gpio[p]['pull']==v for p,v in PUPDR.items()))
            check('the generic mcu-pins drives are in effect',
                  pin_state(gpio,'PB11')==(0,True) and pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PC2')
            gpio=io()
            check('selecting a pin while the alias is off touches nothing',
                  pin_state(gpio,'PB11')==(0,True) and pin_state(gpio,'PC5')==(1,True)
                  and pin_state(gpio,'PC2')==(PINS['PC2'][2],False))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PG14')
            gpio=io()
            check('switching selection while off stays bookkeeping',
                  pin_state(gpio,'PG14')==(PINS['PG14'][2],False)
                  and pin_state(gpio,'PB11')==(0,True) and pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('turning the alias on borrows the un-listed candidate only',
                  pin_state(gpio,'PG14')==(PINS['PG14'][3],True)
                  and pin_state(gpio,'PB11')==(0,True) and pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('turning the alias off releases the un-listed candidate',
                  pin_state(gpio,'PG14')==(PINS['PG14'][2],False))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PB11')
            gpio=io()
            check('asserting over a generic drive keeps the generic level visible',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io();level,driven=pin_state(gpio,'PB11')
            check('the borrowed PB11 reads its assert level (0 here, the generic value)',driven and level==0)
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('deasserting restores the generic drive, not a release',
                  pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='PC5')
            gpio=io()
            check('selecting PC5 while off keeps its generic drive',
                  pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('borrowing PC5 asserts high, the same level as its generic drive',
                  pin_state(gpio,'PC5')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('deasserting PC5 restores the generic high drive (not the alias idle 0)',
                  pin_state(gpio,'PC5')==(1,True))
            stop_child(proc,qmp);qmp=None;check('generic boot reaped',proc.poll() is not None)

            # Third native boot: the alias asserted at machine creation over
            # a machine-time generic drive.
            machine=f'nikon-z8-lab,mcu-image={mcu},mcu-pins=B11=1,mcu-switch-candidate=on,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on'
            report['boots'].append(machine)
            proc,qmp=boot(machine,'creation')
            deadline=time.monotonic()+5
            while True:
                gpio=io()
                if all(gpio[p]['pull']==v for p,v in PUPDR.items()) or time.monotonic()>deadline:break
            check('creation boot applies the pull pattern too',all(gpio[p]['pull']==v for p,v in PUPDR.items()))
            check('the creation-time borrow asserts over the generic drive',
                  qmp.command('qom-get',path='/machine',property='mcu-switch-candidate') is True
                  and pin_state(gpio,'PB11')==(0,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=False)
            gpio=io()
            check('deasserting the creation-time borrow restores the generic drive',
                  pin_state(gpio,'PB11')==(1,True))
            qmp.command('qom-set',path='/machine',property='mcu-switch-candidate',value=True)
            gpio=io()
            check('re-asserting after the creation-time cycle borrows again',
                  pin_state(gpio,'PB11')==(0,True))
            stop_child(proc,qmp);qmp=None;check('creation boot reaped',proc.poll() is not None)

            machine='nikon-z8-lab,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on'
            proc,qmp=boot(machine,'bare');report['boots'].append(machine)
            for prop,value in (('mcu-switch-candidate',True),('mcu-switch-candidate-pin','PB11')):
                rejected=False
                try:qmp.command('qom-set',path='/machine',property=prop,value=value)
                except RuntimeError as error:rejected='native MCU' in str(error)
                check(f'{prop} without native MCU is rejected',rejected)
            rejected=False
            try:qmp.command('qom-set',path='/machine',property='mcu-switch-candidate-pin',value='G7')
            except RuntimeError:rejected=True
            check('whitelist still enforced without native MCU',rejected)
            stop_child(proc,qmp);qmp=None;check('bare boot reaped',proc.poll() is not None)
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'mcu-switch-candidate checks; synthetic programs only')


if __name__=='__main__':main()
