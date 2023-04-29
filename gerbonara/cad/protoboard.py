
import sys
import re
import math
import string
import itertools
from copy import copy, deepcopy
import warnings
import importlib.resources

from ..utils import MM, rotate_point
from .primitives import *
from ..graphic_objects import Region
from ..apertures import RectangleAperture, CircleAperture, ApertureMacroInstance
from ..aperture_macros.parse import ApertureMacro, VariableExpression
from ..aperture_macros import primitive as amp
from .kicad import footprints as kfp
from . import data as package_data


class ProtoBoard(Board):
    def __init__(self, w, h, content, margin=None, corner_radius=None, mounting_hole_dia=None, mounting_hole_offset=None, unit=MM):
        corner_radius = corner_radius or unit(1.5, MM)
        super().__init__(w, h, corner_radius, unit=unit)
        self.margin = margin or unit(2, MM)
        self.content = content

        if mounting_hole_dia:
            mounting_hole_offset = mounting_hole_offset or mounting_hole_dia*2
            ko = mounting_hole_offset*2

            self.add(Hole(mounting_hole_offset, mounting_hole_offset, mounting_hole_dia, unit=unit))
            self.add(Hole(w-mounting_hole_offset, mounting_hole_offset, mounting_hole_dia, unit=unit))
            self.add(Hole(mounting_hole_offset, h-mounting_hole_offset, mounting_hole_dia, unit=unit))
            self.add(Hole(w-mounting_hole_offset, h-mounting_hole_offset, mounting_hole_dia, unit=unit))

            self.keepouts.append(((0, 0), (ko, ko)))
            self.keepouts.append(((w-ko, 0), (w, ko)))
            self.keepouts.append(((0, h-ko), (ko, h)))
            self.keepouts.append(((w-ko, h-ko), (w, h)))

        self.generate()

    def generate(self, unit=MM):
        bbox = ((self.margin, self.margin), (self.w-self.margin, self.h-self.margin))
        bbox = unit.convert_bounds_from(self.unit, bbox)
        for obj in self.content.generate(bbox, (True, True, True, True), unit):
            self.add(obj, keepout_errors='skip')


class PropLayout:
    def __init__(self, content, direction, proportions):
        self.content = list(content)
        if direction not in ('h', 'v'):
            raise ValueError('direction must be one of "h", or "v".')
        self.direction = direction
        self.proportions = list(proportions)
        if len(content) != len(proportions):
            raise ValueError('proportions and content must have same length')

    def generate(self, bbox, border_text, unit=MM):
        for i, (bbox, child) in enumerate(self.layout_2d(bbox, unit)):
            first = bool(i == 0)
            last = bool(i == len(self.content)-1)
            yield from child.generate(bbox, (
                border_text[0] and (last or self.direction == 'h'),
                border_text[1] and (last or self.direction == 'v'),
                border_text[2] and (first or self.direction == 'h'),
                border_text[3] and (first or self.direction == 'v'),
                ), unit)

    def fit_size(self, w, h, unit=MM):
        widths = []
        heights = []
        for ((x_min, y_min), (x_max, y_max)), child in self.layout_2d(((0, 0), (w, h)), unit):
            if not isinstance(child, EmptyProtoArea):
                widths.append(x_max - x_min)
                heights.append(y_max - y_min)
        if self.direction == 'h':
            return sum(widths), max(heights, default=0)
        else:
            return max(widths, default=0), sum(heights)

    def layout_2d(self, bbox, unit=MM):
        (x, y), (w, h) = bbox
        w, h = w-x, h-y

        actual_l = 0
        target_l = 0

        for l, child in zip(self.layout(w if self.direction == 'h' else h, unit), self.content):
            this_x, this_y = x, y
            this_w, this_h = w, h
            target_l += l

            if self.direction == 'h':
                this_w = target_l - actual_l
            else:
                this_h = target_l - actual_l

            this_w, this_h = child.fit_size(this_w, this_h, unit)

            if self.direction == 'h':
                x += this_w
                actual_l += this_w
                this_h = h
            else:
                y += this_h
                actual_l += this_h
                this_w = w

            yield ((this_x, this_y), (this_x+this_w, this_y+this_h)), child

    def layout(self, length, unit=MM):
        out = [ eval_value(value, MM(length, unit)) for value in self.proportions ]
        total_length = sum(value for value in out if value is not None)
        if length - total_length < -1e-6:
            raise ValueError(f'Proportions sum to {total_length} mm, which is greater than the available space of {length} mm.')

        leftover = length - total_length
        sum_props = sum( (value or 1.0) for value in self.proportions if not isinstance(value, str) )
        return [ unit(leftover * (value or 1.0) / sum_props if not isinstance(value, str) else calculated, MM)
                for value, calculated in zip(self.proportions, out) ]

    @property
    def single_sided(self):
        return all(elem.single_sided for elem in self.content)

    def __str__(self):
        children = ', '.join( f'{elem}:{width}' for elem, width in zip(self.content, self.proportions))
        return f'PropLayout[{self.direction.upper()}]({children})'


