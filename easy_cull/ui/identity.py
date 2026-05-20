"""Application identity and asset helpers for EasyCull."""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib.resources
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

ASSET_PACKAGE = 'easy_cull.ui.assets'
ICON_PNG = 'EasyCull.png'
ICON_SVG = 'EasyCull.svg'
ICON_ICNS = 'EasyCull.icns'
ICON_ICO = 'EasyCull.ico'


def _package_version() -> str:
    try:
        return package_version('easy-cull')
    except PackageNotFoundError:
        return 'unknown'


APP_NAME = 'EasyCull'
APP_VERSION = _package_version()


def asset_resource(name: str) -> Traversable:
    """Return a packaged UI asset resource."""
    return importlib.resources.files(ASSET_PACKAGE).joinpath(name)


def easy_cull_icon() -> QIcon:
    """Return the packaged EasyCull app icon."""
    icon = QIcon(str(asset_resource(ICON_PNG)))
    if sys.platform == 'win32':
        # Add the Windows .ico file to the same Qt icon, so the icon contains
        # the standard Windows sizes such as 16x16, 32x32, and 256x256.
        #
        # This is needed because the PyInstaller command-line option named
        # "--icon" embeds the icon into EasyCull.exe, but the live taskbar
        # button comes from Qt's runtime QIcon. If Qt only gets the PNG,
        # Windows can fall back to a generic taskbar icon even though the EXE
        # itself has the correct embedded icon.
        icon.addFile(str(asset_resource(ICON_ICO)))

    return icon


def branded_argv(argv: list[str] | None = None) -> list[str]:
    """Return argv with a user-facing app name in argv[0]."""
    source_argv = argv if argv is not None else sys.argv
    if not source_argv:
        return [APP_NAME]

    return [APP_NAME, *source_argv[1:]]


def prepare_app_identity() -> None:
    """Set app metadata that can be consumed during Qt app construction."""
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)
    QCoreApplication.setOrganizationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(APP_NAME)
    _set_macos_process_name(APP_NAME)


def apply_app_identity(app: QApplication) -> None:
    """Apply the app name and icon used by Qt and native shell surfaces."""
    prepare_app_identity()
    icon = easy_cull_icon()
    app.setWindowIcon(icon)
    _set_macos_application_icon(str(asset_resource(ICON_PNG)))


def _set_macos_process_name(name: str) -> None:
    """Best-effort override for macOS surfaces that show the process name."""
    if sys.platform != 'darwin':
        return

    try:
        libc = ctypes.CDLL(None)
        setprogname = libc.setprogname
        setprogname.argtypes = [ctypes.c_char_p]
        setprogname.restype = None
        setprogname(name.encode('utf-8'))
        bridge = _MacOSObjCBridge.load('Foundation')
        process_info = bridge.send_id(
            bridge.class_named(b'NSProcessInfo'),
            bridge.selector(b'processInfo'),
        )
        process_name = bridge.ns_string(name)
        bridge.send_void_id(
            process_info,
            bridge.selector(b'setProcessName:'),
            process_name,
        )
    except (AttributeError, OSError):
        return


def _set_macos_application_icon(icon_path: str) -> None:
    """Best-effort override for native macOS app switcher icon consumers."""
    if sys.platform != 'darwin':
        return

    try:
        bridge = _MacOSObjCBridge.load('Foundation', 'AppKit')
        icon_file = bridge.ns_string(icon_path)
        ns_image = bridge.send_id(
            bridge.class_named(b'NSImage'),
            bridge.selector(b'alloc'),
        )
        ns_image = bridge.send_id_id(
            ns_image,
            bridge.selector(b'initWithContentsOfFile:'),
            icon_file,
        )
        if not ns_image:
            return

        ns_app = bridge.send_id(
            bridge.class_named(b'NSApplication'),
            bridge.selector(b'sharedApplication'),
        )
        bridge.send_void_id(
            ns_app,
            bridge.selector(b'setApplicationIconImage:'),
            ns_image,
        )
    except (AttributeError, OSError):
        return


class _MacOSObjCBridge:
    """Tiny Objective-C bridge for app identity calls on macOS."""

    def __init__(self, objc: ctypes.CDLL) -> None:
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p

        message_send = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        if message_send is None:
            raise AttributeError('objc_msgSend')

        self._objc = objc
        self.send_id = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(message_send)
        self.send_id_cstr = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
        )(message_send)
        self.send_id_id = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(message_send)
        self.send_void_id = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(message_send)

    @classmethod
    def load(cls, *frameworks: str) -> _MacOSObjCBridge:
        objc_path = ctypes.util.find_library('objc')
        if objc_path is None:
            raise OSError('libobjc not found')

        objc = ctypes.CDLL(objc_path)
        for framework in frameworks:
            framework_path = ctypes.util.find_library(framework)
            if framework_path is None:
                raise OSError(f'{framework} framework not found')

            ctypes.CDLL(framework_path)

        return cls(objc)

    def class_named(self, class_name: bytes) -> int:
        class_pointer = self._objc.objc_getClass(class_name)
        if not class_pointer:
            raise AttributeError(class_name.decode('utf-8'))

        return class_pointer

    def selector(self, name: bytes) -> int:
        return self._objc.sel_registerName(name)

    def ns_string(self, value: str) -> int:
        ns_string_class = self.class_named(b'NSString')
        ns_string = self.send_id_cstr(
            ns_string_class,
            self.selector(b'stringWithUTF8String:'),
            value.encode('utf-8'),
        )
        if not ns_string:
            raise AttributeError('NSString')

        return ns_string
