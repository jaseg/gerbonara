Graphic Objects
===============

Graphic objects are the lego blocks a gerbonara :py:class:`.GerberFile` or :py:class:`.ExcellonFile` is built from. They
are stored in the file's :py:attr:`~.GerberFile.objects` attribute of a :py:class:`.GerberFile`. You can directly
manipulate that list from code.

There are four graphic object types: :py:class:`.Flash`, :py:class:`~.graphic_objects.Line`,
:py:class:`~.graphic_objects.Arc`, and :py:class:`~.graphic_objects.Region` . All of them are derived from
:py:class:`~.graphic_objects.GraphicObject`.

.. autoclass:: gerbonara.graphic_objects.GraphicObject
   :members:

.. autoclass:: gerbonara.graphic_objects.Flash
   :members:

.. autoclass:: gerbonara.graphic_objects.Line
   :members:

.. autoclass:: gerbonara.graphic_objects.Arc
   :members:

.. autoclass:: gerbonara.graphic_objects.Region
   :members:

.. _pcb-tools: https://github.com/opiopan/pcb-tools-extension
.. _gerbolyze: https://github.com/jaseg/gerbolyze
.. _svg-flatten: https://github.com/jaseg/gerbolyze/tree/main/svg-flatten
