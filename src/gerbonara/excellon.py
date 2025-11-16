#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>
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

import math
import operator
import warnings
import functools
import dataclasses
import re
from enum import Enum
from dataclasses import dataclass
from collections import Counter
from pathlib import Path

from .cam import CamFile, FileSettings
from .graphic_objects import Flash, Line, Arc
from .apertures import ExcellonTool
from .utils import Inch, MM, to_unit, InterpMode, RegexMatcher

class ExcellonContext:
    """ Internal helper class used for tracking graphics state when writing Excellon. """

    def __init__(self, settings, tools):
        self.settings = settings
        self.tools = tools
        self.mode = None
        self.current_tool = None
        self.x, self.y = None, None
        self.drill_down = False

    def select_tool(self, tool):
        """ Select the current tool. Retract drill first if necessary. """
        current_id = self.tools.get(self.current_tool)
        new_id = self.tools[tool]
        if new_id != current_id:
            if self.drill_down:
                yield 'M16' # drill up
                self.drill_down = False

            self.current_tool = tool
            yield f'T{new_id:02d}'

    def drill_mode(self):
        """ Enter drill mode. """
        if self.mode != ProgramState.DRILLING:
            self.mode = ProgramState.DRILLING
            if self.drill_down:
                yield 'M16' # drill up
                self.drill_down = False
            yield 'G05' # drill mode

    def route_mode(self, unit, x, y):
        """ Enter route mode and plunge tool at the given coordinates. """
        x, y = self.settings.unit(x, unit), self.settings.unit(y, unit)

        if self.mode == ProgramState.ROUTING and (self.x, self.y) == (x, y):
            return # nothing to do

        if self.drill_down:
            yield 'M16' # drill up

        # route mode
        yield 'G00' + 'X' + self.settings.write_excellon_value(x) + 'Y' + self.settings.write_excellon_value(y)
        yield 'M15' # drill down
        self.drill_down = True
        self.mode = ProgramState.ROUTING
        self.x, self.y = x, y

    def set_current_point(self, unit, x, y):
        """ Update internal last point """
        self.x, self.y = self.settings.unit(x, unit), self.settings.unit(y, unit)

def parse_allegro_ncparam(data, settings=None):
    """ Internal function to parse Excellon format information out of Allegro's nonstandard textual parameter files that
    it generates along with the Excellon file. """
    # This function parses data from allegro's nc_param.txt and ncdrill.log files. We have to parse these files because
    # allegro Excellon files omit crucial information such as the *number format*. nc_param.txt really is the file we
    # want to parse, but sometimes due to user error it doesn't end up in the gerber package. In this case, we want to
    # still be able to extract the same information from the human-readable ncdrill.log.

    if settings is None:
        settings = FileSettings(number_format=(None, None), zeros='leading')

    lz_supp, tz_supp = False, False
    nf_int, nf_frac = settings.number_format
    for line in data.splitlines():
        line = re.sub(r'\s+', ' ', line.strip())

        if (match := re.fullmatch(r'FORMAT ([0-9]+\.[0-9]+)', line)):
            x, _, y = match[1].partition('.')
            nf_int, nf_frac = int(x), int(y)

        elif (match := re.fullmatch(r'INTEGER-PLACES ([0-9]+)', line)):
            nf_int = int(match[1])

        elif (match := re.fullmatch(r'DECIMAL-PLACES ([0-9]+)', line)):
            nf_frac = int(match[1])

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

    settings.number_format = nf_int, nf_frac
    settings.zeros = 'leading' if lz_supp else 'trailing'
    return settings


def parse_allegro_logfile(data):
    """ Internal function to parse Excellon format information out of Allegro's nonstandard textual log files that it
    generates along with the Excellon file. """
    found_tools = {}
    unit = None

    for line in data.splitlines():
        line = line.strip()
        line = re.sub(r'\s+', ' ', line)

        if (m := re.match(r'OUTPUT-UNITS (METRIC|ENGLISH|INCHES)', line)):
            # I have no idea wth is the difference between "ENGLISH" and "INCHES". I think one might just be the one
            # Allegro uses in footprint files, with the other one being used in gerber exports.
            unit = MM if m[1] == 'METRIC' else Inch

        elif (m := re.match(r'T(?P<index1>[0-9]+) (?P<index2>[0-9]+)\. (?P<diameter>[0-9/.]+) [0-9. /+-]* (?P<plated>PLATED|NON_PLATED|OPTIONAL) [0-9]+', line)):
            index1, index2 = int(m['index1']), int(m['index2'])
            if index1 != index2:
                return {}

            diameter = float(m['diameter'])
            if unit == Inch:
                diameter /= 1000
            is_plated = None if m['plated'] is None else (m['plated'] in ('PLATED', 'OPTIONAL'))
            found_tools[index1] = ExcellonTool(diameter=diameter, plated=is_plated, unit=unit)
    return found_tools

