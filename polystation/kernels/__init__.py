"""Kernel registry — discover and instantiate trading kernels by name."""

from __future__ import annotations

from typing import Any

from polystation.core.kernel import Kernel

# Registry of kernel classes by name
_REGISTRY: dict[str, type[Kernel]] = {}


def register(cls: type[Kernel]) -> type[Kernel]:
    """Class decorator to register a kernel.

    Args:
        cls: The Kernel subclass to register. Its ``name`` class attribute
            is used as the registry key.

    Returns:
        The class unchanged (decorator passthrough).
    """
    _REGISTRY[cls.name] = cls
    return cls


def get_kernel_class(name: str) -> type[Kernel] | None:
    """Look up a kernel class by name.

    Args:
        name: The registered kernel name.

    Returns:
        The kernel class, or None if no kernel is registered under *name*.
    """
    return _REGISTRY.get(name)


def list_kernels() -> list[str]:
    """Return all registered kernel names.

    Returns:
        Sorted list of kernel name strings.
    """
    return list(_REGISTRY.keys())


def create_kernel(name: str, **kwargs: Any) -> Kernel:
    """Instantiate a kernel by name.

    Args:
        name: The registered kernel name.
        **kwargs: Forwarded to the kernel's ``__init__``.

    Returns:
        A new kernel instance.

    Raises:
        KeyError: If *name* is not in the registry.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise KeyError(
            f"Unknown kernel: '{name}'. Available: {list(_REGISTRY.keys())}"
        )
    return cls(**kwargs)
