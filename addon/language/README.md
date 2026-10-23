# Language content

User-facing text belongs here. The rest of the add-on imports **`strings.py`**,
the master catalog, rather than individual definition files:

```python
from ..language import strings
```

It re-exports the text variables so definition files can be split, renamed, or
reorganized without changing every menu that uses them. Its generic name covers
future labels, messages, and other user-facing text as well as tooltips.

The current text is English. This is the starting point for future translation;
language selection and other user-facing strings have not been moved yet.

| File | Menus and controls |
| --- | --- |
| `strings.py` | Shared entry point and definition reloads for all user-facing text |
| `tooltip_import.py` | Shared and game-specific mesh, skeleton, map, animation, sequence, terrain, and KineDriver import dialogs; package browser and texture options |
| `tooltip_preferences.py` | Add-on preferences, game paths, CUE4Parse profiles, PBR mappings |
| `tooltip_kinedriver.py` | KineDriver JSON import, graph nodes/viewer, and viewport toggle |
| `tooltip_scene_tools.py` | Object, Pose, and Armature tools; generated mouth controls |
| `tooltip_texture_browser.py` | Unreal Engine Texture node, game dropdown, package browser, previews, and batch loading |
| `tooltip_materials.py` | Generated RMI surface, eye, and hair material properties |

## Editing text

Edit the quoted text in the relevant definition file. Tooltip definition files
use the `tooltip_` prefix; import tooltips are grouped into sections in
`tooltip_import.py`. Comments identify the menus,
dialog sections, and code using each entry. Long text uses adjacent quoted lines;
Python joins them exactly, so keep spaces between words at line boundaries.
Reload or restart the add-on after edits. Material and rig property descriptions
stored in a `.blend` are updated when their setup code next runs.

Keep variable names stable. A control reused in several menus should reference
one text variable through `strings.py`. Different game-specific behavior can
have its own description. Dropdown option descriptions are included; identifiers,
labels, reports, and text supplied by game assets are outside this tooltip pass.

Some descriptions contain named placeholders such as `{game_label}` or
`{definition_game_name}`. Preserve placeholder names when translating; their
position in a sentence may change. Placeholders are filled by the calling code.

To add or move an entry, update its definition and its explicit import in
`strings.py`. When adding or renaming a definition file, also update the reload
list at the top of `strings.py`. Future non-tooltip text can live in its own
definition files and be exported through the same master catalog. The master
and its definitions depend only on Python and can be read without Blender.