class TwoSideLayout:
    def __init__(self, top, bottom):
        self.top, self.bottom = top, bottom

        if not top.single_sided or not bottom.single_sided:
            warnings.warn('Two-sided pattern used on one side of a TwoSideLayout')

    def fit_size(self, w, h, unit=MM):
        w1, h1 = self.top.fit_size(w, h, unit)
        w2, h2 = self.bottom.fit_size(w, h, unit)
        if isinstance(self.top, EmptyProtoArea):
            if isinstance(self.bottom, EmptyProtoArea):
                return w1, h1
            return w2, h2
        if isinstance(self.bottom, EmptyProtoArea):
            return w1, h1
        return max(w1, w2), max(h1, h2)

    def generate(self, bbox, border_text, unit=MM):
        yield from self.top.generate(bbox, border_text, unit)
        for obj in self.bottom.generate(bbox, border_text, unit):
            obj.side = 'bottom'
            yield obj


def numeric(start=1):
    def gen():
        nonlocal start
        for i in itertools.count(start):
            yield str(i)

    return gen


def alphabetic(case='upper'):
    if case not in ('lower', 'upper'):
        raise ValueError('case must be one of "lower" or "upper".')

    index = string.ascii_lowercase if case == 'lower' else string.ascii_uppercase

    def gen():
        nonlocal index

        for i in itertools.count():
            if i<26:
                yield index[i]
                continue

            i -= 26
            if i<26*26:
                yield index[i//26] + index[i%26]
                continue

            i -= 26*26
            if i<26*26*26:
                yield index[i//(26*26)] + index[(i//26)%26] + index[i%26]

            else:
                raise ValueError('row/column index out of range')

    return gen


class PatternProtoArea:
    def __init__(self, pitch_x, pitch_y=None, obj=None, numbers=True, font_size=None, font_stroke=None, number_x_gen=alphabetic(), number_y_gen=numeric(), interval_x=5, interval_y=None, margin=0, unit=MM):
        self.pitch_x = pitch_x
        self.pitch_y = pitch_y or pitch_x
        self.margin = margin
        self.obj = obj
        self.unit = unit
        self.numbers = numbers
        self.font_size = font_size or unit(1.0, MM)
        self.font_stroke = font_stroke or unit(0.2, MM)
        self.interval_x = interval_x
        self.interval_y = interval_y or (1 if MM(self.pitch_y, unit) >= 2.0 else 5)
        self.number_x_gen, self.number_y_gen = number_x_gen, number_y_gen

    def fit_size(self, w, h, unit=MM):
        (min_x, min_y), (max_x, max_y) = self.fit_rect(((0, 0), (max(0, w-2*self.margin), max(0, h-2*self.margin))))
        return max_x-min_x + 2*self.margin, max_y-min_y + 2*self.margin

    def fit_rect(self, bbox, unit=MM):
        (x, y), (w, h) = bbox
        x, y = x+self.margin, y+self.margin
        w, h = w-x-self.margin, h-y-self.margin

        w_mod = round((w + 5e-7) % unit(self.pitch_x, self.unit), 6)
        h_mod = round((h + 5e-7) % unit(self.pitch_y, self.unit), 6)
        w_fit, h_fit = round(w - w_mod, 6), round(h - h_mod, 6)

        x = x + (w-w_fit)/2
        y = y + (h-h_fit)/2
        return (x, y), (x+w_fit, y+h_fit)

    def generate(self, bbox, border_text, unit=MM):
        (x, y), (w, h) = bbox
        w, h = w-x, h-y

        n_x = int(w//unit(self.pitch_x, self.unit))
        n_y = int(h//unit(self.pitch_y, self.unit))
        off_x = (w % unit(self.pitch_x, self.unit)) / 2
        off_y = (h % unit(self.pitch_y, self.unit)) / 2

        if self.numbers:
            for i, lno_i in list(zip(range(n_y), self.number_y_gen())):
                if i == 0 or i == n_y - 1 or (i+1) % self.interval_y == 0:
                    t_y = off_y + y + (n_y - 1 - i + 0.5) * self.pitch_y

                    if border_text[3]:
                        t_x = x + off_x
                        yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'right', 'middle', unit=self.unit)
                        if not self.single_sided:
                            yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'right', 'middle', side='bottom', unit=self.unit)

                    if border_text[1]:
                        t_x = x + w - off_x
                        yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'left', 'middle', unit=self.unit)
                        if not self.single_sided:
                            yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'left', 'middle', side='bottom', unit=self.unit)

            for i, lno_i in zip(range(n_x), self.number_x_gen()):
                if i == 0 or i == n_x - 1 or (i+1) % self.interval_x == 0:
                    t_x = off_x + x + (i + 0.5) * self.pitch_x

                    if border_text[2]:
                        t_y = y + off_y
                        yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'center', 'top', unit=self.unit)
                        if not self.single_sided:
                            yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'center', 'top', side='bottom', unit=self.unit)

                    if border_text[0]:
                        t_y = y + h - off_y
                        yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'center', 'bottom', unit=self.unit)
                        if not self.single_sided:
                            yield Text(t_x, t_y, lno_i, self.font_size, self.font_stroke, 'center', 'bottom', side='bottom', unit=self.unit)


        for i in range(n_x):
            for j in range(n_y):
                if hasattr(self.obj, 'inst'):
                    inst = self.obj.inst(i, j, i == n_x-1, j == n_y-1)
                    if not inst:
                        continue
                else:
                    inst = copy(self.obj)

                inst.x = inst.unit(off_x + x, unit) + (i + 0.5) * inst.unit(self.pitch_x, self.unit)
                inst.y = inst.unit(off_y + y, unit) + (j + 0.5) * inst.unit(self.pitch_y, self.unit)
                yield inst

    @property
    def single_sided(self):
        return self.obj.single_sided


