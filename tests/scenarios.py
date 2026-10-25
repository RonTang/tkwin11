"""M0 S1-S7 real Tk scenarios. Use after/mainloop; never update()."""
import argparse
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from tkinter import ttk
import tkwin11 as ui
from tkwin11.motion import Tween
from tkwin11.switches import frame
from scenario_support import (TweenProbe, add_cleanup, drive, milliseconds,
                              photo_matches, require, steps, visibility)

SCENARIOS = {}
SCENARIO_NAMES = tuple(f'S{index}' for index in range(1, 8))


def scenario(name):
    def register(function):
        SCENARIOS[name] = function
        return function
    return register


def make_root(title, geometry='520x360+80+80'):
    root = tk.Tk()
    root.title(title)
    root.geometry(geometry)
    return root


def close_on_error(root):
    try:
        root.destroy()
    except tk.TclError:
        pass


@scenario('S1')
def scenario_s1():
    began = milliseconds()
    root = make_root('M0 S1 cold switch')
    created = milliseconds()
    measurements = {}

    def start(done):
        stamp = milliseconds()
        ui.apply_theme(root)
        measurements['theme_ms'] = milliseconds()-stamp
        stamp = milliseconds()
        switch = ui.FluentSwitch(root)
        switch.pack(padx=30, pady=30)
        measurements['first_switch_create_ms'] = milliseconds()-stamp
        initial_cache = len(root._switch_frames)
        interaction = {}

        def enter():
            require(switch.control.winfo_ismapped(), 'S1 switch was not mapped')
            stamp = milliseconds()
            switch.control.event_generate('<Motion>', x=5, y=5, warp=True)
            switch.control.event_generate('<Enter>', x=5, y=5)
            interaction['first_enter_dispatch_ms'] = milliseconds()-stamp
            interaction['cache_growth_count'] = len(root._switch_frames)-initial_cache

        def finish():
            require(switch.controller.hover_amount == 1., 'S1 hover did not finish')
            require(switch.controller.hover, 'S1 hover terminal flag is false')
            done({
                'counters': {
                    'initial_frame_cache_count': initial_cache,
                    'final_frame_cache_count': len(root._switch_frames),
                    **{key: value for key, value in interaction.items() if key.endswith('_count')},
                },
                'timings': {
                    'root_create_ms': created-began,
                    **measurements,
                    'first_enter_dispatch_ms': interaction['first_enter_dispatch_ms'],
                    'scenario_ms': milliseconds()-began,
                },
                'cold_process': True,
                'process_id': os.getpid(),
                'base_dpi': round(root.winfo_fpixels('1i')),
            })

        steps(root, [(50, enter), (250, finish)])

    try:
        return drive(root, start)
    except Exception:
        close_on_error(root)
        raise


@scenario('S2')
def scenario_s2():
    root = make_root('M0 S2 switch interactions')
    draws = {'count': 0, 'draw_ms': []}

    def start(done):
        ui.apply_theme(root)
        switch = ui.FluentSwitch(root)
        switch.pack(padx=40, pady=40)
        controller = switch.controller
        original = controller.draw
        def draw(value):
            stamp = milliseconds()
            original(value)
            draws['count'] += 1
            draws['draw_ms'].append(milliseconds()-stamp)
        controller.draw = draw
        control = switch.control

        def event(sequence):
            if sequence == '<Enter>':
                control.event_generate('<Motion>', x=8, y=8, warp=True)
                control.event_generate(sequence, x=8, y=8)
            elif sequence == '<Leave>':
                root.event_generate('<Motion>', x=-30, y=-30, warp=True)
                control.event_generate(sequence, x=-30, y=-30)
            else:
                control.event_generate(sequence, x=8, y=8, state=0)

        def terminal(hover, pressed, position, selected):
            if hover is not None:
                require(abs(controller.hover_amount-hover) < 1e-9,
                        f'S2 hover {controller.hover_amount} != {hover}')
            require(abs(controller.press_amount-pressed) < 1e-9,
                    f'S2 press {controller.press_amount} != {pressed}')
            require(abs(controller.position-position) < 1e-9,
                    f'S2 position {controller.position} != {position}')
            require(bool(switch.variable.get()) == selected, 'S2 variable terminal state mismatch')

        definitions = [
            (50, lambda: require(control.winfo_ismapped(), 'S2 switch was not mapped')),
            (0, lambda: event('<Enter>')),
            (250, lambda: terminal(1., 0., 0., False)),
            (0, lambda: event('<Leave>')),
            (250, lambda: terminal(0., 0., 0., False)),
            (0, lambda: event('<ButtonPress-1>')),
            (250, lambda: require(controller.pressed and switch.variable.get(),
                                  'S2 press did not latch on')),
            (0, lambda: event('<ButtonRelease-1>')),
            (350, lambda: terminal(None, 0., 1., True)),
            (0, lambda: event('<ButtonPress-1>')),
            (250, lambda: require(controller.pressed and not switch.variable.get(),
                                  'S2 second press did not latch off')),
            (0, lambda: event('<ButtonRelease-1>')),
            (350, lambda: terminal(None, 0., 0., False)),
            (0, lambda: event('<Leave>')),
        ]
        def finish():
            terminal(0., 0., 0., False)
            require(draws['count'] > 8, 'S2 did not exercise animated drawing')
            done({
                'counters': {'switch_draw_count': draws['count'],
                             'frame_cache_count': len(root._switch_frames)},
                'timings': {'switch_draw_ms': draws['draw_ms'],
                            'feedback_duration_ms': [83], 'position_duration_ms': [167]},
                'terminal': {'position': controller.position, 'on': bool(switch.variable.get()),
                             'hover_amount': controller.hover_amount,
                             'press_amount': controller.press_amount},
            })
        steps(root, [*definitions, (250, finish)])

    try:
        return drive(root, start)
    except Exception:
        close_on_error(root)
        raise


