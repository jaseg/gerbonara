"""
Library for handling KiCad's schematic files (`*.kicad_sch`).
"""

import math
from pathlib import Path
from dataclasses import field, KW_ONLY
from itertools import chain
import re
import fnmatch
import os.path
import warnings

from .sexp import *
from .base_types import *
from .primitives import *
from .symbols import Symbol
from . import graphical_primitives as gr

from .. import primitives as cad_pr

from ... import graphic_primitives as gp
from ... import graphic_objects as go
from ... import apertures as ap
from ...layers import LayerStack
from ...newstroke import Newstroke
from ...utils import MM, rotate_point, Tag, setup_svg
from .schematic_colors import *


KICAD_PAPER_SIZES = {
    'A5': (210,   148),
    'A4': (297,   210),
    'A3': (420,   297),
    'A2': (594,   420),
    'A1': (841,   594),
    'A0': (1189,  841),
    'A': (11*25.4, 8.5*25.4),
    'B': (17*25.4, 11*15.4),
    'C': (22*25.4, 17*25.4),
    'D': (34*25.4, 22*25.4),
    'E': (44*25.4, 34*25.4),
    'USLetter': (11*25.4, 8.5*25.4),
    'USLegal': (14*25.4, 8.5*25.4),
    'USLedger': (17*25.4, 11*25.4),
    }

@sexp_type('path')
class SheetPath:
    path: str = '/'
    page: Named(str) = '1'


@sexp_type('junction')
class Junction:
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    diameter: Named(float) = 0
    color: Color = field(default_factory=lambda: Color(0, 0, 0, 0))
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        r = (self.diameter/2 or 0.635)
        return (self.at.x - r, self.at.y - r), (self.at.x + r, self.at.y + r)
    
    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield Tag('circle', cx=f'{self.at.x:.3f}', cy=f'{self.at.y:.3f}', r=(self.diameter/2 or 0.635),
                   fill=self.color.svg(colorscheme.wire))


@sexp_type('no_connect')
class NoConnect:
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        r = 0.635
        return (self.at.x - r, self.at.y - r), (self.at.x + r, self.at.y + r)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        r = 0.635
        yield Tag('path', d=f'M {-r:.3f} {-r:.3f} L {r:.3f} {r:.3f} M {-r:.3f} {r:.3f} L {r:.3f} {-r:.3f}',
                   fill='none', stroke_width='0.1', stroke=colorscheme.no_connect)


@sexp_type('bus_entry')
class BusEntry:
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(2.54, 2.54))
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        r = math.hypot(self.size.x, self.size.y)
        x1, y1 = self.at.x, self.at.y
        x2, y2 = rotate_point(x1+r, y1+r, self.at.rotation or 0)
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        r = (self.stroke.width or 0.254) / 2
        return (x1-r, y1-r), (x2+r, y2+r)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield Tag('path', d='M {self.at.x} {self.at.y} l {self.size.x} {self.size.y}',
                   transform=f'rotate({self.at.rotation or 0})',
                   fill='none', stroke=self.stroke.svg_color(colorscheme.bus), width=self.stroke.width or '0.254')


def _polyline_svg(self, default_color):
    da = Dasher(self)
    if len(self.points.xy) < 2:
        warnings.warn(f'Schematic {type(self)} with less than two points')

    p0, *rest = self.points.xy
    da.move(p0.x, p0.y)
    for pn in rest:
        da.line(pn.x, pn.y)

    return da.svg(stroke=self.stroke.svg_color(default_color))


def _polyline_bounds(self):
    x1 = min(pt.x for pt in self.points)
    y1 = min(pt.y for pt in self.points)
    x2 = max(pt.x for pt in self.points)
    y2 = max(pt.y for pt in self.points)

    r = (self.stroke.width or 0.254) / 2
    return (x1-r, y1-r), (x2+r, y2+r)


@sexp_type('wire')
class Wire:
    points: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        return _polyline_bounds(self)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _polyline_svg(self, colorscheme.wire)


@sexp_type('bus')
class Bus:
    points: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        return _polyline_bounds(self)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _polyline_svg(self, colorscheme.bus)


