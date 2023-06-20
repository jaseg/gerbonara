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

class SVGPath:
    def __init__(self, **attrs):
        self.d = ''
        self.attrs = attrs

    def line(self, x, y):
        self.d += f'L {x} {y} '

    def move(self, x, y):
        self.d += f'M {x} {y} '

    def arc(self, x, y, r, large, sweep):
        self.d += f'A {r} {r} 0 {int(large)} {int(sweep)} {x} {y} '

    def close(self):
        self.d += 'Z '

    def __str__(self):
        attrs = ' '.join(f'{key.replace("_", "-")}="{value}"' for key, value in self.attrs.items())
        return f'<path {attrs} d="{self.d.rstrip()}"/>'

class SVGCircle:
    def __init__(self, r, cx, cy, **attrs):
        self.r = r
        self.cx, self.cy = cx, cy
        self.attrs = attrs

    def __str__(self):
        attrs = ' '.join(f'{key.replace("_", "-")}="{value}"' for key, value in self.attrs.items())
        return f'<circle {attrs} r="{self.r}" cx="{self.cx}" cy="{self.cy}"/>'

def svg_file(fn, stuff, vbw, vbh, vbx=0, vby=0):
    with open(fn, 'w') as f:
        f.write('<?xml version="1.0" standalone="no"?>\n')
        f.write('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n')
        f.write(f'<svg version="1.1" width="{vbw}mm" height="{vbh}mm" viewBox="{vbx} {vby} {vbw} {vbh}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">>\n')

        for foo in stuff:
            f.write(str(foo))

        f.write('</svg>\n')

