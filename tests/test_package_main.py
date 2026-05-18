from __future__ import annotations

import easy_cull.__main__ as package_main
import easy_cull.ui.app as ui_app


def test_package_main_module_reexports_ui_main() -> None:
    assert package_main.main is ui_app.main
