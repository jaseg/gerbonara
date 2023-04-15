"""
Library for handling KiCad's footprint files (`*.kicad_mod`).
"""

import copy
import enum
import datetime
import math
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from .sexp import *
from .base_types import *
from .primitives import *
from . import graphical_primitives as gr


@sexp_type('property')
class Property:
    key: str = ''
    value: str = ''


@sexp_type('attr')
class Attribute:
    type: AtomChoice(Atom.smd, Atom.through_hole) = None
    board_only: Flag() = False
    exclude_from_pos_files: Flag() = False
    exclude_from_bom: Flag() = False


@sexp_type('fp_text')
class Text:
    type: AtomChoice(Atom.reference, Atom.value, Atom.user) = Atom.user
    text: str = ""
    at: AtPos = field(default_factory=AtPos)
    unlocked: Flag() = False
    layer: Named(str) = None
    hide: Flag() = False
    effects: TextEffect = field(default_factory=TextEffect)
    tstamp: Timestamp = None


@sexp_type('fp_text_box')
class TextBox:
    locked: Flag() = False
    text: str = None
    start: Rename(XYCoord) = None
    end: Named(XYCoord) = None
    pts: PointList = None
    angle: Named(float) = 0.0
    layer: Named(str) = None
    tstamp: Timestamp = None
    effects: TextEffect = field(default_factory=TextEffect)
    stroke: Stroke = field(default_factory=Stroke)
    render_cache: RenderCache = None


@sexp_type('fp_line')
class Line:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    locked: Flag() = False
    tstamp: Timestamp = None


@sexp_type('fp_rect')
class Rectangle:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    fill: Named(AtomChoice(Atom.solid, Atom.none)) = None
    locked: Flag() = False
    tstamp: Timestamp = None


@sexp_type('fp_circle')
class Circle:
    center: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    fill: Named(AtomChoice(Atom.solid, Atom.none)) = None
    locked: Flag() = False
    tstamp: Timestamp = None


@sexp_type('fp_arc')
class Arc:
    start: Rename(XYCoord) = None
    mid: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    locked: Flag() = False
    tstamp: Timestamp = None


@sexp_type('fp_poly')
class Polygon:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    fill: Named(AtomChoice(Atom.solid, Atom.none)) = None
    locked: Flag() = False
    tstamp: Timestamp = None


@sexp_type('fp_curve')
class Curve:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    locked: Flag() = False
    tstamp: Timestamp = None


@sexp_type('format')
class DimensionFormat:
    prefix: Named(str) = None
    suffix: Named(str) = None
    units: Named(int) = 3
    units_format: Named(int) = 0
    precision: Named(int) = 3
    override_value: Named(str) = None
    suppress_zeros: Flag() = False


@sexp_type('style')
class DimensionStyle:
    thickness: Named(float) = None
    arrow_length: Named(float) = None
    text_position_mode: Named(int) = 0
    extension_height: Named(float) = None
    text_frame: Named(int) = 0
    extension_offset: Named(str) = None
    keep_text_aligned: Flag() = False


@sexp_type('dimension')
class Dimension:
    locked: Flag() = False
    type: AtomChoice(Atom.aligned, Atom.leader, Atom.center, Atom.orthogonal, Atom.radial) = None
    layer: Named(str) = None
    tstamp: Timestamp = None
    pts: PointList = field(default_factory=PointList)
    height: Named(float) = None
    orientation: Named(int) = 0
    leader_length: Named(float) = None
    gr_text: Named(Text) = None
    format: DimensionFormat = field(default_factory=DimensionFormat)
    style: DimensionStyle = field(default_factory=DimensionStyle)


@sexp_type('drill')
class Drill:
    oval: Flag() = False
    diameter: float = 0
    width: float = None
    offset: Rename(XYCoord) = None


@sexp_type('net')
class NetDef:
    number: int = None
    name: str = None


@sexp_type('options')
class CustomPadOptions:
    clearance: Named(AtomChoice(Atom.outline, Atom.convexhull)) = Atom.outline
    anchor: Named(AtomChoice(Atom.rect, Atom.circle)) = Atom.rect


@sexp_type('primitives')
class CustomPadPrimitives:
    annotation_bboxes: List(gr.AnnotationBBox) = field(default_factory=list)
    lines: List(gr.Line) = field(default_factory=list)
    rectangles: List(gr.Rectangle) = field(default_factory=list)
    circles: List(gr.Circle) = field(default_factory=list)
    arcs: List(gr.Arc) = field(default_factory=list)
    polygons: List(gr.Polygon) = field(default_factory=list)
    curves: List(gr.Curve) = field(default_factory=list)
    width: Named(float) = None
    fill: Named(YesNoAtom()) = True


