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
import math
import warnings
import functools
from pathlib import Path
from itertools import count, chain
from io import StringIO
import textwrap

from .gerber_statements import *
from .cam import CamFile, FileSettings
from .utils import sq_distance, rotate_point, MM, Inch, units
from .aperture_macros.parse import ApertureMacro, GenericMacros
from . import graphic_primitives as gp
from . import graphic_objects as go
from . import apertures


def points_close(a, b):
    if a == b:
        return True
    elif a is None or b is None:
        return False
    elif None in a or None in b:
        return False
    else:
        return math.isclose(a[0], b[0]) and math.isclose(a[1], b[1])

class Tag:
    def __init__(self, name, children=None, root=False, **attrs):
        self.name, self.attrs = name, attrs
        self.children = children or []
        self.root = root

    def __str__(self):
        prefix = '<?xml version="1.0" encoding="utf-8"?>\n' if self.root else ''
        opening = ' '.join([self.name] + [f'{key.replace("__", ":")}="{value}"' for key, value in self.attrs.items()])
        if self.children:
            children = '\n'.join(textwrap.indent(str(c), '  ') for c in self.children)
            return f'{prefix}<{opening}>\n{children}\n</{self.name}>'
        else:
            return f'{prefix}<{opening}/>'

class GerberFile(CamFile):
    """ A class representing a single gerber file

    The GerberFile class represents a single gerber file.
    """

    def __init__(self, filename=None):
        super().__init__(filename)
        self.apertures = []
        self.comments = []
        self.objects = []
        self.import_settings = None

    def to_svg(self, tag=Tag, margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None, color='black'):

        if force_bounds is None:
            (min_x, min_y), (max_x, max_y) = self.bounding_box(svg_unit, default=((0, 0), (0, 0)))
        else:
            (min_x, min_y), (max_x, max_y) = force_bounds
            min_x = svg_unit(min_x, arg_unit)
            min_y = svg_unit(min_y, arg_unit)
            max_x = svg_unit(max_x, arg_unit)
            max_y = svg_unit(max_y, arg_unit)

        if margin:
            margin = svg_unit(margin, arg_unit)
            min_x -= margin
            min_y -= margin
            max_x += margin
            max_y += margin

        w, h = max_x - min_x, max_y - min_y
        w = 1.0 if math.isclose(w, 0.0) else w
        h = 1.0 if math.isclose(h, 0.0) else h

        primitives = [ prim.to_svg(tag, color) for obj in self.objects for prim in obj.to_primitives(unit=svg_unit) ]

        # setup viewport transform flipping y axis
        xform = f'translate({min_x} {min_y+h}) scale(1 -1) translate({-min_x} {-min_y})'

        svg_unit = 'in' if svg_unit == 'inch' else 'mm'
        # TODO export apertures as <uses> where reasonable.
        return tag('svg', [tag('g', primitives, transform=xform)],
                width=f'{w}{svg_unit}', height=f'{h}{svg_unit}',
                viewBox=f'{min_x} {min_y} {w} {h}',
                xmlns="http://www.w3.org/2000/svg", xmlns__xlink="http://www.w3.org/1999/xlink", root=True)

    def merge(self, other):
        """ Merge other GerberFile into this one """
        self.comments += other.comments

        # dedup apertures
        new_apertures = {}
        replace_apertures = {}
        mock_settings = self.import_settings
        for ap in self.apertures + other.apertures:
            gbr = ap.to_gerber(mock_settings)
            if gbr not in new_apertures:
                new_apertures[gbr] = ap
            else:
                replace_apertures[id(ap)] = new_apertures[gbr]
        self.apertures = list(new_apertures.values())

        self.objects += other.objects
        for obj in self.objects:
            # If object has an aperture attribute, replace that aperture.
            if (ap := replace_apertures.get(id(getattr(obj, 'aperture', None)))):
                obj.aperture = ap

        # dedup aperture macros
        macros = { m.to_gerber(): m
                for m in [ GenericMacros.circle, GenericMacros.rect, GenericMacros.obround, GenericMacros.polygon] }
        for ap in new_apertures.values():
            if isinstance(ap, apertures.ApertureMacroInstance):
                macro_grb = ap.macro.to_gerber() # use native unit to compare macros
                if macro_grb in macros:
                    ap.macro = macros[macro_grb]
                else:
                    macros[macro_grb] = ap.macro

        # make macro names unique
        seen_macro_names = set()
        for macro in macros.values():
            i = 2
            while (new_name := f'{macro.name}{i}') in seen_macro_names:
                i += 1
            macro.name = new_name
            seen_macro_names.add(new_name)

    def dilate(self, offset, unit=MM, polarity_dark=True):

        self.apertures = [ aperture.dilated(offset, unit) for aperture in self.apertures ]

        offset_circle = CircleAperture(offset, unit=unit)
        self.apertures.append(offset_circle)

        new_primitives = []
        for p in self.primitives:

            p.polarity_dark = polarity_dark

            # Ignore Line, Arc, Flash. Their actual dilation has already been done by dilating the apertures above.
            if isinstance(p, Region):
                ol = p.poly.outline
                for start, end, arc_center in zip(ol, ol[1:] + ol[0], p.poly.arc_centers):
                    if arc_center is not None:
                        new_primitives.append(Arc(*start, *end, *arc_center,
                            polarity_dark=polarity_dark, unit=p.unit, aperture=offset_circle))

                    else:
                        new_primitives.append(Line(*start, *end,
                            polarity_dark=polarity_dark, unit=p.unit, aperture=offset_circle))

        # it's safe to append these at the end since we compute a logical OR of opaque areas anyway.
        self.primitives.extend(new_primitives)

    @classmethod
    def open(kls, filename, enable_includes=False, enable_include_dir=None):
        with open(filename, "r") as f:
            if enable_includes and enable_include_dir is None:
                enable_include_dir = Path(filename).parent
            return kls.from_string(f.read(), enable_include_dir)

    @classmethod
    def from_string(kls, data, enable_include_dir=None):
        obj = kls()
        GerberParser(obj, include_dir=enable_include_dir).parse(data)
        return obj

    def size(self, unit=MM):
        (x0, y0), (x1, y1) = self.bounding_box(unit, default=((0, 0), (0, 0)))
        return (x1 - x0, y1 - y0)

    def bounding_box(self, unit=MM, default=None):
        """ Calculate bounding box of file. Returns value given by 'default' argument when there are no graphical
        objects (default: None)
        """
        bounds = [ p.bounding_box(unit) for p in self.objects ]
        if not bounds:
            return default

        min_x = min(x0 for (x0, y0), (x1, y1) in bounds)
        min_y = min(y0 for (x0, y0), (x1, y1) in bounds)
        max_x = max(x1 for (x0, y0), (x1, y1) in bounds)
        max_y = max(y1 for (x0, y0), (x1, y1) in bounds)

        return ((min_x, min_y), (max_x, max_y))

    def generate_statements(self, drop_comments=True):
        yield UnitStmt()
        yield FormatSpecStmt()
        yield ImagePolarityStmt()
        yield SingleQuadrantModeStmt()
        yield LoadPolarityStmt(True)

        if not drop_comments:
            yield CommentStmt('File processed by Gerbonara. Original comments:')
            for cmt in self.comments:
                yield CommentStmt(cmt)

        # Always emit gerbonara's generic, rotation-capable aperture macro replacements for the standard C/R/O/P shapes.
        # Unconditionally emitting these here is easier than first trying to figure out if we need them later,
        # and they are only a few bytes anyway.
        yield ApertureMacroStmt(GenericMacros.circle)
        yield ApertureMacroStmt(GenericMacros.rect)
        yield ApertureMacroStmt(GenericMacros.obround)
        yield ApertureMacroStmt(GenericMacros.polygon)

        processed_macros = set()
        aperture_map = {}
        for number, aperture in enumerate(self.apertures, start=10):

            if isinstance(aperture, apertures.ApertureMacroInstance):
                macro_grb = aperture._rotated().macro.to_gerber() # use native unit to compare macros
                if macro_grb not in processed_macros:
                    processed_macros.add(macro_grb)
                    yield ApertureMacroStmt(aperture._rotated().macro)

            yield ApertureDefStmt(number, aperture)

            aperture_map[id(aperture)] = number

        gs = GraphicsState(aperture_map=aperture_map)
        for primitive in self.objects:
            yield from primitive.to_statements(gs)

        yield EofStmt()

    def __str__(self):
        return f'<GerberFile with {len(self.apertures)} apertures, {len(self.objects)} objects>'

    def save(self, filename, settings=None):
        with open(filename, 'w', encoding='utf-8') as f: # Encoding is specified as UTF-8 by spec.
            f.write(self.to_gerber(settings))

    def to_gerber(self, settings=None):
        # Use given settings, or use same settings as original file if not given, or use defaults if not imported from a
        # file
        if settings is None:
            settings = self.import_settings.copy() or FileSettings()
            settings.zeros = None
            settings.number_format = (5,6)
        return '\n'.join(stmt.to_gerber(settings) for stmt in self.generate_statements())

    def offset(self, dx=0,  dy=0, unit=MM):
        # TODO round offset to file resolution
    
        self.objects = [ obj.with_offset(dx, dy, unit) for obj in self.objects ]

    def rotate(self, angle:'radian', center=(0,0), unit=MM):
        """ Rotate file contents around given point.

            Arguments:
            angle -- Rotation angle in radian clockwise.
            center -- Center of rotation (default: document origin (0, 0))

            Note that when rotating by odd angles other than 0, 90, 180 or 270 degree this method may replace standard
            rect and oblong apertures by macro apertures. Existing macro apertures are re-written.
        """
        if math.isclose(angle % (2*math.pi), 0):
            return

        # First, rotate apertures. We do this separately from rotating the individual objects below to rotate each
        # aperture exactly once.
        for ap in self.apertures:
            ap.rotation += angle

        for obj in self.objects:
            obj.rotate(angle, *center, unit)

    def invert_polarity(self):
        for obj in self.objects:
            obj.polarity_dark = not p.polarity_dark
    

