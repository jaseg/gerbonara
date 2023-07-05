
import string
import math

from .sexp import *
from .base_types import *
from .primitives import *

from ... import graphic_objects as go
from ... import apertures as ap
from ...newstroke import Newstroke
from ...utils import rotate_point, MM

@sexp_type('layer')
class TextLayer:
    layer: str = ''
    knockout: Flag() = False


@sexp_type('gr_text')
class Text:
    text: str = ''
    at: AtPos = field(default_factory=AtPos)
    layer: TextLayer = field(default_factory=TextLayer)
    tstamp: Timestamp = None
    effects: TextEffect = field(default_factory=TextEffect)
    render_cache: RenderCache = None

    def render(self, variables={}):
        if not self.effects or self.effects.hide or not self.effects.font:
            return

        font = Newstroke.load()
        line_width = self.effects.font.thickness
        text = string.Template(self.text).safe_substitute(variables)
        strokes = list(font.render(text, size=self.effects.font.size.y))
        min_x = min(x for st in strokes for x, y in st)
        min_y = min(y for st in strokes for x, y in st)
        max_x = max(x for st in strokes for x, y in st)
        max_y = max(y for st in strokes for x, y in st)
        w = max_x - min_x
        h = max_y - min_y

        offx = -min_x + {
                None: -w/2,
                Atom.right: -w,
                Atom.left: 0
                }[self.effects.justify.h if self.effects.justify else None]

        offy = {
                None: self.effects.font.size.y/2,
                Atom.top: self.effects.font.size.y,
                Atom.bottom: 0
                }[self.effects.justify.v if self.effects.justify else None]

        aperture = ap.CircleAperture(line_width or 0.2, unit=MM)
        for stroke in strokes:
            out = []

            for x, y in stroke:
                x, y = x+offx, y+offy
                x, y = rotate_point(x, y, math.radians(self.at.rotation or 0))
                x, y = x+self.at.x, y+self.at.y
                out.append((x, y))

            for p1, p2 in zip(out[:-1], out[1:]):
                yield go.Line(*p1, *p2, aperture=aperture, unit=MM)


@sexp_type('gr_text_box')
class TextBox:
    locked: Flag() = False
    text: str = ''
    start: Named(XYCoord) = None
    end: Named(XYCoord) = None
    pts: PointList = field(default_factory=PointList)
    angle: OmitDefault(Named(float)) = 0.0
    layer: Named(str) = ""
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
            reg = go.Region([(p.x, p.y) for p in poly.pts.xy], unit=MM)

            if self.stroke:
                if self.stroke.type not in (None, Atom.default, Atom.solid):
                    raise ValueError('Dashed strokes are not supported on vector text')

                yield from reg.outline_objects(aperture=ap.CircleAperture(self.stroke.width, unit=MM))

            yield reg


@sexp_type('gr_line')
class Line:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    angle: Named(float) = None # wat
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    tstamp: Timestamp = None

    def render(self, variables=None):
        if self.angle:
            raise NotImplementedError('Angles on lines are not implemented. Please raise an issue and provide an example file.')

        dasher = Dasher(self)
        dasher.move(self.start.x, self.start.y)
        dasher.line(self.end.x, self.end.y)

        for x1, y1, x2, y2 in dasher:
            yield go.Line(x1, y1, x2, y2, aperture=ap.CircleAperture(dasher.width, unit=MM), unit=MM)
        # FIXME render all primitives using dasher, maybe share code w/ fp_ prefix primitives


@sexp_type('fill')
class FillMode:
    # Needed for compatibility with weird files
    fill: AtomChoice(Atom.solid, Atom.yes, Atom.no, Atom.none) = False

    @classmethod
    def __map__(self, obj, parent=None):
        return obj[1] in (Atom.solid, Atom.yes)

    @classmethod
    def __sexp__(self, value):
        yield [Atom.fill, Atom.solid if value else Atom.none]

@sexp_type('gr_rect')
class Rectangle:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: FillMode = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        rect = go.Region.from_rectangle(self.start.x, self.start.y,
                                       self.end.x-self.start.x, self.end.y-self.start.y,
                                       unit=MM)

        if self.fill:
            yield rect

        if self.width:
            # FIXME stroke support
            yield from rect.outline_objects(aperture=ap.CircleAperture(self.width, unit=MM))


@sexp_type('gr_circle')
class Circle:
    center: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: FillMode = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        r = math.dist((self.center.x, self.center.y), (self.end.x, self.end.y))
        aperture = ap.CircleAperture(self.width or 0, unit=MM)
        arc = go.Arc.from_circle(self.center.x, self.center.y, r, aperture=aperture, unit=MM)

        if self.width:
            # FIXME stroke support
            yield arc

        if self.fill:
            yield arc.to_region()


@sexp_type('gr_arc')
class Arc:
    start: Rename(XYCoord) = None
    mid: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    tstamp: Timestamp = None

    def render(self, variables=None):
        # FIXME stroke support
        if not self.width:
            return

        aperture = ap.CircleAperture(self.width, unit=MM)
        cx, cy = self.mid.x, self.mid.y
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        yield go.Arc(x1, y1, x2, y2, cx-x1, cy-y1, aperture=aperture, clockwise=True, unit=MM)


@sexp_type('gr_poly')
class Polygon:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: FillMode = True
    tstamp: Timestamp = None

    def render(self, variables=None):
        reg = go.Region([(pt.x, pt.y) for pt in self.pts.xy], unit=MM)
        
        # FIXME stroke support
        if self.width and self.width >= 0.005 or self.stroke.width and self.stroke.width > 0.005:
            yield from reg.outline_objects(aperture=ap.CircleAperture(self.width, unit=MM))

        if self.fill:
            yield reg


@sexp_type('gr_curve')
class Curve:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    tstamp: Timestamp = None

    def render(self, variables=None):
        raise NotImplementedError('Bezier rendering is not yet supported. Please raise an issue and provide an example file.')


@sexp_type('gr_bbox')
class AnnotationBBox:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
 
    def render(self, variables=None):
        return []


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


@sexp_type('dimension')
class Dimension:
    locked: Flag() = False
    dimension_type: Named(AtomChoice(Atom.aligned, Atom.leader, Atom.center, Atom.orthogonal, Atom.radial), name='type') = Atom.aligned
    layer: Named(str) = 'Dwgs.User'
    tstamp: Timestamp = field(default_factory=Timestamp)
    pts: Named(Array(XYCoord)) = field(default_factory=list)
    height: Named(float) = None
    orientation: Named(int) = None
    leader_length: Named(float) = None
    gr_text: Text = None
    dimension_format: OmitDefault(DimensionFormat) = field(default_factory=DimensionFormat)
    dimension_style: OmitDefault(DimensionStyle) = field(default_factory=DimensionStyle)
 
    def render(self, variables=None):
        raise NotImplementedError('Dimension rendering is not yet supported. Please raise an issue.')


