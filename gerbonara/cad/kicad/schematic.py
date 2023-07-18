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
from ...utils import MM, rotate_point


@sexp_type('path')
class SheetPath:
    path: str = '/'
    page: Named(str) = '1'


@sexp_type('junction')
class Junction:
    at: AtPos = field(default_factory=AtPos)
    diameter: Named(float) = 0
    color: Color = field(default_factory=lambda: Color(0, 0, 0, 0))
    uuid: UUID = field(default_factory=UUID)


@sexp_type('no_connect')
class NoConnect:
    at: AtPos = field(default_factory=AtPos)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('bus_entry')
class BusEntry:
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(2.54, 2.54))
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('wire')
class Wire:
    points: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('bus')
class Bus:
    points: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('polyline')
class Polyline:
    points: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('text')
class Text:
    text: str = ''
    exclude_from_sim: Named(YesNoAtom()) = True
    at: AtPos = field(default_factory=AtPos)
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('label')
class LocalLabel:
    text: str = ''
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Wrap(Flag()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)


@sexp_type('global_label')
class GlobalLabel:
    text: str = ''
    shape: Named(AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive)) = Atom.input
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Wrap(Flag()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)
    properties: List(Property) = field(default_factory=list)


@sexp_type('hierarchical_label')
class HierarchicalLabel:
    text: str = ''
    shape: Named(AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive)) = Atom.input
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Wrap(Flag()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)


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
class DrawnProperty:
    key: str = None
    value: str = None
    at: AtPos = field(default_factory=AtPos)
    hide: Flag() = False
    effects: TextEffect = field(default_factory=TextEffect)


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


@sexp_type('sheet')
class Subsheet:
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(2.54, 2.54))
    fields_autoplaced: Wrap(Flag()) = True
    stroke: Stroke = field(default_factory=Stroke)
    fill: gr.FillMode = field(default_factory=gr.FillMode)
    uuid: UUID = field(default_factory=UUID)
    _properties: List(DrawnProperty) = field(default_factory=list)
    pins: List(SubsheetPin) = field(default_factory=list)
    # AFAICT this is completely redundant, just like the one in SymbolInstance
    instances: Named(List(SubsheetCrosslinkProject)) = field(default_factory=list)
    _: KW_ONLY
    sheet_name: object = field(default_factory=lambda: DrawnProperty('Sheetname', ''))
    file_name: object = field(default_factory=lambda: DrawnProperty('Sheetfile', ''))
    parent: object = None

    def __after_parse__(self, parent):
        self.sheet_name, self.file_name = self._properties
        self.parent = parent

    def __before_sexp__(self):
        self._properties = [self.sheet_name, self.file_name]

    def open(self, search_dir=None, safe=True):
        if search_dir is None:
            if not self.parent.original_filename:
                raise FileNotFoundError('No search path given and path of parent schematic unknown')
            else:
                search_dir = Path(self.parent.original_filename).parent
        else:
            search_dir = Path(search_dir)

        resolved = search_dir / self.file_name.value
        if safe and os.path.commonprefix((search_dir.parts, resolved.parts)) != search_dir.parts:
                raise ValueError('Subsheet path traversal to parent directory attempted in Subsheet.open(..., safe=True)')

        return Schematic.open(resolved)


SUPPORTED_FILE_FORMAT_VERSIONS = [20220914]
@sexp_type('kicad_sch')
class Schematic:
    _version: Named(int, name='version') = 20211014
    generator: Named(Atom) = Atom.gerbonara
    uuid: UUID = field(default_factory=UUID)
    page_settings: PageSettings = field(default_factory=PageSettings)
    path: SheetPath = field(default_factory=SheetPath)
    lib_symbols: Named(Array(Symbol)) = field(default_factory=list)
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


if __name__ == '__main__':
    import sys
    from ...layers import LayerStack
    sch = Schematic.open(sys.argv[1])
    print('Loaded schematic with', len(sch.wires), 'wires and', len(sch.symbols), 'symbols.')
    for subsh in sch.subsheets:
        subsh = subsh.open()
        print('Loaded sub-sheet with', len(subsh.wires), 'wires and', len(subsh.symbols), 'symbols.')