class GraphicsState:
    polarity_dark : bool = True
    image_polarity : str = 'positive' # IP image polarity; deprecated
    point : tuple = None
    aperture : apertures.Aperture = None
    file_settings : FileSettings = None
    interpolation_mode : InterpolationModeStmt = LinearModeStmt
    multi_quadrant_mode : bool = None # used only for syntax checking
    aperture_mirroring = (False, False) # LM mirroring (x, y)
    aperture_rotation = 0 # LR rotation in degree, ccw
    aperture_scale = 1 # LS scale factor, NOTE: same for both axes
    # The following are deprecated file-wide settings. We normalize these during parsing.
    image_offset : (float, float) = (0, 0)
    image_rotation: int = 0 # IR image rotation in degree ccw, one of 0, 90, 180 or 270; deprecated
    image_mirror : tuple = (False, False) # IM image mirroring, (x, y); deprecated
    image_scale : tuple = (1.0, 1.0) # SF image scaling (x, y); deprecated
    image_axes : str = 'AXBY' # AS axis mapping; deprecated
    # for statement generation
    aperture_map = {}


    def __init__(self, file_settings=None, aperture_map=None):
        self._mat = None
        self.file_settings = file_settings
        if aperture_map is not None:
            self.aperture_map = aperture_map

    def __setattr__(self, name, value):
        # input validation
        if name == 'image_axes' and value not in [None, 'AXBY', 'AYBX']:
            raise ValueError('image_axes must be either "AXBY", "AYBX" or None')
        elif name == 'image_rotation' and value not in [0, 90, 180, 270]:
            raise ValueError('image_rotation must be 0, 90, 180 or 270')
        elif name == 'image_polarity' and value not in ['positive', 'negative']:
            raise ValueError('image_polarity must be either "positive" or "negative"')
        elif name == 'image_mirror' and len(value) != 2:
            raise ValueError('mirror_image must be 2-tuple of bools: (mirror_a, mirror_b)')
        elif name == 'image_offset' and len(value) != 2:
            raise ValueError('image_offset must be 2-tuple of floats: (offset_a, offset_b)')
        elif name == 'image_scale' and len(value) != 2:
            raise ValueError('image_scale must be 2-tuple of floats: (scale_a, scale_b)')

        # polarity handling
        if name == 'image_polarity': # global IP statement image polarity, can only be set at beginning of file
            if self.image_polarity == 'negative':
                self.polarity_dark = False # evaluated before image_polarity is set below through super().__setattr__

        elif name == 'polarity_dark': # local LP statement polarity for subsequent objects
            if self.image_polarity == 'negative':
                value = not value

        super().__setattr__(name, value)

    def _update_xform(self):
        a, b = 1, 0
        c, d = 0, 1
        off_x, off_y = self.image_offset

        if self.image_mirror[0]:
            a = -1
        if self.image_mirror[1]:
            d = -1

        a *= self.image_scale[0]
        d *= self.image_scale[1]

        if self.image_rotation == 90:
            a, b, c, d = 0, -d, a, 0
            off_x, off_y = off_y, -off_x
        elif self.image_rotation == 180:
            a, b, c, d = -a, 0, 0, -d
            off_x, off_y = -off_x, -off_y
        elif self.image_rotation == 270:
            a, b, c, d = 0, d, -a, 0
            off_x, off_y = -off_y, off_x

        self.image_offset = off_x, off_y
        self._mat = a, b, c, d
    
    def map_coord(self, x, y, relative=False):
        if self._mat is None:
            self._update_xform()
        a, b, c, d = self._mat

        if not relative:
            rx, ry = (a*x + b*y + self.image_offset[0]), (c*x + d*y + self.image_offset[1])
            return rx, ry
        else:
            # Apply mirroring, scale and rotation, but do not apply offset
            rx, ry = (a*x + b*y), (c*x + d*y)
            return rx, ry

    def flash(self, x, y):
        self.update_point(x, y)
        return go.Flash(*self.map_coord(*self.point), self.aperture,
                polarity_dark=self.polarity_dark,
                unit=self.file_settings.unit)

    def interpolate(self, x, y, i=None, j=None, aperture=True):
        if self.point is None:
            warnings.warn('D01 interpolation without preceding D02 move.', SyntaxWarning)
            self.point = (0, 0)
        old_point = self.map_coord(*self.update_point(x, y))

        if aperture and math.isclose(self.aperture.equivalent_width(), 0):
            warnings.warn('D01 interpolation with a zero-size aperture. This is invalid according to spec, however, we '
                    'pass through the created objects here. Note that these will not show up in e.g. SVG output since '
                    'their line width is zero.', SyntaxWarning)

        if self.interpolation_mode == LinearModeStmt:
            if i is not None or j is not None:
                raise SyntaxError("i/j coordinates given for linear D01 operation (which doesn't take i/j)")

            return self._create_line(old_point, self.map_coord(*self.point), aperture)

        else:

            if i is None and j is None:
                warnings.warn('Linear segment implied during arc interpolation mode through D01 w/o I, J values', SyntaxWarning)
                return self._create_line(old_point, self.map_coord(*self.point), aperture)

            else:
                if i is None:
                    warnings.warn('Arc is missing I value', SyntaxWarning)
                    i = 0
                if j is None:
                    warnings.warn('Arc is missing J value', SyntaxWarning)
                    j = 0
                return self._create_arc(old_point, self.map_coord(*self.point), (i, j), aperture)

    def _create_line(self, old_point, new_point, aperture=True):
        return go.Line(*old_point, *new_point, self.aperture if aperture else None,
                polarity_dark=self.polarity_dark, unit=self.file_settings.unit)

    def _create_arc(self, old_point, new_point, control_point, aperture=True):
        clockwise = self.interpolation_mode == CircularCWModeStmt
        return go.Arc(*old_point, *new_point, *self.map_coord(*control_point, relative=True),
                clockwise=clockwise, aperture=(self.aperture if aperture else None),
                polarity_dark=self.polarity_dark, unit=self.file_settings.unit)

    def update_point(self, x, y, unit=None):
        old_point = self.point
        x, y = MM(x, unit), MM(y, unit)

        if x is None:
            x = self.point[0]
        if y is None:
            y = self.point[1]

        self.point = (x, y)
        return old_point

    # Helpers for gerber generation
    def set_polarity(self, polarity_dark):
        if self.polarity_dark != polarity_dark:
            self.polarity_dark = polarity_dark
            yield LoadPolarityStmt(polarity_dark)

    def set_aperture(self, aperture):
        if self.aperture != aperture:
            self.aperture = aperture
            yield ApertureStmt(self.aperture_map[id(aperture)])

    def set_current_point(self, point, unit=None):
        point_mm = MM(point[0], unit), MM(point[1], unit)
        # TODO calculate appropriate precision for math.isclose given file_settings.notation

        if not points_close(self.point, point_mm):
            self.point = point_mm
            yield MoveStmt(*point, unit=unit)

    def set_interpolation_mode(self, mode):
        if self.interpolation_mode != mode:
            self.interpolation_mode = mode
            yield mode()


