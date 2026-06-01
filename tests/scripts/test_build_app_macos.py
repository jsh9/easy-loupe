from __future__ import annotations

import os
import plistlib
import sys
from typing import TYPE_CHECKING

import pytest

from scripts.build_app import build_app_macos as build_app

if TYPE_CHECKING:
    from pathlib import Path


def test_pyinstaller_command_prefers_module_when_binary_missing(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    exiftool_binary = (
        f'{build_app.EXIFTOOL_STAGE_EXE}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_lib = (
        f'{build_app.EXIFTOOL_STAGE_LIB}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}/lib'
    )

    assert build_app.pyinstaller_command() == [
        sys.executable,
        '-m',
        'PyInstaller',
        '--clean',
        '--noconfirm',
        '--windowed',
        '--name',
        'EasyLoupe',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_loupe.ui.assets',
        '--copy-metadata',
        'easy-loupe',
        '--osx-bundle-identifier',
        'com.easyloupe.EasyLoupe',
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_lib,
        str(build_app.ENTRYPOINT),
    ]


def test_pyinstaller_command_uses_binary_when_available(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_app.shutil, 'which', lambda _name: 'pyinstaller')
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )
    exiftool_binary = (
        f'{build_app.EXIFTOOL_STAGE_EXE}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}'
    )
    exiftool_lib = (
        f'{build_app.EXIFTOOL_STAGE_LIB}{os.pathsep}'
        f'{build_app.EXIFTOOL_BUNDLE_DIR}/lib'
    )

    assert build_app.pyinstaller_command(clean=False) == [
        'pyinstaller',
        '--noconfirm',
        '--windowed',
        '--name',
        'EasyLoupe',
        '--icon',
        str(build_app.ICON_PATH),
        '--collect-all',
        'PySide6',
        '--collect-all',
        'shiboken6',
        '--collect-data',
        'easy_loupe.ui.assets',
        '--copy-metadata',
        'easy-loupe',
        '--osx-bundle-identifier',
        'com.easyloupe.EasyLoupe',
        '--add-binary',
        exiftool_binary,
        '--add-data',
        exiftool_lib,
        str(build_app.ENTRYPOINT),
    ]


def test_document_type_entry_registers_supported_photo_extensions() -> None:
    entry = build_app.document_type_entry()

    assert entry['CFBundleTypeRole'] == 'Viewer'
    assert entry['LSHandlerRank'] == 'Alternate'
    assert {'jpg', 'heic', 'arw', 'rw2'} <= set(
        entry['CFBundleTypeExtensions']
    )


def test_inject_document_types_updates_info_plist(tmp_path: Path) -> None:
    app_path = tmp_path / 'EasyLoupe.app'
    contents = app_path / 'Contents'
    contents.mkdir(parents=True)
    info_plist = contents / 'Info.plist'
    with info_plist.open('wb') as file:
        plistlib.dump({'CFBundleName': 'EasyLoupe'}, file)

    build_app.inject_info_plist_metadata(app_path)

    with info_plist.open('rb') as file:
        payload = plistlib.load(file)

    assert payload['CFBundleIdentifier'] == 'com.easyloupe.EasyLoupe'
    assert payload['CFBundleDocumentTypes'] == [
        build_app.document_type_entry()
    ]
    for key, value in build_app.PRIVACY_USAGE_DESCRIPTIONS.items():
        assert payload[key] == value


def test_main_signs_and_verifies_after_metadata_injection(
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        build_app,
        'ensure_exiftool_payload',
        lambda: build_app.EXIFTOOL_STAGE_EXE,
    )

    def pyinstaller_command(*, clean: bool = True) -> list[str]:
        assert clean is True
        return ['pyinstaller']

    monkeypatch.setattr(build_app, 'pyinstaller_command', pyinstaller_command)
    monkeypatch.setattr(
        build_app.subprocess,
        'run',
        lambda *_args, **_kwargs: calls.append('pyinstaller'),
    )
    monkeypatch.setattr(
        build_app,
        'mark_bundled_exiftool_executable',
        lambda: calls.append('chmod'),
    )
    monkeypatch.setattr(
        build_app,
        'remove_bundled_pyside_tool_apps',
        lambda: calls.append('cleanup'),
    )
    monkeypatch.setattr(
        build_app,
        'inject_info_plist_metadata',
        lambda: calls.append('plist'),
    )
    monkeypatch.setattr(
        build_app,
        'sign_app_bundle',
        lambda: calls.append('sign'),
    )
    monkeypatch.setattr(
        build_app,
        'verify_app_signature',
        lambda: calls.append('verify'),
    )

    assert build_app.main([]) == 0

    assert calls == [
        'pyinstaller',
        'chmod',
        'cleanup',
        'plist',
        'sign',
        'verify',
    ]
    assert str(build_app.APP_PATH) in capsys.readouterr().out


