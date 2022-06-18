#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Modified from parser.py by Paulo Henrique Silva <ph.silva@gmail.com>
# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>
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

import re
import math
import warnings
from pathlib import Path
import dataclasses

from .cam import CamFile, FileSettings
from .utils import MM, Inch, units, InterpMode, UnknownStatementWarning
from .aperture_macros.parse import ApertureMacro, GenericMacros
from . import graphic_primitives as gp
from . import graphic_objects as go
from . import apertures
from .excellon import ExcellonFile


def points_close(a, b):
    if a == b:
        return True
    elif a is None or b is None:
        return False
    elif None in a or None in b:
        return False
    else:
        return math.isclose(a[0], b[0]) and math.isclose(a[1], b[1])

class GerberFile(CamFile):
    """ A single gerber file.
    """

    def __init__(self, objects=None, comments=None, import_settings=None, original_path=None, generator_hints=None,
            layer_hints=None, file_attrs=None):
        super().__init__(original_path=original_path)
        self.objects = objects or []
        self.comments = comments or []
        self.generator_hints = generator_hints or []
        self.layer_hints = layer_hints or []
        self.import_settings = import_settings
        self.apertures = [] # FIXME get rid of this? apertures are already in the objects.
        self.file_attrs = file_attrs or {}

    def to_excellon(self, plated=None):
        new_objs = []
        new_tools = {}
        for obj in self.objects:
            if (not isinstance(obj, go.Line) and isinstance(obj, go.Arc) and isinstance(obj, go.Flash)) or \
                not isinstance(obj.aperture, apertures.CircleAperture):
                raise ValueError(f'Cannot convert {obj} to excellon!')

            if not (new_tool := new_tools.get(id(obj.aperture))):
                # TODO plating?
                new_tool = new_tools[id(obj.aperture)] = apertures.ExcellonTool(obj.aperture.diameter, plated=plated, unit=obj.aperture.unit)
            new_objs.append(dataclasses.replace(obj, aperture=new_tool))
            
        return ExcellonFile(objects=new_objs, comments=self.comments)

    def to_gerber(self):
        return

    def merge(self, other, mode='above', keep_settings=False):
        if other is None:
            return

        if not keep_settings:
            self.import_settings = None
        self.comments += other.comments

        # dedup apertures
        new_apertures = {}
        replace_apertures = {}
        mock_settings = FileSettings()
        for ap in self.apertures + other.apertures:
            gbr = ap.to_gerber(mock_settings)
            if gbr not in new_apertures:
                new_apertures[gbr] = ap
            else:
                replace_apertures[id(ap)] = new_apertures[gbr]
        self.apertures = list(new_apertures.values())

        # Join objects
        if mode == 'below':
            self.objects = other.objects + self.objects
        elif mode == 'above':
            self.objects += other.objects
        else:
            raise ValueError(f'Invalid mode "{mode}", must be one of "above" or "below".')
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
        # TODO add tests for this
        self.apertures = [ aperture.dilated(offset, unit) for aperture in self.apertures ]

        offset_circle = apertures.CircleAperture(offset, unit=unit)
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
        """ Load a Gerber file from the file system. The Gerber standard contains this wonderful and totally not
        insecure "include file" setting. We disable it by default and do not parse Gerber includes because a) nobody
        actually uses them, and b) they're a bad idea from a security point of view. In case you actually want these,
        you can enable them by setting ``enable_includes=True``.

        :param filename: str or :py:class:`pathlib.Path`
        :param bool enable_includes: Enable Gerber ``IF`` statement includes (default *off*, recommended *off*)
        :param enable_include_dir: str or :py:class:`pathlib.Path`. Override base dir for include files.

        :rtype: :py:class:`.GerberFile`
        """
        filename = Path(filename)
        with open(filename, "r") as f:
            if enable_includes and enable_include_dir is None:
                enable_include_dir = filename.parent
            return kls.from_string(f.read(), enable_include_dir, filename=filename)

    @classmethod
    def from_string(kls, data, enable_include_dir=None, filename=None):
        """ Parse given string as Gerber file content. For the meaning of the parameters, see
        :py:meth:`~.GerberFile.open`. """
        # filename arg is for error messages
        obj = kls()
        GerberParser(obj, include_dir=enable_include_dir).parse(data, filename=filename)
        return obj

    def _generate_statements(self, settings, drop_comments=True):
        """ Export this file as Gerber code, yields one str per line. """
        yield 'G04 Gerber file generated by Gerbonara*'
        for name, value in self.file_attrs.items():
            attrdef = ','.join([name, *map(str, value)])
            yield f'%TF{attrdef}*%'
        yield '%MOMM*%' if (settings.unit == 'mm') else '%MOIN*%'

        zeros = 'T' if settings.zeros == 'trailing' else 'L' # default to leading if "None" is specified
        notation = 'I' if settings.notation == 'incremental' else 'A' # default to absolute
        number_format = str(settings.number_format[0]) + str(settings.number_format[1])
        yield f'%FS{zeros}{notation}X{number_format}Y{number_format}*%'
        yield '%IPPOS*%'
        yield 'G75'
        yield '%LPD*%'

        if not drop_comments:
            yield 'G04 Comments from original gerber file:*'
            for cmt in self.comments:
                yield f'G04{cmt}*'

        # Always emit gerbonara's generic, rotation-capable aperture macro replacements for the standard C/R/O/P shapes.
        # Unconditionally emitting these here is easier than first trying to figure out if we need them later,
        # and they are only a few bytes anyway.
        am_stmt = lambda macro: f'%AM{macro.name}*\n{macro.to_gerber(unit=settings.unit)}*\n%'
        for macro in [ GenericMacros.circle, GenericMacros.rect, GenericMacros.obround, GenericMacros.polygon ]:
            yield am_stmt(macro)

        processed_macros = set()
        aperture_map = {}
        for number, aperture in enumerate(self.apertures, start=10):

            if isinstance(aperture, apertures.ApertureMacroInstance):
                macro_def = am_stmt(aperture._rotated().macro)
                if macro_def not in processed_macros:
                    processed_macros.add(macro_def)
                    yield macro_def

            yield f'%ADD{number}{aperture.to_gerber(settings)}*%'

            aperture_map[id(aperture)] = number

        def warn(msg, kls=SyntaxWarning):
            warnings.warn(msg, kls)

        gs = GraphicsState(warn=warn, aperture_map=aperture_map, file_settings=settings)
        for primitive in self.objects:
            yield from primitive.to_statements(gs)

        yield 'M02*'

    def __str__(self):
        name = f'{self.original_path.name} ' if self.original_path else ''
        return f'<GerberFile {name}with {len(self.apertures)} apertures, {len(self.objects)} objects>'

    def __repr__(self):
        return str(self)

    def save(self, filename, settings=None, drop_comments=True):
        """ Save this Gerber file to the file system. See :py:meth:`~.GerberFile.generate_gerber` for the meaning
        of the arguments. """
        with open(filename, 'wb') as f: # Encoding is specified as UTF-8 by spec.
            f.write(self.write_to_bytes(settings, drop_comments=drop_comments))

    def write_to_bytes(self, settings=None, drop_comments=True):
        """ Export to Gerber format. Uses either the file's original settings or sane default settings if you don't give
        any.

        :param FileSettings settings: override export settings.
        :param bool drop_comments: If true, do not write comments to output file. This defaults to true because
                otherwise there is a risk that Gerbonara does not consider some obscure magic comment semantically
                meaningful while some other Excellon viewer might still parse it.
        
        :rtype: str
        """
        if settings is None:
            settings = self.import_settings.copy() or FileSettings()
            settings.zeros = None
            settings.number_format = (5,6)
        return '\n'.join(self._generate_statements(settings, drop_comments=drop_comments)).encode('utf-8')

    def __len__(self):
        return len(self.objects)

    def offset(self, dx=0,  dy=0, unit=MM):
        # TODO round offset to file resolution
        for obj in self.objects:
            obj.offset(dx, dy, unit)

    def rotate(self, angle:'radian', center=(0,0), unit=MM):
        if math.isclose(angle % (2*math.pi), 0):
            return

        # First, rotate apertures. We do this separately from rotating the individual objects below to rotate each
        # aperture exactly once.
        for ap in self.apertures:
            ap.rotation += angle

        for obj in self.objects:
            obj.rotate(angle, *center, unit)

    def invert_polarity(self):
        """ Invert the polarity (color) of each object in this file. """
        for obj in self.objects:
            obj.polarity_dark = not p.polarity_dark
    

