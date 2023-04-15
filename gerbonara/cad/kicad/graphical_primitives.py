
from .sexp import *
from .base_types import *
from .primitives import *

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


@sexp_type('gr_line')
class Line:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    angle: Named(float) = None
    layer: Named(str) = None
    width: Named(float) = None
    tstamp: Timestamp = None


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


@sexp_type('gr_circle')
class Circle:
    center: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    fill: FillMode = False
    tstamp: Timestamp = None


@sexp_type('gr_arc')
class Arc:
    start: Rename(XYCoord) = None
    mid: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    tstamp: Timestamp = None


@sexp_type('gr_poly')
class Polygon:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    fill: FillMode= False
    tstamp: Timestamp = None


@sexp_type('gr_curve')
class Curve:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    tstamp: Timestamp = None


@sexp_type('gr_bbox')
class AnnotationBBox:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None

 