@scenario('S3')
def scenario_s3():
    root = make_root('M0 S3 parallel switches', '640x420+80+80')

    def start(done):
        ui.apply_theme(root)
        switches = [ui.FluentSwitch(root) for _ in range(6)]
        for index, switch in enumerate(switches):
            switch.grid(row=index//2, column=index%2, padx=35, pady=20)
        probe = None

        def begin():
            nonlocal probe
            require(all(item.control.winfo_ismapped() for item in switches),
                    'S3 switches were not mapped')
            probe = TweenProbe(root, [tween for item in switches
                                      for tween in (item.controller.animator,
                                                    item.controller.feedback_animator)])
            for item in switches:
                item.control.event_generate('<ButtonPress-1>', x=8, y=8)

        def release():
            for item in switches:
                item.control.event_generate('<ButtonRelease-1>', x=8, y=8)

        def finish():
            for item in switches:
                require(item.position == 1. and item.variable.get(), 'S3 terminal on state mismatch')
                require(item.controller.press_amount == 0., 'S3 press did not finish')
            summary = probe.summary()
            require(summary['active_tween_count_peak'] >= len(switches),
                    f"S3 active Tween peak was only {summary['active_tween_count_peak']}")
            require(summary['tween_update_count'] > len(switches), 'S3 animations did not tick')
            done({
                'counters': {**summary, 'switch_count': len(switches)},
                'timings': {},
                'per_switch': [probe.stats(item.controller.animator) for item in switches],
            })

        steps(root, [(60, begin), (40, release), (500, finish)])

    try:
        return drive(root, start)
    except Exception:
        close_on_error(root)
        raise


@scenario('S4')
def scenario_s4():
    root = make_root('M0 S4 hidden decoration', '480x260+80+80')

    def start(done):
        ui.apply_theme(root)
        unmapped = ui.FluentSwitch(root)
        outside = ui.FluentSwitch(root)
        outside.place(x=-400, y=20)
        area = ui.ScrollArea(root)
        area.pack(fill='both', expand=True)
        ttk.Frame(area.body, height=420).pack()
        scrolled = ui.FluentSwitch(area.body)
        scrolled.pack(pady=10)
        ttk.Frame(area.body, height=420).pack()
        switches = {'unmapped': unmapped, 'mapped_outside_viewport': outside,
                    'scrolled_outside_viewport': scrolled}
        observed = {}
        probe = None

        def scroll():
            area._smooth.direct('moveto', 1.0)

        def begin():
            nonlocal probe
            for key, item in switches.items():
                observed[key] = {'visibility': visibility(item.control)}
            require(observed['unmapped']['visibility'] == 'unmapped', observed)
            require(observed['mapped_outside_viewport']['visibility'] == 'mapped_outside_viewport', observed)
            require(observed['scrolled_outside_viewport']['visibility'] == 'mapped_outside_viewport', observed)
            probe = TweenProbe(root, [item.controller.feedback_animator for item in switches.values()])
            for item in switches.values():
                item.feedback('hover', True)

        def finish():
            for key, item in switches.items():
                stats = probe.stats(item.controller.feedback_animator)
                observed[key].update(stats)
                observed[key]['post_start_update_count'] = max(0, stats['update_count']-1)
                observed[key]['terminal_visibility'] = visibility(item.control)
                require(item.controller.hover_amount == 1., f'S4 {key} hover terminal mismatch')
                require(stats['update_count'] >= 1, f'S4 {key} had no update')
            done({
                'counters': {'hidden_tween_start_count': len(switches),
                             'hidden_update_count': sum(item['update_count'] for item in observed.values()),
                             'hidden_post_start_update_count': sum(item['post_start_update_count']
                                                                  for item in observed.values())},
                'timings': {},
                'widgets': observed,
            })

        steps(root, [(100, scroll), (100, begin), (350, finish)])

    try:
        return drive(root, start)
    except Exception:
        close_on_error(root)
        raise


@scenario('S5')
def scenario_s5():
    root = make_root('M0 S5 DPI factories', '560x360+80+80')

    def start(done):
        ui.apply_theme(root)
        switch = ui.FluentSwitch(root)
        switch.pack(padx=40, pady=30)
        controller = switch.controller
        states = [
            ('off', 0, {}), ('on', 12, {}),
            ('hover', 6, {'hover_amount': 1}),
            ('press', 6, {'press_amount': 1}),
            ('focus', 6, {'focus': True}),
            ('disabled', 6, {'disabled': True}),
            *[('animation_'+str(index), index, {}) for index in (0, 3, 6, 9, 12)],
        ]
        factory_results = []
        images = []
        for name, index, options in states:
            source = frame(root, index, **options)
            images.append(source)
            require(str(source) in root._dpi_resources.image_factories,
                    f'S5 missing factory registration for {name}')
            for ratio in (1., 1.5, 2.):
                stamp = milliseconds()
                rendered = source._fluent_factory(ratio)
                elapsed = milliseconds()-stamp
                images.append(rendered)
                expected = (max(1, round(source.width()*ratio)),
                            max(1, round(source.height()*ratio)))
                require((rendered.width(), rendered.height()) == expected,
                        f'S5 {name} ratio {ratio}: {(rendered.width(), rendered.height())} != {expected}')
                factory_results.append({'state': name, 'ratio': ratio,
                                        'width': rendered.width(), 'height': rendered.height(),
                                        'factory_ms': elapsed})
        sink = tk.PhotoImage(master=root)
        images.append(sink)
        root.tk.call(str(sink), 'copy', str(images[0]))
        require(root._dpi_resources.image_factories.get(str(sink)) is images[0]._fluent_factory,
                'S5 factory did not propagate through PhotoImage copy')
        drawn_indices = []
        original = controller.draw
        def draw(value):
            drawn_indices.append(max(0, min(12, round(value*12))))
            original(value)
        controller.draw = draw

        def focus():
            root._switch_keyboard_focus = True
            root.focus_force()
            switch.control.focus_set()

        def check_focus():
            controller.renderer(controller.position)
            require('focus' in root.tk.splitlist(controller.native('state')),
                    'S5 keyboard focus state missing')
            expected = frame(root, round(controller.position*12), focus=True,
                             hover_amount=controller.hover_amount,
                             press_amount=controller.press_amount)
            require(photo_matches(controller.slot['image'], expected), 'S5 focus pixels mismatch')

        def press():
            switch.control.event_generate('<ButtonPress-1>', x=8, y=8)

        def release():
            switch.control.event_generate('<ButtonRelease-1>', x=8, y=8)

        def disable():
            switch.state(['disabled'])

        def finish():
            require(switch.control.instate(['disabled']), 'S5 disabled state missing')
            require(controller.hover_amount == controller.press_amount == 0.,
                    'S5 disabled feedback was not reset')
            expected = frame(root, round(controller.position*12), disabled=True)
            require(photo_matches(controller.slot['image'], expected), 'S5 disabled pixels mismatch')
            require(len(set(drawn_indices)) >= 3, f'S5 too few animation frames: {drawn_indices}')
            done({
                'counters': {'factory_render_count': len(factory_results),
                             'representative_state_count': len(states),
                             'animated_draw_count': len(drawn_indices)},
                'timings': {'factory_ms': [item['factory_ms'] for item in factory_results]},
                'base_dpi': round(root.winfo_fpixels('1i')),
                'factory_frames': factory_results,
                'drawn_indices': drawn_indices,
                'manual_cross_screen_required': True,
            })

        steps(root, [(60, focus), (60, check_focus), (20, press),
                     (100, release), (400, disable), (80, finish)])

    try:
        return drive(root, start, timeout_ms=30000)
    except Exception:
        close_on_error(root)
        raise


@scenario('S6')
def scenario_s6():
    root = make_root('M0 S6 main-thread blocking')

    def start(done):
        ui.apply_theme(root)
        switch = ui.FluentSwitch(root)
        switch.pack(padx=40, pady=40)
        controller = switch.controller
        probe = None
        cases = []

        def initial():
            nonlocal probe
            probe = TweenProbe(root, [controller.feedback_animator])

        definitions = [(50, initial)]
        for index, requested in enumerate((5, 25, 60)):
            case = {'requested_block_ms': requested}
            cases.append(case)
            def begin(case=case, index=index):
                case['update_offset'] = probe.records[controller.feedback_animator]['update_count']
                case['scheduled_for_ms'] = milliseconds()+20
                def block():
                    case['block_delay_ms'] = milliseconds()-case['scheduled_for_ms']
                    stamp = milliseconds()
                    time.sleep(case['requested_block_ms']/1000)
                    case['actual_sleep_ms'] = milliseconds()-stamp
                    case['sleep_end_ms'] = milliseconds()
                    def resumed():
                        case['after_zero_delay_ms'] = milliseconds()-case['sleep_end_ms']
                    root.after(0, resumed)
                root.after(20, block)
                switch.feedback('hover', bool(index % 2 == 0))
            def check(case=case, index=index):
                target = float(index % 2 == 0)
                require(controller.hover_amount == target,
                        f"S6 {case['requested_block_ms']} ms hover terminal mismatch")
                require('after_zero_delay_ms' in case, 'S6 blocker did not run')
                require(case['actual_sleep_ms'] >= case['requested_block_ms']*.75,
                        f"S6 sleep too short: {case}")
                timestamps = probe.records[controller.feedback_animator]['update_timestamps_ms']
                sample = timestamps[case['update_offset']:]
                case['update_count'] = len(sample)
                case['max_update_gap_ms'] = max((b-a for a, b in zip(sample, sample[1:])), default=0.)
                case.pop('update_offset')
                case.pop('scheduled_for_ms')
                case.pop('sleep_end_ms')
            definitions.extend([(0, begin), (400, check)])

        def finish():
            done({'counters': {'injected_block_count': len(cases)},
                  'timings': {}, 'cases': cases,
                  'blocking_method': 'root.after + time.sleep on Tk main thread'})

        steps(root, [*definitions, (0, finish)])

    try:
        return drive(root, start)
    except Exception:
        close_on_error(root)
        raise


@scenario('S7')
def scenario_s7():
    root = make_root('M0 S7 lifecycle')

    def start(done):
        results = {}

        def cancel_in_update():
            owner = ttk.Frame(root)
            tween = Tween(owner)
            calls = {'update': 0, 'done': 0}
            def update(_):
                calls['update'] += 1
                tween.cancel()
            tween.start(0., 1., update, duration=83, done=lambda: calls.__setitem__('done', calls['done']+1))
            require(calls == {'update': 1, 'done': 0} and tween.job is None,
                    f'S7 cancel in update mismatch: {calls}')
            results['cancel_in_update'] = calls

        def restart_in_update():
            owner = ttk.Frame(root)
            tween = Tween(owner)
            calls = {'old_done': 0, 'new_done': 0, 'restarted': 0, 'value': None}
            def old_update(_):
                if not calls['restarted']:
                    calls['restarted'] = 1
                    tween.start(0., 1., lambda value: calls.__setitem__('value', value),
                                duration=83, done=lambda: calls.__setitem__('new_done', calls['new_done']+1))
            tween.start(0., 1., old_update, duration=83,
                        done=lambda: calls.__setitem__('old_done', calls['old_done']+1))
            root._s7_restart = (tween, calls)

        def check_restart():
            tween, calls = root._s7_restart
            require(calls['old_done'] == 0 and calls['new_done'] == 1 and calls['value'] == 1.,
                    f'S7 restart mismatch: {calls}')
            results['restart_in_update'] = calls

        def restart_in_done():
            owner = ttk.Frame(root)
            tween = Tween(owner)
            calls = {'done': 0, 'value': None}
            def finished():
                calls['done'] += 1
                if calls['done'] == 1:
                    tween.start(0., 1., lambda value: calls.__setitem__('value', value),
                                duration=50, done=finished)
            tween.start(0., 1., lambda value: calls.__setitem__('value', value),
                        duration=50, done=finished)
            root._s7_done = (tween, calls)

        def check_done_restart():
            _, calls = root._s7_done
            require(calls == {'done': 2, 'value': 1.}, f'S7 done restart mismatch: {calls}')
            results['restart_in_done'] = calls

        def destroy_owner():
            owner = ttk.Frame(root)
            tween = Tween(owner)
            calls = {'update': 0, 'done': 0}
            def update(_):
                calls['update'] += 1
            tween.start(0., 1., update, duration=167,
                        done=lambda: calls.__setitem__('done', calls['done']+1))
            root.after(20, owner.destroy)
            root._s7_owner = (tween, calls)

        def check_owner():
            tween, calls = root._s7_owner
            require(not tween.alive() and tween.job is None and calls['done'] == 0,
                    f'S7 owner destroy mismatch: {calls}')
            results['owner_destroy'] = calls

        def double_root():
            second = make_root('M0 S7 second root', '240x160+650+100')
            second.report_callback_exception = root.report_callback_exception
            owners = [ttk.Frame(root), ttk.Frame(second)]
            tweens = [Tween(owner) for owner in owners]
            calls = [{'done': 0, 'value': None} for _ in tweens]
            for tween, call in zip(tweens, calls):
                tween.start(0., 1., lambda value, call=call: call.__setitem__('value', value),
                            duration=83, done=lambda call=call: call.__setitem__('done', call['done']+1))
            root._s7_double = (second, tweens, calls)

        def check_double():
            second, _, calls = root._s7_double
            require(all(call == {'done': 1, 'value': 1.} for call in calls),
                    f'S7 dual root mismatch: {calls}')
            results['double_root'] = calls
            second.destroy()

        def destroy_root():
            second = make_root('M0 S7 destroyed root', '240x160+650+100')
            second.report_callback_exception = root.report_callback_exception
            owner = ttk.Frame(second)
            tween = Tween(owner)
            calls = {'update': 0, 'done': 0, 'root_destroyed': False}
            def destroyed(event):
                if event.widget is second:
                    calls['root_destroyed'] = True
            second.bind('<Destroy>', destroyed, add='+')
            tween.start(0., 1., lambda _: calls.__setitem__('update', calls['update']+1),
                        duration=167, done=lambda: calls.__setitem__('done', calls['done']+1))
            second.after(20, second.destroy)
            root._s7_root = (tween, calls)

        def check_root():
            tween, calls = root._s7_root
            require(calls['root_destroyed'] and calls['done'] == 0 and not tween.alive(),
                    f'S7 root destroy mismatch: {calls}')
            results['root_destroy'] = calls
            done({'counters': {'lifecycle_case_count': len(results)}, 'timings': {}, 'cases': results})

        steps(root, [(0, cancel_in_update), (0, restart_in_update), (250, check_restart),
                     (0, restart_in_done), (250, check_done_restart),
                     (0, destroy_owner), (220, check_owner), (0, double_root),
                     (250, check_double), (0, destroy_root), (220, check_root)])

    try:
        return drive(root, start)
    except Exception:
        close_on_error(root)
        raise


def commit():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1],
                                   text=True).strip()


