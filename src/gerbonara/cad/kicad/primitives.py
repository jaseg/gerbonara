
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


def kicad_arc_svg_flags(start, mid, end):
    """ (center, radius, sweep flag, large arc flag) of a KiCad start/mid/end arc as an SVG arc """
    (cx, cy), r, _ = kicad_mid_to_center_arc(mid, start, end)
    sweep = (mid.x - start.x)*(end.y - start.y) - (mid.y - start.y)*(end.x - start.x) > 0
    a1, a2 = math.atan2(start.y - cy, start.x - cx), math.atan2(end.y - cy, end.x - cx)
    span = (a2 - a1) % (2*math.pi) if sweep else (a1 - a2) % (2*math.pi)
    return (cx, cy), r, sweep, span > math.pi


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
    radius: Named(float) = 0.125
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
    pts: ArcPointList = field(default_factory=list)


@sexp_type('fill_segments')
class FillSegment:
    layer: Named(str) = ""
    pts: ArcPointList = field(default_factory=list)


@sexp_type('polygon')
class ZonePolygon:
    pts: ArcPointList = field(default_factory=list)


@sexp_type('placement')
class ZonePlacement:
    enabled: Named(YesNoAtom()) = False
    sheetname: Named(str) = ''


@sexp_type('teardrop')
class ZoneTeardropSpec:
    type: Named(AtomChoice(Atom.padvia, Atom.track_end)) = Atom.padvia


@sexp_type('attr')
class ZoneAttr:
    teardrop: ZoneTeardropSpec = None


@sexp_type('zone')
class Zone:
    locked: Flag() = False
    net: Named(int) = 0
    net_name: Named(str) = ""
    layer: Named(str) = None
    layers: Named(Array(str)) = None
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None
    name: Named(str) = None
    hatch: Hatch = None
    priority: OmitDefault(Named(int)) = 0
    attr: ZoneAttr = None
    connect_pads: PadConnection = field(default_factory=PadConnection)
    min_thickness: Named(float) = 0.254
    filled_areas_thickness: Named(YesNoAtom()) = True
    keepout: ZoneKeepout = None
    placement: ZonePlacement = None
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


@sexp_type('margins')
class Margins:
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@sexp_type('comment')
class TitleComment:
    number: int = 1
    text: str = ''


@sexp_type('title_block')
class TitleBlock:
    title: Named(str) = ''
    date: Named(str) = ''
    rev: Named(str) = ''
    company: Named(str) = ''
    comments: List(TitleComment) = field(default_factory=list)

    def __after_parse__(self, parent=None):
        comments = {c.number: c.text for c in self.comments}
        self.comments = [comments.get(i, '') for i in range(1, max(comments.keys() or [0])+1)]

    def __before_sexp__(self):
        self.comments = [TitleComment(i, s) for i, s in enumerate(self.comments, start=1) if s]

    @property
    def comments_joined(self):
        return '\n'.join(self.comments)

    @comments_joined.setter
    def comments_joined(self, value):
        self.comments = value.split('\n')


def lib_to_sheet_vector(dx, dy, rotation=0, mirror_x=False, mirror_y=False):
    """ Library symbol coordinates (y up) to sheet coordinates (y down), following rotation and mirroring """
    a = math.radians(rotation or 0)
    c, s = math.cos(a), math.sin(a)
    c, s = (round(c) if abs(c - round(c)) < 1e-9 else c), (round(s) if abs(s - round(s)) < 1e-9 else s)
    x, y = dx, -dy
    x, y = x*c + y*s, -x*s + y*c
    if mirror_x:
        y = -y
    elif mirror_y:
        x = -x
    return x, y


def sheet_to_lib_vector(dx, dy, rotation=0, mirror_x=False, mirror_y=False):
    # The inverse of lib_to_sheet_vector, whose matrix is orthogonal
    (a, b), (c, d) = (lib_to_sheet_vector(*v, rotation, mirror_x, mirror_y) for v in ((1, 0), (0, 1)))
    return a*dx + b*dy, c*dx + d*dy


def kicad_symbol_text_svg(text, size, x, y, rotation=0, h_align='center', v_align='middle', symbol_at=(0, 0),
                          symbol_rotation=0, mirror_x=False, mirror_y=False, **svg_attrs):
    """ Text at (x, y) in a placed symbol's library coordinates, drawn like KiCad draws symbol fields and texts """
    # KiCad lays the text's box out in the symbol's frame, transforms it with the symbol, and draws the text upright and
    # centered on the result.
    vec = lambda dx, dy: lib_to_sheet_vector(dx, -dy, symbol_rotation, mirror_x, mirror_y)
    (x1, y1), (x2, y2) = (vec(*p) for p in kicad_text_box(text, size, x, -y, rotation, h_align, v_align))
    vertical = (round(rotation or 0) % 180 == 90) != (round(symbol_rotation or 0) % 180 == 90)
    return kicad_text_svg(text, symbol_at[0] + (x1+x2)/2, symbol_at[1] + (y1+y2)/2, size, h_align='center',
                          v_align='middle', vertical=vertical, **svg_attrs)


@sexp_type('ellipse')
class Ellipse:
    center: Rename(XYCoord) = field(default_factory=XYCoord)
    major_radius: Named(float) = 0.0
    minor_radius: Named(float) = 0.0
    rotation_angle: Named(float) = 0.0

    def svg_path_d(self, segments=64):
        a, b = self.major_radius, self.minor_radius
        rot = math.radians(self.rotation_angle or 0)
        arc = hasattr(self, 'start_angle')
        t0, t1 = (math.radians(self.start_angle), math.radians(self.end_angle)) if arc else (0, 2*math.pi)
        if t1 <= t0:
            t1 += 2*math.pi
        pts = []
        for i in range(segments + 1):
            t = t0 + (t1 - t0) * i / segments
            x, y = a*math.cos(t), b*math.sin(t)
            x, y = x*math.cos(rot) - y*math.sin(rot), x*math.sin(rot) + y*math.cos(rot)
            # Angles run counter-clockwise on the sheet, whose y axis points down
            pts.append((self.center.x + x, self.center.y - y))
        d = 'M ' + ' L '.join(f'{x:.3f} {y:.3f}' for x, y in pts)
        return d if arc else d + ' Z'


@sexp_type('ellipse_arc')
class EllipseArc(Ellipse):
    start_angle: Named(float) = 0.0
    end_angle: Named(float) = 0.0
