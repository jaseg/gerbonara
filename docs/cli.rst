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

.. program:: gerbonara rewrite

.. code-block:: console
   
    gerbonara rewrite [OPTIONS] INFILE OUTFILE

Parse a single gerber file, apply transformations, and re-serialize it into a new gerber file. Without transformations,
this command can be used to convert a gerber file to use different settings (e.g. units, precision), but can also be
used to "normalize" gerber files in a weird format into a more standards-compatible one as gerbonara's gerber parser is
significantly more robust for weird inputs than others.

.. option:: --warnings <default|ignore|once>

   Enable or disable file format warnings during parsing (default: on)

.. option:: -t, --transform <code>

   Execute python transformation script on input. You have access to the functions ``translate(x, y)``,
   ``scale(factor)`` and ``rotate(angle, center_x?, center_y?)``, the bounding box variables ``x_min``, ``y_min``,
   ``x_max``, ``y_max``, ``width`` and ``height``, and everything from python's built-in math module (e.g. ``pi``,
   ``sqrt``, ``sin``). As convenience methods, ``center()`` and ``origin()`` are provided to center the board
   respectively move its bottom-left corner to the origin. Coordinates are given in ``--command-line-units``, angles in
   degrees, and scale as a scale factor (as opposed to a percentage). Example: ``translate(-10, 0); rotate(45, 0, 5)``

.. option:: --command-line-units <metric|us-customary>

    Units for values given in other options. Default: millimeter

.. option:: -n, --number-format <decimal.fractional>

   Override number format to use during export in ``[integer digits].[decimal digits]`` notation, e.g. ``2.6``.

.. option:: -u, --units <metric|us-customary>

   Override export file units

.. option:: -z, --zero-suppression <off|leading|trailing>

   Override export zero suppression setting. Note: The meaning of this value is like in the Gerber spec for both Gerber
   and Excellon files!

.. option:: --keep-comments, --drop-comments

   Keep gerber comments. Note: Comments will be prepended to the start of file, and will not occur in their old
   position.

.. option:: --default-settings, --reuse-input-settings

   Use sensible defaults for the output file format settings (default) or use the same export settings as the input file
   instead of sensible defaults.

.. option:: --input-number-format <decimal.fractional>

   Override number format of input file (mostly useful for Excellon files)

.. option:: --input-units <metric|us-customary>

   Override units of input file

.. option:: --input-zero-suppression <off|leading|trailing>

   Override zero suppression setting of input file


``gerbonara transform``
***********************

.. program:: gerbonara transform

.. code-block:: console

    gerbonara transform [OPTIONS] TRANSFORM INPATH OUTPATH

Transform all gerber files in a given directory or zip file using the given python transformation script.

In the python transformation script you have access to the functions ``translate(x, y)``, ``scale(factor)`` and
``rotate(angle, center_x?, center_y?)``, the bounding box variables ``x_min``, ``y_min``, ``x_max``, ``y_max``,
``width`` and ``height``, and everything from python's built-in math module (e.g. ``pi``, ``sqrt``, ``sin``). As
convenience methods, ``center()`` and ``origin()`` are provided to center the board resp. move its bottom-left corner to
the origin. Coordinates are given in --command-line-units, angles in degrees, and scale as a scale factor (as opposed to
a percentage). Example: ``translate(-10, 0); rotate(45, 0, 5)``

.. option:: -m, --input-map <json_file>

   Extend or override layer name mapping with name map from JSON file. The JSON file must contain a single JSON dict
   with an arbitrary number of string: string entries. The keys are interpreted as regexes applied to the filenames via
   re.fullmatch, and each value must either be the string ``ignore`` to remove this layer from previous automatic
   guesses, or a gerbonara layer name such as ``top copper``, ``inner_2 copper`` or ``bottom silk``.

.. option:: --use-builtin-name-rules, --no-builtin-name-rules

    Disable built-in layer name rules and use only rules given by ``--input-map``

.. option:: --warnings <default|ignore|once>

   Enable or disable file format warnings during parsing (default: on)

.. option:: --units <metric|us-customary>

    Units for values given in other options. Default: millimeter

.. option:: -n, --number-format <decimal.fractional>

   Override number format to use during export in ``[integer digits].[decimal digits]`` notation, e.g. ``2.6``.

.. option:: --default-settings, --reuse-input-settings

   Use sensible defaults for the output file format settings (default) or use the same export settings as the input file
   instead of sensible defaults.

