"""Resolve streaming references against a mounted map index."""

from .map_import import collect_level_streaming_asset_paths


class StreamingMapQueue:
    """Append discovered sublevels once, including when references form cycles."""

    def __init__(self, selected_paths, indexed_paths, *, content_root=None):
        self.paths = []
        self.seen = set()
        for path in selected_paths:
            if path.casefold() not in self.seen:
                self.seen.add(path.casefold())
                self.paths.append(path)
        self.lookup = {}
        for path in indexed_paths:
            normalized = path.replace("\\", "/").lstrip("/")
            self.lookup[normalized.casefold()] = path
            root, separator, relative = normalized.casefold().partition("/content/")
            if separator:
                is_plugin = "/plugins/" in root
                if is_plugin:
                    self.lookup.setdefault("/" + root.rsplit("/", 1)[-1] + "/" + relative, path)
                elif (content_root is None or
                      (root + "/content").casefold() == content_root.casefold()):
                    self.lookup.setdefault("/game/" + relative, path)

    def extend(self, entries):
        for reference in collect_level_streaming_asset_paths(entries):
            reference = reference.strip().strip("'")
            if "'" in reference:
                reference = reference.split("'", 1)[1].rstrip("'")
            package = reference.split(":", 1)[0]
            slash, dot = package.rfind("/"), package.rfind(".")
            if dot > slash:
                package = package[:dot]
            key = (package + ".umap").casefold()
            path = self.lookup.get(key) or self.lookup.get(key.lstrip("/"))
            if path and path.casefold() not in self.seen:
                self.seen.add(path.casefold())
                self.paths.append(path)