class GraphicsState:
    """ Internal class used to track Gerber processing state during import and export. """

    def __init__(self, warn, file_settings=None, aperture_map=None):
        self.image_polarity = 'positive' # IP image polarity; deprecated
        self.polarity_dark = True
        self.point = None
        self.aperture = None
        self.interpolation_mode = InterpMode.LINEAR
        self.multi_quadrant_mode = None # used only for syntax checking
        self.aperture_mirroring = (False, False) # LM mirroring (x, y)
        self.aperture_rotation = 0 # LR rotation in degree, ccw
        self.aperture_scale = 1 # LS scale factor, NOTE: same for both axes
        # The following are deprecated file-wide settings. We normalize these during parsing.
        self.image_offset = (0, 0)
        self.image_rotation = 0 # IR image rotation in degree ccw, one of 0, 90, 180 or 270; deprecated
        self.image_mirror = (False, False) # IM image mirroring, (x, y); deprecated
        self.image_scale = (1.0, 1.0) # SF image scaling (x, y); deprecated
        self._mat = None
        self.file_settings = file_settings
        self.unit = file_settings.unit if file_settings else None
        self.aperture_map = aperture_map or {}
        self.warn = warn
        self.unit_warning = False
        self.object_attrs = {}

    @property
    def polarity_dark(self):
        return self._polarity_dark

    @polarity_dark.setter
    def polarity_dark(self, value):
        if self.image_polarity == 'negative':
            self._polarity_dark = not value

        else:
            self._polarity_dark = value

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
        if self.unit is None:
            raise SyntaxError('Gerber file does not contain a unit definition.')
        self.update_point_native(x, y)
        obj = go.Flash(*self.map_coord(*self.point), self.aperture,
                polarity_dark=self._polarity_dark,
                unit=self.unit,
                attrs=self.object_attrs)
        return obj

    def interpolate(self, x, y, i=None, j=None, aperture=True, multi_quadrant=False):
        old_point = self.map_coord(*self.update_point_native(x, y))

        if (unit := self.unit) is None:
            raise SyntaxError('Gerber file does not contain a unit definition.')

        if aperture:
            if (aperture := self.aperture) is None:
                raise SyntaxError('Interpolation attempted without selecting aperture first')

            if math.isclose(aperture.equivalent_width(), 0):
                self.warn('D01 interpolation with a zero-size aperture. This is invalid according to spec, '
                        'however, we pass through the created objects here. Note that these will not show up in e.g. '
                        'SVG output since their line width is zero.')

        else:
            aperture = None

        if self.interpolation_mode == InterpMode.LINEAR:
            if i is not None or j is not None:
                raise SyntaxError("i/j coordinates given for linear D01 operation (which doesn't take i/j)")

            return go.Line(*old_point, *self.map_coord(*self.point), aperture,
                    polarity_dark=self._polarity_dark, unit=unit, attrs=self.object_attrs)

        else:
            if i is None and j is None:
                self.warn('Linear segment implied during arc interpolation mode through D01 w/o I, J values')
                return go.Line(*old_point, *self.map_coord(*self.point), aperture,
                        polarity_dark=self._polarity_dark, unit=unit, attrs=self.object_attrs)

            else:
                if i is None:
                    self.warn('Arc is missing I value')
                    i = 0

                if j is None:
                    self.warn('Arc is missing J value')
                    j = 0

                clockwise = self.interpolation_mode == InterpMode.CIRCULAR_CW
                new_point = self.map_coord(*self.point)

                if not multi_quadrant:
                    return go.Arc(*old_point, *new_point, *self.map_coord(i, j, relative=True),
                            clockwise=clockwise, aperture=(self.aperture if aperture else None),
                            polarity_dark=self._polarity_dark, unit=unit, attrs=self.object_attrs)

                else:
                    if math.isclose(old_point[0], new_point[0]) and math.isclose(old_point[1], new_point[1]):
                        # In multi-quadrant mode, an arc with identical start and end points is not rendered at all. Only in
                        # single-quadrant mode it is rendered as a full circle.
                        return None

                    # Super-legacy. No one uses this EXCEPT everything that mentor graphics / siemens make uses this m(
                    (cx, cy) = self.map_coord(i, j, relative=True)

                    arc = lambda cx, cy: go.Arc(*old_point, *new_point, cx, cy,
                            clockwise=clockwise, aperture=aperture,
                            polarity_dark=self._polarity_dark, unit=unit, attrs=self.object_attrs)
                    arcs = [ arc(cx, cy), arc(-cx, cy), arc(cx, -cy), arc(-cx, -cy) ]
                    arcs = sorted(arcs, key=lambda a: a.numeric_error())

                    for a in arcs:
                        d = gp.point_line_distance(old_point, new_point, (old_point[0]+a.cx, old_point[1]+a.cy))
                        if (d > 0) == clockwise:
                            return a
                    assert False

    def update_point(self, x, y, unit=None):
        return self.update_point_native(MM(x, unit), MM(y, unit))

    def update_point_native(self, x, y):
        old_point = self.point
        if (x is None or y is None) and old_point is None:
            self.warn('Coordinate omitted from first coordinate statement in the file. This is likely a Siemens '
                    'file. We pretend the omitted coordinate was 0.')

        if old_point is None:
            old_point = self.point = (0, 0)

        if x is None:
            x = old_point[0]

        if y is None:
            y = old_point[1]

        self.point = (x, y)
        return old_point

    # Helpers for gerber generation
    def set_polarity(self, polarity_dark):
        # breaks if image_polarity is not positive, but that cannot happen during export. 
        if self.polarity_dark != polarity_dark:
            self.polarity_dark = polarity_dark
            yield '%LPD*%' if polarity_dark else '%LPC*%'

    def set_aperture(self, aperture):
        if self.aperture != aperture:
            self.aperture = aperture
            yield f'D{self.aperture_map[id(aperture)]}*'

    def set_current_point(self, point, unit=None):
        point_mm = MM(point[0], unit), MM(point[1], unit)
        # TODO calculate appropriate precision for math.isclose given file_settings.notation

        if not points_close(self.point, point_mm):
            self.point = point_mm
            x = self.file_settings.write_gerber_value(point[0], unit=unit)
            y = self.file_settings.write_gerber_value(point[1], unit=unit)
            yield f'X{x}Y{y}D02*'

    def set_interpolation_mode(self, mode):
        if self.interpolation_mode != mode:
            self.interpolation_mode = mode
            yield self.interpolation_mode_statement()

    def interpolation_mode_statement(self):
        return {
                InterpMode.LINEAR: 'G01',
                InterpMode.CIRCULAR_CW: 'G02',
                InterpMode.CIRCULAR_CCW: 'G03'}[self.interpolation_mode]