class EmptyProtoArea:
    def __init__(self, copper_fill=False):
        self.copper_fill = copper_fill

    def fit_size(self, w, h, unit=MM):
        return w, h

    def generate(self, bbox, border_text, unit=MM):
        if self.copper_fill:
            (min_x, min_y), (max_x, max_y) = bbox
            group = ObjectGroup(0, 0, top_copper=[Region([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)],
                                                unit=unit, polarity_dark=True)])
            group.bounding_box = lambda *args, **kwargs: None
            yield group

    @property
    def single_sided(self):
        return True


class ManhattanPads(ObjectGroup):
    def __init__(self, w, h=None, gap=0.2, unit=MM):
        super().__init__(0, 0)
        h = h or w
        self.gap = gap
        self.unit = unit

        p = (w-2*gap)/2
        q = (h-2*gap)/2
        small_ap = RectangleAperture(p, q, unit=unit)

        s = min(w, h) / 2 / math.sqrt(2)
        large_ap = RectangleAperture(s, s, unit=unit).rotated(math.pi/4)
        large_ap_neg = RectangleAperture(s+2*gap, s+2*gap, unit=unit).rotated(math.pi/4)

        a = gap/2 + p/2
        b = gap/2 + q/2

        self.top_copper.append(Flash(-a, -b, aperture=small_ap, unit=unit))
        self.top_copper.append(Flash(-a,  b, aperture=small_ap, unit=unit))
        self.top_copper.append(Flash( a, -b, aperture=small_ap, unit=unit))
        self.top_copper.append(Flash( a,  b, aperture=small_ap, unit=unit))
        self.top_copper.append(Flash(0, 0, aperture=large_ap_neg, polarity_dark=False, unit=unit))
        self.top_copper.append(Flash(0, 0, aperture=large_ap, unit=unit))
        self.top_mask = self.top_copper


