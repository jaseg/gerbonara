Apertures in Gerbonara
======================

Gerbonara maps all standard Gerber apertures to subclasses of the :py:class:`.Aperture` class. These subclasses:
:py:class:`.CircleAperture`, :py:class:`.RectangleAperture`, :py:class:`.ObroundAperture` and
:py:class:`.PolygonAperture`. :doc:`Aperture macro<aperture-macros>` instantiations get mapped to
:py:class:`.ApertureMacroInstance` (also an :py:class:`Aperture` subclass). The basic aperture shapes each support a
central hole through their :py:class:`~.CircleAperture.hole_dia` attribute. This "hole" is just a cut-out in the
aperture itself, and does not imply an actual drilled hole in the board. Drilled holes in the board are specified
completely separately through an :py:class:`.ExcellonFile`.

Gerbonara is able to rotate any aperture. The Gerber standard does not support rotation for standard apertures in any
widespread way, so Gerbolyze handles rotation by converting rotated standard apertures into aperture macros during
export as necessary.

Aperture generalization
-----------------------

Gerbonara supports rotating both individual graphic objects and whole files. Alas, this was not a use case that was
intended when the Gerber format was developed. We can rotate lines, arcs, and regions alright by simply rotating all of
their points. Flashes are where things get tricky: Individual flashes cannot be rotated at all in any widely supported
way. There are some newer additions to the standard, but I would be surprised if any of the cheap board houses
understand those. The only way to rotate a flash is to rotate the aperture, not the flash. For cirlces, this is a no-op.
For polygons, we simply change the angle parameter. However, for rectangles and obrounds this gets tricky: Neither one
supports a rotation parameter. The only way to rotate these is to convert them to an aperture macro, then rotate that.

This behavior of using aperture macros for general rotated rectangles is common behavior among CAD tools. Gerbonara adds
a non-standard :py:attr:`.RectangleAperture.rotation` attribute to all apertures except :py:class:`.CircleAperture` and
transparently converts rotated instances to the appropriate :py:class:`.ApertureMacroInstance` objects while it writes
out the file. Be aware that this may mean that an object that in memory has a :py:class:`.RectangleAperture` might end
up with an aperture macro instance in the output Gerber file.

Aperture classes
----------------

.. autoclass:: gerbonara.apertures.Aperture
    :members:

.. autoclass:: gerbonara.apertures.CircleAperture
    :members:

.. autoclass:: gerbonara.apertures.RectangleAperture
    :members:

.. autoclass:: gerbonara.apertures.ObroundAperture
    :members:

.. autoclass:: gerbonara.apertures.PolygonAperture
    :members:

.. autoclass:: gerbonara.apertures.ApertureMacroInstance
    :members:

