# Marvel Rivals compatibility

Tested Steam build **25955398** (S10.5, depot build 3939753) with the
workspace add-on in Blender **5.1.2**, on 19 October 2026.

Use **`GAME_MarvelRivals`**, the dedicated CUE4Parse profile for the game's
UE5.3 layout. Both an **AES key** and a matching **`.usmap`** are required.
The supplied `5.3.2-3939753+++depot_marvel+S10.5_release-Marvel.usmap`
was verified by the profile tester and the actual imports.

The shipped **Marvel Rivals** template leaves the game folder, AES key,
and mappings path empty for the user to supply. It does not distribute
keys, mapping files, or machine-specific paths. The existing template
upgrade and reset behavior applies; no add-on version change is needed.

## Import results

Registered Blender import operators were exercised against these assets:

| Asset | Result | Vertices | Triangles | Bones |
|---|---|---:|---:|---:|
| `Characters/1032/1032001/Meshes/SK_1032_1032001` | Pass | 113,499 | 149,274 | 465 |
| `Characters/1032/1032001/Meshes/SK_1032_1032001_Lobby` | Pass | 140,139 | 191,159 | 770 |
| `Characters/1032/1032001/Weapons/Emote/Sand/Meshes/SM_WP_10323022050_Sand` | Pass | 5,136 | 7,916 | — |

All sampled skeletal vertices have skin weights. Armatures, armature
modifiers, finite vertex positions, UV layers, and evaluated vertex counts
were checked. These two skeletal samples are gameplay and lobby variants
of the same character, rather than an audit of every hero.

| Map under `Marvel/Content/Marvel/Maps/` | Mesh objects | Triangles | Missing mesh assets |
|---|---:|---:|---:|
| `Lobby/2001/Lobby_2001003401.umap` | 28 | 12,184 | 0 |
| `AsgardE01/AsgardE01_SelectHero_S1_Art.umap` | 126 | 417,971 | 0 |

Map tests used textures enabled, a 512-pixel texture cap, and recursive
streaming disabled. Both scenes import; they report respectively one and
three unavailable texture assets. The latter are a daylight ambient
cubemap and the `T_RVT_Height` / `T_RVT_Material` runtime virtual-texture
assets, which do not expose conventional Texture2D exports. Their absence
does not prevent the sampled scene geometry imports. Shader parity,
animation playback, and complete streamed worlds were not tested.

## Mounting and browsing

- Without a key, no asset files were readable. The key from the user's
  saved CS.RIN collection unlocked 78 containers and 893,259 mounted files.
- Removing the `.usmap` reproduces an explicit missing unversioned-property
  mappings error on the gameplay SkeletalMesh.
- Plain `GAME_UE5_3` only mounts 39 containers, versus 78 with the dedicated
  profile. It is not an equivalent setting for this installation.
- The map index exposes 2,157 entries representing 2,065 distinct paths.
- An unrestricted mesh index exceeded the 150-second test timeout. Use a
  narrow asset-browser path filter, such as
  `/Characters/1032/1032001/Meshes/`, to avoid scanning the whole installation.
  The actual Blender browser loads that filter in about 4.2 seconds with
  three distinct SkeletalMeshes and no package-read failures; the map list
  loads in about 1.4 seconds.

Machine-local inputs, captured results, console logs, reproducible Blender
scripts, and saved scenes are retained in ignored
`.local/marvel-rivals-tests/`. The actual key is confined to the private
local test configuration. No archive keys or mappings were added to the
distributed add-on.