@sexp_type('polyline')
class Polyline:
    points: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        return _polyline_bounds(self)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _polyline_svg(self, colorscheme.lines)


@sexp_type('text')
class Text(TextMixin):
    text: str = ''
    exclude_from_sim: Named(YesNoAtom()) = True
    at: AtPos = field(default_factory=AtPos)
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield from TextMixin.to_svg(self, colorscheme.text)


@sexp_type('label')
class LocalLabel(TextMixin):
    text: str = ''
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Wrap(Flag()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield from TextMixin.to_svg(self, colorscheme.text)


def label_shape_path_d(shape, w, h):
    l, r = {
        Atom.input: '<]',
        Atom.output: '[>',
        Atom.bidirectional: '<>',
        Atom.tri_state: '<>',
        Atom.passive: '[]'}.get(shape, '<]')
    r = h/2

    if l == '[':
        d = 'M {r:.3f} {r:.3f} L 0 {r:.3f} L 0 {-r:.3f} L {r:.3f} {-r:.3f}'
    else:
        d = 'M {r:.3f} {r:.3f} L 0 0 L {r:.3f} {-r:.3f}'

    e = w+r
    d += ' L {e:.3f} {-r:.3f}'

    if l == '[':
        return d + 'L {e+r:.3f} {-r:.3f} L {e+r:.3f} {r:.3f} L {e:.3f} {r:.3f} Z'
    else:
        return d + 'L {e+r:.3f} {0:.3f} L {e:.3f} {r:.3f} Z'


@sexp_type('global_label')
class GlobalLabel(TextMixin):
    text: str = ''
    shape: Named(AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive)) = Atom.input
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Wrap(Flag()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)
    properties: List(Property) = field(default_factory=list)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        text = super(TextMixin, self).to_svg(colorscheme.text),
        text.attrs['transform'] = f'translate({self.size*0.6:.3f} 0)'
        (x1, y1), (x2, y2) = self.bounding_box()
        frame = Tag('path', fill='none', stroke_width=0.254, stroke=colorscheme.lines,
            d=label_shape_path_d(self.shape, self.size*0.2 + y2-y1, self.size*1.2 + 0.254))
        yield Tag('g', children=[frame, text])