class RFGroundProto(ObjectGroup):
    def __init__(self, pitch=None, drill=None, clearance=None, via_dia=None, via_drill=None, pad_dia=None, trace_width=None, unit=MM):
        super().__init__(0, 0)
        self.unit = unit
        self.pitch = pitch = pitch or unit(2.54, MM)
        self.drill = drill = drill or unit(0.9, MM)
        self.clearance = clearance = clearance or unit(0.3, MM)
        self.via_drill = via_drill = via_drill or unit(0.4, MM)
        self.via_dia = via_dia = via_dia or unit(0.8, MM)

        if pad_dia is None:
            self.trace_width = trace_width = trace_width or unit(0.3, MM)
            pad_dia = pitch - trace_width - 2*clearance 
        elif trace_width is None:
            trace_width = pitch - pad_dia - 2*clearance
        self.pad_dia = pad_dia

        via_ap = RectangleAperture(via_dia, via_dia, unit=unit).rotated(math.pi/4)
        pad_ap = CircleAperture(pad_dia, unit=unit)
        pad_neg_ap = CircleAperture(pad_dia+2*clearance, unit=unit)
        ground_ap = RectangleAperture(pitch + unit(0.01, MM), pitch + unit(0.01, MM), unit=unit)
        pad_drill = ExcellonTool(drill, plated=True, unit=unit)
        via_drill = ExcellonTool(via_drill, plated=True, unit=unit)

        self.top_copper.append(Flash(0, 0, aperture=ground_ap, unit=unit))
        self.top_copper.append(Flash(0, 0, aperture=pad_neg_ap, polarity_dark=False, unit=unit))
        self.top_copper.append(Flash(0, 0, aperture=pad_ap, unit=unit))
        self.top_mask.append(Flash(0, 0, aperture=pad_ap, unit=unit))
        self.top_copper.append(Flash(pitch/2, pitch/2, aperture=via_ap, unit=unit))
        self.top_mask.append(Flash(pitch/2, pitch/2, aperture=via_ap, unit=unit))
        self.drill_pth.append(Flash(0, 0, aperture=pad_drill, unit=unit))
        self.drill_pth.append(Flash(pitch/2, pitch/2, aperture=via_drill, unit=unit))

        self.bottom_copper = self.top_copper
        self.bottom_mask = self.top_mask

    def inst(self, x, y, border_x, border_y):
        inst = copy(self)
        if border_x or border_y:
            inst.drill_pth = inst.drill_pth[:-1]
            inst.top_copper = inst.bottom_copper = inst.top_copper[:-1]
            inst.top_mask = inst.bottom_mask = inst.top_mask[:-1]
        return inst


class THTFlowerProto(ObjectGroup):
    def __init__(self, pitch=None, drill=None, diameter=None, unit=MM):
        super().__init__(0, 0, unit=unit)
        self.pitch = pitch = pitch or unit(2.54, MM)
        drill = drill or unit(0.9, MM)
        diameter = diameter or unit(2.0, MM)

        p = pitch / 2
        self.objects.append(THTPad.circle(-p, 0, drill, diameter, paste=False, unit=unit))
        self.objects.append(THTPad.circle( p, 0, drill, diameter, paste=False, unit=unit))
        self.objects.append(THTPad.circle(0, -p, drill, diameter, paste=False, unit=unit))
        self.objects.append(THTPad.circle(0,  p, drill, diameter, paste=False, unit=unit))

        middle_ap = CircleAperture(diameter, unit=unit)
        self.top_copper.append(Flash(0, 0, aperture=middle_ap, unit=unit))
        self.bottom_copper = self.top_mask = self.bottom_mask = self.top_copper
    
    def inst(self, x, y, border_x, border_y):
        if (x % 2 == 0) and (y % 2 == 0):
            return copy(self)

        if (x % 2 == 1) and (y % 2 == 1):
            return copy(self)

        return None

    def bounding_box(self, unit=MM):
        x, y, rotation = self.abs_pos
        p = self.pitch/2
        return unit.convert_bounds_from(self.unit, ((x-p, y-p), (x+p, y+p)))

