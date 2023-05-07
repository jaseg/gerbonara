
from dataclasses import dataclass

from ..utils import MM
from .primitives import *


@dataclass
class PadRing(Positioned):
    w: int
    h: int
    pitch: float = 2.54
    clearance: float = 0.2
    rows: int = 2
    trace_width: float = 0.4
    drill_dia: float = 0.9
    stagger: bool = False

    def ports(self):
        x, y, rotation = self.abs_pos

        x += self.pitch/2
        y += self.pitch/2

        x += self.pitch * self.rows
        y += self.pitch * self.rows

        pad_dia = self.pitch - 2*self.clearance - self.trace_width
        offset = pad_dia/2 - self.trace_width/2

        for i in range(1, self.w):
            yield (x+self.pitch/2 + i*self.pitch, y+offset)
            yield (x+self.pitch/2 + i*self.pitch, y+(self.h+1)*self.pitch-offset)

        for i in range(0, self.w):
            yield (x + (i+1)*self.pitch, y+offset)
            yield (x + (i+1)*self.pitch, y+(self.h+1)*self.pitch-offset)

        for i in range(1, self.h):
            yield (x+offset, y+self.pitch/2 + i*self.pitch)
            yield (x+(self.w+1)*self.pitch-offset, y+self.pitch/2 + i*self.pitch)

        for i in range(0, self.h):
            yield (x+offset, y + (i+1)*self.pitch)
            yield (x+(self.w+1)*self.pitch-offset, y + (i+1)*self.pitch)


    def generate(self, bbox, border_text, unit=MM):
        x, y, rotation = self.abs_pos

        x += self.pitch/2
        y += self.pitch/2

        x += self.pitch * self.rows
        y += self.pitch * self.rows

        pad_dia = self.pitch - 2*self.clearance - self.trace_width

        for i in range(self.w + 2 + 2*(self.rows-1)):
            for j in range(self.rows):
                yield THTPad.circle(x + (i - (self.rows - 1))*self.pitch, y - j*self.pitch, self.drill_dia, pad_dia, paste=False)
                yield THTPad.circle(x + (i - (self.rows - 1))*self.pitch, y + (self.h + 1 + j)*self.pitch, self.drill_dia, pad_dia, paste=False)

            if self.rows >= 2 and 1 <= i < self.w:
                yield Trace(self.trace_width, start=(x+i*self.pitch, y-self.pitch), end=(x+(i + 0.5)*self.pitch, y+pad_dia/2 - self.trace_width/2))
                yield Trace(self.trace_width, start=(x+i*self.pitch, y+(self.h+2)*self.pitch), end=(x+(i + 0.5)*self.pitch, y+(self.h+1)*self.pitch -pad_dia/2 + self.trace_width/2), orientation=('cw',))

        for i in range(1, self.h+1):
            for j in range(self.rows):
                yield THTPad.circle(x - j*self.pitch, y + i*self.pitch, self.drill_dia, pad_dia, paste=False)
                yield THTPad.circle(x + (self.w + 1 + j)*self.pitch, y + i*self.pitch, self.drill_dia, pad_dia, paste=False)

        for i in range(1, self.h):
            yield (x+offset, y+self.pitch/2 + i*self.pitch)
            yield (x+(self.w+1)*self.pitch-offset, y+self.pitch/2 + i*self.pitch)


    def generate(self, bbox, border_text, unit=MM):
        x, y, rotation = self.abs_pos

        x += self.pitch/2
        y += self.pitch/2

        x += self.pitch * self.rows
        y += self.pitch * self.rows

        pad_dia = self.pitch - 2*self.clearance - self.trace_width

        for i in range(self.w + 2 + 2*(self.rows-1)):
            for j in range(self.rows):
                yield THTPad.circle(x + (i - (self.rows - 1))*self.pitch, y - j*self.pitch, self.drill_dia, pad_dia, paste=False)
                yield THTPad.circle(x + (i - (self.rows - 1))*self.pitch, y + (self.h + 1 + j)*self.pitch, self.drill_dia, pad_dia, paste=False)

            if self.rows >= 2 and 1 <= i < self.w:
                yield Trace(self.trace_width, start=(x+i*self.pitch, y-self.pitch), end=(x+(i + 0.5)*self.pitch, y+pad_dia/2 - self.trace_width/2))
                yield Trace(self.trace_width, start=(x+i*self.pitch, y+(self.h+2)*self.pitch), end=(x+(i + 0.5)*self.pitch, y+(self.h+1)*self.pitch -pad_dia/2 + self.trace_width/2), orientation=('cw',))

        for i in range(1, self.h+1):
            for j in range(self.rows):
                yield THTPad.circle(x - j*self.pitch, y + i*self.pitch, self.drill_dia, pad_dia, paste=False)
                yield THTPad.circle(x + (self.w + 1 + j)*self.pitch, y + i*self.pitch, self.drill_dia, pad_dia, paste=False)

            if self.rows >= 2 and i < self.h:
                yield Trace(self.trace_width,
                            start=(
                                x-self.pitch,
                                y+i*self.pitch),
                            end=(
                                x+pad_dia/2 - self.trace_width/2,
                                y+(i + 0.5)*self.pitch),
                            orientation=('cw',))
                yield Trace(self.trace_width,
                            start=(
                                x+(self.w+2)*self.pitch,
                                y+i*self.pitch),
                            end=(
                                x+(self.w+1)*self.pitch -pad_dia/2 + self.trace_width/2,
                                y+(i + 0.5)*self.pitch))


def _breakout_demo():
    b = Board(100, 80)
    
    ring = PadRing(5, 5, 8, 12)
    for obj in ring.generate(None, None):
        b.add(obj)

    for x, y in ring.ports():
        b.add(Trace(0.1, start=(23, 27), end=(x, y)))

    with open('/tmp/test.svg', 'w') as f:
        f.write(str(b.pretty_svg()))
    b.layer_stack().save_to_directory('/tmp/testdir')


if __name__ == '__main__':
    _breakout_demo()

