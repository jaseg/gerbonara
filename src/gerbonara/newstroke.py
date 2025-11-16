#!/usr/bin/env python

from pathlib import Path
import unicodedata
import re
import ast
from functools import lru_cache
import math
from importlib.resources import files

from . import data
from .utils import rotate_point, Tag


STROKE_FONT_SCALE = 1/21
FONT_OFFSET = -10
DEFAULT_SPACE_WIDTH = 0.6
DEFAULT_CHAR_GAP = 0.2

_dec = lambda c: ord(c)-ord('R') 


class Newstroke:
    def __init__(self, newstroke_cpp=None):
        if newstroke_cpp is None:
            newstroke_cpp = files(data).joinpath('newstroke_font.cpp').read_bytes()
        self.glyphs = dict(self.load_font(newstroke_cpp))

    @classmethod
    @lru_cache
    def load(kls):
        return kls()

    def render(self, text, size=1.0, x0=0, y0=0, rotation=0, h_align='left', v_align='bottom', space_width=DEFAULT_SPACE_WIDTH, char_gap=DEFAULT_CHAR_GAP, scale=(1, 1), mirror=(False, False)):
        text = unicodedata.normalize('NFC', text)
        missing_glyph = self.glyphs['?']
        sx, sy = scale
        mx, my = mirror
        x = 0

        if rotation >= 180:
            rotation -= 180
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
            x0, y0 = -x0, y0

#        if mx:
#            y0 = -y0
#            if rotation == 0:
#                v_align = {'top': 'bottom', 'bottom': 'top'}.get(v_align, v_align)
#            else:
#                h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)

        x0, y0 = rotate_point(x0, y0, math.radians(-rotation))

        alx, aly = 0, 0
        (minx, miny), (maxx, maxy) = bbox = self.bounding_box(text, size, space_width, char_gap)
        w = maxx - minx

        if my:
            if rotation == 0:
                sx = -1
                h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
            else:
                sy = -sy

        if h_align != 'left':
            if h_align == 'right':
                alx = -w
            elif h_align == 'center':
                alx = -w/2
            else:
                raise ValueError(f'Invalid h_align value "{h_align}"')

        if v_align == 'top':
            aly = sy*1.2*size
        elif v_align == 'middle':
            aly = sy*1.2*size/2
        elif v_align != 'bottom':
                raise ValueError(f'Invalid v_align value "{v_align}"')

        for c in text:
            if c == ' ':
                x += space_width
                continue

            width, strokes = self.glyphs.get(c, missing_glyph)
            glyph_w = max(width, max(x for st in strokes for x, _y in st))

            for st in strokes:
                yield [rotate_point((px+x)*sx*size+alx+x0, py*sy*size+aly+y0, math.radians(-rotation), x0, y0) for px, py in st]

            x += glyph_w

    def render_svg(self, text, size=1.0, x0=0, y0=0, rotation=0, h_align='left', v_align='bottom', space_width=DEFAULT_SPACE_WIDTH, char_gap=DEFAULT_CHAR_GAP, scale=(1, -1), mirror=(False, False), **svg_attrs):
        if 'stroke_linecap' not in svg_attrs:
            svg_attrs['stroke_linecap'] = 'round'
        if 'stroke_linejoin' not in svg_attrs:
            svg_attrs['stroke_linejoin'] = 'round'
        if 'stroke_width' not in svg_attrs:
            svg_attrs['stroke_width'] = f'{0.2*size:.3f}'
        svg_attrs['fill'] = 'none'

        strokes = ['M ' + ' L '.join(f'{x:.3f} {y:.3f}' for x, y in stroke)
                   for stroke in self.render(text, size=size, x0=x0, y0=y0, rotation=rotation, h_align=h_align,
                                             v_align=v_align, mirror=mirror, space_width=space_width, char_gap=char_gap,
                                             scale=scale)]
        return Tag('path', d=' '.join(strokes), **svg_attrs)

    def bounding_box(self, text, size=1.0, space_width=DEFAULT_SPACE_WIDTH, char_gap=DEFAULT_CHAR_GAP):
        text = unicodedata.normalize('NFC', text)
        missing_glyph = self.glyphs['?']
        x = 0
        for c in text:
            if c == ' ':
                x += space_width*size
                continue

            width, strokes = self.glyphs.get(c, missing_glyph)
            glyph_w = max(width, max(x for st in strokes for x, _y in st))
            x += glyph_w*size

        return (0, -0.2*size), (x, 1.2*size)

    def load_font(self, newstroke_cpp):
        e = []
        for char, (width, strokes) in self.load_glyphs(newstroke_cpp):
            yield char, (width, strokes)

    @classmethod
    def decode_stroke(kls, stroke, start_x):
        for i in range(0, len(stroke), 2):
            x = (stroke[i]-0x52-start_x)*STROKE_FONT_SCALE
            y = (stroke[i+1]-0x52+FONT_OFFSET)*STROKE_FONT_SCALE
            yield (x, y)

    @classmethod
    def decode_glyph(kls, data):
        start_x, end_x = data[0]-0x52, data[1]-0x52
        width = end_x - start_x

        strokes = tuple(tuple(kls.decode_stroke(st, start_x)) for st in data[2:].split(b' R'))
        return width*STROKE_FONT_SCALE, strokes

    @classmethod
    def load_glyphs(kls, newstroke_cpp):
        it = iter(newstroke_cpp.splitlines())
        
        for line in it:
            if re.search(rb'char.*\*', line):
                break

        charcode = 0x20
        for line in it:
            if (match := re.search(rb'".*"', line)):
                yield chr(charcode), kls.decode_glyph(match.group(0)[1:-1].replace(b'\\\\', b'\\'))
                charcode += 1
            else:
                if b'}' in line:
                    break


if __name__ == '__main__':
    import time
    t1 = time.time()
    Newstroke()
    t2 = time.time()
    print((t2-t1)*1000)
