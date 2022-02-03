Graphic Primitives
==================

Graphic prmitives are the core of Gerbonara's rendering interface. Individual graphic objects such as a Gerber
:py:class:`.Region` as well as entire layers such as a :py:class:`.GerberFile` can be rendered into a list of graphic
primitives. This rendering step resolves aperture definitions, calculates out aperture macros, converts units into a
given target unit, and maps complex shapes to a small number of subclasses of :py:class:`.GraphicPrimitive`.

All graphic primitives have a :py:attr:`~.GraphicPrimitive.polarity_dark` attribute. Its meaning is identical with
:py:attr:`.GraphicObject.polarity_dark`.

.. autoclass:: gerbonara.graphic_primitives.GraphicPrimitive
    :members:

The five types of Graphic Primitives
------------------------------------

Stroked lines
~~~~~~~~~~~~~

.. autoclass:: gerbonara.graphic_primitives.Line
    :members:

.. autoclass:: gerbonara.graphic_primitives.Arc
    :members:

Filled shapes
~~~~~~~~~~~~~

.. autoclass:: gerbonara.graphic_primitives.Circle
    :members:

.. autoclass:: gerbonara.graphic_primitives.Rectangle
    :members:

.. autoclass:: gerbonara.graphic_primitives.ArcPoly
    :members:

