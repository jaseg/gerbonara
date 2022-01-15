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

"""
Excellon File module
====================
**Excellon file classes**

This module provides Excellon file classes and parsing utilities
"""

import math
import operator
import warnings
from enum import Enum

from .cam import CamFile, FileSettings
from .excellon_statements import *
from .excellon_tool import ExcellonToolDefinitionParser
from .graphic_objects import Drill, Slot
from .utils import inch, metric


try:
    from cStringIO import StringIO
except(ImportError):
    from io import StringIO



def read(filename):
    """ Read data from filename and return an ExcellonFile
    Parameters
        ----------
    filename : string
        Filename of file to parse

    Returns
    -------
    file : :class:`gerber.excellon.ExcellonFile`
        An ExcellonFile created from the specified file.

    """
    # File object should use settings from source file by default.
    with open(filename, 'r') as f:
        data = f.read()
    settings = FileSettings(**detect_excellon_format(data))
    return ExcellonParser(settings).parse(filename)

def loads(data, filename=None, settings=None, tools=None):
    """ Read data from string and return an ExcellonFile
    Parameters
    ----------
    data : string
        string containing Excellon file contents

    filename : string, optional
        string containing the filename of the data source

    tools: dict (optional)
        externally defined tools

    Returns
    -------
    file : :class:`gerber.excellon.ExcellonFile`
        An ExcellonFile created from the specified file.

    """
    # File object should use settings from source file by default.
    if not settings:
        settings = FileSettings(**detect_excellon_format(data))
    return ExcellonParser(settings, tools).parse_raw(data, filename)


class DrillHit(object):
    """Drill feature that is a single drill hole.

    Attributes
    ----------
    tool : ExcellonTool
        Tool to drill the hole. Defines the size of the hole that is generated.
    position : tuple(float, float)
        Center position of the drill.

    """
    def __init__(self, tool, position):
        self.tool = tool
        self.position = position

    @property
    def bounding_box(self):
        position = self.position
        radius = self.tool.diameter / 2.

        min_x = position[0] - radius
        max_x = position[0] + radius
        min_y = position[1] - radius
        max_y = position[1] + radius
        return ((min_x, max_x), (min_y, max_y))

    def offset(self, x_offset=0, y_offset=0):
        self.position = tuple(map(operator.add, self.position, (x_offset, y_offset)))

    def __str__(self):
        return 'Hit (%f, %f) {%s}' % (self.position[0], self.position[1], self.tool)

class DrillSlot(object):
    """
    A slot is created between two points. The way the slot is created depends on the statement used to create it
    """

    TYPE_ROUT = 1
    TYPE_G85 = 2

    def __init__(self, tool, start, end, slot_type):
        self.tool = tool
        self.start = start
        self.end = end
        self.slot_type = slot_type

    @property
    def bounding_box(self):
        start = self.start
        end = self.end
        radius = self.tool.diameter / 2.
        min_x = min(start[0], end[0]) - radius
        max_x = max(start[0], end[0]) + radius
        min_y = min(start[1], end[1]) - radius
        max_y = max(start[1], end[1]) + radius
        return ((min_x, max_x), (min_y, max_y))

    def offset(self, x_offset=0, y_offset=0):
        self.start = tuple(map(operator.add, self.start, (x_offset, y_offset)))
        self.end = tuple(map(operator.add, self.end, (x_offset, y_offset)))


