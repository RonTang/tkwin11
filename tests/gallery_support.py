"""Shared real-Tk gallery audit helpers; scenario code never pumps events."""
import time
import tkinter as tk

from tkwin11 import profiling
from scenario_support import milliseconds, require


class Operation:
    """One profile operation with unconditional user-perceived local timing."""

    def __init__(self, root, name, kind, details=None):
        self.root = root
        self.started = time.perf_counter()
        self.record = {
            'name': name,
            'kind': kind,
            'details': dict(details or {}),
            'first_visual_ms': None,
            'settled_ms': None,
            'input_to_first_visual_ms': None,
            'input_to_settled_ms': None,
            'status': 'active',
        }
        self.id = profiling.operation_start(root, name, kind, self.record['details'])
        self.finished = False

    def mark(self, marker='first_visual'):
        if marker == 'first_visual' and self.record['first_visual_ms'] is None:
            elapsed = (time.perf_counter()-self.started)*1000
            self.record['first_visual_ms'] = elapsed
            self.record['input_to_first_visual_ms'] = elapsed
        profiling.operation_mark(self.root, self.id, marker)
        return self.record

    def finish(self, error=None):
        if not self.finished:
            elapsed = (time.perf_counter()-self.started)*1000
            self.record['settled_ms'] = elapsed
            self.record['input_to_settled_ms'] = elapsed
            self.record['status'] = 'error' if error else 'done'
            self.finished = True
        if error and self.record['status'] != 'error':
            self.record['status'] = 'error'
        try:
            profiling.operation_finish(self.root, self.id, error)
        except tk.TclError:
            if error:
                self.record['status'] = 'error'
        return self.record

    def as_dict(self):
        return {
            **self.record,
            'details': dict(self.record['details']),
            'profile_operation_id': self.id,
        }


class OperationLog:
    def __init__(self, root):
        self.root = root
        self.items = []

    def start(self, name, kind, details=None):
        operation = Operation(self.root, name, kind, details)
        self.items.append(operation)
        return operation

    def records(self):
        return [operation.as_dict() for operation in self.items]


def idle(root, callback):
    """Continue after queued geometry/idle work without update_idletasks()."""
    root.after_idle(lambda: root.after_idle(callback))


def wait_until(root, predicate, callback, timeout_ms=4000, interval_ms=8):
    deadline = milliseconds()+timeout_ms

    def check():
        if predicate():
            callback()
        elif milliseconds() >= deadline:
            raise AssertionError(f'gallery condition timed out after {timeout_ms} ms')
        else:
            root.after(interval_ms, check)
    check()


def wait_tweens(root, tweens, callback, timeout_ms=4000):
    tweens = tuple(tweens)

    def settled():
        for tween in tweens:
            try:
                if tween.job is not None:
                    return False
            except tk.TclError:
                pass
        return True
    wait_until(root, settled, lambda: idle(root, callback), timeout_ms)


def run_serial(root, tasks, complete):
    tasks = iter(tasks)

    def advance():
        try:
            task = next(tasks)
        except StopIteration:
            complete()
            return
        task(lambda: root.after(0, advance))
    advance()


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def instances(widget, cls):
    return [item for item in walk(widget) if isinstance(item, cls)]


def one_instance(widget, cls, label):
    found = instances(widget, cls)
    require(found, f'gallery has no {label}')
    return found[0]


def perform(log, name, kind, details, action, terminal, callback,
            tweens=(), timeout_ms=4000):
    operation = log.start(name, kind, details)
    try:
        action()
        operation.mark()
    except Exception as exc:
        operation.finish(str(exc))
        raise

    def verify():
        try:
            terminal(operation.record['details'])
            require(all(tween.job is None for tween in tweens),
                    f'{name} animation did not settle')
            operation.finish()
        except Exception as exc:
            operation.finish(str(exc))
            raise
        callback()
    wait_tweens(log.root, tweens, verify, timeout_ms)
    return operation


def close_on_error(root):
    try:
        root.destroy()
    except tk.TclError:
        pass


def pointer(widget, sequence, x=8, y=8, **kwargs):
    options = dict(x=x, y=y, **kwargs)
    if sequence in ('<Motion>', '<B1-Motion>'):
        options['warp'] = True
    if sequence in ('<ButtonPress-1>', '<ButtonRelease-1>', '<B1-Motion>'):
        options.setdefault('rootx', round(widget.winfo_rootx()+x))
        options.setdefault('rooty', round(widget.winfo_rooty()+y))
    widget.event_generate(sequence, **options)


def tween_jobs_finished(*widgets):
    attributes = ('_page_tween', 'animator', 'feedback_animator', 'thumb_animator')
    for widget in widgets:
        for attribute in attributes:
            tween = getattr(widget, attribute, None)
            if tween is not None and tween.job is not None:
                return False
    return True


def watch_reveal(root, operation, popup):
    def revealed():
        return (popup.winfo_exists() and popup.winfo_ismapped()
                and float(popup.attributes('-alpha')) > 0)
    wait_until(root, revealed, operation.mark)


def popup_visible(popup):
    return (popup is not None and not popup._closed and popup.winfo_exists()
            and popup.winfo_ismapped() and popup._fade.job is None)


def popup_closed(popup):
    return popup is not None and popup._closed and not popup.winfo_exists()