def windows_environment():
    result = {'dpi': 'unknown', 'dpi_scale': 'unknown', 'display_count': 'unknown',
              'power_source': 'unknown', 'battery_percent': 'unknown',
              'power_mode': 'unknown', 'active_power_scheme': 'unknown',
              'system_animation_enabled': 'unknown'}
    if sys.platform != 'win32':
        return result
    import ctypes
    from ctypes import wintypes
    try:
        user32 = ctypes.windll.user32
        result['display_count'] = user32.GetSystemMetrics(80)
        try:
            dpi = user32.GetDpiForSystem()
        except AttributeError:
            dc = user32.GetDC(0)
            try:
                dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
            finally:
                user32.ReleaseDC(0, dc)
        result['dpi'] = int(dpi)
        result['dpi_scale'] = dpi/96
        animations = ctypes.c_int(0)
        if user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(animations), 0):
            result['system_animation_enabled'] = bool(animations.value)
        class PowerStatus(ctypes.Structure):
            _fields_ = [('ac', wintypes.BYTE), ('battery_flag', wintypes.BYTE),
                        ('battery_percent', wintypes.BYTE), ('reserved', wintypes.BYTE),
                        ('battery_seconds', wintypes.DWORD), ('battery_full_seconds', wintypes.DWORD)]
        status = PowerStatus()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            result['power_source'] = {0: 'battery', 1: 'ac'}.get(status.ac, 'unknown')
            if status.battery_percent != 255:
                result['battery_percent'] = status.battery_percent
        completed = subprocess.run(['powercfg', '/getactivescheme'], capture_output=True, timeout=3)
        if completed.returncode == 0:
            ascii_output = completed.stdout.decode('ascii', 'ignore')
            result['active_power_scheme'] = next((token for token in ascii_output.split()
                if len(token) == 36 and token.count('-') == 4), 'unknown')
    except (AttributeError, OSError, subprocess.SubprocessError):
        pass
    return result