class ExcellonFile(CamFile):
    """ A class representing a single excellon file

    The ExcellonFile class represents a single excellon file.

    http://www.excellon.com/manuals/program.htm
    (archived version at https://web.archive.org/web/20150920001043/http://www.excellon.com/manuals/program.htm)

    Parameters
    ----------
    tools : list
        list of gerber file statements

    hits : list of tuples
        list of drill hits as (<Tool>, (x, y))

    settings : dict
        Dictionary of gerber file settings

    filename : string
        Filename of the source gerber file

    Attributes
    ----------
    units : string
        either 'inch' or 'metric'.

    """

    def __init__(self, statements, tools, hits, settings, filename=None):
        super(ExcellonFile, self).__init__(statements=statements,
                                           settings=settings,
                                           filename=filename)
        self.tools = tools
        self.hits = hits

    @property
    def primitives(self):
        """
        Gets the primitives. Note that unlike Gerber, this generates new objects
        """
        primitives = []
        for hit in self.hits:
            if isinstance(hit, DrillHit):
                primitives.append(Drill(hit.position, hit.tool.diameter,
                                        units=self.settings.units))
            elif isinstance(hit, DrillSlot):
                primitives.append(Slot(hit.start, hit.end, hit.tool.diameter,
                                       units=self.settings.units))
            else:
                raise ValueError('Unknown hit type')
        return primitives

    @property
    def bounding_box(self):
        xmin = ymin = 100000000000
        xmax = ymax = -100000000000
        for hit in self.hits:
            bbox = hit.bounding_box
            xmin = min(bbox[0][0], xmin)
            xmax = max(bbox[0][1], xmax)
            ymin = min(bbox[1][0], ymin)
            ymax = max(bbox[1][1], ymax)
        return ((xmin, xmax), (ymin, ymax))

    def report(self, filename=None):
        """ Print or save drill report
        """
        if self.settings.units == 'inch':
            toolfmt = '  T{:0>2d}      {:%d.%df}     {: >3d}     {:f}in.\n' % self.settings.format
        else:
            toolfmt = '  T{:0>2d}      {:%d.%df}     {: >3d}     {:f}mm\n' % self.settings.format
        rprt = '=====================\nExcellon Drill Report\n=====================\n'
        if self.filename is not None:
            rprt += 'NC Drill File: %s\n\n' % self.filename
        rprt += 'Drill File Info:\n----------------\n'
        rprt += ('  Data Mode         %s\n' % 'Absolute'
                 if self.settings.notation == 'absolute' else 'Incremental')
        rprt += ('  Units             %s\n' % 'Inches'
                 if self.settings.units == 'inch' else 'Millimeters')
        rprt += '\nTool List:\n----------\n\n'
        rprt += '  Code      Size     Hits    Path Length\n'
        rprt += '  --------------------------------------\n'
        for tool in iter(self.tools.values()):
            rprt += toolfmt.format(tool.number, tool.diameter,
                                   tool.hit_count, self.path_length(tool.number))
        if filename is not None:
            with open(filename, 'w') as f:
                f.write(rprt)
        return rprt

    def write(self, filename=None):
        filename = filename if filename is not None else self.filename
        with open(filename, 'w') as f:

            # Copy the header verbatim
            for statement in self.statements:
                if not isinstance(statement, ToolSelectionStmt):
                    f.write(statement.to_excellon(self.settings) + '\n')
                else:
                    break

            # Write out coordinates for drill hits by tool
            for tool in iter(self.tools.values()):
                f.write(ToolSelectionStmt(tool.number).to_excellon(self.settings) + '\n')
                for hit in self.hits:
                    if hit.tool.number == tool.number:
                        f.write(CoordinateStmt(
                            *hit.position).to_excellon(self.settings) + '\n')
            f.write(EndOfProgramStmt().to_excellon() + '\n')

    def offset(self, x_offset=0, y_offset=0):
        for statement in self.statements:
            statement.offset(x_offset, y_offset)
        for primitive in self.primitives:
            primitive.offset(x_offset, y_offset)
        for hit in self. hits:
            hit.offset(x_offset, y_offset)

    def path_length(self, tool_number=None):
        """ Return the path length for a given tool
        """
        lengths = {}
        positions = {}
        for hit in self.hits:
            tool = hit.tool
            num = tool.number
            positions[num] = ((0, 0) if positions.get(num) is None
                              else positions[num])
            lengths[num] = 0.0 if lengths.get(num) is None else lengths[num]
            lengths[num] = lengths[
                num] + math.hypot(*tuple(map(operator.sub, positions[num], hit.position)))
            positions[num] = hit.position

        if tool_number is None:
            return lengths
        else:
            return lengths.get(tool_number)

    def hit_count(self, tool_number=None):
        counts = {}
        for tool in iter(self.tools.values()):
            counts[tool.number] = tool.hit_count
        if tool_number is None:
            return counts
        else:
            return counts.get(tool_number)

    def update_tool(self, tool_number, **kwargs):
        """ Change parameters of a tool
        """
        if kwargs.get('feed_rate') is not None:
            self.tools[tool_number].feed_rate = kwargs.get('feed_rate')
        if kwargs.get('retract_rate') is not None:
            self.tools[tool_number].retract_rate = kwargs.get('retract_rate')
        if kwargs.get('rpm') is not None:
            self.tools[tool_number].rpm = kwargs.get('rpm')
        if kwargs.get('diameter') is not None:
            self.tools[tool_number].diameter = kwargs.get('diameter')
        if kwargs.get('max_hit_count') is not None:
            self.tools[tool_number].max_hit_count = kwargs.get('max_hit_count')
        if kwargs.get('depth_offset') is not None:
            self.tools[tool_number].depth_offset = kwargs.get('depth_offset')
        # Update drill hits
        newtool = self.tools[tool_number]
        for hit in self.hits:
            if hit.tool.number == newtool.number:
                hit.tool = newtool

