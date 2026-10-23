"""Terrain topology, attachment, masks, budget and transport regression checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import addon
addon.register()
from addon.formats.ue_map import landscapes, map_import

q=6
yy,xx=np.indices((q+1,q+1),dtype=np.float32)
positions=np.column_stack((xx.ravel()+.25,yy.ravel()-.125,(xx+yy).ravel()/8))
holes=np.zeros((q,q),dtype=np.uint8);holes[2,3]=1
payload=dict(quads=q,sourceQuads=q,lod=0,vertexCount=49,triangleCount=70,holeQuads=1,
             positions=positions,normals=np.tile((0,0,1),(49,1)).astype(np.float32),holes=holes,
             layers=[dict(name=f'Layer{i}',path=f'/Game/Layer{i}',noWeightBlend=i==5) for i in range(6)],
             sectionBase=[100,200],objectPath='/Game/Terrain.Terrain:PersistentLevel.Actor.Patch',
             xyOffsets=True,heightmap='/Game/Height.Height',holePolicy='UE4_STATIC_EXPORT',materials=['/Game/TerrainMat'])
payload.update({f'paint{i}':np.full(49,i*40,dtype=np.uint8) for i in range(6)})
info=dict(sourceMap='/Game/Terrain.umap',objectPath=payload['objectPath'],quads=q,subsectionQuads=3,subsections=2,sectionBase=[100,200])
ref=lambda s:dict(ObjectPath=s,ObjectName=f"Object'{s}'")
entries=[dict(Type='LandscapeComponent',Name='Patch',Outer=ref('/Game/Terrain.Terrain:PersistentLevel.Actor'),Landscape=info,
              Properties=dict(RelativeLocation=dict(X=4,Y=-5,Z=6),AttachParent=ref('/Game/Terrain.Terrain:PersistentLevel.Actor.Root'))),
         dict(Type='SceneComponent',Name='Root',Outer=ref('/Game/Terrain.Terrain:PersistentLevel.Actor'),AttachmentParentOnly=True,
              Properties=dict(RelativeLocation=dict(X=1000,Y=2000,Z=3000),RelativeRotation=dict(Yaw=90),RelativeScale3D=dict(X=2,Y=3,Z=1),AttachParent=ref('/Game/Terrain.Terrain:PersistentLevel.Actor.GrandRoot'))),
         dict(Type='SceneComponent',Name='GrandRoot',Outer=ref('/Game/Terrain.Terrain:PersistentLevel.Actor'),AttachmentParentOnly=True,Properties=dict(RelativeLocation=dict(X=100)))]

class Session:
    calls=0
    def landscape_mesh(self,meta,lod):
        assert meta==info and lod==0
        self.calls+=1
        return payload

session=Session()
for title in [False,True]:
    col=bpy.data.collections.new(f'Terrain fixture {title}');bpy.context.scene.collection.children.link(col)
    count,missing=map_import.import_map_entries(entries,'Terrain.umap',1,1,game_features=title,
        target_collection=col,import_lights=False,import_splines=False,import_reflection_probes=False,
        light_texture_loader=session,landscape_lod=0,max_landscape_vertices=0,landscape_layer_preview=True)
    assert count==3 and not missing,(count,missing)
    obj=next(o for o in col.all_objects if o.type=='MESH');mesh=obj.data
    assert len(mesh.vertices)==49 and len(mesh.polygons)==70 and len(mesh.uv_layers)==2
    assert len(json.loads(mesh['ue_landscape_layers']))==6 and mesh['ue_geometry_source']=='LANDSCAPE_HEIGHTFIELD'
    assert mesh.materials[0]['ue_landscape_material_mode']=='LAYER_PREVIEW'
    assert obj.parent and obj.parent.name!='Terrain.umap'
    bpy.context.view_layer.update()
    for i in [0,1,7,48]:
        x,y,z=positions[i]
        expected=np.array((1100-3*(y-5),-(2000+2*(x+4)),3000+z+6))*.01
        actual=np.array(obj.matrix_world@mesh.vertices[i].co)
        assert np.max(np.abs(expected-actual))<2e-5,(title,i,actual,expected)
    for i in range(6):
        values=np.empty(49,dtype=np.float32);mesh.attributes[f'ue_landscape_weight_{i:03}'].data.foreach_get('value',values)
        assert np.array_equal(values,payload[f'paint{i}'].astype(np.float32)/255)
    assert not mesh.validate(clean_customdata=False)
    # The selected face diagonal and mirrored Y must face up on regular terrain.
    assert all(p.normal.z>0 for p in mesh.polygons)

assert landscapes.plan_lod(entries,0,25)==(1,9)
assert landscapes.plan_lod(entries,0,0)==(0,49)
try:landscapes.plan_lod(entries,0,8)
except ValueError:pass
else:raise AssertionError('Budget smaller than minimum grid accepted')
calls=session.calls
for options in [dict(import_landscapes=False),dict(import_models=False)]:
    map_import.import_map_entries(entries,'DisabledTerrain',1,1,import_lights=False,
        import_reflection_probes=False,light_texture_loader=session,**options)
    assert session.calls==calls

empty=deepcopy(payload);empty['holes']=np.ones((q,q),dtype=np.uint8);empty['holeQuads']=q*q;empty['triangleCount']=0
col=bpy.data.collections.new('All-hole terrain');bpy.context.scene.collection.children.link(col)
obj=landscapes.create_terrain('Empty terrain',empty,col)
assert len(obj.data.vertices)==49 and not obj.data.polygons

with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);directory=root/'landscape-fixture';directory.mkdir()
    streams={}
    for name in ['positions','normals','holes',*(f'paint{i}' for i in range(6))]:
        array=payload[name];file=directory/(name+'.bin');array.tofile(file)
        streams[name]=dict(dtype=array.dtype.str,shape=list(array.shape),file=file.name)
    manifest={k:v for k,v in payload.items() if not isinstance(v,np.ndarray)}
    manifest['binaryLandscape']=dict(version=1,directory=str(directory),streams=streams)
    result=landscapes.load_landscape(manifest,root)
    assert np.array_equal(result['positions'],positions)
    for bad in ['path','shape','missing','nonfinite','truncated','holes']:
        altered=deepcopy(manifest)
        if bad=='path':altered['binaryLandscape']['streams']['positions']['file']='../outside.bin'
        if bad=='shape':altered['binaryLandscape']['streams']['positions']['shape']=[1,3]
        if bad=='missing':del altered['binaryLandscape']['streams']['paint5']
        if bad=='nonfinite':
            broken=positions.copy();broken[0,0]=np.nan;broken.tofile(directory/'positions.bin')
        if bad=='truncated':(directory/'positions.bin').write_bytes(b'\0'*4)
        if bad=='holes':altered['triangleCount']=72
        try:landscapes.load_landscape(altered,root)
        except (ValueError,FileNotFoundError):pass
        else:raise AssertionError('Invalid transport accepted: '+bad)
        positions.tofile(directory/'positions.bin')
print('LANDSCAPE_FIXTURE_OK: generic and SQEX placement, 6 layers, holes, LOD/budgets, disabled imports, all-hole meshes, malformed streams')
