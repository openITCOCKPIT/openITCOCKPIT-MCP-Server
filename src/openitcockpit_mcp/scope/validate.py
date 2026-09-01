"""Validation against an already-fetched "allowed elements" bundle.

No I/O: these operate on a bundle returned by
:class:`~openitcockpit_mcp.scope.service.ScopeService`.

A rejection names the field, every invalid value at once, and either the closest
matching names in scope or the total count of valid ones.
"""

from __future__ import annotations

import difflib
from typing import Any

# How many valid names to echo back before switching to "and N more".
_SAMPLE_SIZE = 10
# difflib cutoff for "did you mean" suggestions - low enough to catch typos,
# high enough not to suggest unrelated names.
_SUGGESTION_CUTOFF = 0.4
_SUGGESTION_COUNT = 3


# openITCOCKPIT's Api::makeItJavaScriptAble() turns id=>name maps into a list of
# {"key": id, "value": name} objects, not a flat {id: name} dict. These three
# helpers are the only readers of that shape.


def scope_options(elements: dict, response_key: str) -> list[dict[str, Any]]:
    """The ``{"key": id, "value": name}`` rows for one key of a scope bundle."""
    return elements.get(response_key) or []


def option_id(option: dict[str, Any]) -> int:
    return int(option["key"])


def option_name(option: dict[str, Any]) -> str:
    return str(option.get("value", ""))


def resolve_scoped_names(
    elements: dict,
    response_key: str,
    names: str | list[str],
    field_label: str,
    scope_label: str,
) -> int | list[int]:
    """Resolve one name (str in, int out) or several (list in, list out) against one scope.

    All invalid names are collected into a single error.
    """
    single_name = names if isinstance(names, str) else None
    name_list = [names] if isinstance(names, str) else list(names)

    options = scope_options(elements, response_key)
    by_value: dict[str, list[dict[str, Any]]] = {}
    for item in options:
        by_value.setdefault(option_name(item), []).append(item)
    all_names = list(dict.fromkeys(option_name(item) for item in options))

    resolved: list[int] = []
    problems: list[str] = []
    for name in name_list:
        matches = by_value.get(name, [])
        if len(matches) == 1:
            resolved.append(option_id(matches[0]))
            continue
        if len(matches) > 1:
            ambiguous = ", ".join(f"id={option_id(item)}" for item in matches)
            problems.append(f"'{name}' is ambiguous ({len(matches)} entries share this name: {ambiguous})")
            continue
        close = difflib.get_close_matches(name, all_names, n=_SUGGESTION_COUNT, cutoff=_SUGGESTION_CUTOFF)
        hint = f" Closest matches: {', '.join(close)}." if close else ""
        problems.append(f"'{name}' is not visible in scope.{hint}")

    if problems:
        raise ValueError(
            f"Field '{field_label}' has {len(problems)} invalid value(s) within {scope_label} "
            f"({len(all_names)} values allowed there in total): {' | '.join(problems)} "
            f"Call get_allowed_elements_for_container to see the full allowed list before retrying."
        )
    return resolved[0] if single_name is not None else resolved


def verify_ids_in_scope(
    elements: dict,
    response_key: str,
    ids: int | list[int],
    field_label: str,
    scope_label: str,
) -> None:
    """Re-verify already-resolved id(s) are still visible in a scope bundle.

    Applies to reference fields the caller did not touch on an update. Such a field was
    valid when set, but its scope can shift - most notably when update_host changes the
    target container. Reports in the same shape as :func:`resolve_scoped_names`.
    """
    id_list = [ids] if isinstance(ids, int) else [int(i) for i in ids]
    if not id_list:
        return
    options = scope_options(elements, response_key)
    valid_ids = {option_id(item) for item in options}
    invalid = [i for i in id_list if i not in valid_ids]
    if not invalid:
        return
    names = [option_name(item) for item in options]
    sample = ", ".join(names[:_SAMPLE_SIZE]) if names else "(none visible in this scope)"
    more = f", and {len(names) - _SAMPLE_SIZE} more" if len(names) > _SAMPLE_SIZE else ""
    raise ValueError(
        f"Field '{field_label}' currently has value(s) {invalid} which are no longer visible within {scope_label} "
        f"({len(names)} values allowed there in total): {sample}{more}. This field was not part of your update, but "
        f"the scope it depends on changed - you must explicitly set it to something valid in the new scope."
    )


def format_legal_container_error(object_type: str, field_label: str, submitted_name: str, legal: list[dict[str, Any]]) -> str:
    paths = [option_name(item) for item in legal]
    sample = ", ".join(paths[:_SAMPLE_SIZE]) if paths else "(none visible to this API user)"
    more = f", and {len(paths) - _SAMPLE_SIZE} more" if len(paths) > _SAMPLE_SIZE else ""
    return (
        f"Field '{field_label}' value '{submitted_name}' resolves to a container that cannot hold a {object_type} "
        f"in openITCOCKPIT (only certain container types qualify as a parent - e.g. Tenant/Location/Node, not a "
        f"Hostgroup/Contactgroup/Servicetemplategroup container). Valid parent containers: {sample}{more}."
    )
