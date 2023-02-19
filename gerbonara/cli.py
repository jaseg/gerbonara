#!/usr/bin/env python3

import math
import click
import re
import warnings
import json
from pathlib import Path

from .utils import MM, Inch
from .cam import FileSettings
from .rs274x import GerberFile
from .layers import LayerStack, NamingScheme
from . import __version__


NAMING_SCHEMES = [n for n in dir(NamingScheme) if not n.startswith('_')]

def print_version(ctx, param, value):
    if value and not ctx.resilient_parsing:
        click.echo(f'Version {__version__}')
        ctx.exit()


def apply_transform(transform, unit, layer_or_stack):
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
        layer_or_stack.rotate(math.radians(angle), (cx, cy), unit)

    (x_min, y_min), (x_max, y_max) = layer_or_stack.bounding_box(unit, default=((0, 0), (0, 0)))
    width, height = x_max - x_min, y_max - y_min

    def origin():
        translate(-x_min, -y_min)

    def center():
        translate(-x_min-width/2, -y_min-height/2)

    exec(transform, {key: value for key, value in math.__dict__.items() if not key.startswith('_')}, locals())


@click.group()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
def cli():
    pass


@cli.command()
@click.option('--format-warnings/--no-warnings', ' /-s', default=False, help='''Enable or disable file format warnings
              during parsing (default: off)''')
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option('-m', '--input-map', type=click.Path(exists=True, path_type=Path), help='''Extend or override layer name
              mapping with name map from JSON file. The JSON file must contain a single JSON dict with an arbitrary
              number of string: string entries. The keys are interpreted as regexes applied to the filenames via
              re.fullmatch, and each value must either be the string "ignore" to remove this layer from previous
              automatic guesses, or a gerbonara layer name such as "top copper", "inner_2 copper" or "bottom silk".''')
@click.option('--use-builtin-name-rules/--no-builtin-name-rules', default=True, help='''Disable built-in layer name
              rules and use only rules given by --input-map''')
@click.option('--force-zip', is_flag=True, help='''Force treating input path as a zip file (default: guess file type
              from extension and contents)''')
@click.option('--top/--bottom', help='Which side of the board to render')
@click.option('--command-line-units', type=click.Choice(['metric', 'us-customary']), default='metric', help='Units for values given in --transform. Default: millimeter')
@click.option('--margin', type=float, default=0.0, help='Add space around the board inside the viewport')
@click.option('--force-bounds', help='Force SVG bounding box to value given as "min_x,min_y,max_x,max_y"')
@click.option('--inkscape/--standard-svg', default=True, help='Export in Inkscape SVG format with layers and stuff.')
@click.option('--colorscheme', type=click.Path(exists=True, path_type=Path), help='''Load colorscheme from given JSON
              file. The JSON file must contain a single dict with keys copper, silk, mask, paste, drill and outline.
              Each key must map to a string containing either a normal 6-digit hex color with leading hash sign, or an
              8-digit hex color with leading hash sign, where the last two digits set the layer's alpha value (opacity),
              with FF being completely opaque, and 00 being invisibly transparent.''')
@click.argument('inpath', type=click.Path(exists=True))
@click.argument('outfile', type=click.File('w'), default='-')
def render(inpath, outfile, format_warnings, input_map, use_builtin_name_rules, force_zip, top, command_line_units,
           margin, force_bounds, inkscape, colorscheme):
    """ Render a gerber file, or a directory or zip of gerber files into an SVG file. """

    overrides = json.loads(input_map.read_bytes()) if input_map else None
    with warnings.catch_warnings():
        warnings.simplefilter('default' if format_warnings else 'ignore')
        if force_zip:
            stack = LayerStack.open_zip(inpath, overrides=overrides, autoguess=use_builtin_name_rules)
        else:
            stack = LayerStack.open(inpath, overrides=overrides, autoguess=use_builtin_name_rules)

    unit = MM if command_line_units == 'metric' else Inch

    if force_bounds:
        min_x, min_y, max_x, max_y = list(map(float, force_bounds.split(',')))
        force_bounds = (min_x, min_y), (max_x, max_y)

    if colorscheme:
        colorscheme = json.loads(colorscheme.read_text())

    outfile.write(str(stack.to_pretty_svg(side='top' if top else 'bottom', margin=margin, arg_unit=unit, svg_unit=MM,
                        force_bounds=force_bounds, inkscape=inkscape, colors=colorscheme)))


@cli.command()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option('--format-warnings/--no-warnings', ' /-s', default=True, help='''Enable or disable file format warnings
              during parsing (default: on)''')
