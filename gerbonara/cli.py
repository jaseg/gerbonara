#!/usr/bin/env python3

import click
import re

from .utils import MM, Inch
from .cam import FileSettings
from .rs274x import GerberFile
from . import __version__


def print_version(ctx, param, value):
    click.echo(f'Version {__version__}')


@click.group()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
def cli():
    pass


@cli.command()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.argument('infiles', nargs=-1, required=True)
@click.argument('outfile', required=False)
def render(infiles, outfile):
    """ Render one or more gerber files into an SVG file. Can process entire folders or zip files of gerber files, and
    can render individual files from zips using "[zip file]:[member]" syntax. To specify a layer mapping, use
    "[layer]=[file]" syntax, e.g. "top-silk=something.zip:foo/bar.gbr". Layers get merged in the same order that they
    appear on the command line, and for each logical layer only the last given file is rendered."""


def apply_transform(transform, unit, layer):
    for name, args, garbage in re.finditer(r'\s*([a-z]+)\s*\([\s-.0-9]*\)\s*|.*'):
        if name not in ('translate', 'scale', 'rotate'):
            raise ValueError(f'Unsupported transform {name}. Supported transforms are "translate", "scale" and "rotate".')

        args = [float(args) for arg in args.split()]
        if not args:
            raise ValueError('No transform arguments given')

        if name == 'translate':
            if len(args) != 2:
                raise ValueError(f'transform "translate" requires exactly two coordinates (x, and y), not {len(args)}')

            x, y = args
            layer.offset(x, y, unit)

        elif name == 'scale':
            if len(args) > 1:
                # We don't support non-uniform scaling with scale_x != scale_y since that isn't possible with straight
                # Gerber polygon or circular apertures, or holes.
                raise ValueError(f'transform "scale" requires exactly one argument, not {len(args)}')

            layer.scale(*args)

        elif name == 'rotate':
            if len(args) not in (1, 3):
                raise ValueError(f'transform "rotate" requires either one or three coordinates (angle, origin x, and origin y), not {len(args)}')

            angle = args[0]
            cx, cy = args[1:] or (0, 0)
            layer.rotate(angle, cx, cy, unit)


@cli.command()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option('-t', '--transform', help='Apply transform given in pseudo-SVG syntax. Supported are "translate", "scale" and "rotate". Example: "translate(-10 0) rotate(45 0 5)"')
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
            input_number_format, input_units, input_zero_suppression, infile, outfile):
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

    f = GerberFile.open(infile, override_settings=input_settings)

    if transform:
        command_line_units = MM if command_line_units == 'metric' else Inch
        apply_transform(transform, command_line_units, f)

    if reuse_input_settings:
        output_settings = FileSettings()
    else:
        output_settings = FileSettings(unit=MM, number_format=(4,5), zeros=None)

    if number_format:
        output_settings = number_format

    if units:
        output_settings.unit = MM if units == 'metric' else Inch

    if zero_suppression:
        output_settings.zeros = None if zero_suppression == 'off' else zero_suppression

    f.save(outfile, output_settings, not keep_comments)


@cli.command()
@click.option('--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option('--units', type=click.Choice(['us-customary', 'metric']), default='metric', help='Output bounding box in this unit (default: millimeter)')
@click.option('--input-number-format', help='Override number format of input file (mostly useful for Excellon files)')
@click.option('--input-units', type=click.Choice(['us-customary', 'metric']), help='Override units of input file')
@click.option('--input-zero-suppression', type=click.Choice(['off', 'leading', 'trailing']), help='Override zero suppression setting of input file')
@click.argument('infile')
def bounding_box(infile, input_number_format, input_units, input_zero_suppression, units):
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

    f = GerberFile.open(infile, override_settings=input_settings)
    units = MM if units == 'metric' else Inch
    (x_min, y_min), (x_max, y_max) = f.bounding_box(unit=units)
    print(f'{x_min:.6f} {y_min:.6f} {x_max:.6f} {y_max:.6f} [{units}]')


if __name__ == '__main__':
    cli()