@sexp_type('hierarchical_label')
class HierarchicalLabel(TextMixin):
    text: str = ''
    shape: Named(AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive)) = Atom.input
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Wrap(Flag()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        text, = TextMixin.to_svg(self, colorscheme.text),
        text.attrs['transform'] = f'translate({self.size*1.2:.3f} 0)'
        frame = Tag('path', fill='none', stroke_width=0.254, stroke=colorscheme.lines,
            d=label_shape_path_d(self.shape, self.size, self.size))
        yield Tag('g', children=[frame, text])


@sexp_type('pin')
class Pin:
    name: str = '1'
    uuid: UUID = field(default_factory=UUID)


# Suddenly, we're doing syntax like this is yaml or something.
@sexp_type('path')
class SymbolCrosslinkSheet:
    path: str = ''
    reference: Named(str) = ''
    unit: Named(int) = 1


@sexp_type('project')
class SymbolCrosslinkProject:
    project_name: str = ''
    instances: List(SymbolCrosslinkSheet) = field(default_factory=list)


@sexp_type('mirror')
class MirrorFlags:
    x: Flag() = False
    y: Flag() = False


@sexp_type('property')
class DrawnProperty(TextMixin):
    key: str = None
    value: str = None
    at: AtPos = field(default_factory=AtPos)
    hide: Flag() = False
    effects: TextEffect = field(default_factory=TextEffect)

    # Alias value for text mixin
    @property
    def text(self):
        return self.value

    @text.setter
    def text(self, value):
        self.value = value

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if not self.hide:
            yield from TextMixin.to_svg(self, colorscheme.text)


@sexp_type('symbol')
class SymbolInstance:
    name: str = None
    lib_name: Named(str) = ''
    lib_id: Named(str) = ''
    at: AtPos = field(default_factory=AtPos)
    mirror: OmitDefault(MirrorFlags) = field(default_factory=MirrorFlags)
    unit: Named(int) = 1
    in_bom: Named(YesNoAtom()) = True
    on_board: Named(YesNoAtom()) = True
    dnp: Named(YesNoAtom()) = True
    fields_autoplaced: Wrap(Flag()) = True
    uuid: UUID = field(default_factory=UUID)
    properties: List(DrawnProperty) = field(default_factory=list)
    # AFAICT this property is completely redundant.
    pins: List(Pin) = field(default_factory=list)
    # AFAICT this property, too,  is completely redundant. It ultimately just lists paths and references of at most
    # three other uses of the same symbol in this schematic.
    instances: Named(List(SymbolCrosslinkProject)) = field(default_factory=list)
    _ : SEXP_END = None
    schematic: object = None

    def __after_parse__(self, parent):
        self.schematic = parent

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        children = []

        for prop in self.properties:
            children += prop.to_svg()

        sym = self.schematic.lookup_symbol(self.lib_name, self.lib_id).raw_units[self.unit - 1]
        for elem in sym.graphical_elements:
            children += elem.to_svg(colorscheme)

        xform = f'translate({self.at.x:.3f} {self.at.y:.3f})'
        if self.at.rotation:
            xform = f'rotate({self.at.rotation}) {xform}'
        if self.mirror.x:
            xform = f'scale(-1 1) {xform}'
        if self.mirror.y:
            xform = f'scale(1 -1) {xform}'

        yield Tag('g', children=children, transform=xform, fill=colorscheme.fill, stroke=colorscheme.lines)


@sexp_type('path')
class SubsheetCrosslinkSheet:
    path: str = ''
    page: Named(str) = ''


@sexp_type('project')
class SubsheetCrosslinkProject:
    project_name: str = ''
    instances: List(SymbolCrosslinkSheet) = field(default_factory=list)


@sexp_type('pin')
class SubsheetPin:
    name: str = '1'
    shape: AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive) = Atom.input
    at: AtPos = field(default_factory=AtPos)
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)
    _ : SEXP_END = None
    subsheet: object = None

    def __after_parse__(self, parent):
        self.subsheet = parent


@sexp_type('fill')
class SubsheetFill:
    color: Color = field(default_factory=lambda: Color(0, 0, 0, 0))


@sexp_type('sheet')
class Subsheet:
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(2.54, 2.54))
    fields_autoplaced: Wrap(Flag()) = True
    stroke: Stroke = field(default_factory=Stroke)
    fill: SubsheetFill = field(default_factory=SubsheetFill)
    uuid: UUID = field(default_factory=UUID)
    _properties: List(DrawnProperty) = field(default_factory=list)
    pins: List(SubsheetPin) = field(default_factory=list)
    # AFAICT this is completely redundant, just like the one in SymbolInstance
    instances: Named(List(SubsheetCrosslinkProject)) = field(default_factory=list)
    _ : SEXP_END = None
    sheet_name: object = field(default_factory=lambda: DrawnProperty('Sheetname', ''))
    file_name: object = field(default_factory=lambda: DrawnProperty('Sheetfile', ''))
    schematic: object = None

    def __after_parse__(self, parent):
        self.sheet_name, self.file_name = self._properties
        self.schematic = parent

    def __before_sexp__(self):
        self._properties = [self.sheet_name, self.file_name]

    def open(self, search_dir=None, safe=True):
        if search_dir is None:
            if not self.schematic.original_filename:
                raise FileNotFoundError('No search path given and path of parent schematic unknown')
            else:
                search_dir = Path(self.schematic.original_filename).parent
        else:
            search_dir = Path(search_dir)

        resolved = search_dir / self.file_name.value
        if safe and os.path.commonprefix((search_dir.parts, resolved.parts)) != search_dir.parts:
                raise ValueError('Subsheet path traversal to parent directory attempted in Subsheet.open(..., safe=True)')

        return Schematic.open(resolved)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        children = []

        for prop in self._properties:
            children += prop.to_svg(colorscheme)

        # FIXME
        #for elem in self.pins:
        #    children += pin.to_svg(colorscheme)

        xform = f'translate({self.at.x:.3f} {self.at.y:.3f})'
        yield Tag('g', children=children, transform=xform,
                  fill=self.fill.color.svg(colorscheme.fill),
                  **self.stroke.svg_attrs(colorscheme.lines))