class PoweredProto(ObjectGroup):
    """ Cell primitive for "powered" THT breadboards. This cell type is based on regular THT pads in a 100 mil grid, but
    adds small SMD pads diagonally between the THT pads. These SMD pads are interconnected with traces and vias in such
    a way that every second one is inter-linked, forming two fully connected grids. Next to every THT pad you have one
    pad of each grid, so this layout is awesome for distributing power throughout the board.

    This design is based on one that Yajima Manufacturing Akizuki Denshi, Akihabara's finest electronics store sells for
    next to nothing. Sadly, they don't ship internationally and they don't even have an English website, but if you ever
    are in Akihabara, Tokyo, Japan I can *highly* recommend a visit. The ones Yajima make are better than what this will
    produce since the Yajima ones use a two-colored silkscreen to visually distinguish the two power pad grids.

    Links:
    Akizuki Denshi product page: https://akizukidenshi.com/catalog/g/gP-07214/
    Yajima Manufacturing Corporation website: http://www.yajima-works.co.jp/index.html
    """

    def __init__(self, pitch=None, drill=None, clearance=None, power_pad_dia=None, via_size=None, trace_width=None, unit=MM):
        super().__init__(0, 0)
        self.unit = unit
        self.pitch = pitch = pitch or unit(2.54, MM)
        self.drill = drill = drill or unit(0.9, MM)
        self.clearance = clearance = clearance or unit(0.3, MM)
        self.trace_width = trace_width = trace_width or unit(0.3, MM)
        self.via_size = via_size = via_size or unit(0.4, MM)

        main_pad_dia = pitch - trace_width - 2*clearance
        power_pad_dia_max = math.sqrt(2)*pitch - main_pad_dia - 2*clearance
        if power_pad_dia is None:
            power_pad_dia = power_pad_dia_max - clearance # reduce some more to give the user more room
        elif power_pad_dia > power_pad_dia_max:
            warnings.warn(f'Power pad diameter {power_pad_dia} > {power_pad_dia_max} violates pad-to-pad clearance')
        self.power_pad_dia = power_pad_dia

        main_ap = CircleAperture(main_pad_dia, unit=unit)
        power_ap = CircleAperture(self.power_pad_dia, unit=unit)

        for l in [self.top_copper, self.bottom_copper]:
            l.append(Flash(0, 0, aperture=main_ap, unit=unit))

            l.append(Flash(-pitch/2, -pitch/2, aperture=power_ap, unit=unit))
            l.append(Flash(-pitch/2,  pitch/2, aperture=power_ap, unit=unit))
            l.append(Flash( pitch/2, -pitch/2, aperture=power_ap, unit=unit))
            l.append(Flash( pitch/2,  pitch/2, aperture=power_ap, unit=unit))

        self.drill_pth.append(Flash(0, 0, ExcellonTool(drill, plated=True, unit=unit), unit=unit))
        self.drill_pth.append(Flash(-pitch/2, -pitch/2, ExcellonTool(via_size, plated=True, unit=unit), unit=unit))

        self.top_mask = copy(self.top_copper)
        self.bottom_mask = copy(self.bottom_copper)

        self.line_ap = CircleAperture(trace_width, unit=unit)
        self.top_copper.append(Line(-pitch/2, -pitch/2, -pitch/2, pitch/2, aperture=self.line_ap, unit=unit))
        self.top_copper.append(Line(pitch/2, -pitch/2, pitch/2, pitch/2, aperture=self.line_ap, unit=unit))
        self.bottom_copper.append(Line(-pitch/2, -pitch/2, pitch/2, -pitch/2, aperture=self.line_ap, unit=unit))
        self.bottom_copper.append(Line(-pitch/2, pitch/2, pitch/2, pitch/2, aperture=self.line_ap, unit=unit))

    def inst(self, x, y, border_x, border_y):
        inst = copy(self)
        if (x + y) % 2 == 0:
            inst.drill_pth = inst.drill_pth[:-1]

        c = self.power_pad_dia/2 + self.clearance
        p = self.pitch/2

        if x == 1:
            inst.top_silk = [Line(-p, -p+c, -p, p-c, aperture=self.line_ap, unit=self.unit)]
        elif x % 2 == 0:
            inst.top_silk = [Line(p, -p+c, p, p-c, aperture=self.line_ap, unit=self.unit)]

        if y == 0:
            inst.bottom_silk = [Line(-p+c, -p, p-c, -p, aperture=self.line_ap, unit=self.unit)]
        elif y % 2 == 1:
            inst.bottom_silk = [Line(-p+c, p, p-c, p, aperture=self.line_ap, unit=self.unit)]

        return inst

    def bounding_box(self, unit=MM):
        x, y, rotation = self.abs_pos
        p = self.pitch/2
        return unit.convert_bounds_from(self.unit, ((x-p, y-p), (x+p, y+p)))


