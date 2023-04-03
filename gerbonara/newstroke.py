#!/usr/bin/env python

from pathlib import Path
import unicodedata
import re
import ast
from importlib.resources import files

from . import data


STROKE_FONT_SCALE = 1/21
FONT_OFFSET = -10
DEFAULT_SPACE_WIDTH = 0.6
DEFAULT_CHAR_GAP = 0.2

_dec = lambda c: ord(c)-ord('R') 


class Newstroke:
    def __init__(self, newstroke_cpp=None):
        if newstroke_cpp is None:
            newstroke_cpp = files(data).joinpath('newstroke_font.cpp').read_bytes()
        self.glyphs = dict(self.load(newstroke_cpp))

    def render(self, text, size=1.0, space_width=DEFAULT_SPACE_WIDTH, char_gap=DEFAULT_CHAR_GAP):
        text = unicodedata.normalize('NFC', text)
        missing_glyph = self.glyphs['?']
        x = 0
        for c in text:
            if c == ' ':
                x += space_width*size
                continue

            width, strokes = self.glyphs.get(c, missing_glyph)
            glyph_w = max(width, max(x for st in strokes for x, _y in st))

            for st in strokes:
                yield self.transform_stroke(st, translate=(x, 0), scale=(size, size))

            x += glyph_w*size

    @classmethod
    def transform_stroke(kls, stroke, translate, scale):
        dx, dy = translate
        sx, sy = scale
        return [(x*sx+dx, y*sy+dy) for x, y in stroke]
            

    def load(self, newstroke_cpp):
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