class RegexMatcher:
    def __init__(self):
        self.mapping = {}

    def match(self, regex):
        def wrapper(fun):
            nonlocal self
            self.mapping[regex] = fun
            return fun
        return wrapper

    def handle(self, inst, line):
        for regex, handler in self.mapping.items():
            if (match := re.fullmatch(regex, line)):
                handler(match)

class ProgramState(Enum):
    HEADER = 0
    DRILLING = 1
    ROUTING = 2
    FINISHED = 2

class InterpMode(Enum):
    LINEAR = 0
    CIRCULAR_CW = 1
    CIRCULAR_CCW = 2


class ExcellonParser(object):
    def __init__(self):
        self.settings = FileSettings(number_format=(2,4))
        self.program_state = None
        self.interpolation_mode = InterpMode.LINEAR
        self.statements = []
        self.tools = {}
        self.comment_tools = {}
        self.hits = []
        self.active_tool = None
        self.pos = 0, 0
        self.drill_down = False
        self.is_plated = None
        self.feed_rate = None

    @property
    def coordinates(self):
        return [(stmt.x, stmt.y) for stmt in self.statements if isinstance(stmt, CoordinateStmt)]

    @property
    def bounds(self):
        xmin = ymin = 100000000000
        xmax = ymax = -100000000000
        for x, y in self.coordinates:
            if x is not None:
                xmin = x if x < xmin else xmin
                xmax = x if x > xmax else xmax
            if y is not None:
                ymin = y if y < ymin else ymin
                ymax = y if y > ymax else ymax
        return ((xmin, xmax), (ymin, ymax))

    @property
    def hole_sizes(self):
        return [stmt.diameter for stmt in self.statements if isinstance(stmt, ExcellonTool)]

    @property
    def hole_count(self):
        return len(self.hits)

    def parse(self, filename):
        with open(filename, 'r') as f:
            data = f.read()
        return self.parse_raw(data, filename)

    def parse_raw(self, data, filename=None):
        for line in StringIO(data):
            self._parse_line(line.strip())
        for stmt in self.statements:
            stmt.units = self.units
        return ExcellonFile(self.statements, self.tools, self.hits, self.settings, filename)

    def parse(self, filelike):
        leftover = None
        for line in filelike:
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

    @exprs.match(';(?P<comment>FILE_FORMAT=(?P<format>[0-9]:[0-9])|TYPE=(?P<plating>PLATED|NON_PLATED)|(?P<header>HEADER:)|.*(?P<tooldef> Holesize)|.*)')
    def parse_comment(self, match):

        # get format from altium comment
        if (fmt := match['format']):
            x, _, y = fmt.partition(':')
            self.settings.number_format = int(x), int(y)

        elif (plating := match('plating']):
            self.is_plated = (plating == 'PLATED')

        elif match['header']:
            self.program_state = ProgramState.HEADER

        elif match['tooldef']:
            self.program_state = ProgramState.HEADER

            # FIXME fix this code.
            # Parse this as a hole definition
            tools = ExcellonToolDefinitionParser(self.settings).parse_raw(comment_stmt.comment)
            if len(tools) == 1:
                tool = tools[tools.keys()[0]]
                self._add_comment_tool(tool)

        else:
            target.comments.append(match['comment'].strip())

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
        if self.program_state is not None:
            warnings.warn(f'M48 "header start" statement found in the middle of the file, currently in {self.program_state}', SyntaxWarning)
        self.program_state = ProgramState.HEADER

    @exprs.match('M95')
    @header_command
    def handle_end_header(self, match)
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

    coord = lambda name, key=None: f'(?P<{key or name}>{name}[+-]?[0-9]*\.?[0-9]*)?'
    xy_coord = coord('X') + coord('Y')

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
        self.cutter_compensation = None
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
        
        if (self.active_tool := self.tools.get(1)):
            return self.active_tool

        warnings.warn('Routing command found before first tool definition.', SyntaxWarning)
        return None

    @exprs.match('(?P<mode>G01|G02|G03)' + xy_coord + aij_coord):
    def handle_linear_mode(self, match)
        x, y, a, i, j = match['x'], match['y'], match['a'], match['i'], match['j']

        start, end = self.do_move(match)

        if match['mode'] == 'G01':
            self.interpolation_mode = InterpMode.LINEAR
            if a or i or j:
                warnings.warn('A/I/J arc coordinates found in linear mode.', SyntaxWarning)

        else:
            self.interpolation_mode = InterpMode.CIRCULAR_CW if match['mode'] == 'G02' else InterpMode.CIRCULAR_CCW
            
            if (x or y) and not (a or i or j):
                warnings.warn('Arc without radius found.', SyntaxWarning)

            if a and (i or j):
                warnings.warn('Arc without both radius and center specified.', SyntaxWarning)

        if self.drill_down:
            if not self.ensure_active_tool():
                return

            # FIXME handle arcs
            # FIXME fix the API below
            self.hits.append(DrillSlot(self.active_tool, start, end, DrillSlot.TYPE_ROUT))
            self.active_tool._hit()

    @exprs.match('M71')
    @header_command
    def handle_metric_mode(self, match):
        self.settings.unit = 'mm'

    @exprs.match('M72')
    @header_command
    def handle_inch_mode(self, match):
        self.settings.unit = 'inch'
    
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

    @exprs.match('G40')
    def handle_cutter_comp_off(self, match):
        self.cutter_compensation = None

    @exprs.match('G41')
    def handle_cutter_comp_off(self, match):
        self.cutter_compensation = 'left'

    @exprs.match('G42')
    def handle_cutter_comp_off(self, match):
        self.cutter_compensation = 'right'

    @exprs.match(coord('F'))
    def handle_feed_rate(self):
        self.feed_rate = self.settings.parse_gerber_value(match['F'])

    @exprs.match('T([0-9]+)(([A-Z][.0-9]+)+)') # Tool definition: T** with at least one parameter
    def parse_tool_definition(self, match):
        params = { m[0]: settings.parse_gerber_value(m[1:]) for m in re.findall('[BCFHSTZ][.0-9]+', match[2]) }
        tool = ExcellonTool(
                retract_rate    = params.get('B'),
                diameter        = params.get('C'),
                feed_rate       = params.get('F'),
                max_hit_count   = params.get('H'),
                rpm             = 1000 * params.get('S'),
                depth_offset    = params.get('Z'),
                plated          = self.plated)

        self.tools[int(match[1])] = tool

    @exprs.match('T([0-9]+)')
    def parse_tool_selection(self, match):
        index = int(match[1])

        if index == 0: # T0 is used as END marker, just ignore
            return

        if (tool := self.tools.get(index)):
            self.active_tool = tool
            return

        # This is a nasty hack for weird files with no tools defined.
        # Calculate tool radius from tool index.
        dia = (16 + 8 * index) / 1000.0
        if self.settings.unit == 'mm':
            dia *= 25.4

        # FIXME fix 'ExcellonTool' API below
        self.tools[index] = ExcellonTool( self._settings(), number=stmt.tool, diameter=diameter)

    @exprs.match(r'R(?P<count>[0-9]+)' + xy_coord).match(line)
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

            self.hits.append(DrillHit(self.active_tool, tuple(self.pos)))
            self.active_tool._hit()

    @exprs.match(coord('X', 'x1') + coord('Y', 'y1') + 'G85' + coord('X', 'x2') + coord('Y', 'y2'))
    def handle_slot_dotted(self, match):
        self.do_move(match, 'X1', 'Y1')
        start, end = self.do_move(match, 'X2', 'Y2')
        
        if self.program_state in (ProgramState.DRILLING, ProgramState.HEADER): # FIXME should we realy handle this in header?
            # FIXME fix API below
            if not self.ensure_active_tool():
                return

            self.hits.append(DrillSlot(self.active_tool, start, end, DrillSlot.TYPE_G85))
            self.active_tool._hit()


    @exprs.match(xy_coord)
    def handle_naked_coordinate(self, match):
        start, end = self.do_move(match)

        # FIXME handle arcs

        # FIXME is this logic correct? Shouldn't we check program_state first, then interpolation_mode?
        if self.interpolation_mode == InterpMode.LINEAR and self.drill_down:
            # FIXME fix API below
            if not self.ensure_active_tool():
                return

            self.hits.append(DrillSlot(self.active_tool, start, end, DrillSlot.TYPE_ROUT))

        # Yes, drills in the header doesn't follow the specification, but it there are many files like this
        elif self.program_state in (ProgramState.DRILLING, ProgramState.HEADER):
            # FIXME fix API below
            if not self.ensure_active_tool():
                return

            self.hits.append(DrillHit(self.active_tool, end))
            self.active_tool._hit()

        else:
            warnings.warn('Found unexpected coordinate', SyntaxWarning)

