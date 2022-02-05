#!/usr/bin/env python3

import math
import sys

from gerbonara import LayerStack
from gerbonara.graphic_objects import Line, Arc
from gerbonara.apertures import CircleAperture
from gerbonara.utils import MM
from gerbonara.utils import rotate_point

def highlight_outline(input_dir, output_dir):
    stack = LayerStack.from_directory(input_dir)

    outline = []
    for obj in stack.outline.objects:
        if isinstance(obj, Line):
            outline.append(obj.converted('mm'))

        elif isinstance(obj, Arc):
            outline += obj.converted('mm').approximate(0.1, 'mm')

    marker_angle = math.pi/3
    marker_spacing = 2
    marker_width = 0.1

    marker_dx, marker_dy = math.sin(marker_angle)*marker_spacing, -math.cos(marker_angle)*marker_spacing
    marker_nx, marker_ny = math.sin(marker_angle), math.cos(marker_angle)

    ap = CircleAperture(0.1, unit=MM)
    stack['top silk'].apertures.append(ap)

    for line in outline:
        cx, cy = (line.x1 + line.x2)/2, (line.y1 + line.y2)/2
        dx, dy = line.x1 - cx, line.y1 - cy

        angle = math.atan2(dy, dx)
        r = math.hypot(dx, dy)
        if r == 0:
            continue

        w = 10
        tl_x, tl_y = line.x1 + math.sin(angle)*w/2, line.y1 - math.cos(angle)*w/2
        tr_x, tr_y = line.x2 + math.sin(angle)*w/2, line.y2 - math.cos(angle)*w/2
        br_x, br_y = line.x2 - math.sin(angle)*w/2, line.y2 + math.cos(angle)*w/2
        bl_x, bl_y = line.x1 - math.sin(angle)*w/2, line.y1 + math.cos(angle)*w/2

        tr = math.dist((tl_x, tl_y), (br_x, br_y))/2

        n = math.ceil(tr/marker_spacing)
        for i in range(-n, n+1):
            px, py = cx + i*marker_dx, cy + i*marker_dy

            lx1, ly1 = px + tr*marker_nx, py + tr*marker_ny
            lx2, ly2 = px - tr*marker_nx, py - tr*marker_ny

            lx1, ly1 = rotate_point(lx1, ly1, angle, cx, cy)
            lx2, ly2 = rotate_point(lx2, ly2, angle, cx, cy)

            def clip_line_point(x1, y1, x2, y2, xabs, yabs):
                if x2 != x1:
                    a = (y2 - y1) / (x2 - x1)
                    x2 = min(xabs, max(-xabs, x2))
                    y2 = y1 + a*(x2 - x1)

                elif abs(x1) > xabs:
                    return None

                if y2 != y1:
                    a = (x2 - x1) / (y2 - y1)
                    y2 = min(yabs, max(-yabs, y2))
                    x2 = x1 + a*(y2 - y1)

                elif abs(y1) > yabs:
                    return None

                return x1, y1, x2, y2

            if not (foo := clip_line_point(lx1-cx, ly1-cy, lx2-cx, ly2-cy, r, w/2)):
                continue
            lx1, ly1, lx2, ly2 = foo

            if not (foo := clip_line_point(lx2, ly2, lx1, ly1, r, w/2)):
                continue
            lx1, ly1, lx2, ly2 = foo

            lx1, ly1, lx2, ly2 = lx1+cx, ly1+cy, lx2+cx, ly2+cy

            lx1, ly1 = rotate_point(lx1, ly1, -angle, cx, cy)
            lx2, ly2 = rotate_point(lx2, ly2, -angle, cx, cy)

            stack['top silk'].objects.append(Line(lx1, ly1, lx2, ly2, unit=MM, aperture=ap, polarity_dark=True))

    stack.save_to_directory(output_dir)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args()
    highlight_outline(args.input, args.output)

