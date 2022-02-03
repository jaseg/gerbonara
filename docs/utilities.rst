Utilities
=========

Physical units
~~~~~~~~~~~~~~

Gerbonara tracks length units using the :py:class:`.LengthUnit` class. :py:class:`.LengthUnit` contains a number of
conventient conversion functions. Everywhere where Gerbonara accepts units as a method argument, it automatically
converts a string ``'mm'`` or ``'inch'`` to the corresponding :py:class:`.LengthUnit`.

.. autoclass:: gerbonara.utils.LengthUnit
   :members:

Format settings
~~~~~~~~~~~~~~~

When reading or writing Gerber or Excellon, Gerbonara stores information about file format options such as zero
suppression or number of decimal places in a :py:class:`.FileSettings` instance. When you are writing a Gerber file,
Gerbonara picks reasonable defaults, but allows you to specify your own :py:class:`.FileSettings` to override these
defaults.

.. autoclass:: gerbonara.cam.FileSettings
   :members:
