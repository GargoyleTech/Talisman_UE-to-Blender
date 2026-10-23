"""Import-scoped datablock lookups; no persistent Blender IDs or quality state."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import bpy


_active_cache = ContextVar("talisman_import_datablocks", default=None)


def live_datablock(kind, item):
    try:
        return item is not None and getattr(bpy.data, kind).get(item.name) == item
    except ReferenceError:
        return False


class DatablockIndex:
    def __init__(self, kind, identity):
        self.kind, self.identity = kind, identity
        self.entries = {}
        self.size = -1
        self.scans = 0

    def rebuild(self):
        collection = getattr(bpy.data, self.kind)
        self.entries.clear()
        for item in collection:
            self.entries.setdefault(self.identity(item), item)
        self.size = len(collection)
        self.scans += 1

    def get(self, key):
        if self.size < 0:
            self.rebuild()
        item = self.entries.get(key)
        if item is not None:
            if live_datablock(self.kind, item) and self.identity(item) == key:
                return item
            # Undo/File > New and deleted or retagged datablocks must not leave
            # dangling RNA references, even when collection sizes are unchanged.
            self.rebuild()
        elif len(getattr(bpy.data, self.kind)) != self.size:
            self.rebuild()
        return self.entries.get(key)

    def remember(self, item):
        if self.size < 0:
            return
        self.entries[self.identity(item)] = item
        self.size = len(getattr(bpy.data, self.kind))


class ImportCache:
    def __init__(self):
        self.indices = {}
        self.refreshed_materials = {}
        self.completed = {}
        self.loaders = {}

    def index(self, kind, label, identity):
        key = (kind, label)
        if key not in self.indices:
            self.indices[key] = DatablockIndex(kind, identity)
        return self.indices[key]

    def remember(self, kind, item):
        # Update every initialized view so one builder's new material/image
        # does not force the next builder to rescan the entire collection.
        for (collection, _label), index in self.indices.items():
            if collection == kind:
                index.remember(item)


def get_import_cache(owner=None):
    if owner is None:
        return _active_cache.get()
    cache = getattr(owner, "_import_datablocks", None)
    if cache is None:
        cache = _active_cache.get() or ImportCache()
        try:
            owner._import_datablocks = cache
        except (AttributeError, TypeError):
            pass
    return cache


def find_datablock(kind, label, key, identity, owner=None):
    cache = get_import_cache(owner)
    if cache is not None:
        return cache.index(kind, label, identity).get(key)
    return next((item for item in getattr(bpy.data, kind) if identity(item) == key), None)


def remember_datablock(kind, item, owner=None):
    cache = get_import_cache(owner)
    if cache is not None:
        cache.remember(kind, item)


@contextmanager
def import_cache_scope(cache=None):
    cache = cache if cache is not None else (_active_cache.get() or ImportCache())
    active = _active_cache
    token = active.set(cache)
    try:
        yield cache
    finally:
        active.reset(token)


def scoped_import(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with import_cache_scope():
            return function(*args, **kwargs)
    return wrapped
