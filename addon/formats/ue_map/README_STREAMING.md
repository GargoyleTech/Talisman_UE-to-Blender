# Recursive map references

Enable **Recursively import streaming levels** to follow serialized sublevel
references from `LevelStreamingAlwaysLoaded`, `LevelStreamingDynamic` and the
legacy `LevelStreamingKismet` class. The generic bridge and explicit SQEX
profiles export Kismet entries without renaming their source class.

Both plain string world references used by older KH packages and structured
`WorldAsset.AssetPathName` references are accepted. `PackageNameToLoad` is a
fallback when `WorldAsset` is absent or `None`. Paths are matched against the
mounted map index, including `/Game` roots, plugin roots, quoted world paths,
spaces and dots in game names. Repeated references and cycles visit each
logical map only once, case-insensitively.

Traversal reads authored references regardless of runtime visibility/loading
flags. It does not run Blueprint streaming logic, model mutually exclusive
game states, apply arbitrary per-level `LevelTransform` values, or create
multiple transformed instances of the same logical package. This is the same
recursive assembly scope as the existing AlwaysLoaded/Dynamic path. The three
tested Kismet source maps did not serialize nonidentity level transforms.

The registered-title fixture in
`bridge/blender_sqex_splines_streaming_test.py` follows a Kismet edge and imports
its child SQEX curve with models and lights disabled. Live checks resolved 19
references in a Remake source map, one in a KH III source map, and five in a
KH 0.2 source map. Each check also read a resolved child UMAP and verified
duplicate/cycle suppression. These are representative traversal checks, not
full Blender imports of every referenced world.
