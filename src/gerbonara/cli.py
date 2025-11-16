#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2023 Jan Sebastian Götte <gerbonara@jaseg.de>
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
import click
import dataclasses
import re
import warnings
import json
import sys
import itertools
import webbrowser
import warnings
from pathlib import Path

from .utils import MM, Inch
from .cam import FileSettings
from .rs274x import GerberFile
from . import layers as lyr
from . import __version__
from .cad.kicad import schematic as kc_schematic
from .cad.kicad import tmtheme
from .cad import protoserve


def _showwarning(message, category, filename, lineno, file=None, line=None):
    if file is None:
        file = sys.stderr

    filename = Path(filename)
    gerbonara_module_install_location = Path(__file__).parent.parent
    if filename.is_relative_to(gerbonara_module_install_location):
        filename = filename.relative_to(gerbonara_module_install_location)

    print(f'{filename}:{lineno}: {message}', file=file)
warnings.showwarning = _showwarning

def _print_version(ctx, param, value):
    if value and not ctx.resilient_parsing:
        click.echo(f'Version {__version__}')
        ctx.exit()


def _apply_transform(transform, unit, layer_or_stack):
    def translate(x, y):
        layer_or_stack.offset(x, y, unit)

    def scale(factor):
        """ Scale layer by a given factor, e.g. 1.0 for no change, 2.0 to double all coordinates in both axes. Note that
        we only offer uniform scaling with a single factor applied along both coordinate axes because anything else
        would not be possible with arbitrary Gerber apertures, and definitely mess up holes. We could still do this, but
        the result would almost certainly not be what the user is looking for.

        The main reason why this function might make sense is to fix up boards exported as G-code by programs that
        aren't EDA tools and that for whatever reason ended up exporting in a weird unit."""
        layer_or_stack.scale(factor)

    def rotate(angle, cx=0, cy=0):
        layer_or_stack.rotate(math.radians(angle), cx, cy, unit)

    (x_min, y_min), (x_max, y_max) = layer_or_stack.bounding_box(unit, default=((0, 0), (0, 0)))
    width, height = x_max - x_min, y_max - y_min

    def origin():
        translate(-x_min, -y_min)

    def center():
        translate(-x_min-width/2, -y_min-height/2)

    exec(transform, {key: value for key, value in math.__dict__.items() if not key.startswith('_')}, locals())


class Coordinate(click.ParamType):
    name = 'coordinate'

    def __init__(self, dimension=2):
        self.dimension = dimension
    
    def convert(self, value, param, ctx):
        try:
            coords = [float(e) for e in value.split(',')]
            if len(coords) != self.dimension:
                raise ValueError()
            return coords

        except ValueError:
            self.fail(f'{value!r} is not a valid coordinate. A coordinate consists of exactly {self.dimension} comma-separate floating-point numbers.')

class Rotation(click.ParamType):
    name = 'rotation'

    def convert(self, value, param, ctx):
        try:
            coords = [float(e) for e in value.split(',')]
            if len(coords) not in (1, 3):
                raise ValueError()

            theta, x, y, *_rest = *coords, 0, 0
            return theta, x, y

        except ValueError:
            self.fail(f'{value!r} is not a valid rotation. A rotation is either a floating point angle ("[theta]"), or the same angle followed by comma-separated X and Y coordinates of the rotation center ("[theta],[cx],[cy]").')


class Unit(click.Choice):
    name = 'unit'

    def __init__(self):
        super().__init__(['metric', 'us-customary'])

    def convert(self, value, param, ctx):
        value = super().convert(value, param, ctx)
        return MM if value == 'metric' else Inch


class NamingScheme(click.Choice):
    name = 'naming_scheme'

    def __init__(self):
        super().__init__([n for n in dir(lyr.NamingScheme) if not n.startswith('_')])

    def convert(self, value, param, ctx):
        return getattr(lyr.NamingScheme, super().convert(value, param, ctx))


@click.group()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
def cli():
    """ The gerbonara CLI allows you to analyze, render, modify and merge both individual Gerber or Excellon files as
    well as sets of those files """
    pass

@cli.group('protoboard')
def protoboard_group():
    pass


