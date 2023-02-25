Layers and Files
================

Gerbonara currently supports three file types: RS-274-X Gerber as `specified by Ucamco
<https://www.ucamco.com/en/gerber>`:py:class:`._` through :py:class:`.GerberFile`, Excellon/XNC through
:py:class:`.ExcellonFile`, and IPC-356 netlists through :py:class:`.Netlist`.

Usually, a PCB is sent to a manufacturer as a bundle of several of these files. Such a bundle of files (each of which is
either a :py:class:`.GerberFile` or an :py:class:`.ExcellonFile`) is represented by :py:class:`.LayerStack`.
:py:class:`.LayerStack` contains logic to automatcally recognize a wide variety of CAD tools from file name and
syntactic hints, and can automatically match all files in a folder to their appropriate layers.

:py:class:`.CamFile` is the common base class for all layer types.

.. autoclass:: gerbonara.cam.CamFile
   :members:

.. autoclass:: gerbonara.rs274x.GerberFile
   :members:

.. autoclass:: gerbonara.excellon.ExcellonFile
   :members:

.. autoclass:: gerbonara.ipc356.Netlist
   :members:

.. autoclass:: gerbonara.layers.LayerStack
   :members:

