# Language content

Hover tooltips live here. The rest of the add-on imports **`tooltips.py`**, the
master module, rather than individual category files. It re-exports the text
variables so category files can be split, renamed, or reorganized without
changing every menu that uses them.

The current text is English. This is the starting point for future translation;
language selection and other user-facing strings have not been moved yet.

| File | Menus and controls |
| --- | --- |
| `shared_import.py` | Shared mesh/skeleton options, dropdown choices, package browser, texture memory |
| `preferences.py` | Add-on preferences, game paths, CUE4Parse profiles, PBR mappings |
| `rebirth_import.py` | Rebirth mesh, skeleton, UMAP, terrain, cutscene, and KineDriver dialogs |
| `remake_import.py` | Remake cutscene and KineDriver dialogs |
| `kingdom_hearts_import.py` | Kingdom Hearts Matinee and KineDriver dialogs |
| `map_import.py` | Shared conventional UMAP import dialogs |
| `loose_map_import.py` | Loose Massive Environment UMAP file picker |
| `animation_import.py` | Shared game animation importers |
| `generic_import.py` | Generic UE4 mesh, map, animation, and sequence dialogs |
| `kinedriver.py` | KineDriver JSON import, graph nodes/viewer, and viewport toggle |
| `scene_tools.py` | Object, Pose, and Armature tools; generated mouth controls |
| `materials.py` | Generated RMI surface, eye, and hair material properties |

## Editing text

Edit the quoted text in the relevant category file. Comments identify the menus,
dialog sections, and code using each entry. Long text uses adjacent quoted lines;
Python joins them exactly, so keep spaces between words at line boundaries.
Reload or restart the add-on after edits. Material and rig property descriptions
stored in a `.blend` are updated when their setup code next runs.

Keep variable names stable. A control reused in several menus should reference
one text variable through `tooltips.py`. Different game-specific behavior can
have its own description. Dropdown option descriptions are included; identifiers,
labels, reports, and text supplied by game assets are outside this tooltip pass.

Some descriptions contain named placeholders such as `{game_label}` or
`{definition_game_name}`. Preserve placeholder names when translating; their
position in a sentence may change. Placeholders are filled by the calling code.

To add or move an entry, update its category definition and its explicit import
in `tooltips.py`. When adding or renaming a category file, also update the category
reload list at the top of `tooltips.py`. The master and its categories depend only
on Python and can be read without Blender.
