"""G1-G6 real gallery performance scenarios; never call update/update_idletasks."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
import traceback
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkwin11 as ui
from tkwin11 import profiling
import gallery
from gallery_support import (OperationLog, close_on_error, idle, instances,
                             one_instance, perform, pointer, popup_closed,
                             popup_visible, run_serial, tween_jobs_finished,
                             wait_tweens, wait_until, walk, watch_reveal)
from scenario_support import TweenProbe, drive, milliseconds, require
from scenarios import commit, environment, round_result

SCENARIOS = {}
SCENARIO_NAMES = tuple(f'G{index}' for index in range(1, 7))


def run_round(name, index):
    began = milliseconds()
    try:
        return round_result(name, index, result=SCENARIOS[name](), began=began)
    except Exception:
        return round_result(name, index, error=traceback.format_exc(), began=began)


def scenario(name):
    def register(function):
        SCENARIOS[name] = function
        return function
    return register


def result(log, counters=None, timings=None, **details):
    return {
        'counters': {'operation_count': len(log.items), **(counters or {})},
        'timings': timings or {},
        'operations': log.records(),
        **details,
    }


def open_page(app, key, callback):
    app.open(key)
    page = app.pages[key]
    wait_tweens(app, (page._page_tween,), lambda: (
        require(app.active == key, f'gallery active page is not {key}'), callback()), 6000)


@scenario('G1')
def scenario_g1():
    app = gallery.Demo()
    log = OperationLog(app)
    keys = [item[0] for item in gallery.NAVIGATION+gallery.BOTTOM if item[0]]
    initial = app.pages.pop('home')
    initial.destroy()
    app.active = None
    app.deck._fluent_presented_page = None

    def start(done):
        sequence = [(key, 'cold') for key in keys]+[(key, 'hot') for key in reversed(keys)]
        visits = iter(sequence)

        def advance():
            try:
                key, kind = next(visits)
            except StopIteration:
                require(len(app.pages) == len(keys), 'G1 did not retain every gallery page')
                done(result(log, {'page_count': len(keys), 'visit_count': 2*len(keys)},
                            page_order=keys))
                return
            require((key in app.pages) == (kind == 'hot'), f'G1 wrong {kind} cache state for {key}')
            operation = log.start('page_open', kind, {'page': key})
            original = getattr(app, 'page_'+key) if kind == 'cold' else None
            if original is not None:
                def build(body, _original=original):
                    with profiling.span(app, 'page_build', kind):
                        _original(body)
                setattr(app, 'page_'+key, build)
            try:
                with profiling.span(app, 'page_prepare_present', kind):
                    app.open(key)
                operation.mark()
            except Exception as exc:
                operation.finish(str(exc))
                raise
            finally:
                if original is not None:
                    setattr(app, 'page_'+key, original)
            page = app.pages[key]
            status = app.status.get()
            match = re.search(r'首次构建 ([0-9.]+) ms', status)
            if match:
                operation.record['details']['reported_build_ms'] = float(match.group(1))

            def finish():
                try:
                    require(app.active == key, f'G1 active {app.active} != {key}')
                    require(page.winfo_manager() == 'place' and page.winfo_ismapped(),
                            f'G1 {key} was not presented')
                    require(page.winfo_y() == 0, f'G1 {key} page tween terminal y={page.winfo_y()}')
                    operation.finish()
                except Exception as exc:
                    operation.finish(str(exc))
                    raise
                app.after(0, advance)
            wait_tweens(app, (page._page_tween,), finish, 8000)
        app.after(0, advance)

    try:
        return drive(app, start, timeout_ms=180000)
    except Exception:
        close_on_error(app)
        raise


@scenario('G2')
def scenario_g2():
    app = gallery.Demo(page='settings_card')
    log = OperationLog(app)

    def start(done):
        page = app.pages['settings_card']
        expanders = instances(page.body, ui.ExpanderCard)
        accordions = instances(page.body, ui.Accordion)
        examples = [item for item in walk(page.body) if isinstance(item, gallery.Example) and item.code]
        require(len(expanders) >= 2 and accordions and examples,
                'G2 settings_card controls are incomplete')

        def nav_toggle(key, target):
            node = app.nav.groups[key]
            def task(next_):
                def terminal(details):
                    require(node.opened is target, f'G2 group {key} opened={node.opened}')
                    details['opened'] = node.opened
                    details['height_px'] = node.height
                    if target:
                        require(node.viewport.winfo_manager() and node.height >= node.body.winfo_reqheight()-1,
                                f'G2 group {key} open height did not settle')
                    else:
                        require(not node.viewport.winfo_manager() and node.height == 0,
                                f'G2 group {key} did not collapse')
                perform(log, 'navigation_toggle', 'expand' if target else 'collapse',
                        {'group': key}, node.button.invoke, terminal, next_,
                        (node.motion,))
            return task

        def nav_select(key):
            button = app.nav.items[key][0]
            def task(next_):
                def terminal(details):
                    require(app.active == key and app.nav.selected_key == key,
                            f'G2 cross-group selection failed for {key}')
                    details['active'] = app.active
                perform(log, 'navigation_select', 'cross_group', {'page': key},
                        button.invoke, terminal, next_,
                        (app.nav.indicator_motion,), 6000)
            return task

        def expansion(widget, target, index):
            button = widget.toggle_button if isinstance(widget, ui.ExpanderCard) else widget.header
            def task(next_):
                def terminal(details):
                    require(widget.opened is target, 'G2 expansion terminal flag mismatch')
                    require((widget.viewport.winfo_manager() != '') is target,
                            'G2 expansion viewport manager mismatch')
                    details.update(opened=widget.opened, height_px=widget.expansion.height,
                                   target_height_px=widget.expansion.target)
                    if target:
                        require(widget.expansion.height >= widget.expansion.measure()-1,
                                'G2 expansion height did not reach content')
                    else:
                        require(widget.expansion.height == 0, 'G2 collapse height is not zero')
                perform(log, 'expansion_toggle', 'expand' if target else 'collapse',
                        {'control': type(widget).__name__, 'index': index, 'opened_before': not target},
                        button.invoke, terminal, next_, (widget.expansion.animator,))
            return task

        def source(example, target, index):
            def task(next_):
                def terminal(details):
                    require(example.code_view is not None, 'G2 source view was not built')
                    require(bool(example.code_view.container.winfo_manager()) is target,
                            'G2 source final visibility mismatch')
                    details['visible'] = target
                    details['height_px'] = example.code_view.container.winfo_height()
                perform(log, 'source_toggle', 'expand' if target else 'collapse',
                        {'example': index, 'title': example.master_title()}, example.code_button.invoke,
                        terminal, next_)
            return task

        tasks = [nav_toggle('basic', False), nav_select('listview'),
                 nav_toggle('collections', False), nav_toggle('collections', True),
                 nav_select('settings_card'), nav_toggle('layout', False), nav_toggle('layout', True)]
        for index, widget in enumerate(expanders[:2]):
            tasks.extend((expansion(widget, not widget.opened, index),
                          expansion(widget, widget.opened, index)))
        tasks.extend((expansion(accordions[0], False, 0), expansion(accordions[0], True, 0),
                      source(examples[0], True, 0), source(examples[0], False, 0),
                      source(examples[0], True, 0)))
        run_serial(app, tasks, lambda: done(result(log, {
            'navigation_group_count': len(app.nav.groups),
            'expander_count': len(expanders), 'accordion_count': len(accordions),
            'source_example_count': len(examples),
        })))

    try:
        return drive(app, start, timeout_ms=45000)
    except Exception:
        close_on_error(app)
        raise


def choice_cycle(app, log, kind, page, opener, accessor, closer=None,
                 select_index=None, extra_check=None):
    def task(next_):
        def begin():
            operation = log.start('popup_cycle', kind, {'page': page})
            previous_focus = app.focus_get()
            opener()
            popup = accessor()
            require(popup is not None, f'G3 {kind} did not create a popup')
            operation.mark()
            operation.record['details']['popup_class'] = type(popup).__name__

            def revealed():
                try:
                    require(popup_visible(popup), f'G3 {kind} did not reveal and settle')
                    require(popup.grab_current() is popup, f'G3 {kind} does not own grab')
                    focus = popup.focus_get()
                    require(focus is not None and focus.winfo_toplevel() is popup,
                            f'G3 {kind} does not own focus')
                    if extra_check:
                        extra_check(popup)
                    operation.record['details']['reveal_verified'] = True
                    if select_index is not None:
                        popup.choose(select_index)
                    elif closer is not None:
                        closer(popup)
                    else:
                        popup.close()
                except Exception as exc:
                    operation.finish(str(exc))
                    raise

                def closed():
                    try:
                        require(popup_closed(popup), f'G3 {kind} did not close')
                        require(app.grab_current() is None, f'G3 {kind} leaked grab')
                        focus = app.focus_get()
                        require(focus is not None, f'G3 {kind} did not restore focus')
                        operation.record['details'].update(closed=True, grab_released=True,
                                                          focus_restored=focus is previous_focus or focus.winfo_exists())
                        operation.finish()
                    except Exception as exc:
                        operation.finish(str(exc))
                        raise
                    next_()
                wait_until(app, lambda: popup_closed(popup), closed)
            wait_until(app, lambda: popup_visible(popup) and popup.grab_current() is popup,
                       revealed, 5000)
        open_page(app, page, begin)
    return task


@scenario('G3')
def scenario_g3():
    app = gallery.Demo(page='combo')
    log = OperationLog(app)
    skipped = [
        {'feature': 'ThemedMenu/MenuPopup/MenuButton', 'reason': 'excluded by gallery audit scope; menu issue #3 is not retested'},
        {'feature': 'Dialogs.info/confirm/ask_string/ask_integer', 'reason': 'blocking nested wait_window dialogs; nonblocking Modal is automated instead'},
    ]

    def start(done):
        combo_page = app.pages['combo']
        combos = instances(combo_page.body, ui.ThemedCombobox)
        dropdowns = instances(combo_page.body, ui.Dropdown)
        options = instances(combo_page.body, ui.OptionMenu)
        require(combos and dropdowns and options, 'G3 combo page controls are incomplete')
        combo, dropdown, option = combos[0], dropdowns[0], options[0]

        def form_flyout(next_):
            def begin():
                operation = log.start('popup_cycle', 'form_flyout_combobox', {'page': 'flyout'})
                anchor = next(item for item in walk(app.pages['flyout'].body)
                              if isinstance(item, ttk.Button) and item.cget('text') == '新建配置')
                app.open_flyout(anchor)
                flyout = app._form_flyout
                operation.mark()

                def shown():
                    require(popup_visible(flyout), 'G3 FormFlyout did not settle')
                    require(flyout.grab_current() is flyout, 'G3 FormFlyout does not own grab')
                    require(flyout.contains_window(flyout.focus_get()), 'G3 FormFlyout focus escaped')
                    source = one_instance(flyout.body, ui.ThemedCombobox, 'FormFlyout Combobox')
                    source.controller.open()
                    popup = source.controller.popup
                    operation.record['details']['nested_popup_class'] = type(popup).__name__

                    def nested_shown():
                        require(popup_visible(popup) and popup.grab_current() is popup,
                                'G3 nested ChoicePopup focus/grab mismatch')
                        operation.record['details']['nested_reveal_verified'] = True
                        popup.close()

                        def nested_closed():
                            require(popup_closed(popup), 'G3 nested ChoicePopup did not close')
                            require(flyout.grab_current() is flyout,
                                    'G3 nested ChoicePopup did not restore FormFlyout grab')
                            flyout.close()

                            def flyout_closed():
                                try:
                                    require(popup_closed(flyout), 'G3 FormFlyout did not close')
                                    require(app.grab_current() is None, 'G3 FormFlyout leaked grab')
                                    operation.record['details']['closed'] = True
                                    operation.finish()
                                except Exception as exc:
                                    operation.finish(str(exc))
                                    raise
                                next_()
                            wait_until(app, lambda: popup_closed(flyout), flyout_closed)
                        wait_until(app, lambda: popup_closed(popup), nested_closed)
                    wait_until(app, lambda: popup_visible(popup), nested_shown)
                wait_until(app, lambda: (popup_visible(flyout)
                                         and flyout.grab_current() is flyout
                                         and flyout.contains_window(flyout.focus_get())), shown)
            open_page(app, 'flyout', begin)

        def modal(next_):
            def begin():
                operation = log.start('popup_cycle', 'modal', {'page': 'dialog'})
                app.open_modal()
                dialog = app.dialog
                operation.mark()

                def shown():
                    require(popup_visible(dialog) and dialog._shown, 'G3 Modal did not reveal')
                    require(dialog.grab_current() is dialog, 'G3 Modal does not own grab')
                    require(dialog.focus_get() is not None, 'G3 Modal has no focus')
                    dialog.primary.invoke()

                    def closed():
                        require(popup_closed(dialog) and not dialog.mask.winfo_exists(),
                                'G3 Modal did not close')
                        require(app.grab_current() is None, 'G3 Modal leaked grab')
                        operation.record['details']['closed'] = True
                        operation.finish()
                        next_()
                    wait_until(app, lambda: popup_closed(dialog), closed)
                wait_until(app, lambda: popup_visible(dialog) and dialog._shown, shown)
            open_page(app, 'dialog', begin)

        def toast(next_):
            def begin():
                operation = log.start('popup_cycle', 'toast', {'page': 'toast'})
                focus = app.focus_get()
                notification = ui.notify(app, 'G3 gallery audit toast', duration=0)
                operation.mark()

                def shown():
                    require(popup_visible(notification), 'G3 Toast did not reveal')
                    require(notification.grab_current() is None, 'G3 Toast took a grab')
                    require(app.focus_get() is focus, 'G3 Toast changed focus')
                    notification.dismiss()
                    wait_until(app, lambda: popup_closed(notification), lambda: (
                        operation.record['details'].update(closed=True, focus_unchanged=True),
                        operation.finish(), next_()))
                wait_until(app, lambda: popup_visible(notification), shown)
            open_page(app, 'toast', begin)

        def tooltip(next_):
            def begin():
                operation = log.start('popup_cycle', 'tooltip', {'page': 'tooltip'})
                button = next(item for item in walk(app.pages['tooltip'].body)
                              if isinstance(item, ttk.Button) and item.cget('text') == '保存')
                focus = app.focus_get()
                pointer(button, '<Enter>', 5, 5)

                def scheduled():
                    tip = getattr(app, '_tkwin11_active_tooltip', None)
                    require(tip is not None and tip.window is not None, 'G3 Tooltip did not open')
                    window = tip.window

                    def shown():
                        require(window.winfo_ismapped() and window._fade.job is None,
                                'G3 Tooltip did not settle')
                        require(app.focus_get() is focus and app.grab_current() is None,
                                'G3 Tooltip stole focus or grab')
                        operation.mark()
                        pointer(button, '<Leave>', -20, -20)
                        wait_until(app, lambda: tip.window is None, lambda: (
                            operation.record['details'].update(closed=True, focus_unchanged=True),
                            operation.finish(), next_()))
                    wait_until(app, lambda: window._fade.job is None, shown)
                app.after(500, scheduled)
            open_page(app, 'tooltip', begin)

        tasks = [
            choice_cycle(app, log, 'combobox', 'combo', combo.controller.open,
                         lambda: combo.controller.popup),
            choice_cycle(app, log, 'dropdown', 'combo', dropdown.open,
                         lambda: dropdown.popup),
            choice_cycle(app, log, 'option_menu', 'combo', option.controller.open,
                         lambda: option.controller.popup, select_index=1),
            choice_cycle(app, log, 'search_suggestions', 'home',
                         lambda: (app.query.set('button'), app.search_list()),
                         lambda: app._choice_popup),
            choice_cycle(app, log, 'calendar_popup', 'date',
                         lambda: one_instance(app.pages['date'].body, ui.DateEntry, 'DateEntry').open_calendar(),
                         lambda: one_instance(app.pages['date'].body, ui.DateEntry, 'DateEntry').popup),
            form_flyout, modal, toast, tooltip,
        ]
        run_serial(app, tasks, lambda: done(result(log, {
            'automated_popup_kind_count': len(log.items), 'skipped_count': len(skipped),
        }, skipped=skipped)))

    try:
        return drive(app, start, timeout_ms=60000)
    except Exception:
        close_on_error(app)
        raise


def wheel_audit(app, log, area, kind, next_):
    canvas = area.canvas
    operation = log.start('scroll', kind, {'initial_yview': list(canvas.yview()), 'wheel_events': 0})
    initial = canvas.yview()[0]
    peak = [initial]
    deltas = [-120]*8+[120]*5

    def emit(index=0):
        if index < len(deltas):
            canvas.event_generate('<MouseWheel>', delta=deltas[index], x=20, y=20)
            operation.record['details']['wheel_events'] += 1
            operation.mark()
            peak[0] = max(peak[0], canvas.yview()[0])
            app.after(24, lambda: emit(index+1))
        else:
            def finished():
                final = canvas.yview()[0]
                details = operation.record['details']
                details.update(final_yview=final, max_yview=peak[0],
                               retargeted_while_active=True)
                require(peak[0] > initial+1e-5, f'G4 {kind} wheel did not change yview')
                require(final < peak[0], f'G4 {kind} reverse wheel did not reverse')
                require(area._smooth.tween.job is None, f'G4 {kind} wheel tween did not settle')
                operation.finish()
                next_()
            wait_tweens(app, (area._smooth.tween,), finished)
    emit()


def direct_audit(app, log, area, kind, next_):
    target = .63
    operation = log.start('scroll', kind, {'target_fraction': target})
    area._smooth.direct('moveto', target)
    operation.mark()

    def finished():
        final = area.canvas.yview()[0]
        operation.record['details']['final_yview'] = final
        require(abs(final-target) < .02, f'G4 {kind} direct final yview={final}')
        require(area._smooth.tween.job is None, f'G4 {kind} direct left a tween active')
        operation.finish()
        next_()
    idle(app, finished)


@scenario('G4')
def scenario_g4():
    app = gallery.Demo(page='all')
    log = OperationLog(app)

    def start(done):
        content = app.pages['all']
        for key, node in app.nav.groups.items():
            app.nav.set_expanded(key, True, animate=False)
        app.query.set('')
        app.search_list()
        popup = app._choice_popup
        require(popup is not None and len(popup.rows) > 20, 'G4 long ChoicePopup was not created')

        def checks(next_):
            require(content.canvas.yview()[1] < 1, 'G4 gallery page is not heavy enough to scroll')
            require(app.nav.area.canvas.yview()[1] < 1, 'G4 sidebar is not scrollable')
            require(popup.area.canvas.yview()[1] < 1, 'G4 ChoicePopup is not scrollable')
            next_()

        def close_popup(_):
            popup.close()
            done(result(log, {
                'wheel_event_count': sum(item.record['details'].get('wheel_events', 0) for item in log.items),
                'choice_popup_row_count': len(popup.rows),
            }, covered=['gallery_page', 'sidebar', 'long_choice_popup']))

        tasks = [
            lambda next_: checks(next_),
            lambda next_: wheel_audit(app, log, content, 'gallery_wheel_reverse', next_),
            lambda next_: direct_audit(app, log, content, 'gallery_scrollbar_direct', next_),
            lambda next_: wheel_audit(app, log, app.nav.area, 'sidebar_wheel_reverse', next_),
            lambda next_: direct_audit(app, log, app.nav.area, 'sidebar_scrollbar_direct', next_),
            lambda next_: wheel_audit(app, log, popup.area, 'choice_popup_wheel_reverse', next_),
            lambda next_: direct_audit(app, log, popup.area, 'choice_popup_scrollbar_direct', next_),
            close_popup,
        ]
        wait_until(app, lambda: (content.canvas.yview()[1] < 1
                                 and app.nav.area.canvas.yview()[1] < 1
                                 and popup.area.canvas.yview()[1] < 1),
                   lambda: run_serial(app, tasks, lambda: None), 6000)

    try:
        return drive(app, start, timeout_ms=30000)
    except Exception:
        close_on_error(app)
        raise


@scenario('G5')
def scenario_g5():
    app = gallery.Demo(page='slider')
    log = OperationLog(app)

    def start(done):
        page = app.pages['slider']
        fluent = one_instance(page.body, ui.FluentSlider, 'FluentSlider')
        scales = [item for item in instances(page.body, ttk.Scale)
                  if str(item.cget('orient')) == 'horizontal' and not item.instate(['disabled'])]
        require(scales, 'G5 native horizontal ttk.Scale is missing')
        native = scales[0]
        require(getattr(native, '_tkwin11_scale', None) is not None,
                'G5 native Scale controller was not attached')
        active = [None]
        counts = {'fluent': 0, 'native': 0}
        fluent_draw = fluent.draw
        native_draw = native._tkwin11_scale.draw

        def draw_fluent(value):
            counts['fluent'] += 1
            if active[0] is not None:
                active[0].mark()
            fluent_draw(value)

        def draw_native():
            counts['native'] += 1
            if active[0] is not None:
                active[0].mark()
            native_draw()
        fluent.draw = draw_fluent
        native._tkwin11_scale.draw = draw_native

        def drag(widget, native_scale, target, next_):
            key = 'native' if native_scale else 'fluent'
            before = counts[key]
            operation = log.start('slider_input', 'press_drag_release',
                                  {'control': 'ttk.Scale' if native_scale else 'FluentSlider',
                                   'input': 'pointer', 'target': target})
            active[0] = operation
            margin = 12 if native_scale else fluent.track_margin()
            x = margin+(widget.winfo_width()-2*margin)*target/100
            y = widget.winfo_height()/2
            pointer(widget, '<ButtonPress-1>', margin, y)
            pointer(widget, '<B1-Motion>', x, y)
            pointer(widget, '<ButtonRelease-1>', x, y)
            operation.mark()
            tweens = ((native._tkwin11_scale.position_animator, native._tkwin11_scale.animator)
                      if native_scale else (fluent.animator, fluent.thumb_animator))

            def finished():
                try:
                    value = float(widget.get())
                    operation.record['details']['final_value'] = value
                    operation.record['details']['draw_count'] = counts[key]-before
                    require(abs(value-target) <= 2, f'G5 {key} drag value={value}, target={target}')
                    require(counts[key] > before, f'G5 {key} drag did not draw')
                    require(app.grab_current() is not widget, f'G5 {key} drag leaked grab')
                    if not native_scale:
                        require(abs(fluent._visual-value) < 1e-7, 'G5 FluentSlider visual did not settle')
                    operation.finish()
                except Exception as exc:
                    operation.finish(str(exc))
                    raise
                active[0] = None
                next_()
            wait_tweens(app, tweens, finished)

        def keyboard(widget, native_scale, next_):
            key = 'native' if native_scale else 'fluent'
            initial = float(widget.get())
            widget.focus_set()
            before = counts[key]
            operation = log.start('slider_input', 'keyboard_continuous',
                                  {'control': 'ttk.Scale' if native_scale else 'FluentSlider',
                                   'input': '8x Right', 'initial_value': initial})
            active[0] = operation

            def emit(index=0):
                if index < 8:
                    widget.event_generate('<Right>')
                    operation.mark()
                    app.after(24, lambda: emit(index+1))
                    return
                tweens = ((native._tkwin11_scale.position_animator, native._tkwin11_scale.animator)
                          if native_scale else (fluent.animator, fluent.thumb_animator))

                def finished():
                    try:
                        expected = initial+8
                        value = float(widget.get())
                        operation.record['details'].update(final_value=value,
                                                          draw_count=counts[key]-before)
                        require(abs(value-expected) < 1e-7,
                                f'G5 {key} keyboard value={value}, expected={expected}')
                        require(counts[key] > before, f'G5 {key} keyboard did not draw')
                        if native_scale:
                            require(abs(native._tkwin11_scale.visual-value) < 1e-7,
                                    'G5 native Scale visual did not settle')
                        else:
                            require(abs(fluent._visual-value) < 1e-7,
                                    'G5 FluentSlider keyboard visual did not settle')
                        operation.finish()
                    except Exception as exc:
                        operation.finish(str(exc))
                        raise
                    active[0] = None
                    next_()
                wait_tweens(app, tweens, finished)
            emit()

        tasks = [lambda next_: drag(fluent, False, 80, next_),
                 lambda next_: keyboard(fluent, False, next_),
                 lambda next_: drag(native, True, 25, next_),
                 lambda next_: keyboard(native, True, next_)]
        run_serial(app, tasks, lambda: done(result(log, {
            'fluent_draw_count': counts['fluent'], 'native_draw_count': counts['native'],
        })))

    try:
        return drive(app, start, timeout_ms=30000)
    except Exception:
        close_on_error(app)
        raise


@scenario('G6')
def scenario_g6():
    app = gallery.Demo(page='home')
    log = OperationLog(app)

    def start(done):
        host = app.pages['home'].body
        surface = ttk.Frame(host, style='Workspace.TFrame', padding=12)
        surface.pack(fill='x', pady=12, before=host.winfo_children()[0])
        clicks = []
        button = ui.FluentButton(surface, text='G6 action', style='Primary.TButton',
                                 command=lambda: clicks.append('button'))
        card = ui.Card(surface, padding=12, command=lambda: clicks.append('card'))
        ttk.Label(card, text='G6 clickable card').pack()
        nav = ui.NavigationView(surface, lambda key: clicks.append('nav:'+key), width=170)
        nav.add_group('group', 'Group', 'folder')
        nav.add('one', 'One', 'controls', parent='group')
        nav.add('two', 'Two', 'controls', parent='group')
        variable = tk.BooleanVar(app, value=False)
        switch = ui.FluentSwitch(surface, variable=variable,
                                 command=lambda: clicks.append('switch'))
        slider = ui.FluentSlider(surface, from_=0, to=100, width=220)
        button.grid(row=0, column=0, padx=8, pady=8)
        card.grid(row=0, column=1, padx=8, pady=8)
        nav.grid(row=1, column=0, rowspan=2, padx=8, pady=8, sticky='ns')
        switch.grid(row=1, column=1, padx=8, pady=8)
        slider.grid(row=2, column=1, padx=8, pady=8)
        nav.select('one', notify=False)
        controllers = [button.controller.animator, card.interaction.tween,
                       nav.indicator_motion, switch.controller.animator,
                       switch.controller.feedback_animator, slider.animator, slider.thumb_animator]
        probe = TweenProbe(app, controllers)

        def mixed(next_):
            operation = log.start('mixed_interaction', 'concurrent_hover_press',
                                  {'controls': ['button', 'card', 'navigation', 'switch', 'slider']})
            for widget in (button, card, switch.control, slider, nav.items['two'][0]):
                pointer(widget, '<Motion>', 8, 8)
                pointer(widget, '<Enter>', 8, 8)
            for widget in (button, card, switch.control):
                pointer(widget, '<ButtonPress-1>', 8, 8)
                pointer(widget, '<ButtonRelease-1>', 8, 8)
            pointer(slider, '<ButtonPress-1>', slider.winfo_width()*.7, slider.winfo_height()/2)
            pointer(slider, '<ButtonRelease-1>', slider.winfo_width()*.7, slider.winfo_height()/2)
            nav.items['two'][0].invoke()
            operation.mark()

            def release():
                def finished():
                    require(clicks.count('button') == 1 and clicks.count('card') == 1,
                            f'G6 button/card commands mismatch: {clicks}')
                    require(clicks.count('switch') == 1 and variable.get(), 'G6 switch did not toggle')
                    require(nav.selected_key == 'two' and 'nav:two' in clicks,
                            'G6 navigation did not select')
                    require(65 <= slider.get() <= 75, f'G6 slider value={slider.get()}')
                    require(tween_jobs_finished(button, card, nav, switch, slider),
                            'G6 mixed animations did not finish')
                    operation.record['details'].update(commands=list(clicks), slider_value=slider.get(),
                                                       **probe.summary())
                    require(operation.record['details']['tween_done_count'] > 0,
                            'G6 no real Tween done callback observed')
                    operation.finish()
                    next_()
                wait_tweens(app, controllers, finished, 6000)
            app.after(45, release)

        def cancel(next_):
            before = probe.summary()['tween_done_count']
            operation = log.start('mixed_interaction', 'interrupt_reverse_cancel', {})
            pointer(card, '<Leave>', -20, -20)
            pointer(switch.control, '<ButtonPress-1>', 8, 8)
            pointer(switch.control, '<ButtonRelease-1>', 8, 8)
            nav.select('one')
            app.after(20, lambda: (pointer(card, '<Enter>', 8, 8),
                                   nav.select('two'), switch.feedback('hover', True)))
            operation.mark()

            def finished():
                after = probe.summary()['tween_done_count']
                require(not variable.get() and switch.controller.position == 0,
                        'G6 interrupted switch terminal mismatch')
                require(nav.selected_key == 'two' and tween_jobs_finished(card, nav, switch),
                        'G6 retargeted animations did not settle')
                require(after >= before, 'G6 Tween done counter regressed')
                operation.record['details'].update(cancel_verified=True,
                                                   done_count_during=after-before,
                                                   switch_on=bool(variable.get()),
                                                   selected=nav.selected_key)
                operation.finish()
                next_()
            app.after(500, finished)

        def destroy(next_):
            operation = log.start('mixed_interaction', 'destroy_during_motion', {})
            pointer(button, '<Enter>', 8, 8)
            pointer(card, '<Enter>', 8, 8)
            switch.feedback('hover', True)
            slider.set(20)
            operation.mark()
            app.after(20, surface.destroy)

            def finished():
                require(not surface.winfo_exists(), 'G6 surface was not destroyed')
                require(all(not tween.alive() and tween.job is None for tween in controllers),
                        'G6 destroy left a live Tween job')
                require(app.grab_current() is None, 'G6 destroy leaked grab')
                operation.record['details']['destroy_verified'] = True
                operation.finish()
                next_()
            app.after(250, finished)

        wait_until(app, lambda: (card.interaction.job is None and card in card.interaction.bound
                                 and slider.winfo_width() > 100 and slider.winfo_ismapped()),
                   lambda: run_serial(app, [mixed, cancel, destroy], lambda: done(result(log, {
                       'mixed_control_kind_count': 5, 'command_count': len(clicks),
                   }, commands=clicks, tween_summary=probe.summary()))))

    try:
        return drive(app, start, timeout_ms=30000)
    except Exception:
        close_on_error(app)
        raise


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description='Real TkWin11 gallery audit G1-G6')
    parser.add_argument('--scenario', choices=('all', *SCENARIO_NAMES), default='all')
    parser.add_argument('--repeat', type=positive, default=1)
    parser.add_argument('--output', help="raw JSON path, or '-' for stdout")
    args = parser.parse_args(argv)

    ui.enable_dpi_awareness()
    rounds = []
    names = SCENARIO_NAMES if args.scenario == 'all' else (args.scenario,)
    for index in range(1, args.repeat+1):
        for name in names:
            began = milliseconds()
            try:
                outcome = run_round(name, index)
                outcome['duration_ms'] = milliseconds()-began
            except Exception:
                outcome = round_result(name, index, error=traceback.format_exc(), began=began)
            rounds.append(outcome)
            print(f"{'PASS' if outcome['pass'] else 'FAIL'} {name} round {index}",
                  file=sys.stderr, flush=True)
            if not outcome['pass']:
                print(outcome['error'], file=sys.stderr, flush=True)
    failed = sum(not item['pass'] for item in rounds)
    document = {
        'schema_version': 1,
        'run': {
            'commit': commit(), 'milestone': 'G0', 'scenario': args.scenario,
            'repeat': args.repeat, 'timestamp_ns': time.time_ns(),
            'environment': environment(), 'profile_enabled': profiling.enabled(),
            'measurement_scope': (
                'Real gallery G1-G6 input-to-first-visual and input-to-settled timings '
                'recorded locally with time.perf_counter in every mode; production '
                'profiling operations/spans/span_totals/update/sched/gap included when enabled'
            ),
        },
        'rounds': rounds,
        'summary': {'round_count': len(rounds), 'passed_count': len(rounds)-failed,
                    'failed_count': failed},
    }
    output = args.output
    if output is None:
        stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
        output = (Path(__file__).resolve().parents[1]/'perf'/'results'/'gallery-audit'
                  /f'gallery_{args.scenario}_{stamp}.json')
    try:
        text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
        if str(output) == '-':
            print(text, end='')
        else:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
            print(f'Raw JSON: {path.resolve()}', file=sys.stderr)
    except Exception:
        traceback.print_exc()
        return 3
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