@click.command()
@click.argument('outfile', required=False, type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--footprint-name', help="Name for the generated footprint. Default: Output file name sans extension.")
@click.option('--target-layer', default='F.Cu', help="Target KiCad layer for the generated footprint. Default: F.Cu.")
@click.option('--jumper-layer', default='B.Cu', help="KiCad layer for jumper connections. Default: B.Cu.")
@click.option('--windings', type=int, default=5, help='Number of windings to generate')
@click.option('--diameter', type=float, default=50, help='Outer diameter')
@click.option('--trace-width', type=float, default=0.15)
@click.option('--via-diameter', type=float, default=0.6)
@click.option('--via-drill', type=float, default=0.3)
@click.option('--twist-width', type=float, default=20, help='Width of twist versus straight coil in percent (0-100, default: 20)')
@click.option('--num-twists', type=int, default=1, help='Number of twists per revolution (default: 1)')
@click.option('--clearance', type=float, default=0.15)
@click.option('--clipboard/--no-clipboard', help='Use clipboard integration (requires wl-clipboard)')
@click.option('--counter-clockwise/--clockwise', help='Direction of generated spiral. Default: clockwise when wound from the inside.')
def generate(outfile, windings, diameter, via_diameter, via_drill, trace_width, clearance, footprint_name, target_layer,
             jumper_layer, twist_width, num_twists, clipboard, counter_clockwise):
    if 'WAYLAND_DISPLAY' in os.environ:
        copy, paste, cliputil = ['wl-copy'], ['wl-paste'], 'xclip'
    else:
        copy, paste, cliputil = ['xclip', '-i', '-sel', 'clipboard'], ['xclip', '-o', '-sel' 'clipboard'], 'wl-clipboard'


    out_path = SVGPath(fill='none', stroke='black', stroke_width=trace_width, stroke_linejoin='round', stroke_linecap='round')
    jumper_path = SVGPath(fill='none', stroke='gray', stroke_width=trace_width, stroke_linejoin='round', stroke_linecap='round')
    svg_stuff = [jumper_path, out_path]

    pitch = clearance + trace_width
    twist_angle = 2*pi / (windings * num_twists - 1)
    twist_width = twist_angle * twist_width/100

    via_diameter = max(trace_width, via_diameter)

    make_pad = lambda num, x, y: kicad_fp.Pad(
            number=str(num),
            type=kicad_fp.Atom.smd,
            shape=kicad_fp.Atom.circle,
            at=kicad_fp.AtPos(x=x, y=y),
            size=kicad_fp.XYCoord(x=trace_width, y=trace_width),
            layers=[target_layer],
            clearance=clearance,
            zone_connect=0)

    make_line = lambda x1, y1, x2, y2, layer=target_layer: kicad_fp.Line(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                end=kicad_fp.XYCoord(x=x2, y=y2),
                layer=layer, 
                stroke=kicad_fp.Stroke(width=trace_width))

    make_arc = lambda x1, y1, x2, y2, xc, yc, layer=target_layer: kicad_fp.Arc(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                mid=kicad_fp.XYCoord(x=xc, y=yc),
                end=kicad_fp.XYCoord(x=x2, y=y2),
                layer=layer, 
                stroke=kicad_fp.Stroke(width=trace_width))


    make_via = lambda x, y: kicad_fp.Pad(number="NC",
                     type=kicad_fp.Atom.thru_hole,
                     shape=kicad_fp.Atom.circle,
                     at=kicad_fp.AtPos(x=x, y=y),
                     size=kicad_fp.XYCoord(x=via_diameter, y=via_diameter),
                     drill=kicad_fp.Drill(diameter=via_drill),
                     layers=[target_layer, jumper_layer],
                     clearance=clearance, 
                     zone_connect=0)

    pads = []
    lines = []
    arcs = []

    for n in range(windings * num_twists - 1):
        for k in range(windings):
            r = diameter/2 - trace_width/2 - k*pitch
            a1 = n*twist_angle + twist_width/2
            a2 = a1 + twist_angle - twist_width
            x1, y1 = r*cos(a1), r*sin(a1)
            out_path.move(x1, y1)
            x2, y2 = r*cos(a2), r*sin(a2)
            out_path.line(x2, y2)
            a3 = (a1 + a2) / 2
            xm, ym = r*cos(a3), r*sin(a3)
            arcs.append(make_arc(x2, y2, x1, y1, xm, ym))

        for k in range(windings-1):
            r1 = diameter/2 - trace_width/2 - (k+1)*pitch
            r2 = diameter/2 - trace_width/2 - k*pitch
            a1 = n*twist_angle - twist_width/2
            a2 = a1 + twist_width
            x1, y1 = r1*cos(a1), r1*sin(a1)
            out_path.move(x1, y1)
            x2, y2 = r2*cos(a2), r2*sin(a2)
            out_path.line(x2, y2)
            a3 = (a1 + a2) / 2
            r3 = (r1 + r2) / 2
            xm, ym = r3*cos(a3), r3*sin(a3)
            arcs.append(make_arc(x2, y2, x1, y1, xm, ym))

        rs = diameter/2 - trace_width/2 
        rv = rs - trace_width/2 + via_diameter/2
        a = n*twist_angle - twist_width/2

        x1, y1 = rs*cos(a), rs*sin(a)
        out_path.move(x1, y1)
        xv1, yv1 = rv*cos(a), rv*sin(a)
        out_path.line(xv1, yv1)
        svg_stuff.append(SVGCircle(via_diameter/2, xv1, yv1, fill='red'))
        pads.append(make_via(xv1, yv1))
        jumper_path.move(xv1, yv1)
        lines.append(make_line(x1, y1, xv1, yv1))

        a += twist_width
        rs = diameter/2 - trace_width/2 - (windings-1)*pitch
        rv = rs + trace_width/2 - via_diameter/2

        x1, y1 = rs*cos(a), rs*sin(a)
        out_path.move(x1, y1)
        xv2, yv2 = rv*cos(a), rv*sin(a)
        out_path.line(xv2, yv2)
        svg_stuff.append(SVGCircle(via_diameter/2, xv2, yv2, fill='red'))
        pads.append(make_via(xv2, yv2))
        lines.append(make_line(x1, y1, xv2, yv2))

        if n > 0:
            jumper_path.line(xv2, yv2)
            lines.append(make_line(xv1, yv1, xv2, yv2, jumper_layer))
        else:
            pads.append(make_pad(1, xv1, yv1))
            pads.append(make_pad(2, xv2, yv2))

    svg_file('/tmp/test.svg', svg_stuff, 100, 100, -50, -50)

    if counter_clockwise:
        for p in pads:
            p.at.y = -p.at.y

        for l in lines:
            l.start.y = -l.start.y
            l.end.y = -l.end.y

        for a in arcs:
            a.start.y = -a.start.y
            a.end.y = -a.end.y

    if footprint_name:
        name = footprint_name
    elif outfile:
        name = outfile.stem,
    else:
        name = 'generated_coil'

    fp = kicad_fp.Footprint(
            name=name,
            generator=kicad_fp.Atom('GerbonaraTwistedCoilGenV1'),
            layer='F.Cu',
            descr=f"{windings} winding twisted coil footprint generated by gerbonara'c Twisted Coil generator, version {__version__}",
            clearance=clearance,
            zone_connect=0,
            lines=lines,
            arcs=arcs,
            pads=pads,
            )

    if clipboard:
        try:
            print(f'Running {copy[0]}.')
            proc = subprocess.Popen(copy, stdin=subprocess.PIPE, text=True)
            proc.communicate(fp.serialize())
        except FileNotFoundError:
            print(f'Error: --clipboard requires the {copy[0]} and {paste[0]} utilities from {cliputil} to be installed.', file=sys.stderr)
    elif not outfile:
        print(fp.serialize())
    else:
        fp.write(outfile)

if __name__ == '__main__':
    generate()
