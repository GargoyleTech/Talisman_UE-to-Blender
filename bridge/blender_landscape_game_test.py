"""Import real cooked terrain through the production bridge/session/map routes."""
import argparse
import json
from pathlib import Path
import sys
import time

import bpy
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import addon
addon.register()
from addon.core.profiles import GamePaths,GameProfile
from addon.formats.ue_map import map_import,landscapes
from addon.formats.unreal_mesh.session import GenericSession
from addon.formats.unreal_package.session import PackageAssetSession
from addon.formats.unreal_mesh import maps

parser=argparse.ArgumentParser()
parser.add_argument('--config',required=True);parser.add_argument('--game',required=True)
parser.add_argument('--report',required=True);parser.add_argument('--save-blend')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
cfg=json.loads(Path(args.config).read_text())[args.game]
directory=ROOT/'.local/landscape-investigation'/args.game
samples=json.loads((directory/'samples.json').read_text())
generic=cfg['bridgeProfile'].startswith('generic:')
if generic:
    mounted=GenericSession(GamePaths(cfg['root'],cfg.get('oodle',''),cfg.get('usmap',''),cfg.get('key','')),cfg['version'],import_textures=False)
else:
    profile=GameProfile(key=args.game,label=cfg['name'],gargoyle_profile=cfg['bridgeProfile'],engine_label=cfg['version'],package_relative_path=(),install_root_property='')
    mounted=PackageAssetSession(cfg['root'],cfg.get('oodle',''),cfg.get('usmap',''),profile=profile,aes_key=cfg.get('key',''),import_textures=False)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
