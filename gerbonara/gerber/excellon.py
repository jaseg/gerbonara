#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import math
import operator
import warnings
import functools
from enum import Enum
from dataclasses import dataclass
from collections import Counter
from pathlib import Path

from .cam import CamFile, FileSettings
from .graphic_objects import Flash, Line, Arc
from .apertures import ExcellonTool
from .utils import Inch, MM, to_unit, InterpMode, RegexMatcher

class ExcellonContext:
    def __init__(self, settings, tools):
        self.settings = settings
        self.tools = tools
        self.mode = None
        self.current_tool = None
        self.x, self.y = None, None

    def select_tool(self, tool):
        if self.current_tool != tool:
            self.current_tool = tool
            yield f'T{tools[tool]:02d}'

    def drill_mode(self):
        if self.mode != ProgramState.DRILLING:
            self.mode = ProgramState.DRILLING
            yield 'G05'

    def route_mode(self, unit, x, y):
        x, y = self.unit(x, unit), self.unit(y, unit)

        if self.mode == ProgramState.ROUTING and (self.x, self.y) == (x, y):
            return # nothing to do

        yield 'G00' + 'X' + self.settings.write_gerber_value(x) + 'Y' + self.settings.write_gerber_value(y)

    def set_current_point(self, unit, x, y):
        self.current_point = self.unit(x, unit), self.unit(y, unit)

def parse_allegro_ncparam(data, settings=None):
    # This function parses data from allegro's nc_param.txt and ncdrill.log files. We have to parse these files because
    # allegro Excellon files omit crucial information such as the *number format*. nc_param.txt really is the file we
    # want to parse, but sometimes due to user error it doesn't end up in the gerber package. In this case, we want to
    # still be able to extract the same information from the human-readable ncdrill.log.

    if settings is None
        self.settings = FileSettings(number_format=(None, None))

    lz_supp, tz_supp = False, False
    for line in data.splitlines():
        line = re.sub('\s+', ' ', line.strip())

        if (match := re.fullmatch(r'FORMAT ([0-9]+\.[0-9]+)', line)):
            x, _, y = match[1].partition('.')
            settings.number_format = int(x), int(y)

        elif (match := re.fullmatch(r'COORDINATES (ABSOLUTE|.*)', line)):
            # I have not been able to find a single incremental-notation allegro file. Probably that is for the better.
            settings.notation = match[1].lower()

        elif (match := re.fullmatch(r'OUTPUT-UNITS (METRIC|ENGLISH|INCHES)', line)):
            # I have no idea wth is the difference between "ENGLISH" and "INCHES". I think one might just be the one
            # Allegro uses in footprint files, with the other one being used in gerber exports.
            settings.unit = MM if match[1] == 'METRIC' else Inch

        elif (match := re.fullmatch(r'SUPPRESS-LEAD-ZEROES (YES|NO)', line)):
            lz_supp = (match[1] == 'YES')

        elif (match := re.fullmatch(r'SUPPRESS-TRAIL-ZEROES (YES|NO)', line)):
            tz_supp = (match[1] == 'YES')

    if lz_supp and tz_supp:
        raise SyntaxError('Allegro Excellon parameters specify both leading and trailing zero suppression. We do not '
                'know how to parse this. Please raise an issue on our issue tracker and provide an example file.')

    settings.zeros = 'leading' if lz_supp else 'trailing'


