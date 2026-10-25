"""Standard-library helpers for real Tk scenarios; never pumps events directly."""
import time
import tkinter as tk


def milliseconds():
    return time.perf_counter()*1000


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def add_cleanup(root, callback):
    cleanups = getattr(root, '_scenario_cleanups', None)
    if cleanups is None:
        cleanups = root._scenario_cleanups = []
    cleanups.append(callback)


def steps(root, definitions):
    """Run synchronous actions through root.after; the last action finishes."""
    definitions = iter(definitions)

    def advance():
        try:
            delay, action = next(definitions)
        except StopIteration:
            return
        def invoke():
            action()
            advance()
        root.after(delay, invoke)

    advance()


def when_mapped(root, widgets, callback, timeout_ms=3000):
    widgets = tuple(widgets)
    deadline = milliseconds()+timeout_ms
    def check():
        if all(widget.winfo_ismapped() for widget in widgets):
            callback()
        elif milliseconds() >= deadline:
            raise AssertionError('widgets were not mapped before the scenario deadline')
        else:
            root.after(16, check)
    check()


def drive(root, start, timeout_ms=15000):
    """Run one asynchronous scenario on mainloop and propagate callback errors."""
    outcome = {}
    watchdog = [None]

    def finish(result=None, error=None):
        if outcome:
            return
        outcome['result'] = result
        outcome['error'] = error
        root.quit()

    def report(*args):
        import traceback
        finish(error=''.join(traceback.format_exception(*args)))

    def begin():
        try:
            start(lambda result: finish(result=result))
        except Exception:
            import traceback
            finish(error=traceback.format_exc())

    def expire():
        finish(error=f'scenario timed out after {timeout_ms} ms')

    root.report_callback_exception = report
    watchdog[0] = root.after(timeout_ms, expire)
    root.after(0, lambda: when_mapped(root, (root,), begin))
    try:
        root.mainloop()
    finally:
        try:
            root.after_cancel(watchdog[0])
        except tk.TclError:
            pass
        for cleanup in reversed(getattr(root, '_scenario_cleanups', [])):
            try:
                cleanup()
            except (tk.TclError, RuntimeError):
                pass
        try:
            root.destroy()
        except tk.TclError:
            pass
    if outcome.get('error'):
        raise RuntimeError(outcome['error'])
    if 'result' not in outcome:
        raise RuntimeError('scenario ended without a result')
    return outcome['result']


class TweenProbe:
    """Scenario-local counters, not the M1 production profiler."""
    def __init__(self, root, tweens):
        self.root = root
        self.records = {}
        self.active_samples = []
        self.job = None
        self.closed = False
        for tween in tweens:
            record = self.records[tween] = {
                'start_count': 0, 'update_count': 0, 'done_count': 0,
                'update_ms': [], 'update_timestamps_ms': [],
            }
            original = tween.start
            def start(start_value, end_value, update, duration=167, done=None,
                      linear=False, *, _original=original, _record=record):
                _record['start_count'] += 1
                def paint(value):
                    began = milliseconds()
                    _record['update_count'] += 1
                    _record['update_timestamps_ms'].append(began)
                    update(value)
                    _record['update_ms'].append(milliseconds()-began)
                def finished():
                    _record['done_count'] += 1
                    if done is not None:
                        done()
                return _original(start_value, end_value, paint, duration=duration,
                                 done=finished if done is not None else None, linear=linear)
            tween.start = start
        add_cleanup(root, self.close)
        self.poll()

    def active_count(self):
        count = 0
        for tween in self.records:
            try:
                count += tween.job is not None and tween.alive()
            except tk.TclError:
                pass
        return count

    def poll(self):
        if self.closed:
            return
        self.active_samples.append(self.active_count())
        self.job = self.root.after(4, self.poll)

    def stats(self, tween):
        record = self.records[tween]
        return {key: value for key, value in record.items() if key != 'update_timestamps_ms'}

    def summary(self):
        return {
            'active_tween_count_peak': max(self.active_samples, default=0),
            'active_sample_count': len(self.active_samples),
            'tween_update_count': sum(item['update_count'] for item in self.records.values()),
            'tween_done_count': sum(item['done_count'] for item in self.records.values()),
        }

    def close(self):
        self.closed = True
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None


def visibility(widget):
    """Classify both unmapped widgets and mapped widgets outside a viewport."""
    try:
        if not widget.winfo_exists():
            return 'destroyed'
        if not widget.winfo_ismapped():
            return 'unmapped'
        left = widget.winfo_rootx()
        top = widget.winfo_rooty()
        right = left+widget.winfo_width()
        bottom = top+widget.winfo_height()
        node = widget.master
        viewport = None
        while node is not None:
            if getattr(node, '_tkwin11_scroll_area', None) is not None:
                viewport = node
                break
            node = node.master
        if viewport is None:
            viewport = widget._root()
        vx, vy = viewport.winfo_rootx(), viewport.winfo_rooty()
        vw, vh = viewport.winfo_width(), viewport.winfo_height()
        if right <= vx or left >= vx+vw or bottom <= vy or top >= vy+vh:
            return 'mapped_outside_viewport'
        return 'visible'
    except tk.TclError:
        return 'destroyed'


def photo_matches(actual, expected):
    if (actual.width(), actual.height()) != (expected.width(), expected.height()):
        return False
    for y in range(actual.height()):
        for x in range(actual.width()):
            if actual.get(x, y) != expected.get(x, y):
                return False
    return True
