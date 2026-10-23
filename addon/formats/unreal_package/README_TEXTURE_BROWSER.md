# Unreal Engine Texture

In the **Shader Editor**, choose **Add > Texture > Unreal Engine Texture**.
The node samples a packed Blender image through an internal native Image Texture
node, with Vector input and Color/Alpha outputs. An unconnected Vector uses the
mesh's usual UV coordinates, just like Image Texture.

The **Game** dropdown combines custom CUE4Parse profiles from the add-on
preferences with Crisis Core Reunion, Final Fantasy VII Remake Intergrade,
Final Fantasy VII Rebirth, Kingdom Hearts III, and Kingdom Hearts 0.2. All names
are sorted together. The first, blank entry means **none**: no package mount,
texture listing, or preview requests. First use defaults to none. New nodes
remember the last chosen game through the normal Blender add-on preferences;
deleted profiles and missing game folders fall back to none. Each existing node
keeps its own game selection. Configure paths, mappings, keys, and the shared
Oodle library in the add-on preferences.

Selecting a game immediately opens a folder browser. Mounting and texture
indexing run in the bridge process. Results appear in batches, so folders,
search, and previews can be used before a large game's first index finishes.
The status line reports progress; search results can grow as indexing continues.
Completed indexes are cached in Blender's user configuration under `talisman/`,
separately for each mount configuration. Container sizes/timestamps and mapping
changes invalidate the cache. **Refresh** remounts and rebuilds it.

Click folders to open them and use the parent-folder button to go up. Search
matches every space-separated term against texture package/object paths.
Large result sets use pages of 128 entries. Checkboxes retain selections when
changing folders, search text, or pages. **Select Visible**, **Invert**, and
**Clear** operate on the visible page or the complete checked selection as
labelled. Each node owns an independent browser and selection. The expand button
opens the same browser in a larger popup.

Highlighting a texture requests a preview without loading it into the shader.
The bridge selects a smaller readable mip where possible, decodes the image,
and returns a PNG bounded to 384 pixels. Requests are delayed briefly during
rapid selection changes; obsolete results are discarded. At most 32 thumbnails
are retained per browser. RGB previews ignore Unreal's packed mask alpha;
imported images preserve their channels and use Blender's Channel Packed alpha
mode. Preview updates never create full-size Blender Image datablocks.

**Load Texture(s)** loads checked textures, or the highlighted texture if none
are checked. The first successful texture fills the current node; additional
textures get separate nodes with their browsers collapsed. Images are extracted
at their highest readable resolution, packed into the blend, and reused when
the same source texture is loaded again. Color Space, Interpolation, and
Extension remain editable. Source dimensions can exceed the readable cooked
mip when the game has omitted streamed data.

Loading is asynchronous between assets; Blender still loads/packs each final
image on its main thread. Escape stops the remaining imports and retains
successful ones. The batch supports undo and redo. Imported images survive
save/reload without the temporary extracted files. Browsing additional packages
still needs the add-on and the configured game files.

Only textures readable by the installed CUE4Parse profile can be used. Generic
single-layer virtual textures and volume slice atlases use the existing texture
adapters. Runtime render targets have no stored pixels; unsupported layouts and
formats report an unavailable preview/import instead of creating empty nodes.
Missing mappings, compression support, or encryption keys still prevent reads.

Browser workers are closed on game changes, node removal, file loading, undo,
redo, and add-on unregister/reload. Idle workers expire. Blender polls atomic
request/result files using application timers; it runs no persistent Python
worker threads or blocking pipe reads for this browser.
