#!/usr/bin/env python3

import click

from .layers import LayerStack


@click.command()
@click.option('-t' ,'--top', help='Render board top side.', is_flag=True)
@click.option('-b' ,'--bottom', help='Render board bottom side.', is_flag=True)
@click.argument('gerber_dir_or_zip', type=click.Path(exists=True))
@click.argument('output_svg', required=False, default='-', type=click.File('w'))
def render(gerber_dir_or_zip, output_svg, top, bottom):
    if (bool(top) + bool(bottom))  != 1:
        raise click.UsageError('Excactly one of --top or --bottom must be given.')

    stack = LayerStack.open(gerber_dir_or_zip, lazy=True)
    print(f'Loaded {stack}')

    svg = stack.to_pretty_svg(side=('top' if top else 'bottom'))
    output_svg.write(str(svg))

if __name__ == '__main__':
    render()

