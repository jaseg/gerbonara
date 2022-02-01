Graphic Objects
===============

Graphic objects are the lego blocks a gerbonara :py:class:`gerbonara.rs274x.GerberFile` or
:py:class:`gerbonara.excellon.ExcellonFile` is built from. They are stored in the file's
:py:attr:`gerbonara.rs274x.GerberFile.objects` list. You can directly manipulate that list from code.

There are four graphic object types: :py:class:`gerbonara.graphic_objects.Flash`,
:py:class:`gerbonara.graphic_objects.Line`, :py:class:`gerbonara.graphic_objects.Arc`, and
:py:class:`gerbonara.graphic_objects.Region` . All of them are derived from
:py:class:`gerbonara.graphic_objects.GraphicObject`.

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