@click.option('-t', '--transform', help='''Execute python transformation script on input. You have access to the functions
              translate(x, y), scale(factor) and rotate(angle, center_x?, center_y?), the bounding box variables x_min,
              y_min, x_max, y_max, width and height, and everything from python\'s built-in math module (e.g. pi, sqrt,
              sin). As convenience methods, center() and origin() are provided to center the board resp. move its
              bottom-left corner to the origin. Coordinates are given in --command-line-units, angles in degrees, and
              scale as a scale factor (as opposed to a percentage). Example: "translate(-10, 0); rotate(45, 0, 5)"''')
@click.option('--command-line-units', type=click.Choice(['metric', 'us-customary']), default='metric', help='Units for values given in --transform. Default: millimeter')
@click.option('-n', '--number-format', help='Override number format to use during export in "[integer digits].[decimal digits]" notation, e.g. "2.6".')
@click.option('-u', '--units', type=click.Choice(['metric', 'us-customary']), help='Override export file units')
@click.option('-z', '--zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='Override export zero suppression setting. Note: The meaning of this value is like in the Gerber spec for both Gerber and Excellon files!')
@click.option('--keep-comments/--drop-comments', help='Keep gerber comments. Note: Comments will be prepended to the start of file, and will not occur in their old position.')
@click.option('--reuse-input-settings/--default-settings,', default=False, help='Use the same export settings as the input file instead of sensible defaults.')
@click.option('--input-number-format', help='Override number format of input file (mostly useful for Excellon files)')
@click.option('--input-units', type=click.Choice(['us-customary', 'metric']), help='Override units of input file')
@click.option('--input-zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='Override zero suppression setting of input file')
@click.argument('infile')
@click.argument('outfile')
def rewrite(transform, command_line_units, number_format, units, zero_suppression, keep_comments, reuse_input_settings,
            input_number_format, input_units, input_zero_suppression, infile, outfile, format_warnings):
    """ Parse a gerber file, apply transformations, and re-serialize it into a new gerber file. Without transformations,
    this command can be used to convert a gerber file to use different settings (e.g. units, precision), but can also be
    used to "normalize" gerber files in a weird format into a more standards-compatible one as gerbonara's gerber parser
    is significantly more robust for weird inputs than others. """

    input_settings = FileSettings()
    if input_number_format:
        a, _, b = input_number_format.partition('.')
        input_settings.number_format = (int(a), int(b))

    if input_zero_suppression:
        input_settings.zeros = None if input_zero_suppression == 'off' else input_zero_suppression

    if input_units:
        input_settings.unit = MM if input_units == 'metric' else Inch

    with warnings.catch_warnings():
        warnings.simplefilter('default' if format_warnings else 'ignore')
        f = GerberFile.open(infile, override_settings=input_settings)

    if transform:
        command_line_units = MM if command_line_units == 'metric' else Inch
        apply_transform(transform, command_line_units, f)

    if reuse_input_settings:
        output_settings = FileSettings()
    else:
        output_settings = FileSettings.defaults()

    if number_format:
        a, _, b = number_format.partition('.')
        output_settings.number_format = (int(a), int(b))

    if units:
        output_settings.unit = MM if units == 'metric' else Inch

    if zero_suppression:
        output_settings.zeros = None if zero_suppression == 'off' else zero_suppression

    f.save(outfile, output_settings, not keep_comments)


@cli.command()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option('-m', '--input-map', type=click.Path(exists=True, path_type=Path), help='''Extend or override layer name
              mapping with name map from JSON file. The JSON file must contain a single JSON dict with an arbitrary
              number of string: string entries. The keys are interpreted as regexes applied to the filenames via
              re.fullmatch, and each value must either be the string "ignore" to remove this layer from previous
              automatic guesses, or a gerbonara layer name such as "top copper", "inner_2 copper" or "bottom silk".''')
@click.option('--use-builtin-name-rules/--no-builtin-name-rules', default=True, help='''Disable built-in layer name
              rules and use only rules given by --input-map''')
@click.option('--format-warnings/--no-warnings', ' /-s', default=True, help='''Enable or disable file format warnings
              during parsing (default: on)''')
@click.option('--units', type=click.Choice(['metric', 'us-customary']), default='metric', help='''Units for values given
              in transform script. Default: millimeter''')
@click.option('-n', '--number-format', help='''Override number format to use during export in
              "[integer digits].[decimal digits]" notation, e.g. "2.6".''')
@click.option('-u', '--units', type=click.Choice(['metric', 'us-customary']), help='Override export file units')
@click.option('-z', '--zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='''Override export zero
              suppression setting for exported Gerber files. Note: This does not affect Excellon output, which *always*
              uses explicit decimal points to avoid mismatches between output format and metadata in job files untouched
              by gerbonara.''')
@click.option('--reuse-input-settings/--default-settings,', default=False, help='''Use the same export settings as the
              input file instead of sensible defaults.''')
@click.option('--force-zip', is_flag=True, help='''Force treating input path as a zip file (default: guess file type
              from extension and contents)''')
@click.option('--output-naming-scheme', type=click.Choice(NAMING_SCHEMES), help=f'''Name output files according to the
              selected naming scheme instead of keeping the old file names. Supported values are:
              {", ".join(NAMING_SCHEMES)}''')
@click.argument('transform')
@click.argument('inpath')
@click.argument('outpath')
def transform(transform, units, number_format, zero_suppression, reuse_input_settings, inpath, outpath,
            format_warnings, input_map, use_builtin_name_rules):
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
        warnings.simplefilter('default' if format_warnings else 'ignore')
        if force_zip:
            stack = LayerStack.open_zip(path, overrides=overrides, autoguess=use_builtin_name_rules)
        else:
            stack = LayerStack.open(path, overrides=overrides, autoguess=use_builtin_name_rules)

    units = MM if units == 'metric' else Inch
    apply_transform(transform, units, stack)

    output_settings = FileSettings() if reuse_input_settings else FileSettings.defaults()

    if number_format:
        a, _, b = number_format.partition('.')
        output_settings.number_format = (int(a), int(b))

    if units:
        output_settings.unit = MM if units == 'metric' else Inch

    if zero_suppression:
        output_settings.zeros = None if zero_suppression == 'off' else zero_suppression

    stack.save_to_directory(outpath, naming_scheme=naming_scheme,
                            gerber_settings=output_settings,
                            excellon_settings=output_settings.replace(zeros=None))


@cli.command()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option('--format-warnings/--no-warnings', ' /-s', default=True, help='''Enable or disable file format warnings
              during parsing (default: on)''')
@click.option('--units', type=click.Choice(['us-customary', 'metric']), default='metric', help='Output bounding box in this unit (default: millimeter)')
@click.option('--input-number-format', help='Override number format of input file (mostly useful for Excellon files)')
@click.option('--input-units', type=click.Choice(['us-customary', 'metric']), help='Override units of input file')
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

    if input_units:
        input_settings.unit = MM if input_units == 'metric' else Inch

    with warnings.catch_warnings():
        warnings.simplefilter('default' if format_warnings else 'ignore')
        f = GerberFile.open(infile, override_settings=input_settings)

    units = MM if units == 'metric' else Inch
    (x_min, y_min), (x_max, y_max) = f.bounding_box(unit=units)
    print(f'{x_min:.6f} {y_min:.6f} {x_max:.6f} {y_max:.6f} [{units}]')


@cli.command()
@click.option('--format-warnings/--no-warnings', ' /-s', default=True, help='''Enable or disable file format warnings
              during parsing (default: on)''')
@click.option('--force-zip', is_flag=True, help='Force treating input path as zip file (default: guess file type from extension and contents)')
@click.argument('path', type=click.Path(exists=True))
def layers(path, force_zip, format_warnings):
    with warnings.catch_warnings():
        warnings.simplefilter('default' if format_warnings else 'ignore')
        if force_zip:
            stack = LayerStack.open_zip(path)
        else:
            stack = LayerStack.open(path)

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
@click.option('--format-warnings/--no-warnings', ' /-s', default=False, help='''Enable or disable file format warnings
              during parsing (default: off)''')
@click.option('--force-zip', is_flag=True, help='Force treating input path as zip file (default: guess file type from extension and contents)')
@click.argument('path', type=click.Path(exists=True))
def meta(path, force_zip, format_warnings):
    """ Extract layer mapping and print it along with layer metadata as JSON to stdout. A machine-readable variant of
    the "layers" command. All lengths in the JSON are given in millimeter. """

    with warnings.catch_warnings():
        warnings.simplefilter('default' if format_warnings else 'ignore')
        if force_zip:
            stack = LayerStack.open_zip(path)
        else:
            stack = LayerStack.open(path)

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
        d[function] = {
                'format': 'Gerber',
                'path': str(layer.original_path),
                'apertures': len(layer.apertures),
                'objects': len(layer.objects),
                'bounding_box': {'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y},
        }

    out['drill_layers'] = []
    for layer in stack.drill_layers:
        out['drill_layers'].append({
            'format': 'Excellon',
            'path': str(layer.original_path),
            'plating': layer.plating_type,
        })

    print(json.dumps(out))


if __name__ == '__main__':
    cli()

