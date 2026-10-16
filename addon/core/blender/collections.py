"""Collection routing shared by mesh, map and sequence imports."""

from contextlib import contextmanager

import bpy


def _ensure_scene_collection(scene, name: str) -> bpy.types.Collection:
    """Get or create *name* as a direct child of the scene's master collection."""
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if scene.collection.children.get(collection.name) is None:
        scene.collection.children.link(collection)
    return collection


def _layer_collection_for(layer_collection, collection):
    """Depth-first search for the LayerCollection wrapping *collection*."""
    if layer_collection.collection is collection:
        return layer_collection
    for child in layer_collection.children:
        found = _layer_collection_for(child, collection)
        if found is not None:
            return found
    return None


@contextmanager
def _active_collection(context, collection):
    """Temporarily make *collection* the active one.

    Most of this add-on's object creation links into ``context.collection``
    (the armature builder, the mesh importer, socket empties, the UMAP actor
    paths), so pointing the active collection at the cutscene's own collection
    is what routes all of it there without threading a parameter through every
    call site.
    """
    view_layer = context.view_layer
    target = _layer_collection_for(view_layer.layer_collection, collection)
    previous = view_layer.active_layer_collection
    if target is not None:
        view_layer.active_layer_collection = target
    try:
        yield
    finally:
        try:
            view_layer.active_layer_collection = previous
        except Exception:
            pass


def _adopt_new_scene_collections(scene, collection, known: set) -> int:
    """Move top-level collections created during an import under *collection*.

    ``formats/ue_map/map_import.py`` links a collection per source UMAP into the
    scene's master collection, so a cutscene's temporary levels would otherwise
    sit outside the cutscene's own collection.
    """
    moved = 0
    for child in list(scene.collection.children):
        if child is collection or child.name in known:
            continue
        if collection.children.get(child.name) is None:
            collection.children.link(child)
        scene.collection.children.unlink(child)
        moved += 1
    return moved
