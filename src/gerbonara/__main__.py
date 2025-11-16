#!/usr/bin/env python3

import click
from zipfile import is_zipfile
from pathlib import Path

from .layers import LayerStack
from .rs274x import GerberFile


@click.group()
def cli():
    pass

@cli.command(help='Render a folder or zip of Gerber and Excellon files to a pretty, semi-photorealistic SVG.')
@click.option('-t' ,'--top', help='Render board top side.', is_flag=True)
@click.option('-b' ,'--bottom', help='Render board bottom side.', is_flag=True)
@click.argument('input_zip_or_dir', type=click.Path(exists=True, path_type=Path))
@click.argument('output_svg', required=False, default='-', type=click.File('w'))
def pretty(input_zip_or_dir, output_svg, top, bottom):
    if (bool(top) + bool(bottom))  != 1:
        raise click.UsageError('Excactly one of --top or --bottom must be given when rendering a dir or zip of gerbers.')

    stack = LayerStack.open(input_zip_or_dir, lazy=True)
    print(f'Loaded {stack}')

    svg = stack.to_pretty_svg(side=('top' if top else 'bottom'))

    output_svg.write(str(svg))

@cli.command(help='Render an individual Gerber or Excellon file to SVG')
@click.option('-f', '--foreground', default='black', help='Foreground color')
@click.option('-b', '--background', default='white', help='Background color used for "clear" areas.')
@click.argument('input_gerber', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output_svg', required=False, default='-', type=click.File('w'))
def render(input_gerber, output_svg, foreground, background):
    layer = GerberFile.open(input_gerber)
    output_svg.write(str(layer.to_svg(fg=foreground, bg=background)))

if __name__ == '__main__':
    cli()