def parse_zuken_logfile(data):
    """ Internal function to parse Excellon format information out of Zuken's nonstandard textual log files that their
    tools generate along with the Excellon file. """
    lines = [ line.strip() for line in data.splitlines() ]
    if '*****  DRILL LIST  *****' not in lines:
        return # likely not a Zuken CR-8000 logfile 

    params = {}
    for line in lines:
        key, colon, value = line.partition(':')
        if colon and value:
            params[key.strip()] = value.strip()

    if not (fmt := params.get('Coordinate Format')):
        return None

    integer, _, decimal = fmt.partition('V')
    settings = FileSettings(number_format=(int(integer), int(decimal)))
    
    if (supp := params.get('Zero Suppress')):
        supp, _1, _2 = supp.partition(' ')
        settings.zeros = supp.lower()

    return settings


class ExcellonFile(CamFile):
    """ Excellon drill file.

    An Excellon file can contain both drills and milled slots. Drills are represented by :py:class:`.Flash` instances
    with their aperture set to the special :py:class:`.ExcellonDrill` aperture class. Drills can be plated or nonplated.
    This information is stored in the :py:class:`.ExcellonTool`. Both can co-exist in the same file, and some CAD tools
    even export files like this. :py:class:`.LayerStack` contains functions to convert between a single drill file with
    mixed plated and nonplated holes and one with separate drill files for each. Best practice is to have separate drill
    files for slots, nonplated holes, and plated holes, because the board house will produce all three in three separate
    processes anyway, and also because there is no standardized way to represent plating in Excellon files. Gerbonara
    uses Altium's convention for this, which uses a magic comment before the tool definition.
    """

    def __init__(self, objects=None, comments=None, import_settings=None, original_path=None, generator_hints=None):
        super().__init__(original_path=original_path)
        self.objects = objects or []
        self.comments = comments or []
        self.import_settings = import_settings
        self.generator_hints = generator_hints or [] # This is a purely informational goodie from the parser. Use it as you wish.

    def __str__(self):
        name = f'{self.original_path.name} ' if self.original_path else ''
        return f'<ExcellonFile {name}{self.plating_type} with {len(list(self.drills()))} drills, {len(list(self.slots()))} slots using {len(self.drill_sizes())} tools>'

    def __repr__(self):
        return str(self)

    @property
    def plating_type(self):
        if self.is_plated:
            return 'plated'
        elif self.is_nonplated:
            return 'nonplated'
        elif self.is_mixed_plating:
            return 'mixed plating'
        else:
            return 'unknown plating'

    @property
    def is_plated(self):
        """ Test if *all* holes or slots in this file are plated. """
        return all(obj.plated for obj in self.objects)

    @property
    def is_nonplated(self):
        """ Test if *all* holes or slots in this file are non-plated. """
        return all(obj.plated == False for obj in self.objects) # False, not None

    @property
    def is_plating_unknown(self):
        """ Test if *all* holes or slots in this file have no known plating. """
        return all(obj.plated is None for obj in self.objects) # False, not None

    @property
    def is_mixed_plating(self):
        """ Test if there are multiple plating values used in this file. """
        return len({obj.plated for obj in self.objects}) > 1

    @property
    def is_plated_tristate(self):
        if self.is_plated:
            return True

        if self.is_nonplated:
            return False

        return None

    def append(self, obj_or_comment):
        """ Add a :py:class:`.GraphicObject` or a comment (str) to this file. """
        if isinstance(obj_or_comment, str):
            self.comments.append(obj_or_comment)
        else:
            self.objects.append(obj_or_comment)

    def to_excellon(self, plated=None, errors='raise'):
        """ Counterpart to :py:meth:`~.rs274x.GerberFile.to_excellon`. Does nothing and returns :py:obj:`self`. """
        return self

    def to_gerber(self, errros='raise'):
        """ Convert this excellon file into a :py:class:`~.rs274x.GerberFile`. """
        out = GerberFile()
        out.comments = self.comments

        apertures = {}
        for obj in self.objects:
            if not (ap := apertures[obj.tool]):
                ap = apertures[obj.tool] = CircleAperture(obj.tool.diameter)

            out.objects.append(dataclasses.replace(obj, aperture=ap))

    @property
    def generator(self):
        return self.generator_hints[0] if self.generator_hints else None

    def merge(self, other, mode='ignored', keep_settings=False):
        if other is None:
            return
        
        if not isinstance(other, ExcellonFile):
            other = other.to_excellon(plated=self.is_plated_tristate)

        self.objects += other.objects
        self.comments += other.comments
        self.generator_hints = None
        if not keep_settings:
            self.import_settings = None

    @classmethod
    def open(kls, filename, plated=None, settings=None, external_tools=None):
        """ Load an Excellon file from the file system.

        Certain CAD tools do not put any information on decimal points into the actual excellon file, and instead put
        that information into a non-standard text file next to the excellon file. Using :py:meth:`~.ExcellonFile.open`
        to open a file gives Gerbonara the opportunity to try to find this data. In contrast to pcb-tools, Gerbonara
        will raise an exception instead of producing garbage parsing results if it cannot determine the file format
        parameters with certainty.

        .. note:: This is preferred over loading Excellon from a str through :py:meth:`~.ExcellonFile.from_string`.

        :param filename: ``str`` or ``pathlib.Path``.
        :param bool plated: If given, set plating status of any tools in this file that have undefined plating. This is
                useful if you already know that this file contains only e.g. plated holes from contextual information
                such as the file name.
        :param FileSettings settings: Format settings to use. If None, try to auto-detect file settings.
        """

        filename = Path(filename)
        external_tools = None
    
        if settings is None:
            # Parse allegro parameter files for settings.
            # Prefer nc_param.txt over ncparam.log since the txt is the machine-readable one.
            for fn in 'nc_param.txt', 'ncdrill.log':
                if (param_file := filename.parent / fn).is_file():
                    settings =  parse_allegro_ncparam(param_file.read_text())
                    warnings.warn(f'Loaded allegro-style excellon settings file {param_file}')
                    break

            # Parse Zuken log file for settings
            if filename.name.endswith('.fdr'):
                logfile = filename.with_suffix('.fdl')
                if logfile.is_file():
                    settings = parse_zuken_logfile(logfile.read_text())
                    warnings.warn(f'Loaded zuken-style excellon log file {logfile}: {settings}')

        if external_tools is None:
            # Parse allegro log files for tools.
            # TODO add try/except aronud this
            log_file = filename.parent / 'ncdrill.log'
            if log_file.is_file():
                external_tools = parse_allegro_logfile(log_file.read_text())


        return kls.from_string(filename.read_text(), settings=settings,
                filename=filename, plated=plated, external_tools=external_tools)

    @classmethod
    def from_string(kls, data, settings=None, filename=None, plated=None, external_tools=None):
        """ Parse the given string as an Excellon file. Note that often, Excellon files do not contain any information
        on which number format (integer/decimal places, zeros suppression) is used. In case Gerbonara cannot determine
        this with certainty, this function *will* error out. Use :py:meth:`~.ExcellonFile.open` if you want Gerbonara to
        parse this metadata from the non-standardized text files many CAD packages produce in addition to drill files.
        """

        parser = ExcellonParser(settings, external_tools=external_tools)
        parser.do_parse(data, filename=filename)
        return kls(objects=parser.objects, comments=parser.comments, import_settings=parser.settings,
                generator_hints=parser.generator_hints, original_path=filename)

    def _generate_statements(self, settings, drop_comments=True):
        """ Export this file as Excellon code, yields one str per line. """
        yield '; XNC file generated by gerbonara'
        if self.comments and not drop_comments:
            yield '; Comments found in original file:'
            for comment in self.comments:
                yield ';' + comment

        yield 'M48'
        yield 'METRIC' if settings.unit == MM else 'INCH'

        # Build tool index
        tool_map = { obj.tool: obj.tool for obj in self.objects }
        tools = sorted(tool_map.items(), key=lambda id_tool: (id_tool[1].plated, id_tool[1].diameter))

        mixed_plating = (len({ tool.plated for tool in tool_map.values() }) > 1)
        if mixed_plating:
            warnings.warn('Multiple plating values in same file. Will use non-standard Altium comment syntax to indicate hole plating.')

        defined_tools = {}
        tool_indices = {}
        index = 1
        for tool_id, tool in tools:
            xnc = tool.to_xnc(settings)
            if (tool.plated, xnc) in defined_tools:
                tool_indices[tool_id] = defined_tools[(tool.plated, xnc)]

            else:
                if mixed_plating:
                    yield ';TYPE=PLATED' if tool.plated else ';TYPE=NON_PLATED'

                yield f'T{index:02d}' + xnc

                tool_indices[tool_id] = defined_tools[(tool.plated, xnc)] = index
                index += 1

                if index >= 100:
                    warnings.warn('More than 99 tools defined. Some programs may not like three-digit tool indices.', SyntaxWarning)

        yield '%'

        ctx = ExcellonContext(settings, tool_indices)

        # Export objects
        for obj in self.objects:
            yield from obj.to_xnc(ctx)

        yield 'M30'

    def write_to_bytes(self, settings=None, drop_comments=True):
        """ Export to Excellon format. This function always generates XNC, which is a well-defined subset of Excellon.
        Uses sane default settings if you don't give any.


        :param bool drop_comments: If true, do not write comments to output file. This defaults to true because
                otherwise there is a risk that Gerbonara does not consider some obscure magic comment semantically
                meaningful while some other Excellon viewer might still parse it.
        
        :rtype: str
        """

        if settings is None:
            if self.import_settings:
                settings = self.import_settings.copy()
                settings.zeros = None
                settings.number_format = (3,5)
            else:
                settings = FileSettings.defaults()
        return '\n'.join(self._generate_statements(settings, drop_comments=drop_comments)).encode('utf-8')

    def save(self, filename, settings=None, drop_comments=True):
        """ Save this Excellon file to the file system. See :py:meth:`~.ExcellonFile.generate_excellon` for the meaning
        of the arguments. """
        with open(filename, 'wb') as f:
            f.write(self.write_to_bytes(settings, drop_comments=drop_comments))

    def offset(self, x=0, y=0, unit=MM):
        for obj in self.objects:
            obj.offset(x, y, unit)

    def rotate(self, angle, cx=0, cy=0, unit=MM):
        if math.isclose(angle % (2*math.pi), 0):
            return

        for obj in self.objects:
            obj.rotate(angle, cx, cy, unit=unit)

    def __len__(self):
        return len(self.objects)

    def split_by_plating(self):
        """ Split this file into two :py:class:`.ExcellonFile` instances, one containing all plated objects, and one
        containing all nonplated objects. In this function, objects with undefined plating are considered nonplated.

        .. note:: This does not copy the objects, so modifications in either of the returned files may clobber the
                  original file.

        :returns: (nonplated_file, plated_file)
        :rtype: tuple
        """
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

    def path_lengths(self, unit=MM):
        """ Calculate path lengths per tool.

        This function only sums actual cut lengths, and ignores travel lengths that the tool is doing without cutting to
        get from one object to another. Travel lengths depend on the CAM program's path planning, which highly depends
        on panelization and other factors. Additionally, an EDA tool will not even attempt to minimize travel distance
        as that's not its job.

        :param unit: :py:class:`.LengthUnit` or str (``'mm'`` or ``'inch'``). Unit to use for return value. Default: mm

        :returns: ``{ tool: float(path length) }``
        :rtype dict:
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
        """ Calculate the number of objects per tool.

        :rtype: collections.Counter
        """
        return Counter(obj.tool for obj in self.objects)

    def drill_sizes(self, unit=MM):
        """ Return a sorted list of all tool diameters found in this file.

        :param unit: :py:class:`.LengthUnit` or str (``'mm'`` or ``'inch'``). Unit to use for return values. Default: mm

        :returns: list of floats, sorted smallest to largest diameter.
        :rtype: list
        """
        # use equivalent_width for unit conversion
        return sorted({ obj.tool.equivalent_width(unit) for obj in self.objects })

    def drills(self):
        """ Return all drilled hole objects in this file.

        :returns: list of :py:class:`.Flash` instances
        :rtype: list
        """
        return (obj for obj in self.objects if isinstance(obj, Flash))

    def slots(self):
        """ Return all milled slot objects in this file.

        :returns: list of :py:class:`~.graphic_objects.Line` or :py:class:`~.graphic_objects.Arc` instances
        :rtype: list
        """
        return (obj for obj in self.objects if not isinstance(obj, Flash))


class ProgramState(Enum):
    """ Internal helper class used to track Excellon program state (i.e. G05/G06 command state). """
    HEADER = 0
    DRILLING = 1
    ROUTING = 2
    FINISHED = 3


class ExcellonParser(object):
    """ Internal helper class that contains all the actual Excellon format parsing logic. """

    def __init__(self, settings=None, external_tools=None):
        # NOTE XNC files do not contain an explicit number format specification, but all values have decimal points.
        # Thus, we set the default number format to (None, None). If the file does not contain an explicit specification
        # and FileSettings.parse_gerber_value encounters a number without an explicit decimal point, it will throw a
        # SyntaxError. In case of e.g. Allegro files where the number format and other options are specified separately
        # from the excellon file, the caller must pass in an already filled-out FileSettings object.
        if settings is None:
            self.settings = FileSettings(number_format=(None, None), zeros='leading')
        else:
            self.settings = settings
        self.program_state = None
        self.interpolation_mode = InterpMode.LINEAR
        self.tools = {}
        self.objects = []
        self.active_tool = None
        self.pos = 0, 0
        self.drill_down = False
        self.is_plated = None
        self.comments = []
        self.generator_hints = []
        self.lineno = None
        self.filename = None
        self.external_tools = external_tools or {}
        self.found_kicad_format_comment = False
        self.allegro_eof_toolchange_hack = False
        self.allegro_eof_toolchange_hack_index = 1

    def warn(self, msg):
        warnings.warn(f'{self.filename}:{self.lineno} "{self.line}": {msg}', SyntaxWarning)

    def do_parse(self, data, filename=None):
        # filename arg is for error messages
        self.filename = filename = filename or '<unknown>'

        leftover = None
        for lineno, line in enumerate(data.splitlines(), start=1):
            line = line.strip()
            self.lineno, self.line = lineno, line # for warnings

            if not line:
                continue

            # Coordinates of G00 and G01 may be on the next line
            if line == 'G00' or line == 'G01':
                if leftover:
                    self.warn('Two consecutive G00/G01 commands without coordinates. Ignoring first.')
                leftover = line
                continue

            if leftover:
                line = leftover + line
                leftover = None

            if line and self.program_state == ProgramState.FINISHED:
                self.warn('Commands found following end of program statement.')
            # TODO check first command in file is "start of header" command.

            try:
                if not self.exprs.handle(self, line):
                    raise ValueError('Unknown excellon statement:', line)
            except Exception as e:
                raise SyntaxError(f'{filename}:{lineno} "{line}": {e}') from e

    exprs = RegexMatcher()

    # NOTE: These must be kept before the generic comment handler at the end of this class so they match first.
    @exprs.match(r';(?P<index1_prefix>T(?P<index1>[0-9]+))?\s+Holesize (?P<index2>[0-9]+)\. = (?P<diameter>[0-9/.]+) Tolerance = \+[0-9/.]+/-[0-9/.]+ (?P<plated>PLATED|NON_PLATED|OPTIONAL) (?P<unit>MILS|MM) Quantity = [0-9]+')
    def parse_allegro_tooldef(self, match):
        # NOTE: We ignore the given tolerances here since they are non-standard.
        self.program_state = ProgramState.HEADER # TODO is this needed? we need a test file.
        self.generator_hints.append('allegro')

        index = int(match['index2'])

        if match['index1'] and index != int(match['index1']): # index1 has leading zeros, index2 not.
            raise SyntaxError('BUG: Allegro excellon tool def has mismatching tool indices. Please file a bug report on our issue tracker and provide this file!')

        if index in self.tools:
            self.warn('Re-definition of tool index {index}, overwriting old definition.') 

        if not match['index1_prefix']:
            # This is a really nasty orcad file without tool change commands, that instead just puts all holes in order
            # of the hole size definitions with M00's in between.
            self.allegro_eof_toolchange_hack = True

        # NOTE: We map "optionally" plated holes to plated holes for API simplicity. If you hit a case where that's a
        # problem, please raise an issue on our issue tracker, explain why you need this and provide an example file.
        is_plated = None if match['plated'] is None else (match['plated'] in ('PLATED', 'OPTIONAL'))

        diameter = float(match['diameter'])

        if match['unit'] == 'MILS':
            diameter /= 1000
            unit = Inch
        else:
            unit = MM

        if self.settings.unit is None:
            self.settings.unit = unit

        elif unit != self.settings.unit:
            self.warn('Allegro Excellon drill file tool definitions in {unit.name}, but file parameters say the '
                    'file should be in {settings.unit.name}. Please double-check that this is correct, and if it is, '
                    'please raise an issue on our issue tracker.')

        self.tools[index] = ExcellonTool(diameter=diameter, plated=is_plated, unit=unit)

        if self.allegro_eof_toolchange_hack and self.active_tool is None:
            self.active_tool = self.tools[index]

    # Searching Github I found that EasyEDA has two different variants of the unit specification here.
    @exprs.match(';Holesize (?P<index>[0-9]+) = (?P<diameter>[.0-9]+) (?P<unit>INCH|inch|METRIC|mm)')
    def parse_easyeda_tooldef(self, match):
        unit = Inch if match['unit'].lower() == 'inch' else MM
        tool = ExcellonTool(diameter=float(match['diameter']), unit=unit, plated=self.is_plated)

        if (index := int(match['index'])) in self.tools:
            self.warn('Re-definition of tool index {index}, overwriting old definition.') 

        self.tools[index] = tool
        self.generator_hints.append('easyeda')

    @exprs.match('T([0-9]+)(([A-Z][.0-9]+)+)') # Tool definition: T** with at least one parameter
    def parse_normal_tooldef(self, match):
        # We ignore parameters like feed rate or spindle speed that are not used for EDA -> CAM file transfer. This is
        # not a parser for the type of Excellon files a CAM program sends to the machine.

        if (index := int(match[1])) in self.tools:
            self.warn('Re-definition of tool index {index}, overwriting old definition.') 

        params = { m[0]: self.settings.parse_gerber_value(m[1:]) for m in re.findall('[BCFHSTZ][.0-9]+', match[2]) }

        self.tools[index] = ExcellonTool(diameter=params.get('C'), plated=self.is_plated,
                unit=self.settings.unit)

        if set(params.keys()) == set('TFSC'):
            self.generator_hints.append('target3001') # target files look like altium files without the comments

        if len(self.tools) >= 3 and list(self.tools.keys()) == reversed(sorted(self.tools.keys())):
            self.generator_hints.append('geda')

    @exprs.match('T([0-9]+)')
    def parse_tool_selection(self, match):
        index = int(match[1])

        if index == 0: # T0 is used as END marker, just ignore
            return
        elif index not in self.tools:
            if not self.tools and index in self.external_tools:
                # allegro is just wonderful.
                self.warn(f'Undefined tool index {index} selected. We found an allegro drill log file next to this, so '
                            'we will use tool definitions from there.')
                self.active_tool = self.external_tools[index]

            else:
                raise SyntaxError(f'Undefined tool index {index} selected.')

        else:
            self.active_tool = self.tools[index]

    coord = lambda name: fr'(?:{name}\+?(-?)([0-9]*\.?[0-9]*))?'
    xy_coord = coord('X') + coord('Y')
    xyaij_coord = xy_coord + coord('A') + coord('I') + coord('J')

    @exprs.match(r'R([0-9]+)' + xy_coord)
    def handle_repeat_hole(self, match):
        if self.program_state == ProgramState.HEADER:
            return

        count, x_s, x, y_s, y = match.groups()
        dx = self.settings.parse_gerber_value(x) or 0
        if x_s:
            dx = -dx
        dy = self.settings.parse_gerber_value(y) or 0
        if y_s:
            dy = -dy

        for i in range(int(count)):
            self.pos = (self.pos[0] + dx, self.pos[1] + dy)
            # FIXME fix API below
            if not self.ensure_active_tool():
                return

            self.objects.append(Flash(*self.pos, self.active_tool, unit=self.settings.unit))

    def header_command(name):
        def wrap(fun):
            @functools.wraps(fun)
            def wrapper(self, *args, **kwargs):
                nonlocal name
                if self.program_state is None:
                    self.warn(f'{name} header statement found before start of header')
                elif self.program_state != ProgramState.HEADER:
                    self.warn(f'{name} header statement found after end of header')
                fun(self, *args, **kwargs)
            return wrapper
        return wrap

    @exprs.match('M48')
    def handle_begin_header(self, match):
        if self.program_state == ProgramState.HEADER:
            # It seems that only fritzing puts both a '%' start of header thingy and an M48 statement at the beginning
            # of the file.
            self.generator_hints.append('fritzing')
        elif self.program_state is not None:
            self.warn(f'M48 "header start" statement found in the middle of the file, currently in {self.program_state}')
        self.program_state = ProgramState.HEADER

    @exprs.match('M95')
    @header_command('M95')
    def handle_end_header(self, match):
        self.program_state = ProgramState.DRILLING

    @exprs.match('M15')
    def handle_drill_down(self, match):
        self.drill_down = True

    @exprs.match('M16|M17')
    def handle_drill_up(self, match):
        self.drill_down = False


    @exprs.match('M30|M00')
    def handle_end_of_program(self, match):
        if self.program_state in (None, ProgramState.HEADER):
            self.warn('M30 statement found before end of header.')

        if self.allegro_eof_toolchange_hack:
            self.allegro_eof_toolchange_hack_index = min(max(self.tools), self.allegro_eof_toolchange_hack_index + 1)
            self.active_tool = self.tools[self.allegro_eof_toolchange_hack_index]
            return

        self.program_state = ProgramState.FINISHED
        # TODO: maybe add warning if this is followed by other commands.

        if match[0] == 'M00':
            self.generator_hints.append('zuken')

    def do_move(self, coord_groups):
        x_s, x, y_s, y = coord_groups

        if (x is not None and '.' not in x) or (y is not None and '.' not in y):
            self.settings._file_has_fixed_width_coordinates = True

            if self.settings.number_format == (None, None):
                # TARGET3001! exports zeros as "00" even when it uses an explicit decimal point everywhere else.
                if x != '00':
                    raise SyntaxError('No number format set and value does not contain a decimal point. If this is an Allegro '
                        'Excellon drill file make sure either nc_param.txt or ncdrill.log ends up in the same folder as '
                        'it, because Allegro does not include this critical information in their Excellon output. If you '
                        'call this through ExcellonFile.from_string, you must manually supply from_string with a '
                        'FileSettings object from excellon.parse_allegro_ncparam.')

        x = self.settings.parse_gerber_value(x)
        if x_s:
            x = -x
        y = self.settings.parse_gerber_value(y)
        if y_s:
            y = -y

        old_pos = self.pos

        if self.settings.is_absolute:
            if x is not None:
                self.pos = (x, self.pos[1])
            if y is not None:
                self.pos = (self.pos[0], y)
        else: # incremental
            if x is not None:
                self.pos = (self.pos[0]+x, self.pos[1])
            if y is not None:
                self.pos = (self.pos[0], self.pos[1]+y)

        return old_pos, self.pos

    @exprs.match('G00' + xy_coord)
    def handle_start_routing(self, match):
        if self.program_state is None:
            self.warn('Routing mode command found before header.')
        self.program_state = ProgramState.ROUTING
        self.do_move(match.groups())

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
        
        self.warn('Routing command found before first tool definition.')
        return None

    @exprs.match('(G01|G02|G03)' + xyaij_coord)
    def handle_linear_mode(self, match):
        mode, *coord_groups = match.groups()
        if mode == 'G01':
            self.interpolation_mode = InterpMode.LINEAR
        else:
            clockwise = (mode == 'G02')
            self.interpolation_mode = InterpMode.CIRCULAR_CW if clockwise else InterpMode.CIRCULAR_CCW

        self.do_interpolation(coord_groups)
    
    def do_interpolation(self, coord_groups):
        x_s, x, y_s, y, a_s, a, i_s, i, j_s, j = coord_groups

        start, end = self.do_move((x_s, x, y_s, y))

        if self.program_state != ProgramState.ROUTING:
            return

        if not self.drill_down or not (x or y) or not self.ensure_active_tool():
            return

        if self.interpolation_mode == InterpMode.LINEAR:
            if a or i or j:
                self.warn('A/I/J arc coordinates found in linear mode.')

            self.objects.append(Line(*start, *end, self.active_tool, unit=self.settings.unit))

        else:
            if (x or y) and not (a or i or j):
                self.warn('Arc without radius found.')

            clockwise = (self.interpolation_mode == InterpMode.CIRCULAR_CW)
            
            if a: # radius given
                if i or j:
                    self.warn('Arc without both radius and center specified.')

                # Convert endpoint-radius-endpoint notation to endpoint-center-endpoint notation. We always use the
                # smaller arc here.
                # from https://math.stackexchange.com/a/1781546
                if a_s:
                    raise ValueError('Negative arc radius given')
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
                if i_s:
                    i = -i
                j = settings.parse_gerber_value(j)
                if j_s:
                    j = -i

            self.objects.append(Arc(*start, *end, i, j, True, self.active_tool, unit=self.settings.unit))

    @exprs.match(r'(M71|METRIC|M72|INCH)(,LZ|,TZ)?(,0*\.0*)?')
    def parse_easyeda_format(self, match):
        metric = match[1] in ('METRIC', 'M71')

        self.settings.unit = MM if metric else Inch

        if match[2]:
            self.settings.zeros = 'trailing' if match[2] == ',LZ' else 'leading'

        # Newer EasyEDA exports have this in an altium-like FILE_FORMAT comment instead. Some files even have both.
        # This is used by newer autodesk eagles, fritzing and diptrace
        if match[3]:
            integer, _, fractional = match[3][1:].partition('.')
            self.settings.number_format = len(integer), len(fractional)

        elif self.settings.number_format == (None, None) and not metric and not self.found_kicad_format_comment:
            self.warn('Using implicit number format from bare "INCH" statement. This is normal for Fritzing, Diptrace, Geda and pcb-rnd.')
            self.settings.number_format = (2,4)
    
    @exprs.match('G90')
    @header_command('G90')
    def handle_absolute_mode(self, match):
        self.settings.notation = 'absolute'

    @exprs.match('G93' + xy_coord)
    def handle_absolute_mode(self, match):
        _x_s, x, _y_s, y = match.groups()
        if int(x or 0) != 0 or int(y or 0) != 0:
            # Siemens tooling likes to include a meaningless G93X0Y0 after its header.
            raise NotImplementedError('G93 zero set command is not supported.')
        self.generator_hints.append('siemens')

    @exprs.match('ICI,?(ON|OFF)')
    def handle_incremental_mode(self, match):
        self.settings.notation = 'absolute' if match[1] == 'OFF' else 'incremental'

    @exprs.match('(FMAT|VER),?([0-9]*)')
    def handle_command_format(self, match):
        if match[1] == 'FMAT':
            # We do not support integer/fractional decimals specification via FMAT because that's stupid. If you need this,
            # please raise an issue on our issue tracker, provide a sample file and tell us where on earth you found that
            # file.
            if match[2] not in ('', '2'):
                raise SyntaxError(f'Unsupported FMAT format version {match[2]}')

        else: # VER
            self.generator_hints.append('zuken')

    @exprs.match(r'G40|G41|G42|F[0-9]+')
    def handle_unhandled(self, match):
        self.warn(f'{match[0]} excellon command intended for CAM tools found in EDA file.')

    @exprs.match(xyaij_coord)
    def handle_bare_coordinate(self, match):
        # Yes, drills in the header doesn't follow the specification, but it there are many files like this.
        if self.program_state in (ProgramState.DRILLING, ProgramState.HEADER):
            _start, end = self.do_move(match.groups()[:4])

            if not self.ensure_active_tool():
                return

            self.objects.append(Flash(*end, self.active_tool, unit=self.settings.unit))

        elif self.program_state == ProgramState.ROUTING:
            # Bare coordinates for routing also seem illegal, but Siemens actually uses these.
            # Example file: siemens/80101_0125_F200_ContourPlated.ncd
            self.do_interpolation(match.groups())

        else:
            self.warn('Bare coordinate after end of file')

    @exprs.match(r'DETECT,ON|ATC,ON|M06')
    def parse_zuken_legacy_statements(self, match):
        self.generator_hints.append('zuken')

    @exprs.match(r'; Format\s*: ([0-9]+\.[0-9]+) / (Absolute|Incremental) / (Inch|MM) / (Leading|Trailing)')
    def parse_siemens_format(self, match):
        x, _, y = match[1].partition('.')
        self.settings.number_format = int(x), int(y)
        # NOTE: Siemens files seem to always contain both this comment and an explicit METRIC/INC statement. However,
        # the meaning of "leading" and "trailing" is swapped in both: When this comment says leading, we get something
        # like "INCH,TZ".
        self.settings.notation = match[2].lower()
        self.settings.unit = to_unit(match[3])
        self.settings.zeros = {'Leading': 'trailing', 'Trailing': 'leading'}[match[4]]
        self.generator_hints.append('siemens')

    @exprs.match('; Contents: (Thru|.*) / (Drill|Mill) / (Plated|Non-Plated)')
    def parse_siemens_meta(self, match):
        self.is_plated = (match[3] == 'Plated')
        self.generator_hints.append('siemens')

    @exprs.match(';FILE_FORMAT=([0-9]:[0-9])')
    def parse_altium_easyeda_number_format_comment(self, match):
        # Altium or newer EasyEDA exports
        x, _, y = match[1].partition(':')
        self.settings.number_format = int(x), int(y)

    @exprs.match(';Layer: (.*)')
    def parse_easyeda_layer_name(self, match):
        # EasyEDA embeds the layer name in a comment. EasyEDA uses separate files for plated/non-plated. The (default?)
        # layer names are: "Drill PTH", "Drill NPTH"
        self.is_plated = 'NPTH' not in match[1]
        self.generator_hints.append('easyeda')

    @exprs.match(';TYPE=(PLATED|NON_PLATED)')
    def parse_altium_composite_plating_comment(self, match):
        # These can happen both before a tool definition and before a tool selection statement.
        # FIXME make sure we do the right thing in both cases.
        self.is_plated = (match[1] == 'PLATED')

    @exprs.match(';(Layer_Color=[-+0-9a-fA-F]*)')
    def parse_altium_layer_color(self, match):
        self.generator_hints.append('altium')
        self.comments.append(match[1])
    
    @exprs.match(';HEADER:')
    def parse_allegro_start_of_header(self, match):
        self.program_state = ProgramState.HEADER
        self.generator_hints.append('allegro')

    @exprs.match(r';GenerationSoftware,Autodesk,EAGLE,.*\*%')
    def parse_eagle_version_header(self, match):
        # NOTE: Only newer eagles export drills as XNC files. Older eagles produce an aperture-only gerber file called
        # "profile.gbr" instead.
        self.generator_hints.append('eagle')

    @exprs.match(';EasyEDA .*')
    def parse_easyeda_version_header(self, match):
        self.generator_hints.append('easyeda')

    @exprs.match(';DRILL .*KiCad .*')
    def parse_kicad_version_header(self, match):
        self.generator_hints.append('kicad')
    
    @exprs.match(';FORMAT={([-0-9]+:[-0-9]+) ?/ (.*) / (inch|.*) / decimal}')
    def parse_kicad_number_format_comment(self, match):
        x, _, y = match[1].partition(':')
        x = None if x == '-' else int(x)
        y = None if y == '-' else int(y)
        self.settings.number_format = x, y
        self.found_kicad_format_comment = True
        self.settings.notation = match[2]
        self.settings.unit = Inch if match[3] == 'inch' else MM

    @exprs.match(';(.*)')
    def parse_comment(self, match):
        self.comments.append(match[1].strip())

        if all(cmt.startswith(marker)
                for cmt, marker in zip(reversed(self.comments), ['Version', 'Job', 'User', 'Date'])):
            self.generator_hints.append('siemens')