def environment():
    release, version, service_pack, _ = platform.win32_ver()
    return {
        'platform': platform.platform(), 'os_version': release, 'os_build': version,
        'service_pack': service_pack, 'machine': platform.machine(), 'python': sys.version,
        'python_bits': struct.calcsize('P')*8, 'tk': str(tk.TkVersion),
        **windows_environment(),
    }


def round_result(name, index, result=None, error=None, began=None):
    result = result or {}
    return {
        'scenario': name, 'round': index, 'pass': error is None,
        'duration_ms': milliseconds()-began if began is not None else None,
        'counters': result.get('counters', {}), 'timings': result.get('timings', {}),
        'details': {key: value for key, value in result.items() if key not in ('counters', 'timings')},
        'error': error,
    }


def run_s1_process(index):
    began = milliseconds()
    command = [sys.executable, str(Path(__file__).resolve()), '--scenario', 'S1',
               '--repeat', '1', '--output', '-', '--_s1-worker']
    try:
        completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                   text=True, capture_output=True, timeout=90)
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            error = f'S1 worker exit {completed.returncode}; invalid JSON\n{completed.stdout}\n{completed.stderr}'
            return round_result('S1', index, error=error, began=began)
        result['round'] = index
        result['duration_ms'] = milliseconds()-began
        result['details']['worker_returncode'] = completed.returncode
        if completed.stderr:
            result['details']['worker_stderr'] = completed.stderr
        if completed.returncode and result['pass']:
            result['pass'] = False
            result['error'] = f'S1 worker exit {completed.returncode}'
        return result
    except Exception:
        return round_result('S1', index, error=traceback.format_exc(), began=began)


