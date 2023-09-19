#!/usr/bin/env python3

import subprocess
import sys
import os
from math import *
from pathlib import Path
from itertools import cycle
from scipy.constants import mu_0

from gerbonara.cad.kicad import pcb as kicad_pcb
from gerbonara.cad.kicad import footprints as kicad_fp
from gerbonara.cad.kicad import graphical_primitives as kicad_gr
from gerbonara.cad.kicad import primitives as kicad_pr
from gerbonara.utils import Tag
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
        f.write(f'<svg version="1.1" width="{vbw*4}mm" height="{vbh*4}mm" viewBox="{vbx} {vby} {vbw} {vbh}" style="background-color: #333" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">>\n')

        for foo in stuff:
            f.write(str(foo))

        f.write('</svg>\n')

@click.command()
@click.argument('outfile', required=False, type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--footprint-name', help="Name for the generated footprint. Default: Output file name sans extension.")
@click.option('--target-layers', default='F.Cu,B.Cu', help="Target KiCad layers for the generated footprint. Default: F.Cu,B.Cu.")
@click.option('--turns', type=int, default=5, help='Number of turns')
@click.option('--diameter', type=float, default=50, help='Outer diameter [mm]')
@click.option('--trace-width', type=float, default=0.15)
@click.option('--via-diameter', type=float, default=0.6)
@click.option('--via-drill', type=float, default=0.3)
@click.option('--keepout-zone/--no-keepout-zone', default=True, help='Add a keepout are to the footprint (default: yes)')
@click.option('--keepout-margin', type=float, default=5, help='Margin between outside of coil and keepout area (mm, default: 5)')
@click.option('--num-twists', type=int, default=1, help='Number of twists per revolution (default: 1)')
@click.option('--clearance', type=float, default=0.15)
@click.option('--clipboard/--no-clipboard', help='Use clipboard integration (requires wl-clipboard)')
@click.option('--counter-clockwise/--clockwise', help='Direction of generated spiral. Default: clockwise when wound from the inside.')
def generate(outfile, turns, diameter, via_diameter, via_drill, trace_width, clearance, footprint_name, target_layers,
             num_twists, clipboard, counter_clockwise, keepout_zone, keepout_margin):
    if 'WAYLAND_DISPLAY' in os.environ:
        copy, paste, cliputil = ['wl-copy'], ['wl-paste'], 'xclip'
    else:
        copy, paste, cliputil = ['xclip', '-i', '-sel', 'clipboard'], ['xclip', '-o', '-sel' 'clipboard'], 'wl-clipboard'


    pitch = clearance + trace_width
    target_layers = [name.strip() for name in target_layers.split(',')]
    via_diameter = max(trace_width, via_diameter)
    rainbow = '#817 #a35 #c66 #e94 #ed0 #9d5 #4d8 #2cb #0bc #09c #36b #639'.split()
    rainbow = rainbow[2::3] + rainbow[1::3] + rainbow[0::3]
    out_paths = [SVGPath(fill='none', stroke=rainbow[i%len(rainbow)], stroke_width=trace_width, stroke_linejoin='round', stroke_linecap='round') for i in range(len(target_layers))]
    svg_stuff = [*out_paths]


    # See https://coil32.net/pcb-coil.html for details

    d_inside  = diameter - 2*(pitch*turns - clearance)
    d_avg = (diameter + d_inside)/2
    phi = (diameter - d_inside) / (diameter + d_inside)
    c1, c2, c3, c4 = 1.00, 2.46, 0.00, 0.20
    L = mu_0 * turns**2 * d_avg*1e3 * c1 / 2 * (log(c2/phi) + c3*phi + c4*phi**2)
    print(f'Outer diameter: {diameter:g} mm', file=sys.stderr)
    print(f'Average diameter: {d_avg:g} mm', file=sys.stderr)
    print(f'Inner diameter: {d_inside:g} mm', file=sys.stderr)
    print(f'Fill factor: {phi:g}', file=sys.stderr)
    print(f'Approximate inductance: {L:g} µH', file=sys.stderr)


    make_pad = lambda num, x, y: kicad_fp.Pad(
            number=str(num),
            type=kicad_fp.Atom.smd,
            shape=kicad_fp.Atom.circle,
            at=kicad_fp.AtPos(x=x, y=y),
            size=kicad_fp.XYCoord(x=trace_width, y=trace_width),
            layers=[target_layer],
            clearance=clearance,
            zone_connect=0)

    make_line = lambda x1, y1, x2, y2, layer: kicad_fp.Line(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                end=kicad_fp.XYCoord(x=x2, y=y2),
                layer=layer, 
                stroke=kicad_fp.Stroke(width=trace_width))

    make_arc = lambda x1, y1, x2, y2, xc, yc, layer: kicad_fp.Arc(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                mid=kicad_fp.XYCoord(x=xc, y=yc),
                end=kicad_fp.XYCoord(x=x2, y=y2),
                layer=layer, 
                stroke=kicad_fp.Stroke(width=trace_width))


    make_via = lambda x, y, layers: kicad_fp.Pad(number="NC",
                     type=kicad_fp.Atom.thru_hole,
                     shape=kicad_fp.Atom.circle,
                     at=kicad_fp.AtPos(x=x, y=y),
                     size=kicad_fp.XYCoord(x=via_diameter, y=via_diameter),
                     drill=kicad_fp.Drill(diameter=via_drill),
                     layers=layers,
                     clearance=clearance, 
                     zone_connect=0)

    pads = []
    lines = []
    arcs = []
    turns_per_layer = ceil((turns-1) / len(target_layers))
    print(f'Splitting {turns} turns into {len(target_layers)} layers using {turns_per_layer} turns per layer plus one weaving turn.', file=sys.stderr)
    sector_angle = 2*pi / turns_per_layer
    ### DELETE THIS:
    d_inside = diameter/2 # FIXME DEBUG
    ###

    def do_spiral(path, r1, r2, a1, a2, layer, fn=64):
        x0, y0 = cos(a1)*r1, sin(a1)*r1
        path.move(x0, y0)
        direction = '↓' if r2 < r1 else '↑'
        dr = 3 if r2 < r1 else -3
        label = f'{direction} {degrees(a1):.0f}'
        svg_stuff.append(Tag('text',
                             [label],
                             x=str(x0 + cos(a1)*dr),
                             y=str(y0 + sin(a1)*dr),
                             style=f'font: 1px bold sans-serif; fill: {path.attrs["stroke"]}'))

        for i in range(fn+1):
            r = r1 + i*(r2-r1)/fn
            a = a1 + i*(a2-a1)/fn
            xn, yn = cos(a)*r, sin(a)*r
            path.line(xn, yn)

        svg_stuff.append(Tag('text',
                             [label],
                             x=str(xn + cos(a2)*-dr),
                             y=str(yn + sin(a2)*-dr + 1.2),
                             style=f'font: 1px bold sans-serif; fill: {path.attrs["stroke"]}'))


    print(f'{turns=} {turns_per_layer=} {len(target_layers)=}', file=sys.stderr)

    start_radius = d_inside/2
    end_radius = diameter/2

    inner_via_ring_radius = start_radius - via_diameter/2
    inner_via_angle = 2*asin(via_diameter/2 / inner_via_ring_radius)

    outer_via_ring_radius = end_radius + via_diameter/2
    outer_via_angle = 2*asin(via_diameter/2 / outer_via_ring_radius)
    print(f'inner via ring @ {inner_via_ring_radius:.2f} mm (from {start_radius:.2f} mm)', file=sys.stderr)
    print(f'    {degrees(inner_via_angle):.1f} deg / via', file=sys.stderr)
    print(f'outer via ring @ {outer_via_ring_radius:.2f} mm (from {end_radius:.2f} mm)', file=sys.stderr)
    print(f'    {degrees(outer_via_angle):.1f} deg / via', file=sys.stderr)

    for n in range(turns-1):
        layer_n = n % len(target_layers)
        layer = target_layers[layer_n]
        layer_turn = floor(n / len(target_layers))
        print(f'    {layer_n=} {layer_turn=}', file=sys.stderr)

        start_angle = sector_angle * (layer_turn - layer_n / len(target_layers))
        end_angle = start_angle + (turns_per_layer + 1/len(target_layers)) * sector_angle

        if layer_n % 2 == 1:
            start_radius, end_radius = end_radius, start_radius

        do_spiral(out_paths[layer_n], start_radius, end_radius, start_angle, end_angle, layer_n)

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

    if keepout_zone:
        r = diameter/2 + keepout_margin
        tol = 0.05 # mm
        n = ceil(pi / acos(1 - tol/r))
        pts = [(r*cos(a*2*pi/n), r*sin(a*2*pi/n)) for a in range(n)]
        zones = [kicad_pr.Zone(layers=['*.Cu'],
            hatch=kicad_pr.Hatch(),
            filled_areas_thickness=False,
            keepout=kicad_pr.ZoneKeepout(copperpour_allowed=False),
            polygon=kicad_pr.ZonePolygon(pts=kicad_pr.PointList(xy=[kicad_pr.XYCoord(x=x, y=y) for x, y in pts])))]
    else:
        zones = []

    fp = kicad_fp.Footprint(
            name=name,
            generator=kicad_fp.Atom('GerbonaraTwistedCoilGenV1'),
            layer='F.Cu',
            descr=f"{turns} turn {diameter:.2f} mm diameter twisted coil footprint, inductance approximately {L:.6f} µH. Generated by gerbonara'c Twisted Coil generator, version {__version__}.",
            clearance=clearance,
            zone_connect=0,
            lines=lines,
            arcs=arcs,
            pads=pads,
            zones=zones,
            )

    if clipboard:
        try:
            print(f'Running {copy[0]}.', file=sys.stderr)
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