class ExcellonFile(CamFile):
    def __init__(self, objects=None, comments=None, import_settings=None, filename=None, generator=None):
        super().__init__(filename=filename)
        self.objects = objects or []
        self.comments = comments or []
        self.import_settings = import_settings
        self.generator = generator # This is a purely informational goodie from the parser. Use it as you wish.

    @classmethod
    def open(kls, filename, plated=None):
        filename = Path(filename)
    
        # Parse allegro parameter files.
        # Prefer nc_param.txt over ncparam.log since the txt is the machine-readable one.
        for fn in 'nc_param.txt', 'ncdrill.log':
            if (param_file := filename.parent / fn).isfile():
                settings =  parse_allegro_ncparam(param_file.read_text())
                break
        else:
            settings = None

        return kls.from_string(filename.read_text(), settings=settings, filename=filename, plated=plated)

    @classmethod
    def from_string(kls, data, settings=None, filename=filename, plated=None):
        parser = ExcellonParser(settings)
        parser._do_parse(data)
        return kls(objects=parser.objects, comments=parser.comments, import_settings=settings,
                generator=parser.generator, filename=filename, plated=plated)

    def _generate_statements(self, settings):

        yield '; XNC file generated by gerbonara'
        if self.comments:
            yield '; Comments found in original file:'
        for comment in self.comments:
            yield ';' + comment

        yield 'M48'
        yield 'METRIC' if settings.unit == MM else 'INCH'

        # Build tool index
        tools = set(obj.tool for obj in self.objects)
        tools = sorted(tools, key=lambda tool: (tool.plated, tool.diameter, tool.depth_offset))
        tools = { tool: index for index, tool in enumerate(tools, start=1) }

        if max(tools) >= 100:
            warnings.warn('More than 99 tools defined. Some programs may not like three-digit tool indices.', SyntaxWarning)

        for tool, index in tools.items():
            yield f'T{index:02d}' + tool.to_xnc(settings)

        yield '%'

        # Export objects
        for obj in self.objects:
            obj.to_xnc(ctx)

        yield 'M30'

    def to_excellon(self, settings=None):
        ''' Export to Excellon format. This function always generates XNC, which is a well-defined subset of Excellon.
        '''
        if settings is None:
            settings = self.import_settings.copy() or FileSettings()
            settings.zeros = None
            settings.number_format = (3,5)
        return '\n'.join(self._generate_statements(settings))

    def offset(self, x=0, y=0, unit=MM):
        self.objects = [ obj.with_offset(x, y, unit) for obj in self.objects ]

    def rotate(self, angle, cx=0, cy=0, unit=MM):
        for obj in self.objects:
            obj.rotate(angle, cx, cy, unit=unit)

    @property
    def has_mixed_plating(self):
        return len(set(obj.plated for obj in self.objects)) > 1
    
    @property
    def is_plated(self):
        return all(obj.plated for obj in self.objects)

    @property
    def is_nonplated(self):
        return not any(obj.plated for obj in self.objects)

    def empty(self):
        return self.objects.empty()

    def __len__(self):
        return len(self.objects)

    def split_by_plating(self):
        plated = ExcellonFile(
            comments = self.comments.copy(),
            import_settings = self.import_settings.copy(),
            objects = [ obj for obj in self.objects if obj.plated ],
            filename = self.filename)

        nonplated = ExcellonFile(
            comments = self.comments.copy(),
            import_settings = self.import_settings.copy(),
            objects = [ obj for obj in self.objects if not obj.plated ],
            filename = self.filename)

        return nonplated, plated

    def path_lengths(self, unit):
        """ Calculate path lengths per tool.

        Returns: dict { tool: float(path length) }

        This function only sums actual cut lengths, and ignores travel lengths that the tool is doing without cutting to
        get from one object to another. Travel lengths depend on the CAM program's path planning, which highly depends
        on panelization and other factors. Additionally, an EDA tool will not even attempt to minimize travel distance
        as that's not its job.
        """
        lengths = {}
        tool = None
        for obj in sorted(self.objects, key=lambda obj: obj.tool):
            if tool != obj.tool:
                tool = obj.tool
                lengths[tool] = 0

            lengths[tool] += obj.curve_length(unit)
        return lengths

    def hit_count(self):
        return Counter(obj.tool for obj in self.objects)

    def drill_sizes(self):
        return sorted({ obj.tool.diameter for obj in self.objects })

    @property
    def bounds(self):
        if not self.objects:
            return None

        (x_min, y_min), (x_max, y_max) = self.objects[0].bounding_box()
        for obj in self.objects:
            (obj_x_min, obj_y_min), (obj_x_max, obj_y_max) = self.objects[0].bounding_box()
            x_min, y_min = min(x_min, obj_x_min), min(y_min, obj_y_min)
            x_max, y_max = max(x_max, obj_x_max), max(y_max, obj_y_max)

        return ((x_min, y_min), (x_max, y_max))

class ProgramState(Enum):
    HEADER = 0
    DRILLING = 1
    ROUTING = 2
    FINISHED = 2


