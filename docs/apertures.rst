Apertures in Gerbonara
======================

Gerbonara maps all standard Gerber apertures to subclasses of the Aperture_ class. These subclasses: CircleAperture_,
RectangleAperture_, ObroundAperture_ and PolygonAperture_. Aperture macro instantiations get mapped to
ApertureMacroInstance_ (also an Aperture_ subclass).

All Aperture_ subclasses have these common attributes:


`hole_dia`
    float with diameter of hole. 0 for no hole.

`hole_rect_h`
    float or None. If not None, specifies a rectangular hole of size `hole_dia * hole_rect_h` instead of a round hole.

`unit`
    LengthUnit_ for all of this aperture's fields

`attrs`
    GerberX2 attributes of this aperture. Note that this will only contain aperture attributes, not file attributes.
    File attributes are stored in the `attrs` of GerberFile_.

`original_number`
    int of aperture index this aperture had when it was read from the Gerber file. This field is purely informational
    since apertures are de-duplicated and re-numbered when writing a Gerber file. For `D10`, this field would be `10`.
    If you programmatically create a new aperture, you do not have to set this.

`rotation`
    Aperture rotation in radians counter-clockwise. This field is not part of the Gerber standard. Standard rectangle
    and obround apertures do not support rotation. Gerbonara converts rotated apertures into aperture macros during
    Gerber export as necessary.

CircleAperture
--------------

This is the only one valid for use in Line_ or Arc_.

Attributes:

Common attributes:
    `hole_dia`, `hole_rect_h`, `unit`, `attrs`, and `original_number`. `rotation` is present but has no effect in
    CircleAperture_.

`diameter`
    float with diameter of aperture in the unit from the aperture's `unit` field. 
    
RectangleAperture
-----------------

Common attributes:
    `hole_dia`, `hole_rect_h`, `unit`, `attrs`, `original_number`, and `rotation`

`w`, `h`
    floats with width or height of rectangle in units from the aperture's `unit` field. 

ObroundAperture
---------------

Aperture whose shape is the convex hull of two circles of equal radii.

Common attributes:
    `hole_dia`, `hole_rect_h`, `unit`, `attrs`, `original_number`, and `rotation`

`w`, `h`
    floats with width and height of bounding box of obround. The smaller one of these will be the diameter of the
    obround's ends. If `w` is larger, the result will be a landscape obround. If `h` is larger, it will be a portrait
    obround.

PolygonAperture
---------------

Aperture whose shape is a regular n-sided polygon (e.g. pentagon, hexagon etc.).


Common attributes:
    `hole_dia`, `unit`, `attrs`, `original_number`, and `rotation`. `hole_rect_h` is not supported in PolygonAperture_
    since the Gerber spec does not list it.

`diameter`
    float with diameter of circumscribing circle, i.e. the circle that all the polygon's corners lie on.

`n_vertices`
    int with number of corners of this polygon. Three for a triangle, four for a square, five for a pentagon etc.

ApertureMacroInstance
---------------------

One instance of an aperture macro. An aperture macro defined with an `AM` statement can be instantiated by multiple `AD`
aperture definition statements using different parameters. An ApertureMacroInstance_ is one such binding of a macro to a
particular set of parameters. Note that you still need an ApertureMacroInstance_ even if your ApertureMacro_ has no
parameters since an ApertureMacro_ is not an Aperture_ by itself.

Attributes:

Common attributes:
    `unit`, `attrs`, `original_number`, and `rotation`. ApertureMacroInstance_ does not support `hole_dia` or
    `hole_rect_h`. `rotation` is handled by re-writing the ApertureMacro_ during export.

`macro`
    The ApertureMacro_ that is bound here

`parameters`
    list of ints or floats with the parameters for this macro. The first element is `$1`, the second is `$2` etc.

ExcellonTool
------------

Special Aperture_ subclass for use in ExcellonFile_. Similar to CircleAperture_, but does not have `hole_dia` or
`hole_rect_h`, and has additional `plated` and `depth_offset` attributes.


Common attributes:
    `unit`, `original_number`

`plated`
    bool or None. True if this hole/slot is copper-plated, False if not, and None if it is undefined or unknown.

`depth_offset`
    float with Excellon depth offset for this hole or slot. If the fab supports this, this can be used to create
    features that do not go all the way through the board.

Aperture generalization
-----------------------

Gerbonara supports rotating both individual graphic objects and whole files. Alas, this was not a use case that was
intended when the Gerber format was developed. We can rotate lines, arcs, and regions alright by simply rotatint all of
their points. Flashes are where things get tricky: Individual flashes cannot be rotated at all in any widely supported
way. There are some newer additions to the standard, but I would be surprised if any of the cheap board houses
understand those. The only way to rotate a flash is to rotate the aperture, not the flash. For cirlces, this is a no-op.
For polygons, we simply change the angle parameter. However, for rectangles and obrounds this gets tricky: Neither one
supports a rotation parameter. The only way to rotate these is to convert them to an aperture macro, then rotate that.

This behavior of using aperture macros for general rotated rectangles is common behavior among CAD tools. Gerbonara adds
a non-standard `rotation` attribute to all apertures except CircleAperture_ and transparently converts rotated instances
to the appropriate ApertureMacroInstance_ objects while it writes out the file. Be aware that this may mean that an
object that in memory has a RectangleAperture_ might end up with an aperture macro instance in the output Gerber file.

