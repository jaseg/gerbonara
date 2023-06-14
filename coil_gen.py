#!/usr/bin/env python3

import subprocess
import sys
import os
from math import *
from pathlib import Path
from itertools import cycle

from gerbonara.cad.kicad import pcb as kicad_pcb
from gerbonara.cad.kicad import footprints as kicad_fp
from gerbonara.cad.kicad import graphical_primitives as kicad_gr
import click


__version__ = '1.0.0'


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

def angle_between_vectors(va, vb):
    angle = atan2(vb[1], vb[0]) - atan2(va[1], va[0])
    if angle < 0:
        angle += 2*pi
    return angle


@click.command()
@click.argument('infile', required=False, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('outfile', required=False, type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--footprint-name', help="Name for the generated footprint. Default: Output file name sans extension.")
@click.option('--target-layer', default='F.Cu', help="Target KiCad layer for the generated footprint. Default: F.Cu.")
@click.option('--polygon', type=int, default=0, help="Use n'th polygon instead of first one. 0-based index.")
@click.option('--start-angle', type=float, default=0, help='Angle for the start at the outermost layer of the spiral in degree')
@click.option('--windings', type=int, default=5, help='Number of windings to generate')
@click.option('--trace-width', type=float, default=0.15)
@click.option('--clearance', type=float, default=0.15)
@click.option('--clipboard/--no-clipboard', help='Use clipboard integration (requires wl-clipboard)')
@click.option('--counter-clockwise/--clockwise', help='Direction of generated spiral. Default: clockwise when wound from the inside.')
def generate(infile, outfile, polygon, start_angle, windings, trace_width, clearance, footprint_name, target_layer, clipboard, counter_clockwise):
    if 'WAYLAND_DISPLAY' in os.environ:
        copy, paste, cliputil = ['wl-copy'], ['wl-paste'], 'xclip'
    else:
        copy, paste, cliputil = ['xclip', '-i', '-sel', 'clipboard'], ['xclip', '-o', '-sel' 'clipboard'], 'wl-clipboard'

    if clipboard:
        try:
            proc = subprocess.run(paste, capture_output=True, text=True, check=True)
        except FileNotFoundError:
            print(f'Error: --clipboard requires the {copy[0]} and {paste[0]} utilities from {cliputil} to be installed.', file=sys.stderr)
        board = kicad_pcb.Board.load(proc.stdout)
    elif not infile:
        board = kicad_pcb.Board.load(sys.stdin.read())
    else:
        board = kicad_pcb.Board.open(infile)

    objs = [obj for obj in board.objects() if isinstance(obj, kicad_gr.Polygon)]
    print(f'Found {len(objs)} polygon(s).', file=sys.stderr)
    poly = objs[polygon]
    xy = [(pt.x, pt.y) for pt in poly.pts.xy]

    if counter_clockwise:
        xy = [(-x, y) for x, y in xy]

    segments = list(zip(xy, xy[1:] + xy[:1]))

    # normalize orientation, make xy counter-clockwise
    if sum((x2 - x1) * (y2 + y1) for (x1, y1), (x2, y2) in segments) < 0:
        print(f'Reversing polygon direction.', file=sys.stderr)
        xy = xy[::-1]
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

    segment_heights = [point_line_distance((cx, cy), (x1, y1), (x2, y2)) for (x1, y1), (x2, y2) in segments]
    segment_foo = list(zip(segment_heights, segments))

    midpoints = []
    for h, ((x1, y1), (x2, y2)) in segment_foo:
        xb = (x1 + x2) / 2
        yb = (y1 + y2) / 2
        midpoints.append((xb, yb))

    normals = []
    for h, ((x1, y1), (x2, y2)) in segment_foo:
        d12 = dist((x1, y1), (x2, y2))
        dx = x2 - x1
        dy = y2 - y1
        normals.append((-dy/d12, dx/d12))

    smallest_radius = min(segment_heights)
    #trace_radius = smallest_radius - stop_radius
    trace_radius = smallest_radius

    segment_foo = list(zip(segment_heights, segments, segment_angles, midpoints, normals))

    dbg_lines1, dbg_lines2 = [], []
    spiral_points = []
    dr_tot = trace_width/2
    for n in range(windings):
        for (ha, (pa1, pa2), aa, ma, na), (hb, (pb1, pb2), ab, mb, nb) in zip(segment_foo[-1:] + segment_foo[:-1], segment_foo):
            pitch = clearance + trace_width
            dr_tot_a = dr_tot
            dr_tot_b = n * pitch + trace_width/2

            xma, yma = ma
            xna, yna = na
            xmb, ymb = mb
            xnb, ynb = nb

            xa1, ya1 = pa1
            xa2, ya2 = pa2
            xb1, yb1 = pb1
            xb2, yb2 = pb2

            dma = dist(pa2, ma)
            dmb = dist(pb1, mb)

            x_cons_a, y_cons_a = p_cons_a = line_line_intersection((pa2, (cx, cy)), (ma, (xma-xna, yma-yna)))
            d_cons_a = dist(p_cons_a, ma)
            qa = dma * dr_tot_a / d_cons_a
            dra = hypot(qa, dr_tot_a)

            nrax = (xa2 - cx) / dist((cx, cy), pa2)
            nray = (ya2 - cy) / dist((cx, cy), pa2)

            xea = xa2 - nrax*dra
            yea = ya2 - nray*dra

            x_cons_b, y_cons_b = p_cons_b = line_line_intersection((pb1, (cx, cy)), (mb, (xmb-xnb, ymb-ynb)))
            d_cons_b = dist(p_cons_b, mb)
            qb = dmb * dr_tot_b / d_cons_b
            drb = hypot(qb, dr_tot_b)

            nrbx = (xb1 - cx) / dist((cx, cy), pb1)
            nrby = (yb1 - cy) / dist((cx, cy), pb1)

            xeb = xb1 - nrbx*drb
            yeb = yb1 - nrby*drb

            xsa = xma - xna*dr_tot_a
            ysa = yma - yna*dr_tot_a

            xsb = xmb - xnb*dr_tot_b
            ysb = ymb - ynb*dr_tot_b

            l1 = (xsa, ysa), (xea, yea)
            l2 = (xsb, ysb), (xeb, yeb)

            dbg_lines1.append(l1)
            dbg_lines2.append(l2)

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

    out = [spiral_points[0]]
    ndrop = 0
    for i, (pa, pb, pc) in enumerate(zip(spiral_points, spiral_points[1:], spiral_points[2:])):
        xa, ya = pa
        xb, yb = pb
        xc, yc = pc
        if ndrop:
            ndrop -= 1
            continue

        angle = angle_between_vectors((xa-xb, ya-yb), (xc-xb, yc-yb))
        if angle > pi:
            ndrop += 1
            for pd, pe in zip(spiral_points[i+2:], spiral_points[i+3:]):
                xd, yd = pd
                xe, ye = pe
                angle = angle_between_vectors((xa-xb, ya-yb), (xe-xd, ye-yd))
                if angle > pi:
                    ndrop += 1
                else:
                    out.append(line_line_intersection((pa, pb), (pd, pe)))
                    break

        else:
            out.append(pb)
    spiral_points = out

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

        for (x1, y1), (x2, y2) in dbg_lines1:
            f.write(f'<path fill="none" stroke="#ff0000" opacity="0.2" stroke-width="0.05" d="M {x1} {y1} L {x2} {y2}"/>')

        for (x1, y1), (x2, y2) in dbg_lines2:
            f.write(f'<path fill="none" stroke="#0000ff" opacity="0.2" stroke-width="0.05" d="M {x1} {y1} L {x2} {y2}"/>')

        for x, y in midpoints:
            f.write(f'<path fill="none" stroke="#a0a0ff" stroke-width="0.05" d="M {cx} {cy} L {x} {y}"/>')
            f.write(f'<circle r="0.1" fill="blue" stroke="none" cx="{x}" cy="{y}"/>\n')

        f.write(f'<circle r="0.1" fill="red" stroke="none" cx="{cx}" cy="{cy}"/>\n')
        f.write('</svg>\n')

    if counter_clockwise:
        spiral_points = [(-x, y) for x, y in spiral_points]

    fp_lines = [
            kicad_fp.Line(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                end=kicad_fp.XYCoord(x=x2, y=y2),
                layer=target_layer, 
                stroke=kicad_fp.Stroke(width=trace_width))
            for (x1, y1), (x2, y2) in zip(spiral_points, spiral_points[1:])]

    make_pad = lambda num, x, y: kicad_fp.Pad(
            number=str(num),
            type=kicad_fp.Atom.smd,
            shape=kicad_fp.Atom.circle,
            at=kicad_fp.AtPos(x=x, y=y),
            size=kicad_fp.XYCoord(x=trace_width, y=trace_width),
            layers=[target_layer],
            clearance=clearance,
            zone_connect=0,
            )

    if footprint_name:
        name = footprint_name
    elif outfile:
        name = outfile.stem,
    else:
        name = 'generated_coil'

    fp = kicad_fp.Footprint(
            name=name,
            generator=kicad_fp.Atom('GerbonaraCoilGenV1'),
            layer='F.Cu',
            descr=f"{windings} winding coil footprint generated by gerbonara'c Coil generator, version {__version__}",
            clearance=clearance,
            zone_connect=0,
            lines=fp_lines,
            pads=[make_pad(1, *spiral_points[0]), make_pad(2, *spiral_points[-1])],
            )

    if clipboard:
        try:
            print(f'Running {copy[0]}. Press Ctrl+C when you are done pasting.')
            subprocess.run(copy, capture_output=True, text=True, check=True, input=fp.serialize())
        except FileNotFoundError:
            print(f'Error: --clipboard requires the {copy[0]} and {paste[0]} utilities from {cliputil} to be installed.', file=sys.stderr)
    elif not outfile:
        print(fp.serialize())
    else:
        fp.write(outfile)

if __name__ == '__main__':
    generate()