class SpikyProto(ObjectGroup):
    """ Cell primitive for the "spiky" protoboard designed by @electroniceel and published on github at the URL below.
    This layout has small-ish standard THT pads, but in between these pads it puts a grid of SMD pads that are designed
    for easy solder bridging to allow for the construction of traces from solder bridging.

    Github URL: https://github.com/electroniceel/protoboard
    """

    def __init__(self, pitch=None, drill=None, clearance=None, power_pad_dia=None, via_size=None, trace_width=None, unit=MM):
        super().__init__(0, 0, unit=unit)
        res = importlib.resources.files(package_data)

        self.fp_center = kfp.Footprint.load(res.joinpath('center-pad-spikes.kicad_mod').read_text(encoding='utf-8'))
        self.corner_pad = kfp.FootprintInstance(1.27, 1.27, self.fp_center, unit=MM)

        self.pad = kfp.Footprint.load(res.joinpath('tht-0.8.kicad_mod').read_text(encoding='utf-8'))
        self.center_pad = kfp.FootprintInstance(0, 0, self.pad, unit=MM)

        self.fp_between = kfp.Footprint.load(res.joinpath('pad-between-spiked.kicad_mod').read_text(encoding='utf-8'))
        self.right_pad = kfp.FootprintInstance(1.27, 0, self.fp_between, unit=MM)
        self.top_pad = kfp.FootprintInstance(0, 1.27, self.fp_between, rotation=math.pi/2, unit=MM)

    @property
    def objects(self):
        return [x for x in (self.center_pad, self.corner_pad, self.right_pad, self.top_pad) if x is not None]

    @objects.setter
    def objects(self, value):
        pass

    def inst(self, x, y, border_x, border_y):
        inst = copy(self)

        if border_x:
            inst.corner_pad = inst.right_pad = None

        if border_y:
            inst.corner_pad = inst.top_pad = None

        return inst


