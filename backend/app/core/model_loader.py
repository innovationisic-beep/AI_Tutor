"""
Discover and collect all Beanie Document models under app.models.
Used at startup to initialize Beanie with all document types without manual registration.
"""
import importlib
import pkgutil
from typing import Type

from beanie import Document

# Import app.models so we have a package path; avoid importing submodules here
# to prevent circular imports. We only reference the package for walk_packages.
import app.models as _models_pkg  # noqa: F401


def get_document_models() -> list[type]:
    """
    Scan app.models (and subpackages), import all modules, and return every
    class that inherits from beanie.Document, excluding the base class from
    app.models.base so it is not registered as a collection.

    Returns an empty list if no document models exist (e.g. only base.py).
    """
    document_models: list[type] = []
    seen: set[type] = set()

    try:
        package_path = _models_pkg.__path__  # type: ignore[union-attr]
        package_prefix = _models_pkg.__name__ + "."
    except (AttributeError, ModuleNotFoundError):
        return []

    for _importer, modname, _ispkg in pkgutil.walk_packages(
        package_path,
        prefix=package_prefix,
    ):
        # Do not scan base or __init__ so we don't register BaseDocument as a collection
        if modname in ("app.models.base", "app.models.__init__"):
            continue

        try:
            module = importlib.import_module(modname)
        except Exception:
            continue

        for attr_name in dir(module):
            try:
                obj = getattr(module, attr_name)
            except Exception:
                continue

            if not isinstance(obj, type) or not issubclass(obj, Document):
                continue
            # Exclude the base class (e.g. if re-exported) so it has no collection
            if obj.__module__ == "app.models.base" or obj.__name__ == "BaseDocument":
                continue
            if obj in seen:
                continue
            seen.add(obj)
            document_models.append(obj)

    return document_models
