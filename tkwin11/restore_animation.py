"""Short-lived native bitmap used only while a minimized Tk window restores."""
import ctypes
import tkinter as tk
from ctypes import wintypes as w


HANDOFF_DELAY_MS=350


class RestoreAnimation:
    def __init__(self,root):
        self.root=root
        self.u=ctypes.WinDLL('user32',use_last_error=True)
        self.g=ctypes.WinDLL('gdi32',use_last_error=True)
        self.dwm=ctypes.WinDLL('dwmapi',use_last_error=True)
        self.dwm.DwmFlush.restype=ctypes.c_long
        self.dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,ctypes.c_void_p,w.DWORD]
        self.dwm.DwmGetWindowAttribute.restype=ctypes.c_long
        self.u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
        self.u.IsZoomed.argtypes=[w.HWND];self.u.IsZoomed.restype=w.BOOL
        self.u.GetDC.argtypes=[w.HWND];self.u.GetDC.restype=w.HDC
        self.u.ReleaseDC.argtypes=[w.HWND,w.HDC]
        self.u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID]
        self.u.CreateWindowExW.restype=w.HWND
        self.u.DestroyWindow.argtypes=[w.HWND];self.u.DestroyWindow.restype=w.BOOL
        self.u.ShowWindow.argtypes=[w.HWND,ctypes.c_int];self.u.ShowWindow.restype=w.BOOL
        self.u.IsWindow.argtypes=[w.HWND];self.u.IsWindow.restype=w.BOOL
        self.u.GetWindowLongPtrW.argtypes=[w.HWND,ctypes.c_int];self.u.GetWindowLongPtrW.restype=ctypes.c_ssize_t
        self.u.SetWindowLongPtrW.argtypes=[w.HWND,ctypes.c_int,ctypes.c_void_p];self.u.SetWindowLongPtrW.restype=ctypes.c_void_p
        self.u.SetLayeredWindowAttributes.argtypes=[w.HWND,w.COLORREF,ctypes.c_ubyte,w.DWORD]
        self.u.SetWindowPos.argtypes=[w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT]
        self.g.CreateCompatibleDC.argtypes=[w.HDC];self.g.CreateCompatibleDC.restype=w.HDC
        self.g.CreateCompatibleBitmap.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int];self.g.CreateCompatibleBitmap.restype=w.HBITMAP
        self.g.SelectObject.argtypes=[w.HDC,w.HGDIOBJ];self.g.SelectObject.restype=w.HGDIOBJ
        self.g.DeleteObject.argtypes=[w.HGDIOBJ];self.g.DeleteObject.restype=w.BOOL
        self.g.DeleteDC.argtypes=[w.HDC];self.g.DeleteDC.restype=w.BOOL
        self.g.BitBlt.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HDC,ctypes.c_int,ctypes.c_int,w.DWORD]
        self.g.BitBlt.restype=w.BOOL
        class PaintStruct(ctypes.Structure):
            _fields_=[('hdc',w.HDC),('erase',w.BOOL),('paint',w.RECT),('restore',w.BOOL),('incremental',w.BOOL),('reserved',ctypes.c_byte*32)]
        self.PaintStruct=PaintStruct
        self.PAINTPROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
        self._paint_callback=self.PAINTPROC(self._paint)
        self.u.BeginPaint.argtypes=[w.HWND,ctypes.c_void_p];self.u.BeginPaint.restype=w.HDC
        self.u.EndPaint.argtypes=[w.HWND,ctypes.c_void_p];self.u.EndPaint.restype=w.BOOL
        self.u.CallWindowProcW.argtypes=[ctypes.c_void_p,w.HWND,w.UINT,w.WPARAM,w.LPARAM]
        self.u.CallWindowProcW.restype=ctypes.c_ssize_t
        self.u.RedrawWindow.argtypes=[w.HWND,ctypes.c_void_p,w.HANDLE,w.UINT]
        self.dc=self.bitmap=self.old_bitmap=None
        self.overlay=self.job=None
        self.parent=None
        self.origin=None

    @property
    def busy(self):
        return self.overlay is not None or self.job is not None

    def _paint(self,hwnd,message,wparam,lparam):
        if message==0x000F:
            paint=self.PaintStruct()
            self.u.BeginPaint(hwnd,ctypes.byref(paint))
            self.g.BitBlt(paint.hdc,0,0,self.origin[2],self.origin[3],self.dc,0,0,0x00CC0020)
            self.u.EndPaint(hwnd,ctypes.byref(paint))
            return 0
        return self.u.CallWindowProcW(self._old_paint_proc,hwnd,message,wparam,lparam)

    def _release(self):
        if self.dc is not None:
            self.g.SelectObject(self.dc,self.old_bitmap)
            self.g.DeleteObject(self.bitmap)
            self.g.DeleteDC(self.dc)
        self.dc=self.bitmap=self.old_bitmap=None
        self.origin=None

    def capture(self,hwnd):
        if self.dc is not None:return True
        if self.busy:return False
        rect=w.RECT();self.u.GetWindowRect(hwnd,ctypes.byref(rect))
        if self.u.IsZoomed(hwnd):
            visible=w.RECT()
            if self.dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(visible),ctypes.sizeof(visible))==0:
                rect=visible
        width=rect.right-rect.left;height=rect.bottom-rect.top
        if width<=0 or height<=0:return False
        screen=self.u.GetDC(None)
        dc=self.g.CreateCompatibleDC(screen) if screen else None
        bitmap=self.g.CreateCompatibleBitmap(screen,width,height) if dc else None
        old=self.g.SelectObject(dc,bitmap) if bitmap else None
        copied=bool(old and self.g.BitBlt(dc,0,0,width,height,screen,rect.left,rect.top,0x00CC0020))
        if screen:self.u.ReleaseDC(None,screen)
        if not copied:
            if old:self.g.SelectObject(dc,old)
            if bitmap:self.g.DeleteObject(bitmap)
            if dc:self.g.DeleteDC(dc)
            return False
        self.dc,self.bitmap,self.old_bitmap=dc,bitmap,old
        self.parent=hwnd
        self.origin=(rect.left,rect.top,width,height)
        return True

    def present(self,destination):
        if self.dc is None:return False
        if self.overlay is None:
            self.overlay=self.u.CreateWindowExW(0x08000000,'Static','',0x40000000,0,0,self.origin[2],self.origin[3],self.parent,None,None,None)
            if not self.overlay:return False
            style=self.u.GetWindowLongPtrW(self.overlay,-20)|0x00080000
            self.u.SetWindowLongPtrW(self.overlay,-20,style)
            self.u.SetLayeredWindowAttributes(self.overlay,0,255,2)
            self._old_paint_proc=self.u.SetWindowLongPtrW(self.overlay,-4,ctypes.cast(self._paint_callback,ctypes.c_void_p))
        self.u.RedrawWindow(self.overlay,None,None,0x0001|0x0004|0x0100)
        self.u.ShowWindow(self.overlay,8)
        self.u.SetWindowPos(self.overlay,0,0,0,0,0,0x0001|0x0002|0x0010|0x0040)
        return True

    def start(self):
        if self.dc is None or self.job is not None:return
        self.job=self.root.after(HANDOFF_DELAY_MS,self._complete)

    def _complete(self):
        self.job=None
        self.dwm.DwmFlush()
        self._destroy_overlay()
        self._release()

    def dismiss(self):
        if self.job is not None:
            try:self.root.after_cancel(self.job)
            except tk.TclError:pass
            self.job=None
        self._destroy_overlay()

    def _destroy_overlay(self):
        if self.overlay and self.u.IsWindow(self.overlay):self.u.DestroyWindow(self.overlay)
        self.overlay=None

    def discard(self):
        if self.job is not None:
            try:self.root.after_cancel(self.job)
            except tk.TclError:pass
            self.job=None
        self._destroy_overlay()
        self._release()
