
from dataclasses import dataclass

from primitives import Primitive

def _flash_hole(self, x, y):
    if self.hole_rect_h is not None:
        return self.primitives(x, y), Rectangle((x, y), (self.hole_dia, self.hole_rect_h), polarity_dark=False)
    else:
        return self.primitives(x, y), Circle((x, y), self.hole_dia, polarity_dark=False)

class Aperture:
    @property
    def hole_shape(self):
        if self.hole_rect_h is not None:
            return 'rect'
        else:
            return 'circle'

    @property
    def hole_size(self):
        return (self.hole_dia, self.hole_rect_h)

    def flash(self, x, y):
        return self.primitives(x, y)


@dataclass
class ApertureCircle(Aperture):
    diameter : float
    hole_dia : float = 0
    hole_rect_h : float = None

    def primitives(self, x, y):
        return Circle((x, y), self.diameter, polarity_dark=True),

    flash = _flash_hole


@dataclass
class ApertureRectangle(Aperture):
    w : float
    h : float
    hole_dia : float = 0
    hole_rect_h : float = None

    def primitives(self, x, y):
        return Rectangle((x, y), (self.w, self.h), polarity_dark=True),

    flash = _flash_hole


@dataclass
class ApertureObround(Aperture):
    w : float
    h : float
    hole_dia : float = 0
    hole_rect_h : float = None

    def primitives(self, x, y):
        return Obround((x, y), self.w, self.h, polarity_dark=True)

    flash = _flash_hole


@dataclass
class AperturePolygon(Aperture):
    diameter : float
    n_vertices : int
    hole_dia : float = 0
    hole_rect_h : float = None

    def primitives(self, x, y):
        return Polygon((x, y), diameter, n_vertices, rotation, polarity_dark=True),

    flash = _flash_hole

class MacroAperture(Aperture):
    parameters : [float]
    self.macro : ApertureMacro

    def primitives(self, x, y):
        return self.macro.execute(x, y, self.parameters)


