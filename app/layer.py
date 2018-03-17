"""
This file is part of blender-osm (OpenStreetMap importer for Blender).
Copyright (C) 2014-2017 Vladimir Elistratov
prokitektura+support@gmail.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import math
import bmesh
from mathutils import Vector
from renderer import Renderer
from util.blender import createEmptyObject, getBmesh, setBmesh


class Layer:
    
    def __init__(self, layerId, app):
        self.app = app
        self.id = layerId
        terrain = app.terrain
        hasTerrain = bool(terrain)
        self.singleObject = app.singleObject
        # instance of BMesh
        self.bm = None
        # Blender object
        self.obj = None
        self.materialIndices = []
        # Blender parent object
        self.parent = None
        # does the layer represents an area (natural or landuse)
        self.area = True
        # apply Blender modifiers (BOOLEAND AND SHRINKWRAP) if a terrain is set
        self.modifiers = hasTerrain
        # slice flat mesh to project it on the terrain correctly
        self.sliceMesh = hasTerrain and app.sliceFlatLayers
        # set layer offsets <self.location>, <self.meshZ> and <self.parentLocation>
        # <self.location> is used for a Blender object
        # <self.meshZ> is used for vertices of a BMesh
        # <self.parentLocation> is used for an EMPTY Blender object serving
        # as a parent for Blender objects of the layer
        self.parentLocation = None
        meshZ = 0.
        _z = app.layerOffsets.get(layerId, 0.)
        if hasTerrain:
            # here we have <self.singleObject is True>
            location = Vector((0., 0., terrain.maxZ + terrain.layerOffset))
            self.swOffset = _z if _z else app.swOffset
            if not self.singleObject:
                # it's the only case when <self.parentLocation> is needed if a terrain is set
                self.parentLocation = Vector((0., 0., _z))
        elif self.singleObject:
            location = Vector((0., 0., _z))
        elif not self.singleObject:
            location = None
            # it's the only case when <self.parentLocation> is needed if a terrain is't set
            self.parentLocation = Vector((0., 0., _z))
        self.location = location
        self.meshZ = meshZ
        
    def getParent(self):
        # The method is called currently in the single place of the code:
        # in <Renderer.prerender(..)> if (not layer.singleObject)
        parent = self.parent
        if not self.parent:
            parent = createEmptyObject(
                self.name,
                self.parentLocation.copy(),
                empty_draw_size=0.01
            )
            parent.parent = Renderer.parent
            self.parent = parent
        return parent
    
    def prepare(self, instance):
        instance.bm = getBmesh(instance.obj)
        instance.materialIndices = {}
    
    @property
    def name(self):
        return "%s_%s" % (Renderer.name, self.id)
    
    def finalizeBlenderObject(self, obj):
        """
        Slice Blender MESH object, add modifiers
        """
        app = self.app
        terrain = app.terrain
        if terrain and self.sliceMesh:
            self.slice(obj, terrain, app)
        if self.modifiers:
            if not terrain.envelope:
                terrain.createEnvelope()
            self.addBoolenModifier(obj, terrain.envelope)
            self.addShrinkwrapModifier(obj, terrain.terrain, self.swOffset)
    
    def addShrinkwrapModifier(self, obj, target, offset):
        m = obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
        m.wrap_method = "PROJECT"
        m.use_positive_direction = False
        m.use_negative_direction = True
        m.use_project_z = True
        m.target = target
        m.offset = offset
    
    def addBoolenModifier(self, obj, operand):
        m = obj.modifiers.new(name="Boolean", type='BOOLEAN')
        m.object = operand
    
    def slice(self, obj, terrain, app):
        sliceSize = app.sliceSize
        bm = getBmesh(obj)
        
        def _slice(index, plane_no, terrainMin, terrainMax):
            # min and max value along the axis defined by <index>
            # 1) terrain
            # a simple conversion from the world coordinate system to the local one
            terrainMin = terrainMin - obj.location[index]
            terrainMax = terrainMax - obj.location[index]
            # 2) <bm>, i.e. Blender mesh
            minValue = min(obj.bound_box, key = lambda v: v[index])[index]
            maxValue = max(obj.bound_box, key = lambda v: v[index])[index]
            
            # cut everything off outside the terrain bounding box
            if minValue < terrainMin:
                minValue = terrainMin
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:]+bm.edges[:]+bm.faces[:],
                    plane_co=(0., minValue, 0.) if index else (minValue, 0., 0.),
                    plane_no=plane_no,
                    clear_inner=True
                )
            
            if maxValue > terrainMax:
                maxValue = terrainMax
                bmesh.ops.bisect_plane(
                    bm,
                    geom=bm.verts[:]+bm.edges[:]+bm.faces[:],
                    plane_co=(0., maxValue, 0.) if index else (maxValue, 0., 0.),
                    plane_no=plane_no,
                    clear_outer=True
                )
            
            # now cut the slices
            width = maxValue - minValue
            if width > sliceSize:
                numSlices = math.ceil(width/sliceSize)
                _sliceSize = width/numSlices
                coord = minValue
                sliceIndex = 1
                while sliceIndex < numSlices:
                    coord += _sliceSize
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=bm.verts[:]+bm.edges[:]+bm.faces[:],
                        plane_co=(0., coord, 0.) if index else (coord, 0., 0.),
                        plane_no=plane_no
                    )
                    sliceIndex += 1
        
        _slice(0, (1., 0., 0.), terrain.minX, terrain.maxX)
        _slice(1, (0., 1., 0.), terrain.minY, terrain.maxY)
        setBmesh(obj, bm)