#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Modified from parser.py by Paulo Henrique Silva <ph.silva@gmail.com>
# Copyright 2022 Jan Götte <code@jaseg.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from dataclasses import dataclass
import math
import re
from enum import Enum
import warnings
from dataclasses import dataclass, KW_ONLY
from pathlib import Path

from .cam import CamFile, FileSettings
from .utils import MM, Inch, LengthUnit, rotate_point


class Netlist(CamFile):
    def __init__(self, test_records=None, conductors=None, outlines=None, comments=None, adjacency=None,
            params=None, import_settings=None, original_path=None, generator_hints=None):
        super().__init__(original_path=original_path, layer_name='netlist', import_settings=import_settings)
        self.test_records = test_records or []
        self.conductors = conductors or []
        self.outlines = outlines or []
        self.comments = comments or []
        self.adjacency = adjacency or {}
        self.params = params or {}
        self.generator_hints = generator_hints or []

    def merge(self, other, our_prefix=None, their_prefix=None):
        ''' Merge other netlist into this netlist. The respective net names are prefixed with the given prefixes
        (default: None). Garbles other. '''
        if other is None:
            return

        if not isinstance(other, Netlist):
            raise TypeError(f'Can only merge Netlist with other Netlist, not {type(other)}')

        self.prefix_nets(our_prefix)
        other.prefix_nets(our_prefix)

        self.test_records.extend(other.test_records)
        self.conductors.extend(other.conductors)
        self.outlines.extend(other.outlines)
        self.comments.extend(other.comments)
        self.adjacency.update(other.adjacency)
        self.params.update(other.params)

        self.params['JOB'] = 'Gerbonara IPC-356 merge'
        self.params['TITLE'] = 'Gerbonara IPC-356 merge'

        for key in 'CODE', 'NUM', 'REV', 'VER':
            if key in self.params:
                del self.params[key]

    def prefix_nets(self, prefix):
        if not prefix:
            return

        for record in self.test_records:
            if record.net_name:
                record.net_name = prefix + record.net_name

        for conductor in self.conductors:
            if conductor.net_name:
                conductor.net_name = prefix + conductor.net_name

        new_adjacency = {}
        for key in self.adjacency:
            new_adjacency[prefix + key] = [ prefix + name for name in self.adjacency[key] ]
        self.adjacency = new_adjacency

    def offset(self, dx=0,  dy=0, unit=MM):
        for obj in self.objects:
            obj.offset(dx, dy, unit)

    def rotate(self, angle:'radian', center=(0,0), unit=MM):
        cx, cy = center

        for obj in self.objects:
            obj.rotate(angle, cx, cy, unit)

    @property
    def objects(self):
        yield from self.test_records
        yield from self.conductors
        yield from self.outlines

    @classmethod
    def open(kls, filename):
        path = Path(filename)
        parser = NetlistParser()
        return parser.parse(path.read_text(), path)

    @classmethod
    def from_string(kls, data, filename=None):
        parser = NetlistParser()
        return parser.parse(data, Path(filename))

    def save(self, filename, settings=None, drop_comments=True):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(self.to_ipc356(settings, drop_comments=drop_comments))

    def to_ipc356(self, settings=None, drop_comments=True, job_name=None):
        if settings is None:
            settings = self.import_settings.copy() or FileSettings()
            settings.zeros = None
            settings.number_format = (5,6)
        return '\n'.join(self._generate_lines(settings, drop_comments=drop_comments))

    def _generate_lines(self, settings, drop_comments, job_name=None):
        yield 'C  IPC-D-356 generated by Gerbonara'
        yield 'C'
        yield f'P  JOB {self.params.get("JOB", "Gerbonara netlist export")}'
        yield 'P  UNITS CUST 0' if settings.unit == Inch else 'P  UNITS CUST 1' 

        if not drop_comments:
            for comment in self.comments:
                yield f'C  {comment}'

        for name, value in self.params.items():
            if name == 'JOB':
                continue

            yield f'P  {name} {value!s}'

        net_name_map = {
                name: f'NNAME{i}' for i, name in enumerate(
                    name for name in self.net_names() if len(name) > 14
                    ) }

        yield 'C'
        yield 'C  Net name mapping:'
        yield 'C'
        for name, alias in net_name_map.items():
            yield f'P  {alias} {name}'

        yield 'C'
        yield 'C  Test records:'
        yield 'C'

        for record in self.test_records:
            yield from record.format(settings, net_name_map)

        if self.conductors:
            yield 'C'
            yield 'C  Conductors:'
            yield 'C'
            for conductor in self.conductors:
                yield from conductor.format(settings, net_name_map)

        if self.outlines:
            yield 'C'
            yield 'C  Outlines:'
            yield 'C'
            for outline in self.outlines:
                yield from outline.format(settings)

        if self.adjacency:
            yield 'C'
            yield 'C  Adjacency data:'
            yield 'C'
            done = set()
            for net, others in self.adjacency.items():
                others_filtered = [ other for other in others if (net, other) not in done and (other, net) not in done ]

                line = '379'
                for net in self.nets:
                    if len(line) + 1 + len(net) > 80:
                        yield line
                        line = f'079 {net}'
                    else:
                        line += f' {net}'
                yield line

    def net_names(self):
        nets = { record.net_name for record in self.test_records }
        nets -= {None}
        return nets

    def vias(self):
        for record in self.test_records:
            if record.is_via:
                yield record

    def reference_designators(self):
        names = { record.ref_des for record in self.test_records }
        names -= {None}
        return names

    def records_by_reference(self, reference_designator):
        for record in self.test_records:
            if record.ref_des == reference_designator:
                yield record

    def records_by_net_name(self, net_name):
        for record in self.test_records:
            if record.net_name == net_name:
                yield record

    def conductors_by_net_name(self, net_name):
        for conductor in self.conductos:
            if conductor.net_name == net_name:
                yield conductor

    def conductors_by_layer(self, layer : int):
        for conductor in self.conductos:
            if conductor.layer == layer:
                yield conductor


class NetlistParser(object):
    # Good resources on IPC-356 syntax are:
    # https://www.downstreamtech.com/downloads/IPCD356_Simplified.pdf
    # https://web.pa.msu.edu/hep/atlas/l1calo/hub/hardware/components/circuit_board/ipc_356a_net_list.pdf

    def __init__(self):
        self.has_unit = False
        self.settings = FileSettings()
        self.net_names = {}
        self.params = {}
        self.comments = []
        self.test_records = []
        self.conductors = []
        self.adjacency = {}
        self.outlines = []
        self.eof = False
        self.generator_hints = []

    def warn(self, msg, kls=SyntaxWarning):
        warnings.warn(f'{self.filename}:{self.start_line}: {msg}', kls)

    def assert_unit(self):
        if not self.has_unit:
            raise SyntaxError('IPC-356 netlist file does not contain unit specification before first entry')

    def parse(self, data, path=None):
        self.filename = path.name

        try:
            oldline = ''
            for lineno, line in enumerate(data.splitlines()):
                # Check for existing multiline data...
                if oldline:
                    if line and line[0] == '0':
                        oldline = oldline.rstrip('\r\n') + line[3:].rstrip()
                    else:
                        self._parse_line(oldline)
                        self.start_line = lineno
                        oldline = line
                else:
                    self.start_line = lineno
                    oldline = line

            self._parse_line(oldline)
        except Exception as e:
            raise SyntaxError(f'Error parsing {self.filename}:{lineno}: {e}') from e

        return Netlist(self.test_records, self.conductors, self.outlines, self.comments, self.adjacency,
                params=self.params, import_settings=self.settings, original_path=path,
                generator_hints=self.generator_hints)

    def _parse_line(self, line):
        if not line:
            return

        if self.eof:
            self.warn('Data following IPC-356 End Of File marker')

        if line[0] == 'C':
            line = line[2:].strip()
            #     +-- sic!
            #     v
            if 'Ouptut' in line and 'Allegro' in line:
                self.generator_hints.append('allegro')

            elif 'Ouptut' not in line and 'Allegro' in line:
                self.warn('This seems to be a file generated by a newer allegro version. Please raise an issue on our '
                          'issue tracker with your Allegro version and if possible please provide an example file '
                          'so we can improve Gerbonara!')

            elif 'EAGLE' in line and 'CadSoft' in line:
                self.generator_hints.append('eagle')

            if line.strip().startswith('NNAME'):
                name, *value = line.strip().split()
                value = ' '.join(value)
                self.warn('File contains non-standard Allegro-style net name alias definitions in comments.')
                if 'allegro' in self.generator_hints:
                    # it's amazing how allegro always seems to have found a way to do the same thing everyone else is
                    # doing just in a different, slightly more messed up, completely incompatible way.
                    self.net_names[name] = value[5:] # strip NNAME because Allegro

                else:
                    self.net_names[name] = value

            else:
                self.comments.append(line)

        elif line[0] == 'P':
            # Parameter
            name, *value = line[2:].split()
            value = ' '.join(value)

            if name == 'UNITS':
                if value in ('CUST', 'CUST 0'):
                    self.settings.units = Inch
                    self.settings.angle_unit = 'degree'
                    self.has_unit = True

                elif value == 'CUST 1':
                    self.settings.units = MM
                    self.settings.angle_unit = 'degree'
                    self.has_unit = True

                elif value == 'CUST 2':
                    self.settings.units = Inch
                    self.settings.angle_unit = 'radian'
                    self.has_unit = True

                else:
                    raise SyntaxError(f'Unsupported IPC-356 netlist unit specification "{line}"')

            elif name.startswith('NNAME'):
                if 'allegro' in self.generator_hints:
                    self.net_names[name] = value[5:]

                else:
                    self.net_names[name] = value

            else:
                self.params[name] = value

        elif line[0] == '9':
            self.eof = True

        elif line[0:3] in ('317', '327', '367'):
            self.assert_unit()
            self.test_records.append(TestRecord.parse(line, self.settings, self.net_names))

        elif line[0:3] == '378':
            self.assert_unit()
            self.conductors.append(Conductor.parse(line, self.settings, self.net_names))

        elif line[0:3] == '379':
            net, *adjacent = line[3:].strip().split()

            for other in adjacent:
                self.adjacency[net] = self.adjacency.get(net, set()) | {other}
                self.adjacency[other] = self.adjacency.get(other, set()) | {net}

        elif line[0:3] == '389':
            self.assert_unit()
            self.outlines.extend(Outline.parse(line, self.settings))

        else:
            self.warn(f'Unknown IPC-356 record type {line[0:3]}')


class PadType(Enum):
    THROUGH_HOLE = 1
    SMD_PAD = 2
    TOOLING_FEATURE = 3
    TOOLING_HOLE = 4
    NONPLATED_HOLE = 6


class SoldermaskInfo(Enum):
    NONE = 0
    PRIMARY = 1
    SECONDARY = 2
    BOTH = 3


@dataclass
class TestRecord:
    __test__ = False # tell pytest to ignore this class
    pad_type : PadType = None
    net_name : str = None
    is_connected : bool = True # None, True or False.
    ref_des : str = None # part reference designator, e.g. "C1" or "U69"
    is_via : bool = False
    pin_num : int = None
    is_middle : bool = False # is this a point in the middle or at the end of a trace/net?
    hole_dia : float = None
    is_plated : bool = None # None, True, or False.
    access_layer : int = None
    x : float = None
    y : float = None
    w : float = None
    h : float = None
    rotation : float = 0
    solder_mask : SoldermaskInfo = None
    lefover : str = None
    _ : KW_ONLY
    unit : LengthUnit = None

    def __str__(self):
        x = self.unit.format(self.x)
        y = self.unit.format(self.y)
        return f'<IPC-356 test record @ {x},{y} {self.net_name} {self.pad_type.name} at {self.ref_des}, pin {self.pin_num}>'

    def rotate(self, angle, cx=0, cy=0, unit=None):
        cx = self.unit(cx, unit)
        cy = self.unit(cy, unit)

        self.angle += angle
        self.x, self.y = rotate_point(self.x, self.y, angle, center=(cx, cy))

    def offset(self, dx=0, dy=0, unit=None):
        dx = self.unit(dx, unit)
        dy = self.unit(dy, unit)
        self.x += dx
        self.y += dy

    @classmethod
    def parse(kls, line, settings, net_name_map={}):
        obj = kls()
        line = f'{line:<80}'

        obj.unit = settings.unit
        obj.pad_type = PadType(int(line[1]))

        net_name = line[3:17].strip() or None
        if net_name == 'N/C':
            obj.net_name = None
            obj.is_connected = False
        else:
            obj.net_name = net_name_map.get(net_name, net_name)
            obj.is_connected = True

        ref_des = line[20:26].strip() or None
        if ref_des == 'VIA':
            obj.is_via = True
            obj.ref_des = None
        else:
            obj.is_via = False
            obj.ref_des = ref_des

        obj.pin = line[27:31].strip() or None

        if line[31] == 'M':
            obj.is_middle = True
        if line[32] == 'D':
            obj.hole_dia = settings.parse_ipc_length(line[33:37])
        if line[37] in ('P', 'U'):
            obj.is_plated = (line[37] == 'P')
        if line[38] == 'A':
            obj.access_layer = int(line[39:41])
        if line[41] == 'X':
            obj.x = settings.parse_ipc_length(line[42:49])
        if line[49] == 'Y':
            obj.y = settings.parse_ipc_length(line[50:57])
        if line[57] == 'X':
            obj.w = settings.parse_ipc_length(line[58:62])
        if line[62] == 'Y':
            obj.h = settings.parse_ipc_length(line[63:67])
        if line[67] == 'R':
            obj.rotation = math.radians(int(line[68:71]))
        else:
            obj.rotation = 0
        if line[72] == 'S':
            obj.solder_mask = SoldermaskInfo(int(line[73]))
        obj.leftover = line[74:].strip() or None

        return obj

    def format(self, settings, net_name_map={}):
        x = settings.unit(self.x, self.unit)
        y = settings.unit(self.y, self.unit)
        w = settings.unit(self.w, self.unit)
        h = settings.unit(self.h, self.unit)
        # TODO: raise warning if any string is too long
        ref_des = 'VIA' if self.is_via else (self.ref_des or '')
        if self.is_connected:
            net_name = net_name_map.get(self.net_name, self.net_name)
        else:
            net_name = 'N/C'

        yield ''.join((
            '3',
            str(self.pad_type.value),
            '7',
            f'{net_name or "":<14}'[:14],
            '   ',
            f'{ref_des or "":<6}'[:6],
            '-',
            f'{self.pin_num or "":<4}'[:4],
            'M' if self.is_middle else ' ',
            settings.format_ipc_length(self.hole_dia, 4, 'D', self.unit),
            {True: 'P', False: 'U', None: ' '}[self.is_plated],
            settings.format_ipc_number(self.access_layer, 2, 'A'),
            settings.format_ipc_length(self.x, 6, 'X', self.unit, sign=True),
            settings.format_ipc_length(self.y, 6, 'Y', self.unit, sign=True),
            settings.format_ipc_length(self.w, 4, 'X', self.unit),
            settings.format_ipc_length(self.h, 4, 'Y', self.unit),
            settings.format_ipc_number(math.degrees(self.rotation) if self.rotation is not None else None, 3, 'R'),
            ' ',
            settings.format_ipc_number(self.solder_mask, 1, 'S'),
            f'{self.leftover or "":<6}'))

class OutlineType(Enum):
    BOARD_EDGE = 0
    PANEL_EDGE = 1
    SCORE_LINE = 2
    OTHER_FAB = 3


def parse_coord_chain(line, settings):
    x, y = None, None
    for segment in line.split('*'):
        coords = []
        for coord in segment.strip().split():
            if not (match := re.match(r'(X[+-]?[0-9]+)?(Y[+-]?[0-9]+)?', coord)):
                raise SyntaxError(f'Invalid IPC-356 coordinate {coord}')

            x = settings.parse_ipc_length(match[1], x)
            y = settings.parse_ipc_length(match[2], y)

            if x is None or y is None:
                raise SyntaxError('Outline or conductor coordinate chain is missing one coordinate in the beginning')

            coords.append((x, y))
        yield coords

def format_coord_chain(line, settings, coords, cont, unit):
    for x, y in coords:
        coord = settings.format_ipc_length(x, 6, 'X', unit=unit, sign=True)
        coord += settings.format_ipc_length(y, 6, 'Y', unit=unit, sign=True)

        if len(line) + len(coord) <= 80:
            line = (line + coord + ' ')[:80]

        else:
            yield line
            line = f'{cont} {coord} '
    yield line


@dataclass
class Outline:
    outline_type : OutlineType
    outline : [(float,)]
    _ : KW_ONLY
    unit : LengthUnit = None

    @classmethod
    def parse(kls, line, settings):
        print('parsing outline', line)
        outline_type = OutlineType[line[3:17].strip()]
        for outline in parse_coord_chain(line[22:], settings):
            print(' ->', outline)
            yield kls(outline_type, outline, unit=settings.unit)

    def format(self, settings):
        line = f'389{self.outline_type.name:<14}     '
        yield from format_coord_chain(line, settings, self.outline, '089', self.unit)

    def __str__(self):
        return f'<IPC-356 {self.outline_type.name} outline with {len(self.outline)} points>'

    def rotate(self, angle, cx=0, cy=0, unit=None):
        cx = self.unit(cx, unit)
        cy = self.unit(cy, unit)
        self.outline = [ rotate_point(x, y, angle, center=(cx, cy)) for x, y in self.outline ]

    def offset(self, dx=0, dy=0, unit=None):
        dx = self.unit(dx, unit)
        dy = self.unit(dy, unit)
        self.outline = [ (x+dx, y+dy) for x, y in self.outline ]