@protoboard_group.command()
@click.option('-h', '--host', default=None, help='Hostname to listen on. Defaults to localhost.')
@click.option('-p', '--port', type=int, default=1337, help='Port to listen on. Defaults to 1337')
def interactive(host, port):
    ''' Launch gerbonar's interactive protoboard designer in your browser '''
    
    if host is None:
        @protoserve.app.before_serving
        async def open_browser():
            webbrowser.open_new(f'http://localhost:{port}/')
    protoserve.app.run(host=host, port=port, use_reloader=False, debug=False)


@cli.group('kicad')
def kicad_group():
    pass


@kicad_group.group('schematic')
def schematic_group():
    pass


@schematic_group.command()
@click.argument('inpath', type=click.Path(exists=True))
@click.argument('theme', type=click.Path(exists=True))
@click.argument('outfile', type=click.File('w'), default='-')
def render(inpath, theme, outfile):
    sch = kc_schematic.Schematic.open(inpath)
    cs = tmtheme.TmThemeSchematic(Path(theme).read_text())
    with outfile as f:
        f.write(str(sch.to_svg(cs)))


@cli.command()
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), default='default',
              help='''Enable or disable file format warnings during parsing (default: on)''')
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('-m', '--input-map', type=click.Path(exists=True, path_type=Path), help='''Extend or override layer name
              mapping with name map from JSON file. The JSON file must contain a single JSON dict with an arbitrary
              number of string: string entries. The keys are interpreted as regexes applied to the filenames via
              re.fullmatch, and each value must either be the string "ignore" to remove this layer from previous
              automatic guesses, or a gerbonara layer name such as "top copper", "inner_2 copper" or "bottom silk".''')
@click.option('--use-builtin-name-rules/--no-builtin-name-rules', default=True, help='''Disable built-in layer name
              rules and use only rules given by --input-map''')
@click.option('--force-zip', is_flag=True, help='''Force treating input path as a zip file (default: guess file type
              from extension and contents)''')
@click.option('--top', 'side', flag_value='top', help='Render top side')
@click.option('--bottom', 'side', flag_value='bottom', help='Render top side')
@click.option('--command-line-units', type=Unit(), help='''Units for values given in other options. Default:
              millimeter''')
@click.option('--margin', type=float, default=0.0, help='Add space around the board inside the viewport')
@click.option('--force-bounds', help='Force SVG bounding box to value given as "min_x,min_y,max_x,max_y"')
@click.option('--inkscape/--standard-svg', default=True, help='Export in Inkscape SVG format with layers and stuff.')
@click.option('--pretty/--no-filters', default=True, help='''Export pseudo-realistic render using filters (default) or
              just stack up layers using given colorscheme. In "--no-filters" mode, by default all layers are exported
              unless either "--top" or "--bottom" is given.''')
@click.option('--drills/--no-drills', default=True, help='''Include (default) or exclude drills ("--no-filters" only!)''')
@click.option('--colorscheme', type=click.Path(exists=True, path_type=Path), help='''Load colorscheme from given JSON
              file. The JSON file must contain a single dict with keys copper, silk, mask, paste, drill and outline.
              Each key must map to a string containing either a normal 6-digit hex color with leading hash sign, or an
              8-digit hex color with leading hash sign, where the last two digits set the layer's alpha value (opacity),
              with FF being completely opaque, and 00 being invisibly transparent.''')
@click.argument('inpath', type=click.Path(exists=True))
@click.argument('outfile', type=click.File('w'), default='-')
def render(inpath, outfile, format_warnings, input_map, use_builtin_name_rules, force_zip, side, drills,
           command_line_units, margin, force_bounds, inkscape, pretty, colorscheme):
    """ Render a gerber file, or a directory or zip of gerber files into an SVG file. """

    overrides = json.loads(input_map.read_bytes()) if input_map else None
    with warnings.catch_warnings():
        warnings.simplefilter(format_warnings)
        if force_zip:
            stack = lyr.LayerStack.open_zip(inpath, overrides=overrides, autoguess=use_builtin_name_rules)
        else:
            stack = lyr.LayerStack.open(inpath, overrides=overrides, autoguess=use_builtin_name_rules)

    if force_bounds:
        min_x, min_y, max_x, max_y = list(map(float, force_bounds.split(',')))
        force_bounds = (min_x, min_y), (max_x, max_y)

    if colorscheme:
        colorscheme = json.loads(colorscheme.read_text())

    if pretty:
        svg = stack.to_pretty_svg(side='bottom' if side == 'bottom' else 'top', margin=margin,
                                              arg_unit=(command_line_units or MM),
                          svg_unit=MM, force_bounds=force_bounds, inkscape=inkscape, colors=colorscheme)
    else:
        svg = stack.to_svg(side_re=side or '.*', margin=margin, drills=drills, arg_unit=(command_line_units or MM),
                          svg_unit=MM, force_bounds=force_bounds, colors=colorscheme)
    outfile.write(str(svg))


@cli.command()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), default='default',
              help='''Enable or disable file format warnings during parsing (default: on)''')
@click.option('-t', '--transform', help='''Execute python transformation script on input. You have access to the
              functions translate(x, y), scale(factor) and rotate(angle, center_x?, center_y?), the bounding box
              variables x_min, y_min, x_max, y_max, width and height, and everything from python\'s built-in math module
              (e.g. pi, sqrt, sin). As convenience methods, center() and origin() are provided to center the board resp.
              move its bottom-left corner to the origin. Coordinates are given in --command-line-units, angles in
              degrees, and scale as a scale factor (as opposed to a percentage). Example: "translate(-10, 0); rotate(45,
              0, 5)"''')
@click.option('--command-line-units', type=Unit(), help='''Units for values given in other options. Default:
              millimeter''')
@click.option('-n', '--number-format', help='''Override number format to use during export in "[integer digits].[decimal
              digits]" notation, e.g. "2.6".''')
@click.option('-u', '--units', type=Unit(), help='Override export file units')
@click.option('-z', '--zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='''Override export
              zero suppression setting. Note: The meaning of this value is like in the Gerber spec for both Gerber and
              Excellon files!''')
@click.option('--keep-comments/--drop-comments', help='''Keep gerber comments. Note: Comments will be prepended to the
              start of file, and will not occur in their old position.''')
@click.option('--reuse-input-settings', 'output_format', flag_value='reuse', help='''Use the same export settings as the
              input file instead of sensible defaults.''')
@click.option('--default-settings', 'output_format', default=True, flag_value='defaults', help='''Use sensible defaults
              for the output file format settings (default).''')
@click.option('--input-number-format', help='Override number format of input file (mostly useful for Excellon files)')
@click.option('--input-units', type=Unit(), help='Override units of input file')
@click.option('--input-zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='''Override zero
              suppression setting of input file''')
@click.argument('infile')
@click.argument('outfile')
def rewrite(transform, command_line_units, number_format, units, zero_suppression, keep_comments, output_format,
            input_number_format, input_units, input_zero_suppression, infile, outfile, format_warnings):
    """ Parse a single gerber file, apply transformations, and re-serialize it into a new gerber file. Without
    transformations, this command can be used to convert a gerber file to use different settings (e.g. units,
    precision), but can also be used to "normalize" gerber files in a weird format into a more standards-compatible one
    as gerbonara's gerber parser is significantly more robust for weird inputs than others. """

    input_settings = FileSettings()
    if input_number_format:
        a, _, b = input_number_format.partition('.')
        input_settings.number_format = (int(a), int(b))

    if input_zero_suppression:
        input_settings.zeros = None if input_zero_suppression == 'off' else input_zero_suppression

    input_settings.unit = input_units

    with warnings.catch_warnings():
        warnings.simplefilter(format_warnings)
        f = GerberFile.open(infile, override_settings=input_settings)

    if transform:
        _apply_transform(transform, command_line_units or MM, f)

    output_format = f.import_settings if output_format == 'reuse' else FileSettings.defaults()
    if number_format:
        a, _, b = number_format.partition('.')
        output_format.number_format = (int(a), int(b))

    if units:
        output_format.unit = units

    if zero_suppression:
        output_format.zeros = None if zero_suppression == 'off' else zero_suppression

    f.save(outfile, output_format, not keep_comments)


@cli.command()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('-m', '--input-map', type=click.Path(exists=True, path_type=Path), help='''Extend or override layer name
              mapping with name map from JSON file. The JSON file must contain a single JSON dict with an arbitrary
              number of string: string entries. The keys are interpreted as regexes applied to the filenames via
              re.fullmatch, and each value must either be the string "ignore" to remove this layer from previous
              automatic guesses, or a gerbonara layer name such as "top copper", "inner_2 copper" or "bottom silk".''')
@click.option('--use-builtin-name-rules/--no-builtin-name-rules', default=True, help='''Disable built-in layer name
              rules and use only rules given by --input-map''')
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), default='default',
              help='''Enable or disable file format warnings during parsing (default: on)''')
@click.option('--units', type=Unit(), help='Units for values given in other options. Default: millimeter')
@click.option('-n', '--number-format', help='''Override number format to use during export in
              "[integer digits].[decimal digits]" notation, e.g. "2.6".''')
@click.option('--reuse-input-settings', 'output_format', flag_value='reuse', help='''Use the same export settings as the
              input file instead of sensible defaults.''')
@click.option('--default-settings', 'output_format', default=True, flag_value='defaults', help='''Use sensible defaults
              for the output file format settings (default).''')
@click.option('--force-zip', is_flag=True, help='''Force treating input path as a zip file (default: guess file type
              from extension and contents)''')
@click.option('--output-naming-scheme', type=NamingScheme(), help=f'''Name output files according to the selected naming
              scheme instead of keeping the old file names.''')
@click.argument('transform')
@click.argument('inpath')
@click.argument('outpath', type=click.Path(path_type=Path))
def transform(transform, units, output_format, inpath, outpath, format_warnings, input_map, use_builtin_name_rules,
              output_naming_scheme, number_format, force_zip):
    """ Transform all gerber files in a given directory or zip file using the given python transformation script.
        
        In the python transformation script you have access to the functions translate(x, y), scale(factor) and
        rotate(angle, center_x?, center_y?), the bounding box variables x_min, y_min, x_max, y_max, width and height,
        and everything from python\'s built-in math module (e.g. pi, sqrt, sin). As convenience methods, center() and
        origin() are provided to center the board resp. move its bottom-left corner to the origin. Coordinates are given
        in --command-line-units, angles in degrees, and scale as a scale factor (as opposed to a percentage). Example:
        "translate(-10, 0); rotate(45, 0, 5)"''')
    """

    overrides = json.loads(input_map.read_bytes()) if input_map else None
    with warnings.catch_warnings():
        warnings.simplefilter(format_warnings)
        if force_zip:
            stack = lyr.LayerStack.open_zip(inpath, overrides=overrides, autoguess=use_builtin_name_rules)
        else:
            stack = lyr.LayerStack.open(inpath, overrides=overrides, autoguess=use_builtin_name_rules)

    _apply_transform(transform, units, stack)

    output_format = None if output_format == 'reuse' else FileSettings.defaults()
    if number_format:
        if output_format is None:
            output_format = FileSettings.defaults()
        a, _, b = number_format.partition('.')
        output_format.number_format = (int(a), int(b))
    if outpath.is_file() or outpath.suffix.lower() == '.zip':
        stack.save_to_zipfile(outpath, naming_scheme=output_naming_scheme or {},
                                gerber_settings=output_format,
                                excellon_settings=dataclasses.replace(output_format, zeros=None))
    else:
        stack.save_to_directory(outpath, naming_scheme=output_naming_scheme or {},
                                gerber_settings=output_format,
                                excellon_settings=dataclasses.replace(output_format, zeros=None))


@cli.command()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('--command-line-units', type=Unit(), help='''Units for values given in --transform. Default:
              millimeter''')
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), default='default',
              help='''Enable or disable file format warnings during parsing (default: on)''')
@click.option('--offset', multiple=True, type=Coordinate(), help="""Offset for the n'th file as a "x,y" string in unit
              given by --command-line-units (default: millimeter). Can be given multiple times, and the first option
              affects the first input, the second option affects the second input, and so on.""")
@click.option('--rotation', multiple=True, type=Rotation(), help="""Rotation for the n'th file in degrees clockwise,
              optionally followed by comma-separated rotation center X and Y coordinates. Can be given multiple times,
              and the first option affects the first input, the second option affects the second input, and so on.""")
@click.option('-m', '--input-map', type=click.Path(exists=True, path_type=Path), multiple=True, help='''Extend or
              override layer name mapping with name map from JSON file. This option can be given multiple times, in
              which case the n'th option affects only the n'th input, like with --offset and --rotation. The JSON file
              must contain a single JSON dict with an arbitrary number of string: string entries. The keys are
              interpreted as regexes applied to the filenames via re.fullmatch, and each value must either be the string
              "ignore" to remove this layer from previous automatic guesses, or a gerbonara layer name such as "top
              copper", "inner_2 copper" or "bottom silk".''')
@click.option('--reuse-input-settings', 'output_format', flag_value='reuse', help='''Use the same export settings as the
              input file instead of sensible defaults.''')
@click.option('--default-settings', 'output_format', default=True, flag_value='defaults', help='''Use sensible defaults
              for the output file format settings (default).''')
@click.option('--output-naming-scheme', type=NamingScheme(), help=f'''Name output files according to the selected naming
              scheme instead of keeping the old file names of the first input.''')
@click.option('--output-board-name', help=f'''Override board name used with --output-naming-scheme''')
@click.option('--use-builtin-name-rules/--no-builtin-name-rules', default=True, help='''Disable built-in layer name
              rules and use only rules given by --input-map''')
@click.argument('inpath', nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.argument('outpath', type=click.Path(path_type=Path))
def merge(inpath, outpath, offset, rotation, input_map, command_line_units, output_format, output_naming_scheme,
          output_board_name, format_warnings, use_builtin_name_rules):
    """ Merge multiple single Gerber or Excellon files, or multiple stacks of Gerber files, into one. Hint: When used
    with only one input, this command "normalizes" the input, converting all files to a well-defined, widely supported
    Gerber subset with sane settings. When a --output-naming-scheme is given, it additionally renames all files to a
    standardized naming convention. """
    if not inpath:
        return

    target = None
    for p, offset, rotation, input_map in itertools.zip_longest(inpath, offset, rotation, input_map):
        if p is None:
            raise click.UsageError('More --offset, --rotation or --input-map options than input files')

        offset = offset or (0, 0)
        theta, cx, cy = rotation or (0, 0, 0)

        overrides = json.loads(input_map.read_bytes()) if input_map else None
        with warnings.catch_warnings():
            warnings.simplefilter(format_warnings)

            stack = lyr.LayerStack.open(p, overrides=overrides, autoguess=use_builtin_name_rules)

            if not math.isclose(offset[0], 0, abs_tol=1e-3) and math.isclose(offset[1], 0, abs_tol=1e-3):
                stack.offset(*offset, command_line_units or MM)

            if not math.isclose(theta, 0, abs_tol=1e-2):
                stack.rotate(theta, cx, cy)

            if target is None:
                target = stack
            else:
                target.merge(stack)

    if output_board_name:
        if not output_naming_scheme:
            warnings.warn('--output-board-name given without --output-naming-scheme. This will be ignored.')
        target.board_name = output_board_name
    output_format = None if output_format == 'reuse' else FileSettings.defaults()
    target.save_to_directory(outpath, naming_scheme=output_naming_scheme or {},
                            gerber_settings=output_format,
                            excellon_settings=dataclasses.replace(output_format, zeros=None))


@cli.command()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), default='default',
              help='''Enable or disable file format warnings during parsing (default: on)''')
@click.option('--units', type=Unit(), default='metric', help='Output bounding box in this unit (default: millimeter)')
@click.option('--input-number-format', help='Override number format of input file (mostly useful for Excellon files)')
@click.option('--input-units', type=Unit(), help='Override units of input file')
@click.option('--input-zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='Override zero suppression setting of input file')
@click.argument('infile')
def bounding_box(infile, format_warnings, input_number_format, input_units, input_zero_suppression, units):
    """ Print the bounding box of a gerber file in "[x_min] [y_min] [x_max] [y_max]" format. The bounding box contains
    all graphic objects in this file, so e.g. a 100 mm by 100 mm square drawn with a 1mm width circular aperture will
    result in an 101 mm by 101 mm bounding box.
    """

    input_settings = FileSettings()
    if input_number_format:
        a, _, b = input_number_format.partition('.')
        input_settings.number_format = (int(a), int(b))

    if input_zero_suppression:
        input_settings.zeros = None if input_zero_suppression == 'off' else input_zero_suppression

    input_settings.unit = input_units

    with warnings.catch_warnings():
        warnings.simplefilter(format_warnings)
        f = GerberFile.open(infile, override_settings=input_settings)

    (x_min, y_min), (x_max, y_max) = f.bounding_box(unit=units)
    print(f'{x_min:.6f} {y_min:.6f} {x_max:.6f} {y_max:.6f} [{units}]')


@cli.command()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), default='default',
              help='''Enable or disable file format warnings during parsing (default: on)''')
@click.option('--force-zip', is_flag=True, help='Force treating input path as zip file (default: guess file type from extension and contents)')
@click.argument('path', type=click.Path(exists=True))
def layers(path, force_zip, format_warnings):
    """ Read layers from a directory or zip with Gerber files and list the found layer / path assignment. """ 
    with warnings.catch_warnings():
        warnings.simplefilter(format_warnings)
        if force_zip:
            stack = lyr.LayerStack.open_zip(path)
        else:
            stack = lyr.LayerStack.open(path)

    print(f'Detected board name: {stack.board_name}')
    print(f'Probably exported by: {stack.generator or "Unknown"}')
    print(f'Board bounding box: {stack.bounding_box()} [mm]')

    if stack.netlist:
        print(f'Found netlist at {stack.netlist.original_path}')
    else:
        print('No netlist found')

    print('Graphical layers:')
    for (side, function), layer in stack.graphic_layers.items():
        print(f'{side} {function}: {layer}')
    if not stack.graphic_layers:
        print('(no graphical layers)')

    print('Drill layers:')
    for layer in stack.drill_layers:
        print(layer)
    if not stack.drill_layers:
        print('(no drill layers)')


@cli.command()
@click.option('--version', is_flag=True, callback=_print_version, expose_value=False, is_eager=True)
@click.option('--warnings', 'format_warnings', type=click.Choice(['default', 'ignore', 'once']), help='''Enable or
              disable file format warnings during parsing (default: on)''')
@click.option('--force-zip', is_flag=True, help='Force treating input path as zip file (default: guess file type from extension and contents)')
@click.argument('path', type=click.Path(exists=True))
def meta(path, force_zip, format_warnings):
    """ Extract layer mapping and print it along with layer metadata as JSON to stdout. A machine-readable variant of
    the "layers" command. All lengths in the JSON are given in millimeter. """

    with warnings.catch_warnings():
        warnings.simplefilter(format_warnings)
        if force_zip:
            stack = lyr.LayerStack.open_zip(path)
        else:
            stack = lyr.LayerStack.open(path)

    out = {}
    out['board_name'] = stack.board_name
    out['generator'] = stack.generator
    (min_x, min_y), (max_x, max_y) = stack.bounding_box(default=((None, None), (None, None)))
    out['bounding_box'] = {'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y}
    out['path'] = str(stack.original_path)

    if stack.netlist:
        out['netlist'] = {
                'format': 'IPC-356',
                'path': str(stack.netlist.original_path),
                'records': len(stack.netlist.test_records),
                'conductors': len(stack.netlist.conductors),
                'outlines': len(stack.netlist.outlines),
        }

    out['graphical_layers'] = {}
    for (side, function), layer in stack.graphic_layers.items():
        d = out['graphical_layers'][side] = out['graphical_layers'].get(side, {})
        (min_x, min_y), (max_x, max_y) = layer.bounding_box(default=((None, None), (None, None)))

        if layer.import_settings:
            numf = layer.import_settings.number_format
            format_settings = {
                'unit': str(layer.import_settings.unit),
                'number_format': f'{numf[0]}.{numf[1]}' if numf else None,
                'zero_suppression': str(layer.import_settings.zeros),
            }

        d[function] = {
                'format': 'Gerber',
                'path': str(layer.original_path),
                'apertures': len(list(layer.apertures())),
                'objects': len(layer.objects),
                'bounding_box': {'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y},
                'format_settings': format_settings,
        }

    out['drill_layers'] = []
    for layer in stack.drill_layers:
        if layer.import_settings:
            numf = layer.import_settings.number_format
            format_settings = {
                'unit': str(layer.import_settings.unit),
                'number_format': f'{numf[0]}.{numf[1]}' if numf else None,
                'zero_suppression': str(layer.import_settings.zeros),
            }

        out['drill_layers'].append({
            'format': 'Excellon',
            'path': str(layer.original_path),
            'plating': layer.plating_type,
            'format_settings': format_settings,
        })

    print(json.dumps(out))


if __name__ == '__main__':
    cli()

