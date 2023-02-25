.. _cli-doc:

Gerbonara's Command-Line Interface
==================================

Gerbonara comes with a built-in command-line interface that has functions for analyzing, rendering, modifying, and
merging Gerber files.

Invocation
----------

There are two ways to call gerbonara's command-line interface:

.. :code:

   $ gerbonara
   $ python -m gerbonara

For the first to work, make sure the installation's ``bin`` dir is in your ``$PATH``. If you installed gerbonara
system-wide, that should be the case already, since the binary should end up in ``/usr/bin``. If you installed gerbonara
using ``pip install --user``, make sure you have your user's ``~/.local/bin`` in your ``$PATH``.

Commands and their usage
------------------------

.. code-block:: console

    $ gerbonara --help
    Usage: gerbonara [OPTIONS] COMMAND [ARGS]...

      The gerbonara CLI allows you to analyze, render, modify and merge both
      individual Gerber or Excellon files as well as sets of those files

    Options:
      --version
      --help     Show this message and exit.

    Commands:
      bounding-box  Print the bounding box of a gerber file in "[x_min]...
      layers        Read layers from a directory or zip with Gerber files and...
      merge         Merge multiple single Gerber or Excellon files, or...
      meta          Extract layer mapping and print it along with layer...
      render        Render a gerber file, or a directory or zip of gerber...
      rewrite       Parse a single gerber file, apply transformations, and...
      transform     Transform all gerber files in a given directory or zip...

Rendering
~~~~~~~~~

Gerbonara can render single Gerber (:py:class:`~.rs274x.GerberFile`) or Excellon (:py:class:`~.excellon.ExcellonFile`)
layers, or whole board stacks (:py:class:`~.layers.LayerStack`) to SVG.

``gerbonara render``
********************
.. program:: gerbonara render

.. code-block:: console

    $ gerbonara render [OPTIONS] INPATH [OUTFILE]

``gerbonara render`` renders one or more Gerber or Excellon files as a single SVG file. It can read single files,
directorys of files, and ZIP files. To read directories or zips, it applies gerbonara's layer filename matching rules.

.. option:: --warnings [default|ignore|once]

    Enable or disable file format warnings during parsing (default: on)


.. option:: -m, --input-map <json_file>

   Extend or override layer name mapping with name map from JSON file. The JSON file must contain a single JSON dict
   with an arbitrary number of string: string entries. The keys are interpreted as regexes applied to the filenames via
   re.fullmatch, and each value must either be the string ``ignore`` to remove this layer from previous automatic guesses,
   or a gerbonara layer name such as ``top copper``, ``inner_2 copper`` or ``bottom silk``.

.. option:: --use-builtin-name-rules / --no-builtin-name-rules

    Disable built-in layer name rules and use only rules given by :option:`--input-map`


.. option:: --force-zip

   Force treating input path as a zip file (default: guess file type from extension and contents)

.. option:: --top, --bottom

   Which side of the board to render

.. option:: --command-line-units <metric|us-customary>

    Units for values given in other options. Default: millimeter

.. option:: --margin <float>

   Add space around the board inside the viewport

.. option:: --force-bounds <min_x,min_y,max_x,max_y>

   Force SVG bounding box to the given value.

.. option:: --inkscape, --standard-svg

   Export in Inkscape SVG format with layers and stuff instead of plain SVG.

.. option:: --colorscheme <json_file>

    Load colorscheme from given JSON file. The JSON file must contain a single dict with keys ``copper``, ``silk``,
    ``mask``, ``paste``, ``drill`` and ``outline``. Each key must map to a string containing either a normal 6-digit hex
    color with leading hash sign, or an 8-digit hex color with leading hash sign, where the last two digits set the
    layer's alpha value (opacity), with ``ff`` being completely opaque, and ``00`` being invisibly transparent.

Modification
~~~~~~~~~~~~

``gerbonara rewrite``
*********************

``gerbonara transform``
***********************

``gerbonara merge``
*******************

File analysis
~~~~~~~~~~~~~

``gerbonara bounding-box``
**************************

``gerbonara meta``
******************

``gerbonara layers``
********************

