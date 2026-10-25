"""Opt-in, root-local measurements for animation performance baselines."""
from contextlib import contextmanager
import os
import statistics
import time
import tkinter as tk


_ENABLED = os.environ.get('TKWIN11_PROFILE') == '1'
_SAMPLE_NAMES = ('frame_cold_ms', 'raster_pixels_ms', 'raster_png_ms', 'raster_photo_ms',
                 'frame_other_ms', 'dpi_rebuild_ms', 'tween_update_ms', 'sched_delay_ms', 'gap_ms')
_COUNTER_NAMES = ('frame_hit_count', 'frame_cold_count', 'switch_copy_count', 'same_frame_copy_count',
                  'dpi_rebuild_count', 'tween_update_ms_total', 'active_tween_count',
                  'active_tween_count_peak', 'hidden_tween_start_count', 'hidden_tween_update_ms',
                  'hidden_tween_sched_count')
_VISIBILITIES = ('unmapped', 'mapped_outside_viewport', 'visible', 'destroyed')


def enabled():
    return _ENABLED


def state(root):
    if not _ENABLED:
        return None
    root = root._root()
    result = getattr(root, '_tkwin11_profile', None)
    if result is None:
        result = root._tkwin11_profile = {
            'samples': {name: [] for name in _SAMPLE_NAMES},
            'counters': {name: 0 for name in _COUNTER_NAMES},
            'visibility': {name: {'update_ms': 0., 'update_count': 0} for name in _VISIBILITIES},
            'frames': [],
            'active': set(),
            'current_frame': None,
        }
    return result


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values)-1)*fraction
    lower = int(position)
    upper = min(len(values)-1, lower+1)
    return values[lower]+(values[upper]-values[lower])*(position-lower)


def summary(samples):
    return {
        'median': {name: statistics.median(values) for name, values in samples.items() if values},
        'p95': {name: percentile(values, .95) for name, values in samples.items() if values},
        'mean': {name: statistics.fmean(values) for name, values in samples.items() if values},
        'pstdev': {name: statistics.pstdev(values) for name, values in samples.items() if len(values) > 1},
    }


def snapshot(root, reset=False):
    profile = state(root)
    if profile is None:
        return None
    result = {
        'samples': {name: list(values) for name, values in profile['samples'].items()},
        'counters': {name: value for name, value in profile['counters'].items()},
        'visibility': {name: dict(value) for name, value in profile['visibility'].items()},
        'frames': [dict(value) for value in profile['frames']],
    }
    result['summary'] = summary(result['samples'])
    if reset:
        root._root()._tkwin11_profile = None
    return result


class FrameCollector:
    def __init__(self, root, kind, details=None):
        self.profile = state(root)
        self.kind = kind
        self.details = details or {}
        self.previous = None
        self.started = 0.
        self.stages = {}

    def __enter__(self):
        if self.profile is not None:
            self.previous = self.profile['current_frame']
            self.profile['current_frame'] = self
            self.started = time.perf_counter()
        return self

    def __exit__(self, *_):
        if self.profile is None:
            return
        elapsed = (time.perf_counter()-self.started)*1000
        self.profile['current_frame'] = self.previous
        if self.kind == 'switch':
            other = max(0., elapsed-sum(self.stages.values()))
            self.profile['samples']['frame_cold_ms'].append(elapsed)
            self.profile['samples']['frame_other_ms'].append(other)
            self.profile['counters']['frame_cold_count'] += 1
            self.profile['frames'].append({**self.details, 'frame_cold_ms': elapsed,
                                           'frame_other_ms': other, **self.stages})
        else:
            self.profile['samples']['dpi_rebuild_ms'].append(elapsed)
            self.profile['counters']['dpi_rebuild_count'] += 1

    @contextmanager
    def stage(self, name):
        if self.profile is None:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter()-started)*1000
            self.stages[name] = self.stages.get(name, 0.)+elapsed
            self.profile['samples'][name].append(elapsed)


def current_frame(root):
    profile = state(root)
    return profile['current_frame'] if profile is not None else None


def frame_hit(root):
    profile = state(root)
    if profile is not None:
        profile['counters']['frame_hit_count'] += 1


def switch_copy(root, repeated):
    profile = state(root)
    if profile is not None:
        profile['counters']['switch_copy_count'] += 1
        profile['counters']['same_frame_copy_count'] += bool(repeated)


def visibility(widget):
    try:
        if not widget.winfo_exists():
            return 'destroyed'
        if not widget.winfo_ismapped():
            return 'unmapped'
        left, top = widget.winfo_rootx(), widget.winfo_rooty()
        right, bottom = left+widget.winfo_width(), top+widget.winfo_height()
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
        width, height = viewport.winfo_width(), viewport.winfo_height()
        if right <= vx or left >= vx+width or bottom <= vy or top >= vy+height:
            return 'mapped_outside_viewport'
        return 'visible'
    except tk.TclError:
        return 'destroyed'


def tween_start(owner, tween):
    profile = state(owner)
    if profile is None:
        return None
    category = visibility(owner)
    tween._profile_visibility = category
    profile['active'].add(tween)
    active = len(profile['active'])
    profile['counters']['active_tween_count'] = active
    profile['counters']['active_tween_count_peak'] = max(
        profile['counters']['active_tween_count_peak'], active)
    if category in ('unmapped', 'mapped_outside_viewport'):
        profile['counters']['hidden_tween_start_count'] += 1
    return profile


def tween_stop(owner, tween, destroyed=False):
    profile = state(owner)
    if profile is None:
        return
    profile['active'].discard(tween)
    profile['counters']['active_tween_count'] = len(profile['active'])
    if destroyed:
        tween._profile_visibility = 'destroyed'


def tween_schedule(owner, tween):
    profile = state(owner)
    if profile is not None and getattr(tween, '_profile_visibility', None) in (
            'unmapped', 'mapped_outside_viewport'):
        profile['counters']['hidden_tween_sched_count'] += 1


def tween_timing(owner, tween, scheduled, previous):
    profile = state(owner)
    if profile is None or scheduled is None:
        return
    now = time.perf_counter()
    profile['samples']['sched_delay_ms'].append(max(0., (now-scheduled)*1000))
    profile['samples']['gap_ms'].append((now-previous)*1000)


def tween_update(owner, tween, elapsed):
    profile = state(owner)
    if profile is None:
        return
    category = getattr(tween, '_profile_visibility', None) or visibility(owner)
    profile['samples']['tween_update_ms'].append(elapsed)
    profile['counters']['tween_update_ms_total'] += elapsed
    profile['visibility'][category]['update_ms'] += elapsed
    profile['visibility'][category]['update_count'] += 1
    if category in ('unmapped', 'mapped_outside_viewport'):
        profile['counters']['hidden_tween_update_ms'] += elapsed