.. option:: --force-zip

   Force treating input path as a zip file (default: guess file type from extension and contents)

.. option:: --output-naming-scheme <altium|kicad>

   Name output files according to the selected naming scheme instead of keeping the old file names.


``gerbonara merge``
*******************

.. program:: gerbonara merge

.. code-block:: console
   
    $ gerbonara merge [OPTIONS] [INPATH]... OUTPATH

Merge multiple single Gerber or Excellon files, or multiple stacks of Gerber files, into one.

.. note::
   When used with only one input, this command *normalizes* the input, converting all files to a well-defined, widely
   supported Gerber subset with sane settings. When a ``--output-naming-scheme`` is given, it additionally renames all
   files to a standardized naming convention.

.. option:: --command-line-units <metric|us-customary>

    Units for values given in --transform. Default: millimeter

.. option:: --warnings <default|ignore|once>

   Enable or disable file format warnings during parsing (default: on)

.. option:: --offset <COORDINATE>

   Offset for the n'th file as a ``x,y`` string in unit given by ``--command-line-units`` (default: millimeter). Can be
   given multiple times, and the first option affects the first input, the second option affects the second input, and
   so on.

.. option:: --rotation <ROTATION>

   Rotation for the n'th file in degrees clockwise, optionally followed by comma- separated rotation center X and Y
   coordinates. Can be given multiple times, and the first option affects the first input, the second option affects the
   second input, and so on.

.. option:: -m, --input-map <json_file>

   Extend or override layer name mapping with name map from JSON file. This option can be given multiple times, in which
   case the n'th option affects only the n'th input, like with ``--offset`` and ``--rotation``. The JSON file must
   contain a single JSON dict with an arbitrary number of string: string entries. The keys are interpreted as regexes
   applied to the filenames via re.fullmatch, and each value must either be the string "ignore" to remove this layer
   from previous automatic guesses, or a gerbonara layer name such as ``top copper``, ``inner_2 copper`` or ``bottom
   silk``.

.. option:: --default-settings, --reuse-input-settings

   Use sensible defaults for the output file format settings (default) or use the same export settings as the input file
   instead of sensible defaults.

.. option:: --output-naming-scheme <altium|kicad>

   Name output files according to the selected naming scheme instead of keeping the old file names of the first input.

.. option:: --output-board-name <TEXT>

    Override board name used with ``--output-naming-scheme``

.. option:: --use-builtin-name-rules, --no-builtin-name-rules
    
    Disable built-in layer name rules and use only rules given by --input-map

File analysis
~~~~~~~~~~~~~

``gerbonara bounding-box``
**************************

.. program:: gerbonara bounding-box

.. code-block:: console

   gerbonara bounding-box [OPTIONS] INFILE

Print the bounding box of a gerber file in ``[x_min] [y_min] [x_max] [y_max]`` format. The bounding box contains all
graphic objects in this file, so e.g. a 100 mm by 100 mm square drawn with a 1mm width circular aperture will result in
an 101 mm by 101 mm bounding box.

.. option:: --warnings <default|ignore|once>

    Enable or disable file format warnings during parsing (default: on)

.. option:: --units <metric|us-customary>
    
    Output bounding box in this unit (default: millimeter)

.. option:: --input-number-format <decimal.fractional>

    Override number format of input file (mostly useful for Excellon files)
    
.. option:: --input-units <metric|us-customary>

    Override units of input file

.. option:: --input-zero-suppression <off|leading|trailing>

    Override zero suppression setting of input file


``gerbonara meta``
******************
.. program:: gerbonara meta

.. code-block:: console

    gerbonara meta [OPTIONS] PATH

Read a board from a folder or zip, and print the found layer mapping along with layer metadata as JSON to stdout. A
machine-readable variant of the :program:`gerbonara render` command. All lengths in the JSON are given in millimeter.

.. option:: --warnings <default|ignore|once>

   Enable or disable file format warnings during parsing (default: on)

.. option:: --force-zip

   Force treating input path as zip file (default: guess file type from extension and contents)


``gerbonara layers``
********************
.. program:: gerbonara render

.. code-block:: console

    $ gerbonara layers [OPTIONS] PATH

Prints a layer-by-layer description of the board found under the given path. The path can be a directory or zip file.

.. option:: --warnings <default|ignore|once>

   Enable or disable file format warnings during parsing (default: on)

.. option:: --force-zip

   Force treating input path as zip file (default: guess file type from extension and contents)
