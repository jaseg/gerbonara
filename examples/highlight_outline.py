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

    # FIXME test code
    #print('<?xml version="1.0" encoding="utf-8"?>')
    #print('<svg width="300mm" height="300mm" viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg">')
    #outline = []
    #for i in range(16):
    #    for j in range(16):
    #        cx, cy = i*3, j*3
    #        w = i/8
    #        angle = j*2*math.pi/16
    #        x1, y1 = cx-w/2, cy
    #        x2, y2 = cx+w/2, cy
    #
    #        x1, y1 = rotate_point(x1, y1, angle, cx, cy)
    #        x2, y2 = rotate_point(x2, y2, angle, cx, cy)
    #
    #        outline.append(Line(x1, y1, x2, y2, aperture=CircleAperture(1.0, unit=MM), unit=MM))
    #        print(f'<path style="stroke: red; stroke-width: 0.01mm;" d="M {x1} {y1} L {x2} {y2}"/>')

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

        cr = math.hypot(cx, cy)
        #w = line.aperture.equivalent_width('mm')
        w = 10

        tl_x, tl_y = line.x1 + math.sin(angle)*w/2, line.y1 - math.cos(angle)*w/2
        tr_x, tr_y = line.x2 + math.sin(angle)*w/2, line.y2 - math.cos(angle)*w/2
        br_x, br_y = line.x2 - math.sin(angle)*w/2, line.y2 + math.cos(angle)*w/2
        bl_x, bl_y = line.x1 - math.sin(angle)*w/2, line.y1 + math.cos(angle)*w/2

        tr = math.dist((tl_x, tl_y), (br_x, br_y))/2

        #print(f'<path style="stroke: red; stroke-width: 0.01mm; fill: none;" d="M {tl_x} {tl_y} L {tr_x} {tr_y} L {br_x} {br_y} L {bl_x} {bl_y} Z"/>')

        n = math.ceil(tr/marker_spacing)
        for i in range(-n, n+1):
            px, py = cx + i*marker_dx, cy + i*marker_dy

            lx1, ly1 = px + tr*marker_nx, py + tr*marker_ny
            lx2, ly2 = px - tr*marker_nx, py - tr*marker_ny

            lx1, ly1 = rotate_point(lx1, ly1, angle, cx, cy)
            lx2, ly2 = rotate_point(lx2, ly2, angle, cx, cy)
            #print(f'<circle style="fill: blue; stroke: none;" r="{marker_spacing/2}" cx="{px}" cy="{py}"/>')

            def clip_line_point(x1, y1, x2, y2, xabs, yabs):
                #print(x1, y1, x2, y2, end=' -> ', file=sys.stderr)
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

                #print(x1, y1, x2, y2, file=sys.stderr)
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

            #print(f'<path style="stroke: blue; stroke-width: {marker_width}mm; opacity: 0.2;" d="M {lx1} {ly1} L {lx2} {ly2}"/>')

            #delta_a = marker_angle - angle
            #ex, ey = px, py
            #print(f'<circle style="fill: blue; stroke: none;" r="{marker_spacing/5}" cx="{ex}" cy="{ey}"/>')
            #print(delta_a, file=sys.stderr)
            # delta_a + math.pi/2

    stack.save_to_directory(output_dir)
    #print('</svg>')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args()
    highlight_outline(args.input, args.output)
