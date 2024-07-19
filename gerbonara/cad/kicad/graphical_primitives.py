
import string
import math

from .sexp import *
from .base_types import *
from .primitives import *

from ... import graphic_objects as go
from ... import apertures as ap
from ...newstroke import Newstroke
from ...utils import rotate_point, MM, arc_bounds

@sexp_type('layer')
class TextLayer:
    layer: str = ''
    knockout: Flag() = False


@sexp_type('gr_text')
class Text(TextMixin, BBoxMixin):
    text: str = ''
    at: AtPos = field(default_factory=AtPos)
    layer: TextLayer = field(default_factory=TextLayer)
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None
    effects: TextEffect = field(default_factory=TextEffect)
    render_cache: RenderCache = None

    def offset(self, x=0, y=0):
        self.at = self.at.with_offset(x, y)


@sexp_type('gr_text_box')
class TextBox(BBoxMixin):
    locked: Flag() = False
    text: str = ''
    start: Named(XYCoord) = None
    end: Named(XYCoord) = None
    pts: PointList = field(default_factory=list)
    angle: OmitDefault(Named(float)) = 0.0
    layer: Named(str) = ""
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None
    effects: TextEffect = field(default_factory=TextEffect)
    stroke: Stroke = field(default_factory=Stroke)
    render_cache: RenderCache = None

    def render(self, variables={}):
        text = string.Template(self.text).safe_substitute(variables)
        if text != self.text:
            raise ValueError('Rendering of vector font text with variables not yet supported')

        if not render_cache or not render_cache.polygons:
            raise ValueError('Vector font text with empty render cache')

        for poly in render_cache.polygons:
            reg = go.Region([(p.x, -p.y) for p in poly.pts], unit=MM)

            if self.stroke:
                if self.stroke.type not in (None, Atom.default, Atom.solid):
                    raise ValueError('Dashed strokes are not supported on vector text')

                yield from reg.outline_objects(aperture=ap.CircleAperture(self.stroke.width, unit=MM))

            yield reg

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.end = self.end.with_offset(x, y)


@sexp_type('gr_line')
class Line(WidthMixin):
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    angle: Named(float) = None # wat
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    def rotate(self, angle, cx=None, cy=None):
        self.start.x, self.start.y = rotate_point(self.start.x, self.start.y, angle, cx, cy)
        self.end.x, self.end.y = rotate_point(self.end.x, self.end.y, angle, cx, cy)

    def render(self, variables=None):
        if self.angle:
            raise NotImplementedError('Angles on lines are not implemented. Please raise an issue and provide an example file.')

        dasher = Dasher(self)
        dasher.move(self.start.x, self.start.y)
        dasher.line(self.end.x, self.end.y)

        for x1, y1, x2, y2 in dasher:
            yield go.Line(x1, -y1, x2, -y2, aperture=ap.CircleAperture(dasher.width, unit=MM), unit=MM)
        # FIXME render all primitives using dasher, maybe share code w/ fp_ prefix primitives

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.end = self.end.with_offset(x, y)

    def bounding_box(self, unit=MM):
        x_min, x_max = min(self.start.x, self.end.x), max(self.start.x, self.end.x)
        y_min, y_max = min(self.start.y, self.end.y), max(self.start.y, self.end.y)
        w = self.stroke.width if self.stroke else self.width
        return (x_min-w, y_max-w), (x_max+w, y_max+w)


@sexp_type('fill')
class FillMode:
    # Needed for compatibility with weird files
    fill: AtomChoice(Atom.solid, Atom.yes, Atom.no, Atom.none) = False

    @classmethod
    def __map__(kls, obj, parent=None):
        return obj[1] in (Atom.solid, Atom.yes)

    @classmethod
    def __sexp__(kls, value):
        yield [Atom.fill, Atom.solid if value else Atom.none]

@sexp_type('gr_rect')
class Rectangle(BBoxMixin, WidthMixin):
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: FillMode = False
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    def render(self, variables=None):
        rect = go.Region.from_rectangle(self.start.x, -self.start.y,
                                       self.end.x-self.start.x, -(self.end.y-self.start.y),
                                       unit=MM)

        if self.fill:
            yield rect

        if (w := self.stroke.width if self.stroke else self.width):
            # FIXME stroke support
            yield from rect.outline_objects(aperture=ap.CircleAperture(w, unit=MM))

    @property
    def top_left(self):
        return ((min(self.start.x, self.end.x), min(self.start.y, self.end.y)),
                (max(self.start.x, self.end.x), max(self.start.y, self.end.y)))

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.end = self.end.with_offset(x, y)


@sexp_type('gr_circle')
class Circle(BBoxMixin, WidthMixin):
    center: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: FillMode = False
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    def render(self, variables=None):
        r = math.dist((self.center.x, -self.center.y), (self.end.x, -self.end.y))
        w = self.stroke.width if self.stroke else self.width
        aperture = ap.CircleAperture(w or 0, unit=MM)
        arc = go.Arc.from_circle(self.center.x, -self.center.y, r, aperture=aperture, unit=MM)

        if w:
            # FIXME stroke support
            yield arc

        if self.fill:
            yield arc.to_region()

    def offset(self, x=0, y=0):
        self.center = self.center.with_offset(x, y)
        self.end = self.end.with_offset(x, y)

    def rotate(self, angle, cx=0, cy=0):
        self.center = self.center.with_rotation(angle, cx, cy)
        self.end = self.end.with_rotation(angle, cx, cy)


