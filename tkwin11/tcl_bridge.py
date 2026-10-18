"""Preserve Tcl script scope and catch semantics across Python command adapters."""
import tkinter as tk


def install_proxy(interpreter, path, callback, native, *, scoped=(), routed=None):
    """Replace command ``path`` with a proc that forwards to ``callback``.

    ``scoped`` subcommands always run natively in the caller's frame.
    When ``routed`` is given, only those subcommands reach Python; every other
    subcommand is a native tailcall. Hot read-only calls made by Tk's own
    bindings (instate, identify, coords, measure ...) then skip Python entirely.
    """
    dispatch = native + '__bridge'
    def call(*args):
        try:
            return (0, callback(*args), ())
        except tk.TclError as error:
            info = interpreter.call('set', '::errorInfo')
            code = interpreter.call('set', '::errorCode')
            return (1, str(error), ('-code', 1, '-level', 0,
                                   '-errorinfo', info, '-errorcode', code))
    interpreter.createcommand(dispatch, call)
    words = lambda values: '[list '+' '.join(tk._stringify(value) for value in values)+']'
    body = ''
    if routed is not None:
        body = 'if {[lindex $args 0] ni '+words(routed)+'} {tailcall '+tk._stringify(native)+' {*}$args}\n'
    elif scoped:
        body = 'if {[lindex $args 0] in '+words(scoped)+'} {tailcall '+tk._stringify(native)+' {*}$args}\n'
    body += ('lassign ['+tk._stringify(dispatch)+' {*}$args] failed result options\n'
             'if {$failed} {return -options $options $result}\nreturn $result')
    interpreter.call('proc', path, 'args', body)
    return dispatch


def delete_callback(interpreter, dispatch):
    if interpreter.call('info', 'commands', dispatch):
        interpreter.deletecommand(dispatch)


def unbind(widget, sequence, funcid):
    """Remove one ``bind(..., add='+')`` handler and keep the others.

    Before Python 3.13, ``Misc.unbind(sequence, funcid)`` clears every script
    bound to ``sequence`` on that widget, silently breaking other components.
    """
    if not funcid:
        return
    try:
        script = str(widget.tk.call('bind', widget._w, sequence))
        prefix = 'if {"[' + funcid + ' '
        kept = [line for line in script.split('\n') if line.strip() and not line.startswith(prefix)]
        widget.tk.call('bind', widget._w, sequence, '\n'.join(kept))
    except tk.TclError:
        pass
    try:
        widget.deletecommand(funcid)
    except (tk.TclError, ValueError):
        pass
