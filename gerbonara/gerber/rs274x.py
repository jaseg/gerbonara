#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>
# Copyright 2021 Jan Götte <code@jaseg.de>
# Modified from parser.py by Paulo Henrique Silva <ph.silva@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
""" This module provides an RS-274-X class and parser.
"""

import copy
import json
import os
import re
import sys
import warnings
from pathlib import Path
from itertools import count, chain
from io import StringIO

from .gerber_statements import *
from .primitives import *
from .cam import CamFile, FileSettings
from .utils import sq_distance, rotate_point



class GerberFile(CamFile):
    """ A class representing a single gerber file

    The GerberFile class represents a single gerber file.

    Parameters
    ----------
    statements : list
        list of gerber file statements

    settings : dict
        Dictionary of gerber file settings

    filename : string
        Filename of the source gerber file

    Attributes
    ----------
    comments: list of strings
        List of comments contained in the gerber file.

    size : tuple, (<float>, <float>)
        Size in [self.units] of the layer described by the gerber file.

    bounds: tuple, ((<float>, <float>), (<float>, <float>))
        boundaries of the layer described by the gerber file.
        `bounds` is stored as ((min x, max x), (min y, max y))

    """

    def __init__(self, statements, settings, primitives, apertures, filename=None):
        super(GerberFile, self).__init__(statements, settings, primitives, filename)

        self.apertures = apertures

        # always explicitly set polarity
        self.statements.insert(0, LPParamStmt('LP', 'dark'))

        self.aperture_macros = {}
        self.aperture_defs = []
        self.main_statements = []

        self.context = GerberContext.from_settings(self.settings)

        for stmt in self.statements:
            self.context.update_from_statement(stmt)

            if isinstance(stmt, CoordStmt):
                self.context.normalize_coordinates(stmt)

            if isinstance(stmt, AMParamStmt):
                self.aperture_macros[stmt.name] = stmt

            elif isinstance(stmt, ADParamStmt):
                self.aperture_defs.append(stmt)

            else:
                # ignore FS, MO, AS, IN, IP, IR, MI, OF, SF, LN statements
                if isinstance(stmt, ParamStmt) and not isinstance(stmt, LPParamStmt):
                    continue

                if isinstance(stmt, (CommentStmt, EofStmt)):
                    continue

                self.main_statements.append(stmt)

        if self.context.angle != 0:
            self.rotate(self.context.angle) # TODO is this correct/useful?

        if self.context.is_negative:
            self.negate_polarity() # TODO is this correct/useful?

        self.context.notation = 'absolute'
        self.context.zeros = 'trailing'


    @classmethod
    def open(kls, filename, enable_includes=False, enable_include_dir=None):
        with open(filename, "r") as f:
            if enable_includes and enable_include_dir is None:
                enable_include_dir = Path(filename).parent
            return kls.from_string(f.read(), enable_include_dir)


    @classmethod
    def from_string(kls, data, enable_include_dir=None):
        return GerberParser().parse(data, enable_include_dir)

    @property
    def comments(self):
        return [stmt.comment for stmt in self.statements if isinstance(stmt, CommentStmt)]

    @property
    def size(self):
        (x0, y0), (x1, y1) = self.bounding_box
        return (x1 - x0, y1 - y0)

    @property
    def bounding_box(self):
        bounds = [ p.bounding_box for p in self.pDeprecatedrimitives ]

        min_x = min(x0 for (x0, y0), (x1, y1) in bounds)
        min_y = min(y0 for (x0, y0), (x1, y1) in bounds)
        max_x = max(x1 for (x0, y0), (x1, y1) in bounds)
        max_y = max(y1 for (x0, y0), (x1, y1) in bounds)

        return ((min_x, max_x), (min_y, max_y))

    # TODO: re-add settings arg
    def write(self, filename):
        self.settings.notation = 'absolute'
        self.settings.zeros = 'trailing'
        self.settings.format = self.format
        self.units = self.units

        with open(filename, 'w') as f:
            print(UnitStmt().to_gerber(self.settings), file=f)
            print(FormatSpecStmt().to_gerber(self.settings), file=f)
            print(ImagePolarityStmt().to_gerber(self.settings), file=f)

            for thing in chain(self.aperture_macros.values(), self.aperture_defs, self.main_statements):
                print(thing.to_gerber(self.settings), file=f)

            print('M02*', file=f)

    def to_inch(self):
        if self.units == 'metric':
            for thing in chain(self.aperture_macros.values(), self.aperture_defs, self.statements, self.primitives):
                thing.to_inch()
            self.units = 'inch'
            self.context.units = 'inch'

    def to_metric(self):
        if self.units == 'inch':
            for thing in chain(self.aperture_macros.values(), self.aperture_defs, self.statements, self.primitives):
                thing.to_metric()
            self.units='metric'
            self.context.units='metric'

    def offset(self, x_offset=0,  y_offset=0):
        for thing in chain(self.main_statements, self.primitives):
            thing.offset(x_offset, y_offset)

    def rotate(self, angle, center=(0,0)):
        if angle % 360 == 0:
            return

        self._generalize_apertures()

        last_x = 0
        last_y = 0
        last_rx = 0
        last_ry = 0

        for macro in self.aperture_macros.values():
            macro.rotate(angle, center)

        for statement in self.main_statements:
            if isinstance(statement, CoordStmt) and statement.x != None and statement.y != None:

                if statement.i is not None and statement.j is not None:
                    cx, cy = last_x + statement.i, last_y + statement.j
                    cx, cy = rotate_point((cx, cy), angle, center)
                    statement.i, statement.j = cx - last_rx, cy - last_ry

                last_x, last_y = statement.x, statement.y
                last_rx, last_ry = rotate_point((statement.x, statement.y), angle, center)
                statement.x, statement.y = last_rx, last_ry
    
    def negate_polarity(self):
        for statement in self.main_statements:
            if isinstance(statement, LPParamStmt):
                statement.lp = 'dark' if statement.lp == 'clear' else 'clear'
    
    def _generalize_apertures(self):
        # For rotation, replace standard apertures with macro apertures.
        if not any(isinstance(stm, ADParamStmt) and stm.shape in 'ROP' for stm in self.aperture_defs):
            return

        # find an unused macro name with the given prefix
        def free_name(prefix):
            return next(f'{prefix}_{i}' for i in count() if f'{prefix}_{i}' not in self.aperture_macros)
        
        rect = free_name('MACR')
        self.aperture_macros[rect] = AMParamStmt.rectangle(rect, self.units)

        obround_landscape = free_name('MACLO')
        self.aperture_macros[obround_landscape] = AMParamStmt.landscape_obround(obround_landscape, self.units)

        obround_portrait = free_name('MACPO')
        self.aperture_macros[obround_portrait] = AMParamStmt.portrait_obround(obround_portrait, self.units)

        polygon = free_name('MACP')
        self.aperture_macros[polygon] = AMParamStmt.polygon(polygon, self.units)

        for statement in self.aperture_defs:
            if isinstance(statement, ADParamStmt):
                if statement.shape == 'R':
                    statement.shape = rect

                elif statement.shape == 'O':
                    x, y, *_ = *statement.modifiers[0], 0, 0
                    statement.shape = obround_landscape if x > y else obround_portrait

                elif statement.shape == 'P':
                    statement.shape = polygon


