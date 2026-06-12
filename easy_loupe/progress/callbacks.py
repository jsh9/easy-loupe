"""Helpers for adapting optional progress callback signatures."""

from __future__ import annotations

import inspect
from typing import Any


def accepted_keyword_arguments(
        signature: inspect.Signature,
        kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Return keyword arguments accepted by ``signature``."""
    if _accepts_var_keyword(signature):
        return kwargs

    return {
        name: value
        for name, value in kwargs.items()
        if (
            name in signature.parameters
            and signature.parameters[name].kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
    }


def accepts_keyword_argument(signature: inspect.Signature, name: str) -> bool:
    """Return whether ``signature`` can receive ``name`` as a keyword."""
    if _accepts_var_keyword(signature):
        return True

    parameter = signature.parameters.get(name)
    return parameter is not None and parameter.kind in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }


def _accepts_var_keyword(signature: inspect.Signature) -> bool:
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