results=[];timer=time.perf_counter()
with mounted:
    assets=maps.MapAssets(bpy.context,mounted,.01) if generic else None
    for path in dict.fromkeys(r['map'] for r in samples):
        payload=mounted.umap_actors(path)
        all_entries=payload['actors']
        assert not any(e.get('SourceType')=='LandscapeNaniteComponent' and e['Type']=='StaticMeshComponent' for e in all_entries)
        assert any(e['Type']=='LandscapeComponent' for e in all_entries)
        wanted={r['objectPath']:r for r in samples if r['map']==path}
        selected=[e for e in all_entries if e.get('Landscape',{}).get('objectPath') in wanted]
        assert len(selected)==len(wanted)
        by_key={k:e for e in all_entries for k in map_import._entry_component_reference_keys(e)}
        seen={id(e) for e in selected}
        for entry in selected:
            props=entry.get('Properties') or {}
            parent=next((by_key[k] for k in map_import._object_reference_lookup_keys(props.get('AttachParent')) if k in by_key),None)
            if parent is not None and id(parent) not in seen:seen.add(id(parent));selected.append(parent)
        before=set(bpy.data.objects)
        if generic:
            created,missing=maps.import_map(bpy.context,mounted,assets,path,actor_payload={'actors':selected},
                import_lights=False,import_light_probes=False,import_splines=False,landscape_lod=0,max_landscape_vertices=0,landscape_layer_preview=True)
        else:
            col=bpy.data.collections.new(Path(path).stem);bpy.context.scene.collection.children.link(col)
            created,missing=map_import.import_map_entries(selected,path,1,1,target_collection=col,import_lights=False,
                import_reflection_probes=False,import_splines=False,light_texture_loader=mounted,landscape_lod=0,max_landscape_vertices=0,landscape_layer_preview=True)
        assert not missing,missing
        bpy.context.view_layer.update()
        terrain={o.get('ue_component_path'):o for o in set(bpy.data.objects)-before if o.get('ue_geometry_source')=='LANDSCAPE_HEIGHTFIELD'}
        assert terrain.keys()==wanted.keys(),(terrain.keys(),wanted.keys())
        for identity,r in wanted.items():
            obj=terrain[identity];mesh=obj.data;q=r['quads'];count=(q+1)**2
            heights=np.fromfile(directory/r['heightFile'],dtype='<u2')
            yy,xx=np.indices((q+1,q+1),dtype=np.float32)
            raw=np.column_stack((xx.ravel(),yy.ravel(),(heights.astype(np.float32)-32768)/128))
            if r.get('xyOffsetFile'):raw[:,:2]+=np.fromfile(directory/r['xyOffsetFile'],dtype='<f4').reshape(-1,2)
            expected=raw*np.array([.01,-.01,.01],dtype=np.float32)
            actual=np.empty(count*3,dtype=np.float32);mesh.vertices.foreach_get('co',actual);actual=actual.reshape(-1,3)
            local_error=float(np.max(np.abs(expected-actual)));assert local_error<1e-5,(identity,local_error)
            holes=r.get('holeQuads',0);assert len(mesh.polygons)==2*(q*q-holes)
            assert mesh.has_custom_normals and not mesh.validate(clean_customdata=False)
            layer_metadata=json.loads(mesh['ue_landscape_layers'])
            assert len(layer_metadata)==sum('Visibility' not in (a['layer'] or '') for a in r['layers'])
            for paint in r.get('paintLayers',[]):
                index=next(i for i,l in enumerate(layer_metadata) if l['path']==paint['layer'])
                values=np.empty(count,dtype=np.float32);mesh.attributes[f'ue_landscape_weight_{index:03}'].data.foreach_get('value',values)
                reference=np.fromfile(directory/paint['file'],dtype=np.uint8).astype(np.float32)/255
                assert np.array_equal(values,reference)
            B=np.array(r['worldBasis'],dtype=np.float64);world_error=0
            for index in np.linspace(0,count-1,min(count,128),dtype=np.int32):
                world=(B[0]+raw[index]@B[1:])*np.array([.01,-.01,.01])
                actual_world=np.asarray(obj.matrix_world@mesh.vertices[int(index)].co)
                world_error=max(world_error,float(np.max(np.abs(world-actual_world))))
            assert world_error<.005,(identity,world_error)
            results.append(dict(component=identity,vertices=count,triangles=len(mesh.polygons),layers=len(layer_metadata),holes=holes,xyOffsets=bool(r.get('xyOffsetFile')),localErrorMeters=local_error,worldErrorMeters=world_error))
        # Production lower-detail export keeps component endpoints and holes.
        entry=next(e for e in selected if e.get('Landscape'))
        low=mounted.landscape_mesh(entry['Landscape'],1)
        assert low['vertexCount']<=((entry['Landscape']['quads']+1)**2)
        if low['holeQuads']:assert low['holePolicy']=='ANY_COVERED_QUAD'
        r=wanted[entry['Landscape']['objectPath']];q0=r['quads'];q1=low['quads']
        h=np.fromfile(directory/r['heightFile'],dtype='<u2')
        yy,xx=np.indices((q0+1,q0+1),dtype=np.float32)
        full=np.column_stack((xx.ravel(),yy.ravel(),(h.astype(np.float32)-32768)/128))
        if r.get('xyOffsetFile'):full[:,:2]+=np.fromfile(directory/r['xyOffsetFile'],dtype='<f4').reshape(-1,2)
        assert np.array_equal(low['positions'][[0,q1,q1*(q1+1),-1]],full[[0,q0,q0*(q0+1),-1]])
        if r.get('visibilityFile'):
            mask=np.fromfile(directory/r['visibilityFile'],dtype=np.uint8).reshape(q0+1,q0+1)[:-1,:-1]>=170
            integral=np.pad(mask.astype(np.int64).cumsum(0).cumsum(1),((1,0),(1,0)))
            starts=np.arange(q1)*q0//q1;ends=(np.arange(1,q1+1)*q0+q1-1)//q1
            area=integral[ends[:,None],ends]-integral[starts[:,None],ends]-integral[ends[:,None],starts]+integral[starts[:,None],starts]
            assert np.array_equal(low['holes'],area>0)
        if args.game=='last_flag':
            terrain_entries=[e for e in all_entries if e.get('Landscape')]
            seen={id(e) for e in terrain_entries}
            for e in terrain_entries:
                parent=next((by_key[k] for k in map_import._object_reference_lookup_keys((e.get('Properties') or {}).get('AttachParent')) if k in by_key),None)
                if parent is not None and id(parent) not in seen:seen.add(id(parent));terrain_entries.append(parent)
            budget=100_000;before_budget=set(bpy.data.objects)
            _,missing=maps.import_map(bpy.context,mounted,assets,path,actor_payload={'actors':terrain_entries},import_lights=False,
                import_light_probes=False,import_splines=False,landscape_lod=0,max_landscape_vertices=budget)
            objects=[o for o in set(bpy.data.objects)-before_budget if o.get('ue_geometry_source')=='LANDSCAPE_HEIGHTFIELD']
            assert not missing and len(objects)==sum(bool(e.get('Landscape')) for e in all_entries)
            assert sum(len(o.data.vertices) for o in objects)<=budget
    if args.save_blend:
        bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)
report=dict(game=args.game,backend='generic' if generic else cfg['bridgeProfile'],blender=bpy.app.version_string,
            components=len(results),vertices=sum(r['vertices'] for r in results),triangles=sum(r['triangles'] for r in results),
            maxWorldErrorMeters=max(r['worldErrorMeters'] for r in results),seconds=time.perf_counter()-timer,samples=results)
Path(args.report).parent.mkdir(parents=True,exist_ok=True);Path(args.report).write_text(json.dumps(report,indent=2))
print('LANDSCAPE_GAME_OK',json.dumps({k:v for k,v in report.items() if k!='samples'}))
