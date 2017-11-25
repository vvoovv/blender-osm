import math, os
import numpy
from urllib import request
import bpy

from util.blender import getBmesh, setBmesh, appendMaterialsFromFile
from app import app


earthRadius = 6378137.
halfEquator = math.pi * earthRadius
equator = 2. * halfEquator

# a Python dictionary to replace prohibited characters in a file name
prohibitedCharacters = {
    ord('/'):'!',
    ord('\\'):'!',
    ord(':'):'!',
    ord('*'):'!',
    ord('?'):'!',
    ord('"'):'!',
    ord('<'):'!',
    ord('>'):'!',
    ord('|'):'!'
}


class Overlay:
    
    tileWidth = 256
    tileHeight = 256
        
    maxNumTiles = 256 # i.e. 4096x4096 pixels
    
    tileCoordsTemplate = "{z}/{x}/{y}"
    
    blenderImageName = "overlay"
    
    # the name for the base UV map
    uvName = "UVMap"
    
    # relative path to default materials
    materialPath = "realistic/assets/base.blend"
    
    # name of the default material from <Overlay.materialPath>
    defaultMaterial = "overlay"
    
    def __init__(self, url, maxZoom, addonName):
        self.maxZoom = maxZoom
        self.subdomains = None
        self.numSubdomains = 0
        self.tileCounter = 0
        self.numTiles = 0
        self.imageExtension = "png"
        
        # where to stop searching for sundomains {suddomain1,subdomain2}
        subdomainsEnd = len(url)
        # check if have {z}/{x}/{y} in <url> (i.e. tile coords)
        coordsPosition = url.find(self.tileCoordsTemplate)
        if coordsPosition > 0:
            subdomainsEnd = coordsPosition
            urlEnd = url[coordsPosition+len(self.tileCoordsTemplate):]
        else:
            if url[-1] != '/':
                url = url + '/'
            urlEnd = ".png"
        leftBracketPosition = url.find("{", 0, subdomainsEnd)
        rightBracketPosition = url.find("}", leftBracketPosition+2, subdomainsEnd)
        if leftBracketPosition > -1 and rightBracketPosition > -1:
            self.subdomains = tuple(
                s.strip() for s in url[leftBracketPosition+1:rightBracketPosition].split(',')
            )
            self.numSubdomains = len(self.subdomains)
            urlStart = url[:leftBracketPosition]
            urlMid = url[rightBracketPosition+1:coordsPosition]\
                if coordsPosition > 0 else\
                url[rightBracketPosition+1:]
        else:
            urlStart = url[rightBracketPosition+1:coordsPosition] if coordsPosition > 0 else url
            urlMid = None
        self.urlStart = urlStart
        self.urlMid = urlMid
        self.urlEnd = urlEnd
    
    def doImport(self, left, bottom, right, top):
        def toTileCoord(coord, zoom, tileSize=0):
            """
            An auxiliary method used in the code
            
            Returns:
            A single integer tile coordinate if <tileSize>==0.
            A Python tuple with two elements otherwise:
                0) a single integer tile coordinate
                1) number of pixels converted from the fractional part of the tile coordinate,
                    using <tileSize>
            """
            coord = coord * math.pow(2., zoom) / equator
            floor = math.floor(coord)
            return int(floor)
            #return ( int(floor), int(math.ceil((coord - floor) * tileSize)) )\
            #    if tileSize else\
            #    int(floor)
        
        def fromTileCoord(coord, zoom):
            return coord * equator / math.pow(2., zoom)
        
        # Convert the coordinates from degrees to spherical Mercator coordinate system
        # and move zero to the top left corner (that's why the 3d argument in the function below)
        b, l = Overlay.toSphericalMercator(bottom, left, True)
        t, r = Overlay.toSphericalMercator(top, right, True)
        # find the maximum zoom
        zoom = int(math.floor(
            0.5 * math.log2(
                self.maxNumTiles * equator * equator / (b-t) / (r-l)
            )
        ))
        if zoom >= self.maxZoom:
            zoom = self.maxZoom
        else:
            _zoom = zoom + 1
            while _zoom <= self.maxZoom:
                # convert <l>, <b>, <r>, <t> to tile coordinates
                _l, _b, _r, _t = tuple(toTileCoord(coord, _zoom) for coord in (l, b, r, t))
                if (_r - _l + 1) * (_b - _t + 1) > self.maxNumTiles:
                    break
                zoom = _zoom
                _zoom += 1
        
        # convert <l>, <b>, <r>, <t> to tile coordinates
        l, b, r, t = tuple(toTileCoord(coord, zoom, self.tileWidth) for coord in (l, b, r, t))
        numTilesX = r - l + 1
        numTilesY = b - t + 1
        self.numTiles = numTilesX * numTilesY
        # a numpy array for the resulting image stitched out of all tiles
        imageData = numpy.zeros(4*numTilesX*self.tileWidth * numTilesY*self.tileHeight)
        w = 4 * self.tileWidth
        # get individual tiles
        for x in range(l, r+1):
            for y in range(t, b+1):
                self.tileCounter += 1
                tileData = self.getTileData(zoom, x, y)
                if not tileData is None:
                    for _y in range(self.tileHeight):
                        i1 = w * ( (numTilesY-1-y+t) * self.tileHeight*numTilesX + _y*numTilesX + x-l )
                        imageData[i1:i1+w] = tileData[_y*w:(_y+1)*w]
        # create the resulting Blender image stitched out of all tiles
        image = bpy.data.images.new(
            self.blenderImageName,
            width = (r - l + 1) * self.tileWidth,
            height = (b - t + 1) * self.tileHeight
        )
        image.pixels = imageData
        # pack the image into .blend file
        image.pack(as_png=True)
        
        if app.terrain:
            self.setUvForTerrain(
                app.terrain.terrain,
                fromTileCoord(l, zoom) - halfEquator,
                halfEquator - fromTileCoord(b+1, zoom),
                fromTileCoord(r+1, zoom) - halfEquator,
                halfEquator - fromTileCoord(t, zoom)
            )
        # load and append the default material
        if app.setOverlayMaterial:
            materials = app.terrain.terrain.data.materials
            material = appendMaterialsFromFile(
                os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    os.pardir,
                    self.materialPath
                ),
                self.defaultMaterial
            )[0]
            material.node_tree.nodes["Image Texture"].image = image
            if materials:
                # ensure that <material> is placed at the very first material slot
                materials.append(None)
                materials[-1] = materials[0]
                materials[0] = material
            else:
                materials.append(material)
    
    def getTileData(self, zoom, x, y):
        # check if we the tile in the file cache
        j = os.path.join
        tileDir = j(self.overlayDir, str(zoom), str(x))
        tilePath = j(tileDir, "%s.%s" % (y, self.imageExtension))
        tileUrl = self.getTileUrl(zoom, x, y)
        if os.path.exists(tilePath):
            print(
                "Using the cached version of the tile image %s (%s of %s)" %
                (tileUrl, self.tileCounter, self.numTiles)
            )
        else:
            print(
                "Downloading the tile image %s (%s if %s)" %
                (tileUrl, self.tileCounter, self.numTiles)
            )
            try:
                tileData = request.urlopen(tileUrl).read()
            except:
                print("\tUnable to download the tile image %s" % tileUrl)
                return None
            # ensure that all directories in <tileDir> exist
            if not os.path.exists(tileDir):
                os.makedirs(tileDir)
            # save the tile to file cache
            with open(tilePath, 'wb') as f:
                f.write(tileData)
        # Create a temporary Blender image out of the tile image
        # to create a numpy array out of the image raw data
        tmpImage = bpy.data.images.load(tilePath)
        tileData = numpy.array(tmpImage.pixels)
        # delete the temporary Blender image
        bpy.data.images.remove(tmpImage, True)
        return tileData
        
    
    def getOverlaySubDir(self):
        urlStart = self.urlStart
        if urlStart[:7] == "http://":
            urlStart = urlStart[7:]
        elif urlStart[:8] == "https://":
            urlStart = urlStart[8:]
        urlStart = urlStart.translate(prohibitedCharacters)
        return\
            "%s%s%s" % (urlStart, ''.join(self.subdomains), self.urlMid[:-1].translate(prohibitedCharacters))\
            if self.subdomains else\
            urlStart
    
    def getTileUrl(self, zoom, x, y):
        if self.subdomains:
            url = "%s%s%s%s/%s/%s%s" % (
                self.urlStart,
                self.subdomains[self.tileCounter % self.numSubdomains],
                self.urlMid,
                zoom,
                x,
                y,
                self.urlEnd
            )
        else:
            url = "%s%s/%s/%s%s" % (
                self.urlStart,
                zoom,
                x,
                y,
                self.urlEnd
            )
        return url
    
    def setUvForTerrain(self, terrain, l, b, r, t):
        bm = getBmesh(terrain)
        uv = bm.loops.layers.uv
        
        uvName = self.uvName
        # create a data UV layer
        if not uvName in uv:
            uv.new(uvName)
        
        width = r - l
        height = t - b
        uvLayer = bm.loops.layers.uv[uvName]
        worldMatrix = terrain.matrix_world
        projection = app.projection
        for vert in bm.verts:
            for loop in vert.link_loops:
                x, y = (worldMatrix * vert.co)[:2]
                lat, lon = projection.toGeographic(x, y)
                lat, lon = Overlay.toSphericalMercator(lat, lon, False)
                loop[uvLayer].uv = (lon - l)/width, (lat - b)/height
        
        setBmesh(terrain, bm)
    
    @staticmethod
    def toSphericalMercator(lat, lon, moveToTopLeft=False):
        lat = earthRadius * math.log(math.tan(math.pi/4 + lat*math.pi/360))
        lon = earthRadius * lon * math.pi / 180
        # move zero to the top left corner
        if moveToTopLeft:
            lat = halfEquator - lat
            lon = lon + halfEquator
        return lat, lon


from .mapbox import Mapbox


overlayTypeData = {
    'mapbox-satellite': (Mapbox, "mapbox.satellite", 19),
    'osm-mapnik': (Overlay, "http://{a,b,c}.tile.openstreetmap.org", 19),
    'mapbox-streets': (Mapbox, "mapbox.streets", 19),
    'custom': (Overlay, '', 19)
}