class GerberParser:
    NUMBER = r"[\+-]?\d+"
    DECIMAL = r"[\+-]?\d+([.]?\d+)?"
    NAME = r"[a-zA-Z_$\.][a-zA-Z_$\.0-9+\-]+"

    STATEMENT_REGEXES = {
        'unit_mode': r"MO(?P<unit>(MM|IN))",
        'interpolation_mode': r"(?P<code>G0?[123]|G74|G75)?",
        'coord': = fr"(X(?P<x>{NUMBER}))?(Y(?P<y>{NUMBER}))?" \
            fr"(I(?P<i>{NUMBER}))?(J(?P<j>{NUMBER}))?" \
            fr"(?P<operation>D0?[123])?\*",
        'aperture': r"(G54|G55)?D(?P<number>\d+)\*",
        'comment': r"G0?4(?P<comment>[^*]*)(\*)?",
        'format_spec': r"FS(?P<zero>(L|T|D))?(?P<notation>(A|I))[NG0-9]*X(?P<x>[0-7][0-7])Y(?P<y>[0-7][0-7])[DM0-9]*",
        'load_polarity': r"LP(?P<polarity>(D|C))",
        'load_name': r"LN(?P<name>.*)",
        'offset': fr"OF(A(?P<a>{DECIMAL}))?(B(?P<b>{DECIMAL}))?",
        'include_file': r"IF(?P<filename>.*)",
        'image_name': r"IN(?P<name>.*)",
        'axis_selection': r"AS(?P<axes>AXBY|AYBX)",
        'image_polarity': r"IP(?P<polarity>(POS|NEG))",
        'image_rotation': fr"IR(?P<rotation>{NUMBER})",
        'mirror_image': r"MI(A(?P<a>0|1))?(B(?P<b>0|1))?",
        'scale_factor': fr"SF(A(?P<a>{DECIMAL}))?(B(?P<b>{DECIMAL}))?",
        'aperture_definition': fr"ADD(?P<number>\d+)(?P<shape>C|R|O|P|{NAME})[,]?(?P<modifiers>[^,%]*)",
        'aperture_macro': fr"AM(?P<name>{NAME})\*(?P<macro>[^%]*)",
        'region_mode': r'(?P<mode>G3[67])\*',
        'quadrant_mode': r'(?P<mode>G7[45])\*',
        'old_unit':r'(?P<mode>G7[01])\*',
        'old_notation': r'(?P<mode>G9[01])\*',
        'eof': r"M0?[02]\*",
        'ignored': r"(?P<stmt>M01)\*",
        }

    STATEMENT_REGEXES = { key: re.compile(value) for key, value in STATEMENT_REGEXES.items() }


    def __init__(self, include_dir=None):
        """ Pass an include dir to enable IF include statements (potentially DANGEROUS!). """
        self.include_dir = include_dir
        self.include_stack = []
        self.settings = FileSettings()
        self.statements = []
        self.primitives = []
        self.apertures = {}
        self.macros = {}
        self.current_region = None
        self.x = 0
        self.y = 0
        self.last_operation = None
        self.op = "D02"
        self.aperture = 0
        self.interpolation = 'linear'
        self.direction = 'clockwise'
        self.image_polarity = 'positive'
        self.level_polarity = 'dark'
        self.region_mode = 'off'
        self.quadrant_mode = 'multi-quadrant'
        self.step_and_repeat = (1, 1, 0, 0)

    def parse(self, data):
        for stmt in self._parse(data):
            self.evaluate(stmt)
            self.statements.append(stmt)

        # Initialize statement units
        for stmt in self.statements:
            stmt.units = self.settings.units

        return GerberFile(self.statements, self.settings, self.primitives, self.apertures.values())

    @classmethod
    def _split_commands(kls, data):
        """
        Split the data into commands. Commands end with * (and also newline to help with some badly formatted files)
        """

        start = 0
        extended_command = False

        for pos, c in enumerate(data):
            if c == '%':
                if extended_command:
                    yield data[start:pos+1]
                    extended_command = False
                    start = pos + 1

                else:
                    extended_command = True

                continue

            elif extended_command:
                continue

            if c == '\r' or c == '\n' or c == '*':
                word_command = data[start:pos+1].strip()
                if word_command and word_command != '*':
                    yield word_command
                start = cur + 1

    def dump_json(self):
        return json.dumps({"statements": [stmt.__dict__ for stmt in self.statements]})

    def dump_str(self):
        return '\n'.join(str(stmt) for stmt in self.statements) + '\n'

    def _parse(self, data):
        for line in self._split_commands(data):
            # We cannot assume input gerber to use well-formed statement delimiters. Thus, we may need to parse
            # multiple statements from one line.
            while line:
                for name, le_regex in self.STATEMENT_REGEXES.items():
                    if (match := le_regex.match(line))
                        yield from getattr(self, f'_parse_{name}')(self, match.groupdict())
                        line = line[match.end(0):]
                        break

                else:
                    if line[-1] == '*':
                        yield UnknownStmt(line)
                        line = ''

    def _parse_interpolation_mode(self, match):
        if match['code'] == 'G01':
            yield LinearModeStmt()
        elif match['code'] == 'G02':
            yield CircularCWModeStmt()
        elif match['code'] == 'G03':
            yield CircularCCWModeStmt()
        elif match['code'] == 'G74':
            yield MultiQuadrantModeStmt()
        elif match['code'] == 'G75':
            yield SingleQuadrantModeStmt()

    def _parse_coord(self, match):
        x = parse_gerber_value(match.get('x'), self.settings)
        y = parse_gerber_value(match.get('y'), self.settings)
        i = parse_gerber_value(match.get('i'), self.settings)
        j = parse_gerber_value(match.get('j'), self.settings)
        if not (op := match['operation']):
            if self.last_operation == 'D01':
                warnings.warn('Coordinate statement without explicit operation code. This is forbidden by spec.',
                        SyntaxWarning)
                op = 'D01'
            else:
                raise SyntaxError('Ambiguous coordinate statement. Coordinate statement does not have an operation '\
                                  'mode and the last operation statement was not D01.')

        if op in ('D1', 'D01'):
            yield InterpolateStmt(x, y, i, j)

        if i is not None or j is not None:
            raise SyntaxError("i/j coordinates given for D02/D03 operation (which doesn't take i/j)")
            
        if op in ('D2', 'D02'):
            yield MoveStmt(x, y, i, j)
        else: # D03
            yield FlashStmt(x, y, i, j)


    def _parse_aperture(self, match):
        number = int(match['number'])
        if number < 10:
            raise SyntaxError(f'Invalid aperture number {number}: Aperture number must be >= 10.')
        yield ApertureStmt(number)
    
    def _parse_format_spec(self, match):
        # This is a common problem in Eagle files, so just suppress it
        self.settings.zero_suppression = {'L': 'leading', 'T': 'trailing'}.get(match['zero'], 'leading')
        self.settings.notation = 'absolute' if match.['notation'] == 'A' else 'incremental'

        if match['x'] != match['y']:
            raise SyntaxError(f'FS specifies different coordinate formats for X and Y ({match["x"]} != {match["y"]})')
        self.settings.number_format = int(match['x'][0]), int(match['x'][1])

        yield FormatSpecStmt()

    def _parse_unit_mode(self, match):
        if match['unit'] == 'MM':
            self.settings.units = 'mm'
        else:
            self.settings.units = 'inch'

        yield MOParamStmt()

    def _parse_load_polarity(self, match):
        yield LoadPolarityStmt(dark=(match['polarity'] == 'D'))

    def _parse_offset(self, match):
        a, b = match['a'], match['b']
        a = float(a) if a else 0
        b = float(b) if b else 0
        yield OffsetStmt(a, b)

    def _parse_include_file(self, match):
        if self.include_dir is None:
            warnings.warn('IF Include File statement found, but includes are deactivated.', ResourceWarning)
        else:
            warnings.warn('IF Include File statement found. Includes are activated, but is this really a good idea?', ResourceWarning)

        include_file = self.include_dir / param["filename"]
        if include_file in self.include_stack
            raise ValueError("Recusive file inclusion via IF include statement.")
        self.include_stack.append(include_file)

        # Spec 2020-09 section 3.1: Gerber files must use UTF-8
        yield from self._parse(f.read_text(encoding='UTF-8'))
        self.include_stack.pop()


    def _parse_image_name(self, match):
        warnings.warn('Deprecated IN (image name) statement found. This deprecated since rev. I4 (Oct 2013).',
                DeprecationWarning)
        yield CommentStmt(f'Image name: {match["name"]}')

    def _parse_load_name(self, match):
        warnings.warn('Deprecated LN (load name) statement found. This deprecated since rev. I4 (Oct 2013).',
                DeprecationWarning)
        yield CommentStmt(f'Name of subsequent part: {match["name"]}')

    def _parse_axis_selection(self, match):
        warnings.warn('Deprecated AS (axis selection) statement found. This deprecated since rev. I1 (Dec 2012).',
                DeprecationWarning)
        self.settings.output_axes = match['axes']
        yield AxisSelectionStmt()

    def _parse_image_polarity(self, match):
        warnings.warn('Deprecated IP (image polarity) statement found. This deprecated since rev. I4 (Oct 2013).',
                DeprecationWarning)
        self.settings.image_polarity = match['polarity']
        yield ImagePolarityStmt()
    
    def _parse_image_rotation(self, match):
        warnings.warn('Deprecated IR (image rotation) statement found. This deprecated since rev. I1 (Dec 2012).',
                DeprecationWarning)
        self.settings.image_rotation = int(match['rotation'])
        yield ImageRotationStmt()

    def _parse_mirror_image(self, match):
        warnings.warn('Deprecated MI (mirror image) statement found. This deprecated since rev. I1 (Dec 2012).',
                DeprecationWarning)
        self.settings.mirror = bool(int(match['a'] or '0')), bool(int(match['b'] or '1'))
        yield MirrorImageStmt()

    def _parse_scale_factor(self, match):
        warnings.warn('Deprecated SF (scale factor) statement found. This deprecated since rev. I1 (Dec 2012).',
                DeprecationWarning)
        a = float(match['a']) if match['a'] else 1.0
        b = float(match['b']) if match['b'] else 1.0
        self.settings.scale_factor = a, b
        yield ScaleFactorStmt()

    def _parse_comment(self, match):
        yield CommentStmt(match["comment"])

    def _parse_region_mode(self, match):
        yield RegionStartStatement() if match['mode'] == 'G36' else RegionEndStatement()

        elif param["param"] == "AM":
            yield AMParamStmt.from_dict(param, units=self.settings.units)
        elif param["param"] == "AD":
            yield ADParamStmt.from_dict(param)

    def _parse_quadrant_mode(self, match):
        if match['mode'] == 'G74':
            warnings.warn('Deprecated G74 single quadrant mode statement found. This deprecated since 2021.',
                    DeprecationWarning)
            yield SingleQuadrantModeStmt()
        else:
            yield MultiQuadrantModeStmt()

    def _parse_old_unit(self, match):
        self.settings.units = 'inch' if match['mode'] == 'G70' else 'mm'
        warnings.warn(f'Deprecated {match["mode"]} unit mode statement found. This deprecated since 2012.',
                    DeprecationWarning)
        yield CommentStmt(f'Replaced deprecated {match["mode"]} unit mode statement with MO statement')
        yield UnitStmt()

    def _parse_old_unit(self, match):
        # FIXME make sure we always have FS at end of processing.
        self.settings.notation = 'absolute' if match['mode'] == 'G90' else 'incremental'
        warnings.warn(f'Deprecated {match["mode"]} notation mode statement found. This deprecated since 2012.',
                    DeprecationWarning)
        yield CommentStmt(f'Replaced deprecated {match["mode"]} notation mode statement with FS statement')
    
    def _parse_eof(self, match):
        yield EofStmt()

    def _parse_ignored(self, match):
        yield CommentStmt(f'Ignoring {match{"stmt"]} statement.')

    def evaluate(self, stmt):
        """ Evaluate Gerber statement and update image accordingly.

        This method is called once for each statement in the file as it
        is parsed.

        Parameters
        ----------
        statement : Statement
            Gerber/Excellon statement to evaluate.

        """
        if isinstance(stmt, CoordStmt):
            self._evaluate_coord(stmt)

        elif isinstance(stmt, ParamStmt):
            self._evaluate_param(stmt)

        elif isinstance(stmt, ApertureStmt):
            self._evaluate_aperture(stmt)

        elif isinstance(stmt, (RegionModeStmt, QuadrantModeStmt)):
            self._evaluate_mode(stmt)

        elif isinstance(stmt, (CommentStmt, UnknownStmt, DeprecatedStmt, EofStmt)):
            return

        else:
            raise Exception("Invalid statement to evaluate")

    def _define_aperture(self, d, shape, modifiers):
        aperture = None
        if shape == 'C':
            diameter = modifiers[0][0]

            hole_diameter = 0
            rectangular_hole = (0, 0)
            if len(modifiers[0]) == 2:
                hole_diameter = modifiers[0][1]
            elif len(modifiers[0]) == 3:
                rectangular_hole = modifiers[0][1:3]

            aperture = Circle(position=None, diameter=diameter,
                              hole_diameter=hole_diameter,
                              hole_width=rectangular_hole[0],
                              hole_height=rectangular_hole[1],
                              units=self.settings.units)

        elif shape == 'R':
            width = modifiers[0][0]
            height = modifiers[0][1]

            hole_diameter = 0
            rectangular_hole = (0, 0)
            if len(modifiers[0]) == 3:
                hole_diameter = modifiers[0][2]
            elif len(modifiers[0]) == 4:
                rectangular_hole = modifiers[0][2:4]

            aperture = Rectangle(position=None, width=width, height=height,
                                 hole_diameter=hole_diameter,
                                 hole_width=rectangular_hole[0],
                                 hole_height=rectangular_hole[1],
                                 units=self.settings.units)
        elif shape == 'O':
            width = modifiers[0][0]
            height = modifiers[0][1]

            hole_diameter = 0
            rectangular_hole = (0, 0)
            if len(modifiers[0]) == 3:
                hole_diameter = modifiers[0][2]
            elif len(modifiers[0]) == 4:
                rectangular_hole = modifiers[0][2:4]

            aperture = Obround(position=None, width=width, height=height,
                               hole_diameter=hole_diameter,
                               hole_width=rectangular_hole[0],
                               hole_height=rectangular_hole[1],
                               units=self.settings.units)
        elif shape == 'P':
            outer_diameter = modifiers[0][0]
            number_vertices = int(modifiers[0][1])
            if len(modifiers[0]) > 2:
                rotation = modifiers[0][2]
            else:
                rotation = 0

            hole_diameter = 0
            rectangular_hole = (0, 0)
            if len(modifiers[0]) == 4:
                hole_diameter = modifiers[0][3]
            elif len(modifiers[0]) >= 5:
                rectangular_hole = modifiers[0][3:5]

            aperture = Polygon(position=None, sides=number_vertices,
                               radius=outer_diameter/2.0,
                               hole_diameter=hole_diameter,
                               hole_width=rectangular_hole[0],
                               hole_height=rectangular_hole[1],
                               rotation=rotation)
        else:
            aperture = self.macros[shape].build(modifiers)

        aperture.units = self.settings.units
        self.apertures[d] = aperture

    def _evaluate_mode(self, stmt):
        if stmt.type == 'RegionMode':
            if self.region_mode == 'on' and stmt.mode == 'off':
                # Sometimes we have regions that have no points. Skip those
                if self.current_region:
                    self.primitives.append(Region(self.current_region,
                                                  level_polarity=self.level_polarity, units=self.settings.units))

                self.current_region = None
            self.region_mode = stmt.mode
        elif stmt.type == 'QuadrantMode':
            self.quadrant_mode = stmt.mode

    def _evaluate_param(self, stmt):
        if stmt.param == "FS":
            self.settings.zero_suppression = stmt.zero_suppression
            self.settings.format = stmt.format
            self.settings.notation = stmt.notation
        elif stmt.param == "MO":
            self.settings.units = stmt.mode
        elif stmt.param == "IP":
            self.image_polarity = stmt.ip
        elif stmt.param == "LP":
            self.level_polarity = stmt.lp
        elif stmt.param == "AM":
            self.macros[stmt.name] = stmt
        elif stmt.param == "AD":
            self._define_aperture(stmt.d, stmt.shape, stmt.modifiers)

    def _evaluate_coord(self, stmt):
        x = self.x if stmt.x is None else stmt.x
        y = self.y if stmt.y is None else stmt.y

        if stmt.function in ("G01", "G1"):
            self.interpolation = 'linear'
        elif stmt.function in ('G02', 'G2', 'G03', 'G3'):
            self.interpolation = 'arc'
            self.direction = ('clockwise' if stmt.function in
                              ('G02', 'G2') else 'counterclockwise')

        if stmt.only_function:
            # Sometimes we get a coordinate statement
            # that only sets the function. If so, don't
            # try futher otherwise that might draw/flash something
            return

        if stmt.op:
            self.op = stmt.op
        else:
            # no implicit op allowed, force here if coord block doesn't have it
            stmt.op = self.op

        if self.op == "D01" or self.op == "D1":
            start = (self.x, self.y)
            end = (x, y)

            if self.interpolation == 'linear':
                if self.region_mode == 'off':
                    self.primitives.append(Line(start, end,
                                                self.apertures[self.aperture],
                                                level_polarity=self.level_polarity,
                                                units=self.settings.units))
                else:
                    # from gerber spec revision J3, Section 4.5, page 55:
                    #  The segments are not graphics objects in themselves; segments are part of region which is the graphics object. The segments have no thickness.
                    # The current aperture is associated with the region.
                    # This has no graphical effect, but allows all its attributes to
                    # be applied to the region.

                    if self.current_region is None:
                        self.current_region = [Line(start, end,
                                                    self.apertures.get(self.aperture,
                                                                       Circle((0, 0), 0)),
                                                    level_polarity=self.level_polarity,
                                                    units=self.settings.units), ]
                    else:
                        self.current_region.append(Line(start, end,
                                                        self.apertures.get(self.aperture,
                                                                           Circle((0, 0), 0)),
                                                        level_polarity=self.level_polarity,
                                                        units=self.settings.units))
            else:
                i = 0 if stmt.i is None else stmt.i
                j = 0 if stmt.j is None else stmt.j
                center = self._find_center(start, end, (i, j))
                if self.region_mode == 'off':
                    self.primitives.append(Arc(start, end, center, self.direction,
                                               self.apertures[self.aperture],
                                               quadrant_mode=self.quadrant_mode,
                                               level_polarity=self.level_polarity,
                                               units=self.settings.units))
                else:
                    if self.current_region is None:
                        self.current_region = [Arc(start, end, center, self.direction,
                                                   self.apertures.get(self.aperture, Circle((0,0), 0)),
                                                   quadrant_mode=self.quadrant_mode,
                                                   level_polarity=self.level_polarity,
                                                   units=self.settings.units),]
                    else:
                        self.current_region.append(Arc(start, end, center, self.direction,
                                                       self.apertures.get(self.aperture, Circle((0,0), 0)),
                                                       quadrant_mode=self.quadrant_mode,
                                                       level_polarity=self.level_polarity,
                                                       units=self.settings.units))
                    # Gerbv seems to reset interpolation mode in regions..
                    # TODO: Make sure this is right.
                    self.interpolation = 'linear'

        elif self.op == "D02" or self.op == "D2":

            if self.region_mode == "on":
                # D02 in the middle of a region finishes that region and starts a new one
                if self.current_region and len(self.current_region) > 1:
                    self.primitives.append(Region(self.current_region,
                                                  level_polarity=self.level_polarity,
                                                  units=self.settings.units))
                self.current_region = None

        elif self.op == "D03" or self.op == "D3":
            primitive = copy.deepcopy(self.apertures[self.aperture])

            if primitive is not None:

                if not isinstance(primitive, AMParamStmt):
                    primitive.position = (x, y)
                    primitive.level_polarity = self.level_polarity
                    primitive.units = self.settings.units
                    self.primitives.append(primitive)
                else:
                    # Aperture Macro
                    for am_prim in primitive.primitives:
                        renderable = am_prim.to_primitive((x, y),
                                                          self.level_polarity,
                                                          self.settings.units)
                        if renderable is not None:
                            self.primitives.append(renderable)
        self.x, self.y = x, y

    def _find_center(self, start, end, offsets):
        """
        In single quadrant mode, the offsets are always positive, which means
        there are 4 possible centers. The correct center is the only one that
        results in an arc with sweep angle of less than or equal to 90 degrees
        in the specified direction
        """
        two_pi = 2 * math.pi
        if self.quadrant_mode == 'single-quadrant':
            # The Gerber spec says single quadrant only has one possible center,
            # and you can detect it based on the angle. But for real files, this
            # seems to work better - there is usually only one option that makes
            # sense for the center (since the distance should be the same
            # from start and end). We select the center with the least error in
            # radius from all the options with a valid sweep angle.

            sqdist_diff_min = sys.maxsize
            center = None
            for factors in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:

                test_center = (start[0] + offsets[0] * factors[0],
                               start[1] + offsets[1] * factors[1])

                # Find angle from center to start and end points
                start_angle = math.atan2(*reversed([_start - _center for _start, _center in zip(start, test_center)]))
                end_angle = math.atan2(*reversed([_end - _center for _end, _center in zip(end, test_center)]))

                # Clamp angles to 0, 2pi
                theta0 = (start_angle + two_pi) % two_pi
                theta1 = (end_angle + two_pi) % two_pi

                # Determine sweep angle in the current arc direction
                if self.direction == 'counterclockwise':
                    sweep_angle = abs(theta1 - theta0)
                else:
                    theta0 += two_pi
                    sweep_angle = abs(theta0 - theta1) % two_pi

                # Calculate the radius error
                sqdist_start = sq_distance(start, test_center)
                sqdist_end = sq_distance(end, test_center)
                sqdist_diff = abs(sqdist_start - sqdist_end)

                # Take the option with the lowest radius error from the set of
                # options with a valid sweep angle
                # In some rare cases, the sweep angle is numerically (10**-14) above pi/2
                # So it is safer to compare the angles with some tolerance
                is_lowest_radius_error = sqdist_diff < sqdist_diff_min
                is_valid_sweep_angle = sweep_angle >= 0 and sweep_angle <= math.pi / 2.0 + 1e-6
                if is_lowest_radius_error and is_valid_sweep_angle:
                    center = test_center
                    sqdist_diff_min = sqdist_diff
            return center
        else:
            return (start[0] + offsets[0], start[1] + offsets[1])

    def _evaluate_aperture(self, stmt):
        self.aperture = stmt.d

