# Talisman: A Blender addon for interfacing with Unreal Engine formats.
<img width="2560" height="1392" alt="image" src="https://github.com/user-attachments/assets/74c2ed0f-45e0-410b-be01-e497498c9a2b" />

Solid chance your favorite game could run on UE, but existing tools for working with its formats are yucky yuck when all you want is your beloved treasured worlds and characters in Blender to poke around with. At the minimum you're going to end up with a bunch of loose texture and model files in intermediary formats to get them into Blender. Built on [CUE4Parse](https://github.com/FabianFG/CUE4Parse), the same foundation [FModel](https://github.com/4sval/FModel) is built on, we benefit from the same wide range of compatibility as FModel, but directly within a Blender File->Import dialog! 

Do you want skeletons? We got skeletons fuh days, baby. We got state of the art skeleton correction so that you get rigs that were actually meant to work in Blender instead of that sideways Dr. Spaghetti that you get from other UE->Blender pipelines. Meshes, armatures, textures, and animations. Or boom, check it out right here, map importing goodness:
<img width="966" height="960" alt="image" src="https://github.com/user-attachments/assets/5784d54d-b41e-4b46-b31a-28c68e08af28" />
We even get the less important stuff like splines.

## Game specific enhancements !
This project was originally created with Final Fantasy VII Rebirth in mind, and scope creep sort of took over from there. In development since early 2026, we have some game-specific support for FF/KH games on UE4, and some general support for most builds of UE4. 
<img width="952" height="1293" alt="image" src="https://github.com/user-attachments/assets/f76a5e82-826e-43fc-a2ed-80d1f6a1a953" />

For the prior mentioned Square Enix titles, proprietary binary formats such as the terrain mesh (Massive Environment) or bone driver (KineDriver) systems are wholly supported.

## What's here .

- [`addon/`](addon/) — the installable Blender add-on (Python), including
  the prebuilt bridge binaries in `addon/bridge/` so it works out of the box.
  See [`addon/README_ADDON.md`](addon/README_ADDON.md) for feature details.
- [`bridge/`](bridge/) — the C# source for `FF7RGameAssetBridge`, the helper
  process that reads package data straight out of a mounted game install.
  See [`bridge/README.md`](bridge/README.md) to rebuild it.

Inside the add-on, reusable infrastructure lives in `core/`, reusable decoded
formats live in `formats/`, engine/material/import differences live in
`games/<title>/`, and Blender-facing menus and preferences live in `ui/`.

## What's not here.
- Oodle DLL used for decompressing Unreal package files. You probably already have a game that ships with an oo2core_7.dll or oo2core_9.dll such as Final Fantasy VII Remake or even some non-Unreal games such as Elden Ring.
- Game-specific .usmap files. Many games require a .usmap file to understand the pak files. Can be found either via google or in the [FModel](https://github.com/4sval/FModel) discord server.
- Game-specific AES keys that many games also require. It's not really hard to find them online. For example https://cs.rin.ru/forum/viewtopic.php?f=10&t=100672 has a lot of them.

## Installation notes.
Addon zips are under "releases". I will make a Blender extension repository eventually. Make sure to read the addon settings and fill out fields as-needed.

Disable and ideally uninstall any of my older FF7R addons you might have installed — they share several operator IDs with this one.

## Building the bridge yourself

Not required — `addon/bridge/` already has working binaries. If you want to
audit or modify the bridge, see [`bridge/README.md`](bridge/README.md).

## [Come find me on Discord if you must...](https://discord.gg/FHFamAN94b)

## License and slopcode disclosure

Original code in this repository is dedicated to the public domain under
[The Unlicense](LICENSE). Bundled third-party components (CUE4Parse and its
own dependencies) keep their own licenses — see [NOTICE.md](NOTICE.md). OpenAI Codex was used to aid development because I have very little interest in programming, solely working with code out of spite for the tools I want to use not already existing.