class AlioCell(ObjectGroup):
    """ Cell primitive for the ALio protoboard designed by arief ibrahim adha and published on hackaday.io at the URL
    below. Similar to electroniceel's spiky protoboard, this layout has small-ish standard THT pads, but in between
    these pads it puts a grid of SMD pads that are designed for easy solder bridging to allow for the construction of
    traces from solder bridging.

    Hackaday.io URL: https://hackaday.io/project/28570/
    """

    def __init__(self, pitch=None, drill=None, clearance=None, link_pad_width=None, link_trace_width=None, via_size=None, unit=MM):
        super().__init__(0, 0, unit=unit)
        self.pitch = pitch or unit(2.54, MM)
        self.drill = drill or unit(0.9, MM)
        self.clearance = clearance or unit(0.3, MM)
        self.link_pad_width = link_pad_width or unit(1.1, MM)
        self.link_trace_width = link_trace_width or unit(0.5, MM)
        self.via_size = via_size or unit(0.4, MM)
        self.border_x, self.border_y = False, False
        self.inst_x, self.inst_y = None, None

    @property
    def single_sided(self):
        return False

    def inst(self, x, y, border_x, border_y):
        inst = copy(self)
        inst.border_x, inst.border_y = border_x, border_y
        inst.inst_x, inst.inst_y = x, y
        return inst

    def bounding_box(self, unit):
        x, y, rotation = self.abs_pos
        # FIXME hack
        return self.unit.convert_bounds_to(unit, ((x-self.pitch/2, y-self.pitch/2), (x+self.pitch/2, y+self.pitch/2)))

    def render(self, layer_stack, cache=None):
        x, y, rotation = self.abs_pos
        def xf(fe):
            fe = copy(fe)
            fe.rotate(rotation)
            fe.offset(x, y, self.unit)
            return fe

        var = VariableExpression
        # parameters: [1: total height = pad width, 2: pitch, 3: trace width, 4: corner radius, 5: rotation, 6: clearance]
        alio_main_macro = ApertureMacro('ALIOM', (
            amp.CenterLine(MM, 1, var(2)-var(6), var(2)-var(3)-2*var(6), 0, 0, var(5)),
            amp.Outline(MM, 0, 5, (
                -var(2)/2,          -var(2)/2,
                -var(2)/2,          -(var(7)-var(8)),
                -var(7),            -(var(7)-var(8)),
                -(var(7)-var(8)),   -var(7),
                -(var(7)-var(8)),   -var(2)/2, 
                -var(2)/2,          -var(2)/2,
                ), var(5)),
            amp.Outline(MM, 0, 5, (
                -var(2)/2,           var(2)/2,
                -var(2)/2,           (var(7)-var(8)),
                -var(7),             (var(7)-var(8)),
                -(var(7)-var(8)),    var(7),
                -(var(7)-var(8)),    var(2)/2, 
                -var(2)/2,           var(2)/2,
                ), var(5)),
            amp.Outline(MM, 0, 5, (
                 var(2)/2,          -var(2)/2,
                 var(2)/2,          -(var(7)-var(8)),
                 var(7),            -(var(7)-var(8)),
                 (var(7)-var(8)),   -var(7),
                 (var(7)-var(8)),   -var(2)/2, 
                 var(2)/2,          -var(2)/2,
                ), var(5)),
            amp.Outline(MM, 0, 5, (
                 var(2)/2,           var(2)/2,
                 var(2)/2,           (var(7)-var(8)),
                 var(7),             (var(7)-var(8)),
                 (var(7)-var(8)),    var(7),
                 (var(7)-var(8)),    var(2)/2, 
                 var(2)/2,           var(2)/2,
                ), var(5)),
            amp.Circle(MM, 0, 2*var(8), -var(7), -var(7), var(5)),
            amp.Circle(MM, 0, 2*var(8), -var(7),  var(7), var(5)),
            amp.Circle(MM, 0, 2*var(8),  var(7), -var(7), var(5)),
            amp.Circle(MM, 0, 2*var(8),  var(7),  var(7), var(5)),
            ), (
                None, # 1
                None, # 2
                None, # 3
                None, # 4
                None, # 5
                None, # 6
                var(2)/2 - var(1)/2 + var(4),   # 7
                var(4)+var(6),                  # 8
                ))
        corner_radius = (self.link_pad_width - self.link_trace_width)/3
        main_ap = ApertureMacroInstance(alio_main_macro, (self.link_pad_width,         # 1
                                                          self.pitch,                  # 2
                                                          self.link_trace_width,       # 3
                                                          corner_radius,               # 4
                                                          rotation,                    # 5
                                                          self.clearance), unit=MM)    # 6
        main_ap_90 = ApertureMacroInstance(alio_main_macro, (self.link_pad_width,      # 1
                                                          self.pitch,                  # 2
                                                          self.link_trace_width,       # 3
                                                          corner_radius,               # 4
                                                          rotation-90,                 # 5
                                                          self.clearance), unit=MM)    # 6
        main_drill = ExcellonTool(self.drill, plated=True, unit=self.unit)
        via_drill = ExcellonTool(self.via_size, plated=True, unit=self.unit)

        # parameters: [1: total height = pad width, 2: total width, 3: trace width, 4: corner radius, 5: rotation]
        alio_macro = ApertureMacro('ALIOP', (
            amp.CenterLine(MM, 1, var(1)-2*var(4), var(1), 0, 0, var(5)),
            amp.CenterLine(MM, 1, var(1), var(1)-2*var(4), 0, 0, var(5)),
            amp.Circle(MM, 1, 2*var(4), -var(1)/2+var(4), -var(1)/2+var(4), var(5)),
            amp.Circle(MM, 1, 2*var(4), -var(1)/2+var(4),  var(1)/2-var(4), var(5)),
            amp.Circle(MM, 1, 2*var(4),  var(1)/2-var(4), -var(1)/2+var(4), var(5)),
            amp.Circle(MM, 1, 2*var(4),  var(1)/2-var(4),  var(1)/2-var(4), var(5)),
            amp.CenterLine(MM, 1, var(2), var(3), -var(2)/2 + var(1)/2, 0, var(5)),
            ))
        alio_dark = ApertureMacroInstance(alio_macro, (self.link_pad_width,         # 1
                                                       self.pitch-self.clearance,   # 2
                                                       self.link_trace_width,       # 3
                                                       corner_radius,               # 4
                                                       rotation), unit=MM)          # 5
        alio_dark_90 = ApertureMacroInstance(alio_macro, (self.link_pad_width,          # 1
                                                          self.pitch-self.clearance,    # 2
                                                          self.link_trace_width,        # 3
                                                          corner_radius,                # 4
                                                          rotation+90), unit=MM)        # 5

        # all layers are identical here
        for side, use in (('top', 'copper'), ('top', 'mask'), ('bottom', 'copper'), ('bottom', 'mask')):
            if side == 'top':
                layer_stack[side, use].objects.insert(0, xf(Flash(0, 0, aperture=main_ap, unit=self.unit)))
                if not self.border_y:
                    layer_stack[side, use].objects.append(xf(Flash(self.pitch/2, self.pitch/2, aperture=alio_dark, unit=self.unit)))
            else:
                layer_stack[side, use].objects.insert(0, xf(Flash(0, 0, aperture=main_ap_90, unit=self.unit)))
                if not self.border_x:
                    layer_stack[side, use].objects.append(xf(Flash(self.pitch/2, self.pitch/2, aperture=alio_dark_90, unit=self.unit)))

        layer_stack.drill_pth.append(Flash(x, y, aperture=main_drill, unit=self.unit))
        if not (self.border_x or self.border_y):
            layer_stack.drill_pth.append(xf(Flash(self.pitch/2, self.pitch/2, aperture=via_drill, unit=self.unit)))


