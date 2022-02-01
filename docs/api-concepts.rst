Gerbonara API concepts
======================

High-level overview
-------------------

Gerbonara's API is split into three larger sub-areas:

**File API**
    This is where the main user interface classes live: :py:class:`.LayerStack` (for opening a directory/zip full of
    files, and automatically matching file roles based on filenames), :py:class:`.GerberFile` (for opening an individual
    RS-274X file), :py:class:`.ExcellonFile` (for Excellon drill files) and :py:class:`.Netlist` (for IPC-356 netlist
    files).

**Graphic Object API**
    This is where the nuts and bolts inside a :py:class:`.GerberFile` or :py:class:`.ExcellonFile` such as
    :py:class:`~.graphic_objects.Line`, :py:class:`~.graphic_objects.Arc`, :py:class:`.Region` and :py:class:`.Flash`
    live. Everything in here has explicit unit support. A part of the Graphic object API is the :doc:`Aperture
    API<apertures>`.

**Graphic Primitive API**
    This is a rendering abstraction layer. Graphic objects can be converted into graphic primitives for rendering.
    Graphic primitives are unit-less. Units are converted during :py:class:`.GraphicObject` to
    :py:class:`.GraphicPrimitive` rendering.

The hierarchy works like: A :py:class:`.LayerStack` contains either a :py:class:`.GerberFile`, an
:py:class:`.ExcellonFile` or a :py:class:`.Netlist` for each layer. Each of these file objects contains a number of
:py:class:`.GraphicObject` instances such as :py:class:`~.graphic_objects.Line` or :py:class:`.Flash`. These objects can
easily be changed or deleted, and new ones can be created programmatically. For rendering, each of these objects as well
as file objects can be rendered into :py:class:`.GraphicPrimitive` instances using
:py:meth:`.GraphicObject.to_primitives`.

Apertures
---------

Gerber apertures are represented by subclasses of :py:class:`.Aperture` such as :py:class:`.CircleAperture`. An instance
of an aperture class is stored inside the :py:attr:`~.graphic_objects.Line.aperture` field of a
:py:class:`.GraphicObject`. :py:class:`.GraphicObject` subclasses that have an aperture are
:py:class:`~.graphic_objects.Line`, :py:class:`~.graphic_objects.Arc` and :py:class:`.Flash`. You can create and
duplicate :py:class:`.Aperture` objects as needed. They are automatically de-duplicated when a Gerber file is written.

Gerbonara has full aperture macro support. Each aperture macro is represented by an :py:class:`.parse.ApertureMacro`
instance. Like apertures, :py:class:`.parse.ApertureMacro` instances are de-duplicated when writing a file. An aperture
macro-based aperture definition is represented by the :py:class:`.ApertureMacroInstance` subclass of
:py:class:`.Aperture`. An aperture macro instance basically binds an aperture macro to a given set of macro parameters.
Note that even if a macro does not accept any parameters you still cannot directly stick it into the aperture field of a
graphic object, and instead need to wrap it inside an :py:class:`.ApertureMacroInstance` first. 

Excellon vs. Gerber
-------------------

Excellon files use the same graphic object classes as Gerber files. Inside an Excellon file, only
:py:class:`~.graphic_objects.Line`, :py:class:`~.graphic_objects.Arc` and :py:class:`.Flash` are allowed. Lines and arcs map to milled
Excellon slots. Excellon drills are mapped to :py:class:`.Flash` instances. 

Excellon drills are internally handled using a special :py:class:`.ExcellonTool` aperture class. When you put a
:py:class:`.GraphicObject` from an Excellon file into a Gerber file, these become circular apertures. You can also take
objects from an Excellon file and put them into a Gerber file if they have a simple :py:class:`.CircleAperture`. Copying
objects with other apertures into an Excellon file will raise an error when saving. 