@dataclass
class Conductor:
    net_name : str
    layer : int
    aperture : (float,)
    coords : [(float,)]
    _ : KW_ONLY
    unit : LengthUnit = None

    @classmethod
    def parse(kls, line, settings, net_name_map={}):
        net_name = line[3:17].strip() or None
        net_name = net_name_map.get(net_name, net_name)

        if line[18] != 'L':
            raise SytaxError(f'Invalid IPC-356 layer number specification for conductor in line "{line}"')
        layer = int(line[19:21])

        aperture_def, _, coords = line[22:].partition(' ')
        if not (m := re.match(r'(X[+-]?[0-9]+)(Y[+-]?[0-9]+)?', coord)):
            raise SyntaxError('Invalid IPC-356 aperture specification "{aperture_def"}')
        aperture = settings.parse_ipc_length(m[1]), settings.parse_ipc_length(m[2])

        for chain in parse_coord_chain(coords, settings):
            yield kls(net_name, layer, aperture, chain, unit=settings.unit)

    def format(self, settings, net_name_map):
        net_name = net_name_map.get(self.net_name, self.net_name)
        net_name = f'{net_name:<14}[:14]'
        line = f'378{net_name} L{self.layer:02d} '
        yield from format_coord_chain(line, settings, self.outline, '078', self.unit)

    def __str__(self):
        return f'<IPC-356 conductor {self.net_name} with {len(self.coords)} points>'

    def rotate(self, angle, cx=0, cy=0, unit=None):
        cx = self.unit(cx, unit)
        cy = self.unit(cy, unit)
        self.coords = [ rotate_point(x, y, angle, center=(cx, cy)) for x, y in self.coords ]

    def offset(self, dx=0, dy=0, unit=None):
        dx = self.unit(dx, unit)
        dy = self.unit(dy, unit)
        self.coords = [ (x+dx, y+dy) for x, y in self.coords ]

