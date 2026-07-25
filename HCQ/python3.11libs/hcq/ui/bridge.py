"""Loose coupling helpers between widgets and the HCQ manager."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Iterable


def value(source: Any, name: str, default: Any = None) -> Any:
    """Read an attribute, a mapping value, or a zero-argument getter."""
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    candidate = getattr(source, name, default)
    if callable(candidate) and name.startswith(("get_", "list_", "is_")):
        try:
            return candidate()
        except Exception:
            return default
    return candidate


def mapping(source: Any) -> dict[str, Any]:
    if source is None:
        return {}
    if isinstance(source, dict):
        return source
    if is_dataclass(source):
        return asdict(source)
    to_dict = getattr(source, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:
            return {}
    try:
        return dict(vars(source))
    except (TypeError, AttributeError):
        return {}


def sequence(source: Any) -> list[Any]:
    if source is None:
        return []
    if isinstance(source, dict):
        for key in ("items", "queues", "jobs", "registrations", "sessions"):
            if isinstance(source.get(key), list):
                return source[key]
        return []
    if isinstance(source, (str, bytes)):
        return []
    try:
        return list(source)
    except TypeError:
        return []


def call(
    target: Any,
    names: str | Iterable[str],
    *args: Any,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Call the first available method, tolerating signature drift."""
    if target is None:
        return default
    if isinstance(names, str):
        names = (names,)
    for name in names:
        candidate = getattr(target, name, None)
        if not callable(candidate):
            continue
        try:
            return candidate(*args, **kwargs)
        except TypeError:
            # Some manager facades intentionally expose argument-free refresh
            # or selection-aware actions.
            try:
                return candidate()
            except TypeError:
                continue
    return default


def connect_refresh(
    source: Any, callback: Callable[[], None]
) -> Callable[[], None]:
    """Connect to commonly used manager signals without requiring one shape."""
    disconnectors: list[Callable[[], None]] = []
    listener = getattr(source, "add_listener", None)
    if callable(listener):
        try:
            remove = listener(lambda *_args, **_kwargs: callback())
            if callable(remove):
                disconnectors.append(remove)
        except Exception:
            pass
    seen: set[int] = set()
    for owner in (
        source,
        value(source, "monitor"),
        value(source, "runner"),
        value(source, "storage"),
    ):
        if owner is None:
            continue
        for name in (
            "refresh",
            "changed",
            "state_changed",
            "data_changed",
            "queues_changed",
            "run_list_changed",
            "history_changed",
        ):
            signal = getattr(owner, name, None)
            if signal is None or id(signal) in seen:
                continue
            connector = getattr(signal, "connect", None)
            if callable(connector):
                try:
                    connector(callback)
                    seen.add(id(signal))
                    disconnectors.append(
                        lambda signal=signal: signal.disconnect(callback)
                    )
                except Exception:
                    pass

    def disconnect() -> None:
        for remove in reversed(disconnectors):
            try:
                remove()
            except Exception:
                pass
        disconnectors.clear()

    return disconnect


def manager_collection(manager: Any, name: str) -> list[Any]:
    direct = value(manager, name)
    if callable(direct):
        try:
            direct = direct()
        except Exception:
            direct = None
    if direct is None:
        direct = call(manager, (f"get_{name}", f"list_{name}"))
    if name == "run_list":
        queues = value(direct, "queues")
        if queues is not None:
            direct = queues
    return sequence(direct)


def item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)