class ExcellonParser(object):
    def __init__(self, settings=None):
        # NOTE XNC files do not contain an explicit number format specification, but all values have decimal points.
        # Thus, we set the default number format to (None, None). If the file does not contain an explicit specification
        # and FileSettings.parse_gerber_value encounters a number without an explicit decimal point, it will throw a
        # SyntaxError. In case of e.g. Allegro files where the number format and other options are specified separately
        # from the excellon file, the caller must pass in an already filled-out FileSettings object.
        if settings is None:
            self.settings = FileSettings(number_format=(None, None))
        self.program_state = None
        self.interpolation_mode = InterpMode.LINEAR
        self.tools = {}
        self.objects = []
        self.active_tool = None
        self.pos = 0, 0
        self.drill_down = False
        self.is_plated = None
        self.generator = None

    def _do_parse(self, data):
        leftover = None
        for line in data.splitlines():
            line = line.strip()

            if not line:
                continue

            # Coordinates of G00 and G01 may be on the next line
            if line == 'G00' or line == 'G01':
                if leftover:
                    warnings.warn('Two consecutive G00/G01 commands without coordinates. Ignoring first.', SyntaxWarning)
                leftover = line
                continue

            if leftover:
                line = leftover + line
                leftover = None

            if line and self.program_state == ProgramState.FINISHED:
                warnings.warn('Commands found following end of program statement.', SyntaxWarning)
            # TODO check first command in file is "start of header" command.

            self.exprs.handle(self, line)

    exprs = RegexMatcher()

    # NOTE: These must be kept before the generic comment handler at the end of this class so they match first.
    @exprs.match(';T(?P<index1>[0-9]+) Holesize (?P<index2>[0-9]+)\. = (?P<diameter>[0-9/.]+) Tolerance = \+[0-9/.]+/-[0-9/.]+ (?P<plated>PLATED|NON_PLATED|OPTIONAL) (?P<unit>MILS|MM) Quantity = [0-9]+')
    def parse_allegro_tooldef(self, match):
        # NOTE: We ignore the given tolerances here since they are non-standard.
        self.program_state = ProgramState.HEADER # TODO is this needed? we need a test file.
        self.generator = 'allegro'

        if (index := int(match['index1'])) != int(match['index2']): # index1 has leading zeros, index2 not.
            raise SyntaxError('BUG: Allegro excellon tool def has mismatching tool indices. Please file a bug report on our issue tracker and provide this file!')

        if index in self.tools:
            warnings.warn('Re-definition of tool index {index}, overwriting old definition.', SyntaxWarning) 

        # NOTE: We map "optionally" plated holes to plated holes for API simplicity. If you hit a case where that's a
        # problem, please raise an issue on our issue tracker, explain why you need this and provide an example file.
        is_plated = None if match['plated'] is None else (match['plated'] in ('PLATED', 'OPTIONAL'))

        diameter = float(match['diameter'])

        if match['unit'] == 'MILS':
            diameter /= 1000
            unit = Inch
        else:
            unit = MM

        if unit != self.settings.unit:
            warnings.warn('Allegro Excellon drill file tool definitions in {unit.name}, but file parameters say the '
                    'file should be in {settings.unit.name}. Please double-check that this is correct, and if it is, '
                    'please raise an issue on our issue tracker.', SyntaxWarning)

        self.tools[index] = ExcellonTool(diameter=diameter, plated=is_plated, unit=unit)

    # Searching Github I found that EasyEDA has two different variants of the unit specification here.
    @exprs.match(';Holesize (?P<index>[0-9]+) = (?P<diameter>[.0-9]+) (?P<unit>INCH|inch|METRIC|mm)')
    def parse_easyeda_tooldef(self, match):
        unit = Inch if match['unit'].lower() == 'inch' else MM
        tool = ExcellonTool(diameter=float(match['diameter']), unit=unit, plated=self.is_plated)

        if (index := int(match['index'])) in self.tools:
            warnings.warn('Re-definition of tool index {index}, overwriting old definition.', SyntaxWarning) 

        tools[index] = tool

    @exprs.match('T([0-9]+)(([A-Z][.0-9]+)+)') # Tool definition: T** with at least one parameter
    def parse_normal_tooldef(self, match):
        # We ignore parameters like feed rate or spindle speed that are not used for EDA -> CAM file transfer. This is
        # not a parser for the type of Excellon files a CAM program sends to the machine.

        if (index := int(match[1])) in self.tools:
            warnings.warn('Re-definition of tool index {index}, overwriting old definition.', SyntaxWarning) 

        params = { m[0]: settings.parse_gerber_value(m[1:]) for m in re.findall('[BCFHSTZ][.0-9]+', match[2]) }

        if set(params.keys()) == set('TFSC') and self.generator is None:
            self.generator = 'target3001' # target files look like altium files without the comments
        self.tools[index] = ExcellonTool(diameter=params.get('C'), depth_offset=params.get('Z'), plated=self.is_plated)

    @exprs.match('T([0-9]+)')
    def parse_tool_selection(self, match):
        index = int(match[1])

        if index == 0: # T0 is used as END marker, just ignore
            return
        elif index not in self.tools:
            raise SyntaxError(f'Undefined tool index {index} selected.')

        self.active_tool = self.tools[index]

    coord = lambda name, key=None: f'(?P<{key or name}>{name}[+-]?[0-9]*\.?[0-9]*)?'
    xy_coord = coord('X') + coord('Y')

    @exprs.match(r'R(?P<count>[0-9]+)' + xy_coord)
    def handle_repeat_hole(self, match):
        if self.program_state == ProgramState.HEADER:
            return

        dx = int(match['x'] or '0')
        dy = int(match['y'] or '0')

        for i in range(int(match['count'])):
            self.pos[0] += dx
            self.pos[1] += dy
            # FIXME fix API below
            if not self.ensure_active_tool():
                return

            self.objects.append(Flash(*self.pos, self.active_tool, unit=self.settings.unit))

    def header_command(fun):
        @functools.wraps(fun)
        def wrapper(*args, **kwargs):
            if self.program_state is None:
                warnings.warn('Header statement found before start of header')
            elif self.program_state != ProgramState.HEADER:
                warnings.warn('Header statement found after end of header')
            fun(*args, **kwargs)
        return wrapper

    @exprs.match('M48')
    def handle_begin_header(self, match):
        if self.program_state == ProgramState.HEADER:
            # It seems that only fritzing puts both a '%' start of header thingy and an M48 statement at the beginning
            # of the file.
            self.generator = 'fritzing'
        elif self.program_state is not None:
            warnings.warn(f'M48 "header start" statement found in the middle of the file, currently in {self.program_state}', SyntaxWarning)
        self.program_state = ProgramState.HEADER

    @exprs.match('M95')
    @header_command
    def handle_end_header(self, match):
        self.program_state = ProgramState.DRILLING

    @exprs.match('M00')
    def handle_next_tool(self, match):
        #FIXME is this correct? Shouldn't this be "end of program"?
        if self.active_tool:
            self.active_tool = self.tools[self.tools.index(self.active_tool) + 1]

        else:
            warnings.warn('M00 statement found before first tool selection statement.', SyntaxWarning)

    @exprs.match('M15')
    def handle_drill_down(self, match):
        self.drill_down = True

    @exprs.match('M16|M17')
    def handle_drill_up(self, match):
        self.drill_down = False


    @exprs.match('M30')
    def handle_end_of_program(self, match):
        if self.program_state in (None, ProgramState.HEADER):
            warnings.warn('M30 statement found before end of header.', SyntaxWarning)
        self.program_state = FINISHED
        # ignore.
        # TODO: maybe add warning if this is followed by other commands.

    def do_move(self, match=None, x='X', y='Y'):
        x = settings.parse_gerber_value(match['X'])
        y = settings.parse_gerber_value(match['Y'])

        old_pos = self.pos

        if self.settings.absolute:
            if x is not None:
                self.pos[0] = x
            if y is not None:
                self.pos[1] = y
        else: # incremental
            if x is not None:
                self.pos[0] += x
            if y is not None:
                self.pos[1] += y

        return old_pos, new_pos

    @exprs.match('G00' + xy_coord)
    def handle_start_routing(self, match):
        if self.program_state is None:
            warnings.warn('Routing mode command found before header.', SyntaxWarning)
        self.program_state = ProgramState.ROUTING
        self.do_move(match)

    @exprs.match('%')
    def handle_rewind_shorthand(self, match):
        if self.program_state is None:
            self.program_state = ProgramState.HEADER
        elif self.program_state is ProgramState.HEADER:
            self.program_state = ProgramState.DRILLING
        # FIXME handle rewind start

    @exprs.match('G05')
    def handle_drill_mode(self, match):
        self.drill_down = False
        self.program_state = ProgramState.DRILLING

    def ensure_active_tool(self):
        if self.active_tool:
            return self.active_tool
        
        warnings.warn('Routing command found before first tool definition.', SyntaxWarning)
        return None

    @exprs.match('(?P<mode>G01|G02|G03)' + xy_coord + coord('A') + coord('I') + coord('J'))
    def handle_linear_mode(self, match):
        if match['mode'] == 'G01':
            self.interpolation_mode = InterpMode.LINEAR
        else:
            clockwise = (match['mode'] == 'G02')
            self.interpolation_mode = InterpMode.CIRCULAR_CW if clockwise else InterpMode.CIRCULAR_CCW

        self.do_interpolation(match)
    
    def do_interpolation(self, match):
        x, y, a, i, j = match['X'], match['Y'], match['A'], match['I'], match['J']

        start, end = self.do_move(match)

        # Yes, drills in the header doesn't follow the specification, but it there are many files like this
        if self.program_state not in (ProgramState.DRILLING, ProgramState.HEADER):
            return

        if not self.drill_down or not (match['x'] or match['y']) or not self.ensure_active_tool():
            return

        if self.interpolation_mode == InterpMode.LINEAR:
            if a or i or j:
                warnings.warn('A/I/J arc coordinates found in linear mode.', SyntaxWarning)

            self.objects.append(Line(*start, *end, self.active_tool, unit=self.settings.unit))

        else:
            if (x or y) and not (a or i or j):
                warnings.warn('Arc without radius found.', SyntaxWarning)

            clockwise = (self.interpolation_mode == InterpMode.CIRCULAR_CW)
            
            if a: # radius given
                if i or j:
                    warnings.warn('Arc without both radius and center specified.', SyntaxWarning)

                # Convert endpoint-radius-endpoint notation to endpoint-center-endpoint notation. We always use the
                # smaller arc here.
                # from https://math.stackexchange.com/a/1781546
                r = settings.parse_gerber_value(a)
                x1, y1 = start
                x2, y2 = end
                dx, dy = (x2-x1)/2, (y2-y1)/2
                x0, y0 = x1+dx, y1+dy
                f = math.hypot(dx, dy) / math.sqrt(r**2 - a**2)
                if clockwise:
                    cx = x0 + f*dy
                    cy = y0 - f*dx
                else:
                    cx = x0 - f*dy
                    cy = y0 + f*dx
                i, j = cx-start[0], cy-start[1]

            else: # explicit center given
                i = settings.parse_gerber_value(i)
                j = settings.parse_gerber_value(j)

            self.objects.append(Arc(*start, *end, i, j, True, self.active_tool, unit=self.settings.unit))

    @exprs.match('M71|METRIC') # XNC uses "METRIC"
    @header_command
    def handle_metric_mode(self, match):
        self.settings.unit = MM

    @exprs.match('M72|INCH') # XNC uses "INCH"
    @header_command
    def handle_inch_mode(self, match):
        self.settings.unit = Inch

    @exprs.match('(METRIC|INCH),(LZ|TZ)(0*\.0*)?')
    def parse_easyeda_format(self, match):
        self.settings.unit = MM if match[1] == 'METRIC' else Inch
        self.settings.zeros = 'leading' if match[2] == 'LZ' else 'trailing'
        # Newer EasyEDA exports have this in an altium-like FILE_FORMAT comment instead. Some files even have both.
        # This is used by newer autodesk eagles, fritzing and diptrace
        if match[3]:
            if self.generator is None:
                # newer eagles identify themselvees through a comment, and fritzing uses this wonky double-header-start
                # with a "%" line followed  by an "M48" line. Thus, thus must be diptrace.
                self.generator = 'diptrace'
            integer, _, fractional = match[3].partition('.')
            self.settings.number_format = len(integer), len(fractional)
    
    @exprs.match('G90')
    @header_command
    def handle_absolute_mode(self, match):
        self.settings.notation = 'absolute'

    @exprs.match('ICI,?(ON|OFF)')
    def handle_incremental_mode(self, match):
        self.settings.notation = 'absolute' if match[1] == 'OFF' else 'incremental'

    @exprs.match('(FMAT|VER),?([0-9]*)')
    def handle_command_format(self, match):
        # We do not support integer/fractional decimals specification via FMAT because that's stupid. If you need this,
        # please raise an issue on our issue tracker, provide a sample file and tell us where on earth you found that
        # file.
        if match[2] not in ('', '2'):
            raise SyntaxError(f'Unsupported FMAT format version {match["version"]}')

    @exprs.match('G40|G41|G42|{coord("F")}')
    def handle_unhandled(self, match):
        warnings.warn(f'{match[0]} excellon command intended for CAM tools found in EDA file.', SyntaxWarning)

    @exprs.match(coord('X', 'x1') + coord('Y', 'y1') + 'G85' + coord('X', 'x2') + coord('Y', 'y2'))
    def handle_slot_dotted(self, match):
        warnings.warn('Weird G85 excellon slot command used. Please raise an issue on our issue tracker and provide this file for testing.', SyntaxWarning)
        self.do_move(match, 'X1', 'Y1')
        start, end = self.do_move(match, 'X2', 'Y2')
        
        if self.program_state in (ProgramState.DRILLING, ProgramState.HEADER): # FIXME should we realy handle this in header?
            if self.ensure_active_tool():
                # We ignore whether a slot is a "routed" G00/G01 slot or a "drilled" G85 slot and export both as routed
                # slots.
                self.objects.append(Line(*start, *end, self.active_tool, unit=self.settings.unit))

    @exprs.match(xy_coord)
    def handle_naked_coordinate(self, match):
        self.do_interpolation(match)

    @exprs.match(r'; Format\s*: ([0-9]+\.[0-9]+) / (Absolute|Incremental) / (Inch|MM) / (Leading|Trailing)')
    def parse_siemens_format(self, match):
        x, _, y = match[1].split('.')
        self.settings.number_format = int(x), int(y)
        # NOTE: Siemens files seem to always contain both this comment and an explicit METRIC/INC statement. However,
        # the meaning of "leading" and "trailing" is swapped in both: When this comment says leading, we get something
        # like "INCH,TZ".
        self.settings.notation = {'Leading': 'trailing', 'Trailing': 'leading'}[match[2]]
        self.settings.unit = to_unit(match[3])
        self.settings.zeros = match[4].lower()
        self.generator = 'siemens'

    @exprs.match('; Contents: (Thru|.*) / (Drill|Mill) / (Plated|Non-Plated)')
    def parse_siemens_meta(self, match):
        self.is_plated = (match[3] == 'Plated')
        self.generator = 'siemens'

    @exprs.match(';FILE_FORMAT=([0-9]:[0-9])')
    def parse_altium_easyeda_number_format_comment(self, match):
        # Altium or newer EasyEDA exports
        x, _, y = fmt.partition(':')
        self.settings.number_format = int(x), int(y)

    @exprs.match(';Layer: (.*)')
    def parse_easyeda_layer_name(self, match):
        # EasyEDA embeds the layer name in a comment. EasyEDA uses separate files for plated/non-plated. The (default?)
        # layer names are: "Drill PTH", "Drill NPTH"
        self.is_plated = 'NPTH' not in match[1]

    @exprs.match(';TYPE=(PLATED|NON_PLATED)')
    def parse_altium_composite_plating_comment(self, match):
        # These can happen both before a tool definition and before a tool selection statement.
        # FIXME make sure we do the right thing in both cases.
        self.is_plated = (match[1] == 'PLATED')

    @exprs.match(';(Layer_Color=[-+0-9a-fA-F]*)')
    def parse_altium_layer_color(self, match):
        self.generator = 'altium'
        self.comments.append(match[1])
    
    @exprs.match(';HEADER:')
    def parse_allegro_start_of_header(self, match):
        self.program_state = ProgramState.HEADER
        self.generator = 'allegro'

    @exprs.match(';GenerationSoftware,Autodesk,EAGLE,.*\*%')
    def parse_eagle_version_header(self, match):
        # NOTE: Only newer eagles export drills as XNC files. Older eagles produce an aperture-only gerber file called
        # "profile.gbr" instead.
        self.generator = 'eagle'

    @exprs.match(';EasyEDA .*')
    def parse_easyeda_version_header(self, match):
        self.generator = 'easyeda'

    @exprs.match(';(.*)')
    def parse_comment(self, match):
        self.comments.append(match[1].strip())

