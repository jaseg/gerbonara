from os import path, listdir
from glob import glob

from . import __version__

import click


@click.group()
@click.version_option(__version__)
def cli():
    pass


@click.command()
@click.option('-o', '--outfile', type=click.File(mode='wb'), help='Output Filename (extension will be added automatically)')
@click.option('-t', '--theme', default='default', type=click.Choice(['default', 'OSH Park', 'Blue', 'Transparent Copper', 'Transparent Multilayer'], case_sensitive=False), help='Select render theme')
@click.option('-w', '--width', type=click.INT, help='Maximum width')
@click.option('-h', '--height', type=click.INT, help='Maximum height')
@click.option('-v', '--verbose', is_flag=True, help='Increase verbosity of the output')
@click.argument('filenames', nargs=-1, type=click.Path(exists=True))
def render(outfile, theme, width, height, verbose, filenames):
    """Render gerber files to image. If a directory is provided, it should be provided alone and should contain the gerber files for a single PCB."""
    if len(filenames) == 0:
        raise click.UsageError(message='No files or folders provided')
    if len(filenames) > 1:
        for f in filenames:
            if path.isdir(f):
                raise click.UsageError(message='If a directory is provided, it should be provided alone and should contain the gerber files for a single PCB')

    # list files if folder id given
    if len(filenames) == 1 and path.isdir(filenames[0]):
        filenames = listdir(filenames[0])
        #filenames = [f for f in glob(f'{filenames[0]}/*.txt')]

    click.echo(f'render {filenames} with theme {theme}')


cli.add_command(render)
