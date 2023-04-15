
import enum

from .sexp import *
from .base_types import *


@sexp_type('hatch')
class Hatch:
    style: AtomChoice(Atom.none, Atom.edge, Atom.full) = Atom.edge
    pitch: float = 0.5


@sexp_type('connect_pads')
class PadConnection:
    type: AtomChoice(Atom.thru_hole_only, Atom.full, Atom.no) = None
    clearance: Named(float) = 0


@sexp_type('keepout')
class ZoneKeepout:
    tracks_allowed:     Named(YesNoAtom(yes=Atom.allowed, no=Atom.not_allowed), name='tracks')       = True
    vias_allowed:       Named(YesNoAtom(yes=Atom.allowed, no=Atom.not_allowed), name='vias')         = True
    pads_allowed:       Named(YesNoAtom(yes=Atom.allowed, no=Atom.not_allowed), name='pads')         = True
    copperpour_allowed: Named(YesNoAtom(yes=Atom.allowed, no=Atom.not_allowed), name='copperpour')   = True
    footprints_allowed: Named(YesNoAtom(yes=Atom.allowed, no=Atom.not_allowed), name='footprints')   = True


@sexp_type('smoothing')
class ZoneSmoothing:
    style: AtomChoice(Atom.chamfer, Atom.fillet) = Atom.chamfer
    radius: Named(float) = None


@sexp_type('fill')
class ZoneFill:
    yes: Flag() = False
    mode: Flag(atom=Atom.hatched) = False
    thermal_gap: Named(float) = 0.508
    thermal_bridge_width: Named(float) = 0.508
    smoothing: ZoneSmoothing = None
    island_removal_node: Named(int) = None
    islan_area_min: Named(float) = None
    hatch_thickness: Named(float) = None
    hatch_gap: Named(float) = None
    hatch_orientation: Named(int) = None
    hatch_smoothing_level: Named(int) = None
    hatch_smoothing_value: Named(float) = None
    hatch_border_algorithm: Named(int) = None
    hatch_min_hole_area: Named(float) = None


@sexp_type('filled_polygon')
class FillPolygon:
    layer: Named(str) = ""
    pts: PointList = field(default_factory=PointList)


@sexp_type('fill_segments')
class FillSegment:
    layer: Named(str) = ""
    pts: PointList = field(default_factory=PointList)


@sexp_type('zone')
class Zone:
    net: Named(int) = 0
    net_name: Named(str) = ""
    layer: Named(str) = None
    layers: Named(Array(str)) = None
    tstamp: Timestamp = None
    name: Named(str) = None
    hatch: Hatch = None
    priority: OmitDefault(Named(int)) = 0
    connect_pads: PadConnection = field(default_factory=PadConnection)
    min_thickness: Named(float) = 0.254
    filled_areas_thickness: Flag() = True
    keepouts: List(ZoneKeepout) = field(default_factory=list)
    fill: ZoneFill = field(default_factory=ZoneFill)
    polygon: Named(PointList) = field(default_factory=PointList)
    fill_polygons: List(FillPolygon) = field(default_factory=list)
    fill_segments: List(FillSegment) = field(default_factory=list)


@sexp_type('polygon')
class RenderCachePolygon:
    pts: PointList = field(default_factory=PointList)


@sexp_type('render_cache')
class RenderCache:
    text: str = None
    rotation: int = 0
    polygons: List(RenderCachePolygon) = field(default_factory=list)