def convert_to_mm(value, unit):
    unitl  = unit.lower()
    if unitl == 'mm':
        return value
    elif unitl == 'cm':
        return value*10
    elif unitl == 'in':
        return value*25.4
    elif unitl == 'mil':
        return value/1000*25.4
    else:
        raise ValueError(f'Invalid unit {unit}, allowed units are mm, cm, in, and mil.')


_VALUE_RE = re.compile('([0-9]*\.?[0-9]+)(cm|mm|in|mil|%)')
def eval_value(value, total_length=None):
    if not isinstance(value, str):
        return None

    m = _VALUE_RE.match(value.lower())
    number, unit = m.groups()
    if unit == '%':
        if total_length is None:
            raise ValueError('Percentages are not allowed for this value')
        return total_length * float(number) / 100
    return convert_to_mm(float(number), unit)


def _demo():
    #pattern1 = PatternProtoArea(2.54, obj=THTPad.circle(0, 0, 0.9, 1.8, paste=False))
    #pattern1 = PatternProtoArea(2.54, 2.54, obj=SpikyProto())
    #pattern2 = PatternProtoArea(1.2, 2.0, obj=SMDPad.rect(0, 0, 1.0, 1.8, paste=False))
    #pattern3 = PatternProtoArea(2.54, 1.27, obj=SMDPad.rect(0, 0, 2.3, 1.0, paste=False))
    #pattern3 = EmptyProtoArea(copper_fill=True)
    #stack = TwoSideLayout(pattern2, pattern3)
    #pattern2 = PatternProtoArea(2.54, obj=PoweredProto(), margin=1)
    #pattern3 = PatternProtoArea(2.54, obj=RFGroundProto())
    #stack = PropLayout([pattern2, pattern3], 'h', [0.5, 0.5])
    #pattern = PropLayout([pattern1, stack], 'h', [0.5, 0.5])
    #pattern = PatternProtoArea(2.54, obj=ManhattanPads(2.54))
    #pattern = PatternProtoArea(2.54*1.5, obj=THTFlowerProto())
    #pattern = PatternProtoArea(2.54, obj=THTPad.circle(0, 0, 0.9, 1.8, paste=False))
    #pattern = PatternProtoArea(2.54, obj=PoweredProto())
    pattern = PatternProtoArea(2.54, obj=AlioCell(), margin=2)
    pb = ProtoBoard(50, 47, pattern, mounting_hole_dia=3.2, mounting_hole_offset=5)
    #pb = ProtoBoard(10, 10, pattern1)
    print(pb.pretty_svg())
    pb.layer_stack().save_to_directory('/tmp/testdir')


if __name__ == '__main__':
    _demo()
    #cnt = alphabetic()()
    #for _ in range(32):
    #    for _ in range(26):
    #        print(f'{next(cnt):>2}', end=' ', file=sys.stderr)
    #    print(file=sys.stderr)