@sexp_type('chamfer')
class Chamfer:
    top_left: Flag() = False
    top_right: Flag() = False
    bottom_left: Flag() = False
    bottom_right: Flag() = False

@sexp_type('pad')
class Pad:
    number: str = None
    type: AtomChoice(Atom.thru_hole, Atom.smd, Atom.connect, Atom.np_thru_hole) = None
    shape: AtomChoice(Atom.circle, Atom.rect, Atom.oval, Atom.trapezoid, Atom.roundrect, Atom.custom) = None
    at: AtPos = field(default_factory=AtPos)
    locked: Wrap(Flag()) = False
    size: Rename(XYCoord) = field(default_factory=XYCoord)
    drill: Drill = None
    layers: Named(Array(str)) = field(default_factory=list)
    properties: List(Property) = field(default_factory=list)
    remove_unused_layers: Wrap(Flag()) = False
    keep_end_layers: Wrap(Flag()) = False
    rect_delta: Rename(XYCoord) = None
    roundrect_rratio: Named(float) = None
    thermal_bridge_angle: Named(int) = 45
    chamfer_ratio: Named(float) = None
    chamfer: Chamfer = None
    net: NetDef = None
    tstamp: Timestamp = None
    pin_function: Named(str) = None
    pintype: Named(str) = None
    die_length: Named(float) = None
    solder_mask_margin: Named(float) = None
    solder_paste_margin: Named(float) = None
    solder_paste_margin_ratio: Named(float) = None
    clearance: Named(float) = None
    zone_connect: Named(int) = None
    thermal_width: Named(float) = None
    thermal_gap: Named(float) = None
    options: OmitDefault(CustomPadOptions) = None
    primitives: OmitDefault(CustomPadPrimitives) = None


@sexp_type('group')
class Group:
    name: str = ""
    id: Named(str) = ""
    members: Named(List(str)) = field(default_factory=list)


@sexp_type('model')
class Model:
    name: str = ''
    at: Named(XYZCoord) = field(default_factory=XYZCoord)
    offset: Named(XYZCoord) = field(default_factory=XYZCoord)
    scale: Named(XYZCoord) = field(default_factory=XYZCoord)
    rotate: Named(XYZCoord) = field(default_factory=XYZCoord)


SUPPORTED_FILE_FORMAT_VERSIONS = [20210108, 20211014, 20221018]
@sexp_type('footprint')
class Footprint:
    name: str = None
    _version: Named(int, name='version') = 20210108
    generator: Named(Atom) = Atom.kicad_library_utils
    locked: Flag() = False
    placed: Flag() = False
    layer: Named(str) = 'F.Cu'
    tedit: EditTime = field(default_factory=EditTime)
    tstamp: Timestamp = None
    at: AtPos = field(default_factory=AtPos)
    descr: Named(str) = None
    tags: Named(str) = None
    properties: List(Property) = field(default_factory=list)
    path: Named(str) = None
    autoplace_cost90: Named(float) = None
    autoplace_cost180: Named(float) = None
    solder_mask_margin: Named(float) = None
    solder_paste_margin: Named(float) = None
    solder_paste_ratio: Named(float) = None
    clearance: Named(float) = None
    zone_connect: Named(int) = None
    thermal_width: Named(float) = None
    thermal_gap: Named(float) = None
    attributes: List(Attribute) = field(default_factory=list)
    private_layers: Named(str) = None
    net_tie_pad_groups: Named(str) = None
    texts: List(Text) = field(default_factory=list)
    text_boxes: List(TextBox) = field(default_factory=list)
    lines: List(Line) = field(default_factory=list)
    rectangles: List(Rectangle) = field(default_factory=list)
    circles: List(Circle) = field(default_factory=list)
    arcs: List(Arc) = field(default_factory=list)
    polygons: List(Polygon) = field(default_factory=list)
    curves: List(Curve) = field(default_factory=list)
    dimensions: List(Dimension) = field(default_factory=list)
    pads: List(Pad) = field(default_factory=list)
    zones: List(Zone) = field(default_factory=list)
    groups: List(Group) = field(default_factory=list)
    models: List(Model) = field(default_factory=list)
    _ : SEXP_END = None
    original_filename: str = None

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        if value not in SUPPORTED_FILE_FORMAT_VERSIONS:
            raise FormatError(f'File format version {value} is not supported. Supported versions are {", ".join(map(str, SUPPORTED_FILE_FORMAT_VERSIONS))}.')

    @classmethod
    def open(cls, filename: str) -> 'Library':
        with open(filename) as f:
            return cls.parse(f.read())

    def write(self, filename=None) -> None:
        with open(filename or self.original_filename, 'w') as f:
            f.write(build_sexp(sexp(self)))