def run_round(name, index):
    began = milliseconds()
    try:
        return round_result(name, index, result=SCENARIOS[name](), began=began)
    except Exception:
        return round_result(name, index, error=traceback.format_exc(), began=began)


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description='M0 real Tk scenarios S1-S7')
    parser.add_argument('--scenario', choices=('all', *SCENARIO_NAMES), default='all')
    parser.add_argument('--repeat', type=positive, default=1)
    parser.add_argument('--output', help="raw JSON path, or '-' for stdout")
    parser.add_argument('--_s1-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    ui.enable_dpi_awareness()
    if args._s1_worker:
        if args.scenario != 'S1' or args.repeat != 1 or args.output != '-':
            parser.error('internal S1 worker requires --scenario S1 --repeat 1 --output -')
        result = run_round('S1', 1)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['pass'] else 1

    rounds = []
    names = SCENARIO_NAMES if args.scenario == 'all' else (args.scenario,)
    for index in range(1, args.repeat+1):
        for name in names:
            result = run_s1_process(index) if name == 'S1' else run_round(name, index)
            rounds.append(result)
            print(f"{'PASS' if result['pass'] else 'FAIL'} {name} round {index}", flush=True)
            if not result['pass']:
                print(result['error'].rstrip().splitlines()[-1], file=sys.stderr, flush=True)
    failed = sum(not result['pass'] for result in rounds)
    document = {
        'schema_version': 1,
        'run': {
            'commit': commit(), 'milestone': 'M0', 'scenario': args.scenario,
            'repeat': args.repeat, 'timestamp_ns': time.time_ns(),
            'environment': environment(), 'profile_enabled': False,
            'measurement_scope': 'M0 observable scenario counters/timings; not M1 production profile',
        },
        'rounds': rounds,
        'summary': {'round_count': len(rounds), 'passed_count': len(rounds)-failed,
                    'failed_count': failed},
    }
    output = args.output
    if output is None:
        stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
        output = Path(__file__).resolve().parents[1]/'perf'/'results'/'m0'/f'scenarios_{args.scenario}_{stamp}.json'
    try:
        text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
        if str(output) == '-':
            print(text, end='')
        else:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
            print(f'Raw JSON: {path.resolve()}')
    except Exception:
        traceback.print_exc()
        return 3
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