def test_remove_bundled_pyside_tool_apps_removes_unused_qt_apps(
        tmp_path: Path,
) -> None:
    app_path = tmp_path / 'EasyLoupe.app'
    frameworks = app_path / 'Contents' / 'Frameworks' / 'PySide6'
    resources = app_path / 'Contents' / 'Resources' / 'PySide6'
    for base in (frameworks, resources):
        for app_name in build_app.PYSIDE_TOOL_APP_NAMES:
            (base / f'{app_name}.app').mkdir(parents=True)
            (base / f'{app_name}__dot__app').mkdir(parents=True)

    webengine = (
        frameworks
        / 'Qt'
        / 'lib'
        / 'QtWebEngineCore.framework'
        / 'Versions'
        / 'A'
        / 'Helpers'
        / 'QtWebEngineProcess.app'
    )
    webengine.mkdir(parents=True)

    build_app.remove_bundled_pyside_tool_apps(app_path)

    for base in (frameworks, resources):
        for app_name in build_app.PYSIDE_TOOL_APP_NAMES:
            assert not (base / f'{app_name}.app').exists()
            assert not (base / f'{app_name}__dot__app').exists()

    assert webengine.exists()


def test_sign_app_bundle_runs_ad_hoc_codesign(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_path = tmp_path / 'EasyLoupe.app'
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> None:
        calls.append(command)

    monkeypatch.setattr(build_app.subprocess, 'run', run)

    build_app.sign_app_bundle(app_path)

    assert calls == [
        ['codesign', '--force', '--deep', '--sign', '-', str(app_path)]
    ]


def test_verify_app_signature_requires_bundle_identifier(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_path = tmp_path / 'EasyLoupe.app'
    calls: list[list[str]] = []

    class Result:
        stderr = 'Identifier=com.easyloupe.EasyLoupe\n'
        stdout = ''
        returncode = 0

    def run(command: list[str], **_kwargs: object) -> Result:
        calls.append(command)
        return Result()

    monkeypatch.setattr(build_app.subprocess, 'run', run)

    build_app.verify_app_signature(app_path)

    assert calls == [
        [
            'codesign',
            '--verify',
            '--deep',
            '--strict',
            '--verbose=4',
            str(app_path),
        ],
        ['codesign', '-dv', '--verbose=4', str(app_path)],
    ]


def test_verify_app_signature_rejects_wrong_bundle_identifier(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_path = tmp_path / 'EasyLoupe.app'

    class Result:
        stderr = 'Identifier=EasyLoupe\n'
        stdout = ''
        returncode = 0

    monkeypatch.setattr(
        build_app.subprocess,
        'run',
        lambda *_args, **_kwargs: Result(),
    )

    with pytest.raises(RuntimeError) as exc_info:
        build_app.verify_app_signature(app_path)

    assert 'com.easyloupe.EasyLoupe' in str(exc_info.value)


def test_print_diagnostics_reports_signature_verification_failure(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
) -> None:
    app_path = tmp_path / 'EasyLoupe.app'
    contents = app_path / 'Contents'
    contents.mkdir(parents=True)
    with (contents / 'Info.plist').open('wb') as file:
        plistlib.dump({'CFBundleIdentifier': 'com.easyloupe.EasyLoupe'}, file)

    class FailedVerify:
        stderr = 'invalid Info.plist'
        stdout = ''
        returncode = 1

    class SigningDetails:
        stderr = 'Identifier=EasyLoupe\nSignature=adhoc\n'
        stdout = ''
        returncode = 0

    def run(command: list[str], **_kwargs: object) -> object:
        if '--verify' in command:
            return FailedVerify()

        return SigningDetails()

    monkeypatch.setattr(build_app, 'APP_PATH', app_path)
    monkeypatch.setattr(
        build_app.utils,
        'print_common_diagnostics',
        lambda: None,
    )
    monkeypatch.setattr(
        build_app.utils,
        'print_path_matches',
        lambda *_args: None,
    )
    monkeypatch.setattr(
        build_app,
        '_print_exiftool_diagnostic',
        lambda: None,
    )
    monkeypatch.setattr(build_app.subprocess, 'run', run)

    build_app.print_diagnostics()

    output = capsys.readouterr().out
    assert 'codesign verify: failed: invalid Info.plist' in output


def test_print_diagnostics_reports_bundle_identity_and_privacy_keys(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
) -> None:
    app_path = tmp_path / 'EasyLoupe.app'
    contents = app_path / 'Contents'
    contents.mkdir(parents=True)
    with (contents / 'Info.plist').open('wb') as file:
        plistlib.dump(
            {
                'CFBundleIdentifier': 'com.easyloupe.EasyLoupe',
                'CFBundleDocumentTypes': [build_app.document_type_entry()],
                **build_app.PRIVACY_USAGE_DESCRIPTIONS,
            },
            file,
        )

    class Result:
        stderr = (
            'Identifier=com.easyloupe.EasyLoupe\n'
            'Signature=adhoc\n'
            'TeamIdentifier=not set\n'
        )
        stdout = ''

    monkeypatch.setattr(build_app, 'APP_PATH', app_path)
    monkeypatch.setattr(
        build_app.utils,
        'print_common_diagnostics',
        lambda: None,
    )
    monkeypatch.setattr(
        build_app.utils,
        'print_path_matches',
        lambda *_args: None,
    )
    monkeypatch.setattr(
        build_app,
        '_print_exiftool_diagnostic',
        lambda: None,
    )
    monkeypatch.setattr(
        build_app.subprocess,
        'run',
        lambda *_args, **_kwargs: Result(),
    )

    build_app.print_diagnostics()

    output = capsys.readouterr().out
    assert 'Bundle ID: com.easyloupe.EasyLoupe' in output
    assert 'codesign verify: ok' in output
    assert 'codesign Identifier=com.easyloupe.EasyLoupe' in output
    assert 'codesign Signature=adhoc' in output
    assert 'Entitlements: none' in output
    assert 'NSDesktopFolderUsageDescription: present' in output
