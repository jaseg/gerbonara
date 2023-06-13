#!/usr/bin/env python3

from math import *
from pathlib import Path
from itertools import cycle

from gerbonara.cad.kicad import pcb as kicad_pcb
from gerbonara.cad.kicad import graphical_primitives as kicad_gr
import click


def point_line_distance(p, l1, l2):
    x0, y0 = p
    x1, y1 = l1
    x2, y2 = l2
    # https://en.wikipedia.org/wiki/Distance_from_a_point_to_a_line
    return abs((x2-x1)*(y1-y0) - (x1-x0)*(y2-y1)) / sqrt((x2-x1)**2 + (y2-y1)**2)

def line_line_intersection(l1, l2):
    p1, p2 = l1
    p3, p4 = l2
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    
    # https://en.wikipedia.org/wiki/Line%E2%80%93line_intersection
    px = ((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/((x1-x2)*(y3-y4)-(y1-y2)*(x3-x4))
    py = ((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/((x1-x2)*(y3-y4)-(y1-y2)*(x3-x4))
    return px, py


@click.command()
@click.argument('infile', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outfile', type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--polygon', type=int, default=0, help="Use n'th polygon instead of first one. 0-based index.")
@click.option('--start-angle', type=float, default=0, help='Angle for the start at the outermost layer of the spiral in degree')
@click.option('--stop-radius', type=float, default=1, help='Inner radius of spiral')
@click.option('--trace-width', type=float, default=0.15)
@click.option('--clearance', type=float, default=0.15)
def generate(infile, outfile, polygon, start_angle, stop_radius, trace_width, clearance):
    board = kicad_pcb.Board.open(infile)
    objs = [obj for obj in board.objects() if isinstance(obj, kicad_gr.Polygon)]
    print(f'Found {len(objs)} polygon(s).')
    poly = objs[polygon]
    xy = [(pt.x, pt.y) for pt in poly.pts.xy]
    segments = list(zip(xy, xy[1:] + xy[:1]))

    vbx, vby = min(x for x, y in xy), min(y for x, y, in xy)
    vbw, vbh = max(x for x, y in xy), max(y for x, y, in xy)
    vbw, vbh = vbw-vbx, vbh-vby

    vbx -= 5
    vby -= 5
    vbw += 10
    vbh += 10

    cx, cy = 0, 0
    ls = 0
    for (x1, y1), (x2, y2) in segments:
        l = dist((x1, y1), (x2, y2))
        cx += x1*l/2 + x2*l/2
        cy += y1*l/2 + y2*l/2
        ls += l
    cx /= ls
    cy /= ls

    segment_angles = [(atan2(y1-cy, x1-cx) - atan2(y2-cy, x2-cx) + 2*pi) % (2*pi) for (x1, y1), (x2, y2) in segments]
    angle_strs = [f'{degrees(a):.2f}' for a in segment_angles]
    print(f'Segment angles: {" ".join(angle_strs)}')
    print(f'Sum of segment angles: {degrees(sum(segment_angles)):.2f}')

    segment_heights = [point_line_distance((cx, cy), (x1, y1), (x2, y2)) for (x1, y1), (x2, y2) in segments]
    segment_foo = list(zip(segment_heights, segments))

    closest_points = []
    for h, ((x1, y1), (x2, y2)) in segment_foo:
        dc1 = dist((x1, y1), (cx, cy))
        d12 = dist((x1, y1), (x2, y2))
        db = sqrt(dc1**2 - h**2)
        xn = (x2 - x1) / d12
        yn = (y2 - y1) / d12
        xb = x1 + xn * db
        yb = y1 + yn * db
        closest_points.append((xb, yb))

    smallest_radius = min(segment_heights)
    #trace_radius = smallest_radius - stop_radius
    trace_radius = smallest_radius
    num_windings = floor((trace_radius - trace_width) / (clearance + trace_width))
    print(f'Going for {num_windings} windings')

    segment_foo = list(zip(segment_heights, segments, segment_angles, closest_points))

    dbg_lines = []
    spiral_points = []
    dr_tot = 0
    for n in range(num_windings):
        for (ha, (pa1, pa2), aa, ma), (hb, (pb1, pb2), ab, mb) in zip(segment_foo[-1:] + segment_foo[:-1], segment_foo):
            pitch = clearance + trace_width
            dr_tot_a = dr_tot
            dr_tot_b = dr_tot + ab/(2*pi) * pitch

            xma, yma = ma
            xmb, ymb = mb

            xra = (xma - cx) / ha
            yra = (yma - cy) / ha
            xrb = (xmb - cx) / hb
            yrb = (ymb - cy) / hb

            xa1, ya1 = pa1
            xa2, ya2 = pa2
            xb1, yb1 = pb1
            xb2, yb2 = pb2

            dma = dist(pa2, ma)
            dmb = dist(pb1, mb)

            qa = dr_tot_a*dma/h
            dra = hypot(dr_tot_a, qa)
            xea = xa2 + (cx - xa2) / dist((cx, cy), pa2) * dra
            yea = ya2 + (cy - ya2) / dist((cx, cy), pa2) * dra

            qb = dr_tot_b*dmb/h
            drb = hypot(dr_tot_b, qb)
            xeb = xb1 + (cx - xb1) / dist((cx, cy), pb1) * drb
            yeb = yb1 + (cy - yb1) / dist((cx, cy), pb1) * drb

            xsa = xma - xra*dr_tot_a
            ysa = yma - yra*dr_tot_a

            xsb = xmb - xrb*dr_tot_b
            ysb = ymb - yrb*dr_tot_b

            l1 = (xsa, ysa), (xea, yea)
            l2 = (xsb, ysb), (xeb, yeb)

            dbg_lines.append(l1)
            dbg_lines.append(l2)

            pic = line_line_intersection(l1, l2)
            spiral_points.append(pic)

            dr_tot = dr_tot_b

    #spiral_points = []
    #r_now = 0
    #for winding in range(num_windings):
    #    for angle, ((x1, y1), (x2, y2)) in zip(segment_angles, segments):
    #        angle_frac = angle/(2*pi)
    #        d_r = angle_frac * (clearance + trace_width)
    #        r_pt = dist((cx, cy), (x1, y1)) * (num_windings - winding) / num_windings
#
#            x1, y1 = x1-cx, y1-cy
#            x2, y2 = x2-cx, y2-cy
#            l1, l2 = hypot(x1, y1), hypot(x2, y2)
#            x1, y1 = x1/l1, y1/l1
#            x2, y2 = x2/l2, y2/l2
#
#            r_now += d_r
#            spiral_points.append((cx + x1*r_pt, cy + y1*r_pt))

    path_d = ' '.join([f'M {xy[0][0]} {xy[0][1]}', *[f'L {x} {y}' for x, y in xy[1:]], 'Z'])
    path_d2 = ' '.join(f'M {cx} {cy} L {x} {y}' for x, y in xy)
    path_d3 = ' '.join([f'M {spiral_points[0][0]} {spiral_points[0][1]}', *[f'L {x} {y}' for x, y in spiral_points[1:]]])
    
    with open('/tmp/test.svg', 'w') as f:
        f.write('<?xml version="1.0" standalone="no"?>\n')
        f.write('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n')
        f.write(f'<svg version="1.1" width="200mm" height="200mm" viewBox="{vbx} {vby} {vbw} {vbh}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">>\n')
        f.write(f'<path fill="none" stroke="#303030" stroke-width="0.05" d="{path_d}"/>\n')
        f.write(f'<path fill="none" stroke="#a0a0a0" stroke-width="0.05" d="{path_d2}"/>\n')
        f.write(f'<path fill="none" stroke="#ff00ff" opacity="0.5" stroke-width="{trace_width}" d="{path_d3}"/>\n')
        f.write(f'<circle r="0.1" fill="red" stroke="none" cx="{cx}" cy="{cy}"/>\n')
        for x, y in closest_points:
            f.write(f'<circle r="0.1" fill="blue" stroke="none" cx="{x}" cy="{y}"/>\n')
            f.write(f'<path fill="none" stroke="#a0a0ff" stroke-width="0.05" d="M {cx} {cy} L {x} {y}"/>')

        for (x1, y1), (x2, y2) in dbg_lines:
            f.write(f'<path fill="none" stroke="#000000" opacity="0.2" stroke-width="0.05" d="M {x1} {y1} L {x2} {y2}"/>')
        f.write('</svg>\n')

if __name__ == '__main__':
    generate()