class GerberParser:
    NUMBER = r"[\+-]?\d+"
    DECIMAL = r"[\+-]?\d+([.]?\d+)?"
    NAME = r"[a-zA-Z_$\.][a-zA-Z_$\.0-9+\-]+"

    STATEMENT_REGEXES = {
        'unit_mode': r"MO(?P<unit>(MM|IN))",
        'interpolation_mode': r"(?P<code>G0?[123]|G74|G75)$",
        'coord': fr"(X(?P<x>{NUMBER}))?(Y(?P<y>{NUMBER}))?" \
            fr"(I(?P<i>{NUMBER}))?(J(?P<j>{NUMBER}))?" \
            fr"(?P<operation>D0?[123])$",
        'aperture': r"(G54|G55)?D(?P<number>\d+)",
        'comment': r"G0?4(?P<comment>[^*]*)",
        'format_spec': r"FS(?P<zero>(L|T|D))?(?P<notation>(A|I))[NG0-9]*X(?P<x>[0-7][0-7])Y(?P<y>[0-7][0-7])[DM0-9]*",
        'load_polarity': r"LP(?P<polarity>(D|C))",
        # FIXME LM, LR, LS
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
        'region_start': r'G36',
        'region_end': r'G37',
        'old_unit':r'(?P<mode>G7[01])',
        'old_notation': r'(?P<mode>G9[01])',
        'eof': r"M0?[02]",
        'ignored': r"(?P<stmt>M01)",
        }

    STATEMENT_REGEXES = { key: re.compile(value) for key, value in STATEMENT_REGEXES.items() }


    def __init__(self, target, include_dir=None):
        """ Pass an include dir to enable IF include statements (potentially DANGEROUS!). """
        self.target = target
        self.include_dir = include_dir
        self.include_stack = []
        self.file_settings = FileSettings()
        self.graphics_state = GraphicsState(file_settings=self.file_settings)
        self.aperture_map = {}
        self.aperture_macros = {}
        self.current_region = None
        self.eof_found = False
        self.multi_quadrant_mode = None # used only for syntax checking
        self.macros = {}
        self.last_operation = None

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
                    yield data[start:pos]
                    extended_command = False

                else:
                    extended_command = True

                start = pos + 1
                continue

            elif extended_command:
                continue

            if c == '\r' or c == '\n' or c == '*':
                word_command = data[start:pos].strip()
                if word_command and word_command != '*':
                    yield word_command
                start = pos + 1

    def parse(self, data):
        for line in self._split_commands(data):
            if not line.strip():
                continue
            line = line.rstrip('*').strip()
            # We cannot assume input gerber to use well-formed statement delimiters. Thus, we may need to parse
            # multiple statements from one line.
            if line.strip() and self.eof_found:
                warnings.warn('Data found in gerber file after EOF.', SyntaxWarning)

            for name, le_regex in self.STATEMENT_REGEXES.items():
                if (match := le_regex.match(line)):
                    getattr(self, f'_parse_{name}')(match.groupdict())
                    line = line[match.end(0):]
                    break

            else:
                warnings.warn(f'Unknown statement found: "{line}", ignoring.', SyntaxWarning)
                self.target.comments.append(f'Unknown statement found: "{line}", ignoring.')
        
        self.target.apertures = list(self.aperture_map.values())
        self.target.import_settings = self.file_settings
        self.target.unit = self.file_settings.unit

        if not self.eof_found:
                    warnings.warn('File is missing mandatory M02 EOF marker. File may be truncated.', SyntaxWarning)

    def _parse_interpolation_mode(self, match):
        if match['code'] == 'G01':
            self.graphics_state.interpolation_mode = LinearModeStmt
        elif match['code'] == 'G02':
            self.graphics_state.interpolation_mode = CircularCWModeStmt
        elif match['code'] == 'G03':
            self.graphics_state.interpolation_mode = CircularCCWModeStmt
        elif match['code'] == 'G74':
            self.multi_quadrant_mode = True # used only for syntax checking
        elif match['code'] == 'G75':
            self.multi_quadrant_mode = False
            # we always emit a G75 at the beginning of the file.

    def _parse_coord(self, match):
        x = self.file_settings.parse_gerber_value(match['x'])
        y = self.file_settings.parse_gerber_value(match['y'])
        i = self.file_settings.parse_gerber_value(match['i'])
        j = self.file_settings.parse_gerber_value(match['j'])

        if not (op := match['operation']):
            if self.last_operation == 'D01':
                warnings.warn('Coordinate statement without explicit operation code. This is forbidden by spec.',
                        SyntaxWarning)
                op = 'D01'
            else:
                raise SyntaxError('Ambiguous coordinate statement. Coordinate statement does not have an operation '\
                                  'mode and the last operation statement was not D01.')

        self.last_operation = op

        if op in ('D1', 'D01'):
            if self.graphics_state.interpolation_mode != LinearModeStmt:
                if self.multi_quadrant_mode is None:
                    warnings.warn('Circular arc interpolation without explicit G75 Single-Quadrant mode statement. '\
                            'This can cause problems with older gerber interpreters.', SyntaxWarning)

                elif self.multi_quadrant_mode:
                    raise SyntaxError('Circular arc interpolation in multi-quadrant mode (G74) is not implemented.')

            if self.current_region is None:
                self.target.objects.append(self.graphics_state.interpolate(x, y, i, j))
            else:
                self.current_region.append(self.graphics_state.interpolate(x, y, i, j, aperture=False))

        else:
            if i is not None or j is not None:
                raise SyntaxError("i/j coordinates given for D02/D03 operation (which doesn't take i/j)")
                
            if op in ('D2', 'D02'):
                self.graphics_state.update_point(x, y)
                if self.current_region:
                    # Start a new region for every outline. As gerber has no concept of fill rules or winding numbers,
                    # it does not make a graphical difference, and it makes the implementation slightly easier.
                    self.target.objects.append(self.current_region)
                    self.current_region = go.Region(
                            polarity_dark=self.graphics_state.polarity_dark,
                            unit=self.file_settings.unit)

            else: # D03
                if self.current_region is None:
                    self.target.objects.append(self.graphics_state.flash(x, y))
                else:
                    raise SyntaxError('DO3 flash statement inside region')

    def _parse_aperture(self, match):
        number = int(match['number'])
        if number < 10:
            raise SyntaxError(f'Invalid aperture number {number}: Aperture number must be >= 10.')

        if number not in self.aperture_map:
            raise SyntaxError(f'Tried to access undefined aperture {number}')

        self.graphics_state.aperture = self.aperture_map[number]

    def _parse_aperture_definition(self, match):
        # number, shape, modifiers
        modifiers = [ float(val) for val in match['modifiers'].split('X') ] if match['modifiers'].strip() else []

        aperture_classes = {
                'C': apertures.CircleAperture,
                'R': apertures.RectangleAperture,
                'O': apertures.ObroundAperture,
                'P': apertures.PolygonAperture,
            }

        if (kls := aperture_classes.get(match['shape'])):
            if match['shape'] == 'P' and math.isclose(modifiers[0], 0):
                warnings.warn('Definition of zero-size polygon aperture. This is invalid according to spec.' , SyntaxWarning)

            if match['shape'] in 'RO' and (math.isclose(modifiers[0], 0) or math.isclose(modifiers[1], 0)):
                warnings.warn('Definition of zero-width and/or zero-height rectangle or obround aperture. This is invalid according to spec.' , SyntaxWarning)

            new_aperture = kls(*modifiers, unit=self.file_settings.unit)

        elif (macro := self.aperture_macros.get(match['shape'])):
            new_aperture = apertures.ApertureMacroInstance(macro, modifiers, unit=self.file_settings.unit)

        else:
            raise ValueError(f'Aperture shape "{match["shape"]}" is unknown')

        self.aperture_map[int(match['number'])] = new_aperture

    def _parse_aperture_macro(self, match):
        self.aperture_macros[match['name']] = ApertureMacro.parse_macro(
                match['name'], match['macro'], self.file_settings.unit)
    
    def _parse_format_spec(self, match):
        # This is a common problem in Eagle files, so just suppress it
        self.file_settings.zeros = {'L': 'leading', 'T': 'trailing'}.get(match['zero'], 'leading')
        self.file_settings.notation = 'incremental' if match['notation'] == 'I' else 'absolute'

        if match['x'] != match['y']:
            raise SyntaxError(f'FS specifies different coordinate formats for X and Y ({match["x"]} != {match["y"]})')
        self.file_settings.number_format = int(match['x'][0]), int(match['x'][1])

    def _parse_unit_mode(self, match):
        if match['unit'] == 'MM':
            self.file_settings.unit = MM
        else:
            self.file_settings.unit = Inch

    def _parse_load_polarity(self, match):
        self.graphics_state.polarity_dark = match['polarity'] == 'D'

    def _parse_offset(self, match):
        a, b = match['a'], match['b']
        a = float(a) if a else 0
        b = float(b) if b else 0
        self.graphics_state.offset = a, b

    def _parse_include_file(self, match):
        if self.include_dir is None:
            warnings.warn('IF include statement found, but includes are deactivated.', ResourceWarning)
        else:
            warnings.warn('IF include statement found. Includes are activated, but is this really a good idea?', ResourceWarning)

        include_file = self.include_dir / param["filename"]
        # Do not check if path exists to avoid leaking existence via error message
        include_file = include_file.resolve(strict=False)
        
        if not include_file.is_relative_to(self.include_dir):
            raise FileNotFoundError('Attempted traversal to parent of include dir in path from IF include statement')

        if not include_file.is_file():
            raise FileNotFoundError('File pointed to by IF include statement does not exist')

        if include_file in self.include_stack:
            raise ValueError("Recusive inclusion via IF include statement.")
        self.include_stack.append(include_file)

        # Spec 2020-09 section 3.1: Gerber files must use UTF-8
        self._parse(f.read_text(encoding='UTF-8'))
        self.include_stack.pop()

    def _parse_image_name(self, match):
        warnings.warn('Deprecated IN (image name) statement found. This deprecated since rev. I4 (Oct 2013).', DeprecationWarning)
        self.target.comments.append(f'Image name: {match["name"]}')

    def _parse_load_name(self, match):
        warnings.warn('Deprecated LN (load name) statement found. This deprecated since rev. I4 (Oct 2013).', DeprecationWarning)

    def _parse_axis_selection(self, match):
        warnings.warn('Deprecated AS (axis selection) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)
        self.graphics_state.output_axes = match['axes']

    def _parse_image_polarity(self, match):
        # Do not warn, this is still common.
        # warnings.warn('Deprecated IP (image polarity) statement found. This deprecated since rev. I4 (Oct 2013).',
        #         DeprecationWarning)
        self.graphics_state.image_polarity = dict(POS='positive', NEG='negative')[match['polarity']]
    
    def _parse_image_rotation(self, match):
        warnings.warn('Deprecated IR (image rotation) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)
        self.graphics_state.image_rotation = int(match['rotation'])

    def _parse_mirror_image(self, match):
        warnings.warn('Deprecated MI (mirror image) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)
        self.graphics_state.mirror = bool(int(match['a'] or '0')), bool(int(match['b'] or '1'))

    def _parse_scale_factor(self, match):
        warnings.warn('Deprecated SF (scale factor) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)
        a = float(match['a']) if match['a'] else 1.0
        b = float(match['b']) if match['b'] else 1.0
        self.graphics_state.scale_factor = a, b

    def _parse_comment(self, match):
        self.target.comments.append(match["comment"])

    def _parse_region_start(self, _match):
        self.current_region = go.Region(
                polarity_dark=self.graphics_state.polarity_dark,
                unit=self.file_settings.unit)

    def _parse_region_end(self, _match):
        if self.current_region is None:
            raise SyntaxError('Region end command (G37) outside of region')
        
        if self.current_region: # ignore empty regions
            self.target.objects.append(self.current_region)
        self.current_region = None

    def _parse_old_unit(self, match):
        self.file_settings.unit = Inch if match['mode'] == 'G70' else MM
        warnings.warn(f'Deprecated {match["mode"]} unit mode statement found. This deprecated since 2012.', DeprecationWarning)
        self.target.comments.append('Replaced deprecated {match["mode"]} unit mode statement with MO statement')

    def _parse_old_notation(self, match):
        # FIXME make sure we always have FS at end of processing.
        self.file_settings.notation = 'absolute' if match['mode'] == 'G90' else 'incremental'
        warnings.warn(f'Deprecated {match["mode"]} notation mode statement found. This deprecated since 2012.', DeprecationWarning)
        self.target.comments.append('Replaced deprecated {match["mode"]} notation mode statement with FS statement')
    
    def _parse_eof(self, _match):
        self.eof_found = True

    def _parse_ignored(self, match):
        pass


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

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('testfile')
    args = parser.parse_args()

    print(GerberFile.open(args.testfile).to_gerber())

