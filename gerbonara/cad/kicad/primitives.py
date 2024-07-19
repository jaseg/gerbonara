
import enum
import math
import re

from .sexp import *
from .base_types import *


def unfuck_layers(layers):
    if layers and layers[0] == 'F&B.Cu':
        return ['F.Cu', 'B.Cu', *layers[1:]]
    else:
        return layers


def fuck_layers(layers):
    if layers and 'F.Cu' in layers and 'B.Cu' in layers and not any(re.match(r'^In[0-9]+\.Cu$', l) for l in layers):
        return ['F&B.Cu', *(l for l in layers if l not in ('F.Cu', 'B.Cu'))]
    else:
        return layers


def layer_mask(layers):
    if isinstance(layers, int):
        return layers

    if isinstance(layers, str):
        layers = [l.strip() for l in layers.split(',')]

    mask = 0
    for layer in layers:
        match layer:
            case '*.Cu':
                return 0xffffffff
            case 'F.Cu':
                mask |= 1<<0
            case 'B.Cu':
                mask |= 1<<31
            case _:
                if (m := re.match(fr'In([0-9]+)\.Cu', layer)):
                    mask |= 1<<int(m.group(1))
    return mask


def center_arc_to_kicad_mid(center, start, end):
    # Convert normal p1/p2/center notation to the insanity that is kicad's midpoint notation
    cx, cy = center.x, center.y
    x1, y1 = start.x - cx, start.y - cy
    x2, y2 = end.x - cx, end.y - cy
    # Get a vector pointing from the center to the "mid" point.
    dx, dy = x1 - x2, y1 - y2 # Get a vector pointing from "end" to "start"
    dx, dy = -dy, dx # rotate by 90 degrees counter-clockwise
    # normalize vector, and multiply by radius to get final point
    r = math.hypot(x1, y1)
    l = math.hypot(dx, dy)
    mx = cx + dx / l * r
    my = cy + dy / l * r
    return XYCoord(mx, my)


def kicad_mid_to_center_arc(mid, start, end):
    """ Convert kicad's slightly insane midpoint notation to standrad center/p1/p2 notation.

    returns a ((center_x, center_y), radius, clockwise) tuple in KiCad coordinates.

    Returns the center and radius of the circle passing the given 3 points.
    In case the 3 points form a line, raises a ValueError.
    """
    # https://stackoverflow.com/questions/28910718/give-3-points-and-a-plot-circle
    p1, p2, p3 = start, mid, end

    temp = p2[0] * p2[0] + p2[1] * p2[1]
    bc = (p1[0] * p1[0] + p1[1] * p1[1] - temp) / 2
    cd = (temp - p3[0] * p3[0] - p3[1] * p3[1]) / 2
    det = (p1[0] - p2[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p2[1])

    if abs(det) < 1.0e-6:
        raise ValueError()

    # Center of circle
    cx = (bc*(p2[1] - p3[1]) - cd*(p1[1] - p2[1])) / det
    cy = ((p1[0] - p2[0]) * cd - (p2[0] - p3[0]) * bc) / det

    radius = math.sqrt((cx - p1[0])**2 + (cy - p1[1])**2)
    return (cx, cy), radius, det < 0


@sexp_type('hatch')
class Hatch:
    style: AtomChoice(Atom.none, Atom.edge, Atom.full) = Atom.edge
    pitch: float = 0.5


@sexp_type('connect_pads')
class PadConnection:
    type: AtomChoice(Atom.yes, Atom.thru_hole_only, Atom.full, Atom.no) = None
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
    mode: Named(Flag(atom=Atom.hatch)) = False
    thermal_gap: Named(float) = 0.508
    thermal_bridge_width: Named(float) = 0.508
    smoothing: ZoneSmoothing = None
    island_removal_mode: Named(int) = None
    island_area_min: Named(float) = None
    hatch_thickness: Named(float) = None
    hatch_gap: Named(float) = None
    hatch_orientation: Named(int) = None
    hatch_smoothing_level: Named(int) = None
    hatch_smoothing_value: Named(float) = None
    hatch_border_algorithm: Named(AtomChoice(Atom.hatch_thickness, Atom.min_thickness)) = None
    hatch_min_hole_area: Named(float) = None


@sexp_type('filled_polygon')
class FillPolygon:
    layer: Named(str) = ""
    island: Wrap(Flag()) = False
    pts: PointList = field(default_factory=list)


@sexp_type('fill_segments')
class FillSegment:
    layer: Named(str) = ""
    pts: PointList = field(default_factory=list)


@sexp_type('polygon')
class ZonePolygon:
    pts: PointList = field(default_factory=list)


@sexp_type('zone')
class Zone:
    net: Named(int) = 0
    net_name: Named(str) = ""
    layer: Named(str) = None
    layers: Named(Array(str)) = None
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None
    name: Named(str) = None
    hatch: Hatch = None
    priority: OmitDefault(Named(int)) = 0
    connect_pads: PadConnection = field(default_factory=PadConnection)
    min_thickness: Named(float) = 0.254
    filled_areas_thickness: Named(YesNoAtom()) = True
    keepout: ZoneKeepout = None
    fill: ZoneFill = field(default_factory=ZoneFill)
    polygon: ZonePolygon = field(default_factory=ZonePolygon)
    fill_polygons: List(FillPolygon) = field(default_factory=list)
    fill_segments: List(FillSegment) = field(default_factory=list)

    def __after_parse__(self, parent=None):
        self.layers = unfuck_layers(self.layers)

    def __before_sexp__(self):
        self.layers = fuck_layers(self.layers)

    def unfill(self):
        self.fill.yes = False
        self.fill_polygons = []
        self.fill_segments = []

    def rotate(self, angle, cx=None, cy=None):
        self.unfill()
        self.polygon.pts = [pt.with_rotation(angle, cx, cy) for pt in self.polygon.pts]

    def offset(self, x=0, y=0):
        self.unfill()
        self.polygon.pts = [pt.with_offset(x, y) for pt in self.polygon.pts]


    def bounding_box(self):
        min_x = min(pt.x for pt in self.polygon.pts)
        min_y = min(pt.y for pt in self.polygon.pts)
        max_x = max(pt.x for pt in self.polygon.pts)
        max_y = max(pt.y for pt in self.polygon.pts)
        return (min_x, min_y), (max_x, max_y)


@sexp_type('polygon')
class RenderCachePolygon:
    pts: PointList = field(default_factory=list)


@sexp_type('render_cache')
class RenderCache:
    text: str = None
    rotation: int = 0
    polygons: List(RenderCachePolygon) = field(default_factory=list)



