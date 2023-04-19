
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

    def render(self):
        if not self.effects or self.effects.hide or not self.effects.font:
            return

        font = Newstroke.load()
        strokes = list(font.render(self.text, size=self.effects.font.size.y))
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
                None: -h/2,
                Atom.top: -h,
                Atom.bottom: 0
                }[self.effects.justify.v if self.effects.justify else None]

        aperture = ap.CircleAperture(self.effects.font.width or 0.2, unit=MM)
        for stroke in strokes:
            out = []
            for point in stroke:
                x, y = rotate_point(x, y, math.radians(self.at.rotation or 0))
                x, y = x+offx, y+offy
                out.append((x, y))
            for p1, p2 in zip(out[:-1], out[1:]):
                yield go.Line(*p1, *p2, aperture=ap, unit=MM)


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

    def render(self):
        if not render_cache or not render_cache.polygons:
            raise ValueError('Text box with empty render cache')

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
    tstamp: Timestamp = None

    def render(self):
        if self.angle:
            raise NotImplementedError('Angles on lines are not implemented. Please raise an issue and provide an example file.')

        ap = ap.CircleAperture(self.width, unit=MM)
        return go.Line(self.start.x, self.start.y, self.end.x, self.end.y, aperture=ap, unit=MM)


@sexp_type('fill')
class FillMode:
    # Needed for compatibility with weird files
    fill: AtomChoice(Atom.solid, Atom.yes, Atom.no, Atom.none) = False

    @classmethod
    def __map__(self, obj, parent=None):
        return obj[0] in (Atom.solid, Atom.yes)

    @classmethod
    def __sexp__(self, value):
        yield [Atom.fill, Atom.solid if value else Atom.none]

@sexp_type('gr_rect')
class Rectangle:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    fill: FillMode = False
    tstamp: Timestamp = None

    def render(self):
        rect = go.Region.from_rectangle(self.start.x, self.start.y,
                                       self.end.x-self.start.x, self.end.y-self.start.y,
                                       unit=MM)

        if self.fill:
            yield rect

        if self.width:
            yield from rect.outline_objects(aperture=ap.CircleAperture(self.width, unit=MM))


@sexp_type('gr_circle')
class Circle:
    center: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    fill: FillMode = False
    tstamp: Timestamp = None

    def render(self):
        r = math.dist((self.center.x, self.center.y), (self.end.x, self.end.y))
        arc = go.Arc.from_circle(self.center.x, self.center.y, r, unit=MM)

        if self.width:
            arc.aperture = ap.CircleAperture(self.width, unit=MM)
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
    tstamp: Timestamp = None

    def render(self):
        cx, cy = self.mid.x, self.mid.y
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        arc = go.Arc(x1, y1, x2, y2, cx-x1, cy-y1, unit=MM)

        if self.width:
            arc.aperture = ap.CircleAperture(self.width, unit=MM)
            yield arc

        if self.fill:
            yield arc.to_region()


@sexp_type('gr_poly')
class Polygon:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    fill: FillMode = True
    tstamp: Timestamp = None

    def render(self):
        reg = go.Region([(pt.x, pt.y) for pt in self.pts.xy], unit=MM)
        
        if self.width and self.width >= 0.005:
            yield from reg.outline_objects(aperture=ap.CircleAperture(self.width, unit=MM))

        if self.fill:
            yield reg


@sexp_type('gr_curve')
class Curve:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    tstamp: Timestamp = None

    def render(self):
        raise NotImplementedError('Bezier rendering is not yet supported. Please raise an issue and provide an example file.')


@sexp_type('gr_bbox')
class AnnotationBBox:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
 
    def render(self):
        return []