class GerberParser:
    """ Internal class that contains all of the actual Gerber parsing magic. """

    NUMBER = r"[\+-]?\d+"
    DECIMAL = r"[\+-]?\d+([.]?\d+)?"
    NAME = r"[a-zA-Z_$\.][a-zA-Z_$\.0-9+\-]+"

    STATEMENT_REGEXES = {
        'coord': fr"(G0?[123]|G74|G75|G54|G55)?\s*(?:X\+?(-?)({NUMBER}))?(?:Y\+?(-?)({NUMBER}))?" \
            fr"(?:I\+?(-?)({NUMBER}))?(?:J\+?(-?)({NUMBER}))?\s*" \
            fr"(?:D0?([123]))?$",
        'region_start': r'G36$',
        'region_end': r'G37$',
        'aperture': r"(G54|G55)?\s*D(?P<number>\d+)",
        # Allegro combines format spec and unit into one long illegal extended command.
        'allegro_format_spec': r"FS(?P<zero>(L|T|D))?(?P<notation>(A|I))[NG0-9]*X(?P<x>[0-7][0-7])Y(?P<y>[0-7][0-7])[DM0-9]*\*MO(?P<unit>IN|MM)",
        'unit_mode': r"MO(?P<unit>(MM|IN))",
        'format_spec': r"FS(?P<zero>(L|T|D))?(?P<notation>(A|I))[NG0-9]*X(?P<x>[0-7][0-7])Y(?P<y>[0-7][0-7])[DM0-9]*",
        'allegro_legacy_params': fr'^IR(?P<rotation>[0-9]+)\*IP(?P<polarity>(POS|NEG))\*OF(A(?P<a>{DECIMAL}))?(B(?P<b>{DECIMAL}))?\*MI(A(?P<ma>0|1))?(B(?P<mb>0|1))?\*SF(A(?P<sa>{DECIMAL}))?(B(?P<sb>{DECIMAL}))?',
        'load_polarity': r"LP(?P<polarity>(D|C))",
        # FIXME LM, LR, LS
        'load_name': r"LN(?P<name>.*)",
        'offset': fr"OF(A(?P<a>{DECIMAL}))?(B(?P<b>{DECIMAL}))?",
        'include_file': r"IF(?P<filename>.*)",
        'image_name': r"^IN(?P<name>.*)",
        'axis_selection': r"^AS(?P<axes>AXBY|AYBX)",
        'image_polarity': r"^IP(?P<polarity>(POS|NEG))",
        'image_rotation': fr"^IR(?P<rotation>{NUMBER})",
        'mirror_image': r"^MI(A(?P<ma>0|1))?(B(?P<mb>0|1))?",
        'scale_factor': fr"^SF(A(?P<sa>{DECIMAL}))?(B(?P<sb>{DECIMAL}))?",
        'aperture_definition': fr"ADD(?P<number>\d+)(?P<shape>C|R|O|P|{NAME})(,(?P<modifiers>[^,%]*))?$",
        'aperture_macro': fr"AM(?P<name>{NAME})\*(?P<macro>[^%]*)",
        'siemens_garbage': r'^ICAS$',
        'old_unit':r'(?P<mode>G7[01])',
        'old_notation': r'(?P<mode>G9[01])',
        'eof': r"M0?[02]",
        'ignored': r"(?P<stmt>M01)",
        # NOTE: The official spec says names can be empty or contain commas. I think that doesn't make sense.
        'attribute': r"(?P<eagle_garbage>G04 #@! %)?(?P<type>TF|TA|TO|TD)(?P<name>[._$a-zA-Z][._$a-zA-Z0-9]*)?(,(?P<value>.*))?",
        # Eagle file attributes handled above.
        'comment': r"G0?4(?P<comment>[^*]*)",
        }

    def __init__(self, target, include_dir=None):
        """ Pass an include dir to enable IF include statements (potentially DANGEROUS!). """
        self.target = target
        self.include_dir = include_dir
        self.include_stack = []
        self.file_settings = FileSettings()
        self.graphics_state = GraphicsState(warn=self.warn, file_settings=self.file_settings)
        self.aperture_map = {}
        self.aperture_macros = {}
        self.current_region = None
        self.eof_found = False
        self.multi_quadrant_mode = None # used only for syntax checking
        self.macros = {}
        self.last_operation = None
        self.generator_hints = []
        self.layer_hints = []
        self.file_attrs = {}
        self.aperture_attrs = {}
        self.filename = None
        self.line = None
        self.lineno = 0

    def _shorten_line(self):
        line_joined = self.line.replace('\r', '').replace('\n', '\\n')
        if len(line_joined) > 80:
            return f'{line_joined[:20]}[...]{line_joined[-20:]}'
        else:
            return line_joined

    def warn(self, msg, kls=SyntaxWarning):
        warnings.warn(f'{self.filename}:{self.lineno} "{self._shorten_line()}": {msg}', kls)

    def _split_commands(self, data):
        # Ignore '%' signs within G04 commments because eagle likes to put completely broken file attributes inside G04
        # comments, and those contain % signs. Best of all, they're not even balanced.
        self.lineno = 1
        for match in re.finditer(r'G04.*?\*\s*|%.*?%\s*|[^*%]*\*\s*', data, re.DOTALL):
            cmd = match[0]
            newlines = cmd.count('\n')
            cmd = cmd.strip().strip('%').rstrip('*')
            if cmd:
                # Expensive, but only used in case something goes wrong.
                self.line = cmd
                yield cmd
            self.lineno += newlines
        self.lineno = 0
        self.line = ''

    def parse(self, data, filename=None):
        # filename arg is for error messages
        filename = self.filename = filename or '<unknown>'

        regex_cache = [ (re.compile(exp), getattr(self, f'_parse_{name}')) for name, exp in self.STATEMENT_REGEXES.items() ]

        for line in self._split_commands(data):
            #if self.eof_found:
            #    self.warn('Data found in gerber file after EOF.')

            for le_regex, fun in regex_cache:
                if (match := le_regex.match(line)):
                    try:
                        fun(match)
                    except Exception as e:
                        raise SyntaxError(f'{filename}:{self.lineno} "{self._shorten_line()}": {e}') from e
                    line = line[match.end(0):]
                    break

            else:
                self.warn(f'Unknown statement found: "{self._shorten_line()}", ignoring.', UnknownStatementWarning)
                self.target.comments.append(f'Unknown statement found: "{self._shorten_line()}", ignoring.')
        
        self.target.apertures = list(self.aperture_map.values())
        self.target.import_settings = self.file_settings
        self.target.unit = self.file_settings.unit
        self.target.file_attrs = self.file_attrs
        self.target.original_path = filename

        if not self.eof_found:
                    self.warn('File is missing mandatory M02 EOF marker. File may be truncated.')

    def _parse_coord(self, match):
        interp, x_s, x, y_s, y, i_s, i, j_s, j, op = match.groups() # faster than name-based group access
        has_coord = x or y or i or j

        if not interp:
            pass # performance hack, error out early before descending into if/else chain
        elif interp == 'G01':
            self.graphics_state.interpolation_mode = InterpMode.LINEAR
        elif interp == 'G02':
            self.graphics_state.interpolation_mode = InterpMode.CIRCULAR_CW
        elif interp == 'G03':
            self.graphics_state.interpolation_mode = InterpMode.CIRCULAR_CCW
        elif interp == 'G74':
            self.multi_quadrant_mode = True # used only for syntax checking
            if has_coord:
                raise SyntaxError('G74/G75 combined with coord')
        elif interp == 'G75':
            self.multi_quadrant_mode = False
            if has_coord:
                raise SyntaxError('G74/G75 combined with coord')
        elif interp == 'G54':
            pass # ignore.
        elif interp == 'G55':
            self.generator_hints.append('zuken')

        x = self.file_settings.parse_gerber_value(x)
        if x_s:
            x = -x
        y = self.file_settings.parse_gerber_value(y)
        if y_s:
            y = -y

        if not op and has_coord:
            if self.last_operation == '1':
                self.warn('Coordinate statement without explicit operation code. This is forbidden by spec.')
                op = '1'

            else:
                if 'siemens' in self.generator_hints:
                    self.warn('Ambiguous coordinate statement. Coordinate statement does not have an operation '\
                                  'mode and the last operation statement was not D01. This is garbage, and forbidden '\
                                  'by spec. but since this looks like a Siemens/Mentor Graphics file, we will let it '\
                                  'slide and treat this as the same as the last operation.')
                    # Yes, we repeat the last op, and don't do a D01. This is confirmed by
                    # resources/siemens/80101_0125_F200_L12_Bottom.gdo which contains an implicit-double-D02
                    op = self.last_operation
                else:
                    raise SyntaxError('Ambiguous coordinate statement. Coordinate statement does not have an '\
                            'operation mode and the last operation statement was not D01. This is garbage, and '\
                            'forbidden by spec.')

        self.last_operation = op

        if op == '1':
            if self.graphics_state.interpolation_mode != InterpMode.LINEAR:
                if self.multi_quadrant_mode is None:
                    self.warn('Circular arc interpolation without explicit G75 Single-Quadrant mode statement. '\
                            'This can cause problems with older gerber interpreters.')

                elif self.multi_quadrant_mode:
                    self.warn('Deprecated G74 multi-quadant mode arc found. G74 is bad and you should feel bad.')

            i = self.file_settings.parse_gerber_value(i)
            if i_s:
                i = -i
            j = self.file_settings.parse_gerber_value(j)
            if j_s:
                j = -j

            if self.current_region is None:
                # in multi-quadrant mode this may return None if start and end point of the arc are the same.
                obj = self.graphics_state.interpolate(x, y, i, j, multi_quadrant=self.multi_quadrant_mode)
                if obj is not None:
                    self.target.objects.append(obj)
            else:
                obj = self.graphics_state.interpolate(x, y, i, j, aperture=False, multi_quadrant=self.multi_quadrant_mode)
                if obj is not None:
                    self.current_region.append(obj)

        elif op == '2':
            self.graphics_state.update_point_native(x, y)
            if self.current_region:
                # Start a new region for every outline. As gerber has no concept of fill rules or winding numbers,
                # it does not make a graphical difference, and it makes the implementation slightly easier.
                self.target.objects.append(self.current_region)
                self.current_region = go.Region(
                        polarity_dark=self.graphics_state.polarity_dark,
                        unit=self.file_settings.unit)

        elif op == '3':
            if self.current_region is None:
                self.target.objects.append(self.graphics_state.flash(x, y))
            else:
                raise SyntaxError('DO3 flash statement inside region')

        else:
            # Do nothing if there is no explicit D code.
            pass

    def _parse_aperture(self, match):
        number = int(match['number'])
        if number < 10:
            raise SyntaxError(f'Invalid aperture number {number}: Aperture number must be >= 10.')

        if number not in self.aperture_map:
            if number == 10 and 'zuken' in self.generator_hints:
                self.warn(f'Tried to access undefined aperture D10. This looks like a Zuken CR-8000 file. For these '
                            'files, it is normal that an undefined aperture is used for region specifications.')
            else:
                raise SyntaxError(f'Tried to access undefined aperture {number}')

        self.graphics_state.aperture = self.aperture_map[number]

    def _parse_aperture_definition(self, match):
        # number, shape, modifiers
        modifiers = [ float(val) for val in match['modifiers'].strip(' ,').split('X') ] if match['modifiers'] else []
        number = int(match['number'])

        aperture_classes = {
                'C': apertures.CircleAperture,
                'R': apertures.RectangleAperture,
                'O': apertures.ObroundAperture,
                'P': apertures.PolygonAperture,
            }

        if (kls := aperture_classes.get(match['shape'])):
            if match['shape'] == 'P' and math.isclose(modifiers[0], 0):
                self.warn('Definition of zero-size polygon aperture. This is invalid according to spec.' )

            if match['shape'] in 'RO' and (math.isclose(modifiers[0], 0) or math.isclose(modifiers[1], 0)):
                self.warn('Definition of zero-width and/or zero-height rectangle or obround aperture. This is invalid according to spec.' )

            new_aperture = kls(*modifiers, unit=self.file_settings.unit, attrs=self.aperture_attrs.copy(),
                    original_number=number)

        elif (macro := self.aperture_macros.get(match['shape'])):
            new_aperture = apertures.ApertureMacroInstance(macro, modifiers, unit=self.file_settings.unit,
                    attrs=self.aperture_attrs.copy(), original_number=number)

        else:
            raise ValueError(f'Aperture shape "{match["shape"]}" is unknown')

        self.aperture_map[number] = new_aperture

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
            self.graphics_state.unit = self.file_settings.unit = MM
        else:
            self.graphics_state.unit = self.file_settings.unit = Inch

    def _parse_allegro_format_spec(self, match):
        self._parse_format_spec(match)
        self._parse_unit_mode(match)

    def _parse_load_polarity(self, match):
        self.graphics_state.polarity_dark = match['polarity'] == 'D'

    def _parse_offset(self, match):
        a, b = match['a'], match['b']
        a = float(a) if a else 0
        b = float(b) if b else 0
        self.graphics_state.image_offset = a, b

    def _parse_allegro_legacy_params(self, match):
        self._parse_image_rotation(match)
        self._parse_offset(match)
        self._parse_image_polarity(match)
        self._parse_mirror_image(match)
        self._parse_scale_factor(match)

    def _parse_include_file(self, match):
        if self.include_dir is None:
            self.warn('IF include statement found, but includes are deactivated.', ResourceWarning)
        else:
            self.warn('IF include statement found. Includes are activated, but is this really a good idea?', ResourceWarning)

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
        self._parse(f.read_text(encoding='UTF-8'), filename=include_file.name)
        self.include_stack.pop()

    def _parse_image_name(self, match):
        self.warn('Deprecated IN (image name) statement found. This deprecated since rev. I4 (Oct 2013).', DeprecationWarning)
        self.target.comments.append(f'Image name: {match["name"]}')

    def _parse_load_name(self, match):
        self.warn('Deprecated LN (load name) statement found. This deprecated since rev. I4 (Oct 2013).', DeprecationWarning)

    def _parse_axis_selection(self, match):
        if match['axes'] != 'AXBY':
            self.warn('Deprecated AS (axis selection) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)
        self.graphics_state.output_axes = match['axes']

    def _parse_image_polarity(self, match):
        polarity = dict(POS='positive', NEG='negative')[match['polarity']]
        if polarity != 'positive':
            self.warn('Deprecated IP (image polarity) statement found. This deprecated since rev. I4 (Oct 2013).', DeprecationWarning)

        if polarity not in ('positive', 'negative'):
            raise ValueError('image_polarity must be either "positive" or "negative"')

        self.graphics_state.image_polarity = polarity
    
    def _parse_image_rotation(self, match):
        rotation = int(match['rotation'])
        if rotation:
            self.warn('Deprecated IR (image rotation) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)

        if rotation not in [0, 90, 180, 270]:
            raise ValueError('image_rotation must be 0, 90, 180 or 270')

        self.graphics_state.image_rotation = rotation

    def _parse_mirror_image(self, match):
        mirror = bool(int(match['ma'] or '0')), bool(int(match['mb'] or '1'))
        if mirror != (False, False):
            self.warn('Deprecated MI (mirror image) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)

        self.graphics_state.image_mirror = mirror

    def _parse_scale_factor(self, match):
        a = float(match['sa']) if match['sa'] else 1.0
        b = float(match['sb']) if match['sb'] else 1.0
        if not math.isclose(math.dist((a, b), (1, 1)), 0):
            self.warn('Deprecated SF (scale factor) statement found. This deprecated since rev. I1 (Dec 2012).', DeprecationWarning)
        self.graphics_state.image_scale = a, b

    def _parse_siemens_garbage(self, match):
        self.generator_hints.append('siemens')

    def _parse_comment(self, match):
        cmt = match["comment"].strip()

        # Parse metadata from allegro comments
        # We do this for layer identification since allegro files usually do not follow any defined naming scheme
        if cmt.startswith('File Origin:') and 'Allegro' in cmt:
            self.generator_hints.append('allegro')

        elif cmt.startswith('PADS') and 'generated Gerber' in cmt:
            self.generator_hints.append('pads')

        elif cmt.startswith('Layer:'):
            if 'BOARD GEOMETRY' in cmt:
                if 'SOLDERMASK_TOP' in cmt:
                    self.layer_hints.append('top mask')
                if 'SOLDERMASK_BOTTOM' in cmt:
                    self.layer_hints.append('bottom mask')
                if 'PASTEMASK_TOP' in cmt:
                    self.layer_hints.append('top paste')
                if 'PASTEMASK_BOTTOM' in cmt:
                    self.layer_hints.append('bottom paste')
                if 'SILKSCREEN_TOP' in cmt:
                    self.layer_hints.append('top silk')
                if 'SILKSCREEN_BOTTOM' in cmt:
                    self.layer_hints.append('bottom silk')
            elif 'ETCH' in cmt:
                _1, _2, name = cmt.partition('/')
                name = re.sub(r'\W+', '_', name)
                self.layer_hints.append(f'{name} copper')

        elif cmt.startswith('Mentor Graphics'):
            self.generator_hints.append('siemens')

        else:
            self.target.comments.append(cmt)

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
        self.graphics_state.unit = self.file_settings.unit = Inch if match['mode'] == 'G70' else MM
        self.warn(f'Deprecated {match["mode"]} unit mode statement found. This deprecated since 2012.', DeprecationWarning)
        self.target.comments.append('Replaced deprecated {match["mode"]} unit mode statement with MO statement')

    def _parse_old_notation(self, match):
        # FIXME make sure we always have FS at end of processing.
        self.file_settings.notation = 'absolute' if match['mode'] == 'G90' else 'incremental'
        self.warn(f'Deprecated {match["mode"]} notation mode statement found. This deprecated since 2012.', DeprecationWarning)
        self.target.comments.append('Replaced deprecated {match["mode"]} notation mode statement with FS statement')

    def _parse_attribute(self, match):
        if match['type'] == 'TD':
            if match['value']:
                raise SyntaxError('TD attribute deletion command must not contain attribute fields')

            if not match['name']:
                self.graphics_state.object_attrs = {}
                self.aperture_attrs = {}
                return

            if match['name'] in self.file_attrs:
                raise SyntaxError('Attempt to TD delete file attribute. This does not make sense.')
            elif match['name'] in self.graphics_state.object_attrs:
                del self.graphics_state.object_attrs[match['name']]
            elif match['name'] in self.aperture_attrs:
                del self.aperture_attrs[match['name']]
            else:
                raise SyntaxError(f'Attempt to TD delete previously undefined attribute {match["name"]}.')

        else:
            target = {'TF': self.file_attrs, 'TO': self.graphics_state.object_attrs, 'TA': self.aperture_attrs}[match['type']]
            target[match['name']] = match['value'].split(',')

            if 'EAGLE' in self.file_attrs.get('.GenerationSoftware', []) or match['eagle_garbage']:
                self.generator_hints.append('eagle')
    
    def _parse_eof(self, match):
        self.eof_found = True

        if match[0] == 'M00':
            self.generator_hints.append('zuken')

    def _parse_ignored(self, match):
        pass

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('testfile')
    args = parser.parse_args()

    bounds = (0.0, 0.0), (6.0, 6.0) # bottom left, top right
    svg = str(GerberFile.open(args.testfile).to_svg(force_bounds=bounds, arg_unit='inch', fg='white', bg='black'))
    print(svg)