@sexp_type('lib_symbols')
class LocalLibrary:
    symbols: List(Symbol) = field(default_factory=list)


SUPPORTED_FILE_FORMAT_VERSIONS = [20230620]
@sexp_type('kicad_sch')
class Schematic:
    _version: Named(int, name='version') = 20230620
    generator: Named(Atom) = Atom.gerbonara
    uuid: UUID = field(default_factory=UUID)
    page_settings: PageSettings = field(default_factory=PageSettings)
    # The doc says this is expected, but eeschema barfs when it's there.
    # path: SheetPath = field(default_factory=SheetPath)
    lib_symbols: LocalLibrary = field(default_factory=list)
    junctions: List(Junction) = field(default_factory=list)
    no_connects: List(NoConnect) = field(default_factory=list)
    bus_entries: List(BusEntry) = field(default_factory=list)
    wires: List(Wire) = field(default_factory=list)
    buses: List(Bus) = field(default_factory=list)
    images: List(gr.Image) = field(default_factory=list)
    polylines: List(Polyline) = field(default_factory=list)
    texts: List(Text) = field(default_factory=list)
    local_labels: List(LocalLabel) = field(default_factory=list)
    global_labels: List(GlobalLabel) = field(default_factory=list)
    hierarchical_labels: List(HierarchicalLabel) = field(default_factory=list)
    symbols: List(SymbolInstance) = field(default_factory=list)
    subsheets: List(Subsheet) = field(default_factory=list)
    sheet_instances: Named(List(SubsheetCrosslinkSheet)) = field(default_factory=list)
    _ : SEXP_END = None
    original_filename: str = None

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        if value not in SUPPORTED_FILE_FORMAT_VERSIONS:
            raise FormatError(f'File format version {value} is not supported. Supported versions are {", ".join(map(str, SUPPORTED_FILE_FORMAT_VERSIONS))}.')


    def lookup_symbol(self, lib_name, lib_id):
        key = lib_name or lib_id
        for sym in self.lib_symbols.symbols:
            if sym.name == key or sym.raw_name == key:
                return sym
        raise KeyError(f'Symbol with {lib_name=} {lib_id=} not found')

    def write(self, filename=None):
        with open(filename or self.original_filename, 'w') as f:
            f.write(self.serialize())

    def serialize(self):
        return build_sexp(sexp(type(self), self)[0])

    @classmethod
    def open(kls, pcb_file, *args, **kwargs):
        return kls.load(Path(pcb_file).read_text(), *args, **kwargs, original_filename=pcb_file)

    @classmethod
    def load(kls, data, *args, **kwargs):
        return kls.parse(data, *args, **kwargs)

    @property
    def elements(self):
        yield from self.junctions
        yield from self.no_connects
        yield from self.bus_entries
        yield from self.wires
        yield from self.buses
        yield from self.images
        yield from self.polylines
        yield from self.texts
        yield from self.local_labels
        yield from self.global_labels
        yield from self.hierarchical_labels
        yield from self.symbols
        yield from self.subsheets

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        children = []
        for elem in self.elements:
            children += elem.to_svg(colorscheme)
        w, h = KICAD_PAPER_SIZES[self.page_settings.page_format]
        return setup_svg(children, ((0, 0), (w, h)))


if __name__ == '__main__':
    import sys
    from ...layers import LayerStack
    sch = Schematic.open(sys.argv[1])
    print('Loaded schematic with', len(sch.wires), 'wires and', len(sch.symbols), 'symbols.')
    for subsh in sch.subsheets:
        subsh = subsh.open()
        print('Loaded sub-sheet with', len(subsh.wires), 'wires and', len(subsh.symbols), 'symbols.')

    sch.write('/tmp/test.kicad_sch')
    Path('/tmp/test.svg').write_text(str(sch.to_svg()))