@sexp_type('gr_arc')
class Arc(WidthMixin, BBoxMixin):
    start: Rename(XYCoord) = None
    mid: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None
    _: SEXP_END = None
    center: XYCoord = None

    def __post_init__(self):
        self.start = XYCoord(self.start)
        self.end = XYCoord(self.end)
        if self.mid or self.center is None:
            self.mid = XYCoord(self.mid)
        elif self.center:
            self.mid = center_arc_to_kicad_mid(XYCoord(self.center), self.start, self.end)
            self.center = None

    def render(self, variables=None):
        if not (w := self.stroke.width if self.stroke else self.width):
            return

        aperture = ap.CircleAperture(w, unit=MM)
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        (cx, cy), _r, clockwise = kicad_mid_to_center_arc(self.mid, self.start, self.end)
        yield go.Arc(x1, -y1, x2, -y2, cx-x1, -(cy-y1), aperture=aperture, clockwise=not clockwise, unit=MM)

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.mid = self.mid.with_offset(x, y)
        self.end = self.end.with_offset(x, y)

    def rotate(self, angle, cx=None, cy=None):
        self.start.x, self.start.y = rotate_point(self.start.x, self.start.y, angle, cx, cy)
        self.mid.x, self.mid.y = rotate_point(self.mid.x, self.mid.y, angle, cx, cy)
        self.end.x, self.end.y = rotate_point(self.end.x, self.end.y, angle, cx, cy)


@sexp_type('gr_poly')
class Polygon(BBoxMixin, WidthMixin):
    pts: ArcPointList = field(default_factory=list)
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: FillMode = True
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    def render(self, variables=None):
        points = []
        centers = []
        for point_or_arc in self.pts:
            if points:
                centers.append((None, (None, None)))

            if isinstance(point_or_arc, XYCoord):
                points.append((point_or_arc.x, -point_or_arc.y))

            else: # base_types.Arc
                points.append((point_or_arc.start.x, -point_or_arc.start.y))
                points.append((point_or_arc.end.x, -point_or_arc.end.y))
                (cx, cy), _r, clockwise = kicad_mid_to_center_arc(point_or_arc.mid, point_or_arc.start, point_or_arc.end)
                centers.append((not clockwise, (cx, -cy)))

        reg = go.Region(points, centers, unit=MM)
        reg.close()
        
        w = self.stroke.width if self.stroke else self.width
        # FIXME stroke support
        if w and w >= 0.005:
            yield from reg.outline_objects(aperture=ap.CircleAperture(w, unit=MM))

        if self.fill:
            yield reg

    def offset(self, x=0, y=0):
        self.pts = [pt.with_offset(x, y) for pt in self.pts]

    def rotate(self, angle, cx=0, cy=0):
        self.pts = [pt.with_rotation(angle, cx, cy) for pt in self.pts]


@sexp_type('gr_curve')
class Curve(BBoxMixin, WidthMixin):
    pts: PointList = field(default_factory=list)
    layer: Named(str) = None
    width: Named(float) = None
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    def render(self, variables=None):
        raise NotImplementedError('Bezier rendering is not yet supported. Please raise an issue and provide an example file.')

    def offset(self, x=0, y=0):
        self.pts =[pt.with_offset(x, y) for pt in self.pts]


@sexp_type('gr_bbox')
class AnnotationBBox:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
 
    def render(self, variables=None):
        return []

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.end = self.end.with_offset(x, y)


@sexp_type('format')
class DimensionFormat:
    prefix: Named(str) = None
    suffix: Named(str) = None
    units: Named(int) = 2
    units_format: Named(int) = 1
    precision: Named(int) = 7
    override_value: Named(str) = None
    suppress_zeros: Flag() = False
    

@sexp_type('style')
class DimensionStyle:
    thickness: Named(float) = 0.1
    arrow_length: Named(float) = 1.27
    text_position_mode: Named(int) = 0
    extension_height: Named(float) = None
    text_frame: Named(float) = None
    extension_offset: Named(float) = None
    keep_text_aligned: Flag() = False


@sexp_type('image')
class Image:
    at: AtPos = field(default_factory=AtPos)
    scale: Named(float) = None
    layer: Named(str) = None
    uuid: UUID = field(default_factory=UUID)
    data: str = ''

    def offset(self, x=0, y=0):
        self.at = self.at.with_offset(x, y)


@sexp_type('dimension')
class Dimension:
    locked: Flag() = False
    dimension_type: Named(AtomChoice(Atom.aligned, Atom.leader, Atom.center, Atom.orthogonal, Atom.radial), name='type') = Atom.aligned
    layer: Named(str) = 'Dwgs.User'
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = field(default_factory=Timestamp)
    pts: PointList = field(default_factory=list)
    height: Named(float) = None
    orientation: Named(int) = None
    leader_length: Named(float) = None
    gr_text: Text = None
    dimension_format: OmitDefault(DimensionFormat) = field(default_factory=DimensionFormat)
    dimension_style: OmitDefault(DimensionStyle) = field(default_factory=DimensionStyle)
 
    def render(self, variables=None):
        raise NotImplementedError('Dimension rendering is not yet supported. Please raise an issue.')

    def offset(self, x=0, y=0):
        self.pts = [pt.with_offset(x, y) for pt in self.pts]

