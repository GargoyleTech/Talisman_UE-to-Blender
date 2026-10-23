"""Profile name filters applied once when an object is imported."""

from fnmatch import fnmatchcase


def apply_default_visibility(obj, patterns, *source_names):
    """Hide a matching object and its visual children without discarding data."""
    patterns = tuple(pattern.strip().casefold() for pattern in patterns if pattern.strip())
    if not patterns:
        return
    values = [*source_names, obj.name]
    for target in (obj, getattr(obj, "data", None)):
        if target is not None:
            values.extend(target.get(key, "") for key in (
                "ue_virtual_path", "template_object_path", "source_name",
                "ue_actor_path", "ue_component_name", "ue_component_path",
            ))
    names = set()
    for value in values:
        if not value:
            continue
        value = str(value).replace("\\", "/").strip("'\"")
        # A package basename identifies the uasset; the final subobject token
        # identifies an actor or component in serialized Unreal references.
        package, _, subobject = value.partition(":")
        if subobject:
            names.update(part.casefold() for part in subobject.split(".") if part != "PersistentLevel")
        else:
            names.add(package.rsplit("/", 1)[-1].split(".", 1)[0].casefold())
    if any(fnmatchcase(name, pattern) for name in names for pattern in patterns):
        for target in (obj, *obj.children_recursive):
            target["ue_hidden_by_profile"] = True
            target.hide_set(True)
            target.hide_render = True