def _match_one(expr, data):
    match = expr.match(data)
    if match is None:
        return ({}, None)
    else:
        return (match.groupdict(), data[match.end(0):])


def _match_one_from_many(exprs, data):
    for expr in exprs:
        match = expr.match(data)
        if match:
            return (match.groupdict(), data[match.end(0):])

    return ({}, None)

class GerberContext(FileSettings):
    TYPE_NONE = 'none'
    TYPE_AM = 'am'
    TYPE_AD = 'ad'
    TYPE_MAIN = 'main'
    IP_LINEAR = 'linear'
    IP_ARC = 'arc'
    DIR_CLOCKWISE = 'cw'
    DIR_COUNTERCLOCKWISE = 'ccw'

    @classmethod
    def from_settings(cls, settings):
        return cls(settings.notation, settings.units, settings.zero_suppression,
                   settings.format, settings.zeros, settings.angle_units)

    def __init__(self, notation='absolute', units='inch',
                 zero_suppression=None, format=(2, 5), zeros=None,
                 angle_units='degrees',
                 mirror=(False, False), offset=(0., 0.), scale=(1., 1.),
                 angle=0., axis='xy'):
        super(GerberContext, self).__init__(notation, units, zero_suppression, 
                                      format, zeros, angle_units)
        self.mirror = mirror
        self.offset = offset
        self.scale = scale
        self.angle = angle
        self.axis = axis

        self.is_negative = False
        self.no_polarity = True
        self.in_single_quadrant_mode = False
        self.op = None
        self.interpolation = self.IP_LINEAR
        self.direction = self.DIR_CLOCKWISE
        self.x, self.y = 0, 0

    def update_from_statement(self, stmt):
        if isinstance(stmt, MIParamStmt):
            self.mirror = (stmt.a, stmt.b)

        elif isinstance(stmt, OFParamStmt):
            self.offset = (stmt.a, stmt.b)

        elif isinstance(stmt, SFParamStmt):
            self.scale = (stmt.a, stmt.b)

        elif isinstance(stmt, ASParamStmt):
            self.axis = 'yx' if stmt.mode == 'AYBX' else 'xy'

        elif isinstance(stmt, IRParamStmt):
            self.angle = stmt.angle

        elif isinstance(stmt, QuadrantModeStmt):
            self.in_single_quadrant_mode = stmt.mode == 'single-quadrant'
            stmt.mode = 'multi-quadrant'

        elif isinstance(stmt, IPParamStmt):
            self.is_negative = stmt.ip == 'negative'

        elif isinstance(stmt, LPParamStmt):
            self.no_polarity = False

    @property
    def matrix(self):
        if self.axis == 'xy':
            mx = -1 if self.mirror[0] else 1
            my = -1 if self.mirror[1] else 1
            return (
                self.scale[0] * mx, self.offset[0],
                self.scale[1] * my, self.offset[1],
                self.scale[0] * mx, self.scale[1] * my)
        else:
            mx = -1 if self.mirror[1] else 1
            my = -1 if self.mirror[0] else 1
            return (
                self.scale[1] * mx, self.offset[1],
                self.scale[0] * my, self.offset[0],
                self.scale[1] * mx, self.scale[0] * my)

    def normalize_coordinates(self, stmt):
        if stmt.function == 'G01' or stmt.function == 'G1':
            self.interpolation = self.IP_LINEAR

        elif stmt.function == 'G02' or stmt.function == 'G2':
            self.interpolation = self.IP_ARC
            self.direction = self.DIR_CLOCKWISE
            if self.mirror[0] != self.mirror[1]:
                stmt.function = 'G03'

        elif stmt.function == 'G03' or stmt.function == 'G3':
            self.interpolation = self.IP_ARC
            self.direction = self.DIR_COUNTERCLOCKWISE
            if self.mirror[0] != self.mirror[1]:
                stmt.function = 'G02'

        if stmt.only_function:
            return

        last_x, last_y = self.x, self.y
        if self.notation == 'absolute':
            x = stmt.x if stmt.x is not None else self.x
            y = stmt.y if stmt.y is not None else self.y

        else:
            x = self.x + stmt.x if stmt.x is not None else 0
            y = self.y + stmt.y if stmt.y is not None else 0

        self.x, self.y = x, y
        self.op = stmt.op if stmt.op is not None else self.op

        stmt.op = self.op
        stmt.x = self.matrix[0] * x + self.matrix[1]
        stmt.y = self.matrix[2] * y + self.matrix[3]

        if stmt.op == 'D01' and self.interpolation == self.IP_ARC:
            qx, qy = 1, 1
            if self.in_single_quadrant_mode:
                if self.direction == self.DIR_CLOCKWISE:
                    qx = 1 if y > last_y else -1
                    qy = 1 if x < last_x else -1
                else:
                    qx = 1 if y < last_y else -1
                    qy = 1 if x > last_x else -1
                if last_x == x and last_y == y:
                    qx, qy = 0, 0

            stmt.i = qx * self.matrix[4] * stmt.i if stmt.i is not None else 0
            stmt.j = qy * self.matrix[5] * stmt.j if stmt.j is not None else 0

