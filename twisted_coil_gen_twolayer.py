#!/usr/bin/env python3

import subprocess
import sys
import multiprocessing
import os
from math import *
from pathlib import Path
from itertools import cycle

from scipy.constants import mu_0
import numpy as np
import click
import matplotlib as mpl

from gerbonara.cad.kicad import pcb as kicad_pcb
from gerbonara.cad.kicad import footprints as kicad_fp
from gerbonara.cad.kicad import graphical_primitives as kicad_gr
from gerbonara.cad.kicad import primitives as kicad_pr
from gerbonara.utils import Tag
from gerbonara import graphic_primitives as gp
from gerbonara import graphic_objects as go


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


def traces_to_gmsh(traces, mesh_out, bbox, model_name='gerbonara_board', log=True, copper_thickness=0.035, board_thickness=0.8, air_box_margin=5.0):
    import gmsh
    occ = gmsh.model.occ
    eps = 1e-6

    board_thickness -= 2*copper_thickness

    gmsh.initialize()
    gmsh.model.add('gerbonara_board')
    if log:
        gmsh.logger.start()

    trace_tags = {}
    trace_ends = set()
    render_cache = {}
    for i, tr in enumerate(traces, start=1):
        layer = tr[1].layer
        z0 = 0 if layer == 'F.Cu' else -(board_thickness+copper_thickness)

        prims = [prim
                 for elem in tr
                 for obj in elem.render(cache=render_cache)
                 for prim in obj.to_primitives()]

        tags = []
        for prim in prims:
            if isinstance(prim, gp.Line):
                length = dist((prim.x1, prim.y1), (prim.x2, prim.y2))
                box_tag = occ.addBox(0, -prim.width/2, 0, length, prim.width, copper_thickness)
                angle = atan2(prim.y2 - prim.y1, prim.x2 - prim.x1)
                occ.rotate([(3, box_tag)], 0, 0, 0, 0, 0, 1, angle)
                occ.translate([(3, box_tag)], prim.x1, prim.y1, z0)
                tags.append(box_tag)

                for x, y in ((prim.x1, prim.y1), (prim.x2, prim.y2)):
                    disc_id = (round(x, 3), round(y, 3), round(z0, 3), round(prim.width, 3))
                    if disc_id  in trace_ends:
                        continue

                    trace_ends.add(disc_id)
                    cylinder_tag = occ.addCylinder(x, y, z0, 0, 0, copper_thickness, prim.width/2)
                    tags.append(cylinder_tag)
        print('fusing', tags)
        tags, tag_map = occ.fuse([(3, tags[0])], [(3, tag) for tag in tags[1:]])
        print(tags)
        assert len(tags) == 1
        (_dim, tag), = tags
        trace_tags[i] = tag

    (x1, y1), (x2, y2) = bbox
    substrate = occ.addBox(x1, y1, -board_thickness, x2-x1, y2-y1, board_thickness)

    x1, y1 = x1-air_box_margin, y1-air_box_margin
    x2, y2 = x2+air_box_margin, y2+air_box_margin
    w, d = x2-x1, y2-y1
    z0 = -board_thickness-air_box_margin
    ab_h = board_thickness + 2*air_box_margin
    airbox = occ.addBox(x1, y1, z0, w, d, ab_h)

    print('Cutting airbox')
    occ.cut([(3, airbox)], [(3, tag) for tag in trace_tags.values()], removeObject=True, removeTool=False)
    print('Fragmenting')
    fragment_tags, fragment_hierarchy = occ.fragment([(3, airbox)], [(3, substrate)] + [(3, tag) for tag in trace_tags.values()])

    print('Synchronizing')
    occ.synchronize()
    substrate_physical = gmsh.model.add_physical_group(3, [substrate], name='substrate')
    airbox_physical = gmsh.model.add_physical_group(3, [airbox], name='airbox')
    trace_physical_surfaces = [
            gmsh.model.add_physical_group(2, list(gmsh.model.getAdjacencies(3, tag)[1]), name=f'trace{i}')
            for i, tag in trace_tags.items()]
    
    airbox_adjacent = set(gmsh.model.getAdjacencies(3, airbox)[1])
    in_bbox = {tag for _dim, tag in gmsh.model.getEntitiesInBoundingBox(x1+eps, y1+eps, z0+eps, x1+w-eps, y1+d-eps, z0+ab_h-eps, dim=3)}
    airbox_physical_surface = gmsh.model.add_physical_group(2, list(airbox_adjacent - in_bbox), name='airbox_surface')
    
    points_airbox_adjacent = set(gmsh.model.getAdjacencies(0, airbox)[1])
    points_inside = {tag for _dim, tag in gmsh.model.getEntitiesInBoundingBox(x1+eps, y1+eps, z0+eps, x1+w-eps, y1+d-eps, z0+ab_h-eps, dim=0)}
    gmsh.model.mesh.setSize([(0, tag) for tag in points_airbox_adjacent - points_inside], 10e-3)

    #gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 90)
    gmsh.option.setNumber('Mesh.Smoothing', 10)
    gmsh.option.setNumber('Mesh.Algorithm3D', 10)
    gmsh.option.setNumber('Mesh.MeshSizeMax', 1)
    gmsh.option.setNumber('General.NumThreads', multiprocessing.cpu_count())

    print('Meshing')
    gmsh.model.mesh.generate(dim=3)
    print('Writing')
    gmsh.write(str(mesh_out))


def traces_to_gmsh_mag(traces, mesh_out, bbox, model_name='gerbonara_board', log=True, copper_thickness=0.035, board_thickness=0.8, air_box_margin_h=30.0, air_box_margin_v=80.0):
    import gmsh
    occ = gmsh.model.occ
    eps = 1e-6

    board_thickness -= 2*copper_thickness

    gmsh.initialize()
    gmsh.model.add('gerbonara_board')
    if log:
        gmsh.logger.start()

    trace_tags = []
    trace_ends = set()
    render_cache = {}
    first_disk, last_disk = None, None
    for i, tr in enumerate(traces, start=1):
        layer = tr[1].layer
        z0 = 0 if layer == 'F.Cu' else -(board_thickness+copper_thickness)

        objs = [obj
                 for elem in tr
                 for obj in elem.render(cache=render_cache)]

        tags = []
        for ob in objs:
            if isinstance(ob, go.Line):
                length = dist((ob.x1, ob.y1), (ob.x2, ob.y2))
                w = ob.aperture.equivalent_width('mm')
                box_tag = occ.addBox(0, -w/2, 0, length, w, copper_thickness)
                angle = atan2(ob.y2 - ob.y1, ob.x2 - ob.x1)
                occ.rotate([(3, box_tag)], 0, 0, 0, 0, 0, 1, angle)
                occ.translate([(3, box_tag)], ob.x1, ob.y1, z0)
                tags.append(box_tag)

                for x, y in ((ob.x1, ob.y1), (ob.x2, ob.y2)):
                    disc_id = (round(x, 3), round(y, 3), round(z0, 3), round(w, 3))
                    if disc_id  in trace_ends:
                        continue

                    trace_ends.add(disc_id)
                    cylinder_tag = occ.addCylinder(x, y, z0, 0, 0, copper_thickness, w/2)
                    tags.append(cylinder_tag)

                    if first_disk is None:
                        occ.synchronize()
                        adjacent = gmsh.model.getAdjacencies(3, cylinder_tag)
                        first_disk = adjacent
                    elif i == len(traces) and last_disk is None:
                        occ.synchronize()
                        adjacent = gmsh.model.getAdjacencies(3, cylinder_tag)
                        last_disk = adjacent
            
        for elem in tr:
            if isinstance(elem, kicad_pcb.Via):
                cylinder_tag = occ.addCylinder(elem.at.x, elem.at.y, 0, 0, 0, -board_thickness, elem.drill)
                tags.append(cylinder_tag)
                occ.synchronize()

        print('fusing', tags)
        tags, tag_map = occ.fuse([(3, tags[0])], [(3, tag) for tag in tags[1:]])
        print(tags)
        assert len(tags) == 1
        (_dim, tag), = tags
        trace_tags.append(tag)

    print('fusing top-level', trace_tags)
    tags, tag_map = occ.fuse([(3, trace_tags[0])], [(3, tag) for tag in trace_tags[1:]])
    print(tags)
    assert len(tags) == 1
    (_dim, toplevel_tag), = tags

    (x1, y1), (x2, y2) = bbox
    #print('first disk', first_disk)
    #print('bbox', [occ.getBoundingBox(2, tag) for tag in first_disk[1]])
    #print('last disk', last_disk)
    #print('bbox', [occ.getBoundingBox(2, tag) for tag in last_disk[1]])

    first_geom = traces[0][0]
    interface_tag_top = occ.addDisk(first_geom.start.x, first_geom.start.y, 0, first_geom.width/2, first_geom.width/2)
    interface_tag_bottom = occ.addDisk(first_geom.start.x, first_geom.start.y, -board_thickness, first_geom.width/2, first_geom.width/2)

    #occ.synchronize()
    #_, toplevel_adjacent = gmsh.model.getAdjacencies(3, toplevel_tag)

    #x0, y0, w = traces[0][0].start.x, traces[0][0].start.y, traces[0][0].width
    #print(x0, y0, w)
    #in_bbox = occ.getEntitiesInBoundingBox(x0-w/2-eps, y0-w/2-eps, -board_thickness-eps, x0+w/2+eps, y0+w/2+eps, eps, dim=1)
    #print('in bbox', in_bbox)
    #for dim, tag in in_bbox:
    #    print(tag, 'adjacent', gmsh.model.getAdjacencies(dim, tag))

    #print('fragment', occ.fragment([(2, tag) for tag in toplevel_adjacent], [(2, interface_tag_top), (2, interface_tag_bottom)]))

    substrate = occ.addBox(x1, y1, -board_thickness, x2-x1, y2-y1, board_thickness)

    x1, y1 = x1-air_box_margin_h, y1-air_box_margin_h
    x2, y2 = x2+air_box_margin_h, y2+air_box_margin_h
    w, d = x2-x1, y2-y1
    z0 = -board_thickness-air_box_margin_v
    ab_h = board_thickness + 2*air_box_margin_v
    airbox = occ.addBox(x1, y1, z0, w, d, ab_h)

    print('Fragmenting trace')
    print(occ.fragment([(3, toplevel_tag)], [(2, interface_tag_top), (2, interface_tag_bottom)], removeObject=True, removeTool=False))

    print('Fragmenting substrate')
    print(occ.cut([(3, substrate)], [(3, toplevel_tag)], removeObject=True, removeTool=False))
    print(occ.fragment([(3, substrate)], [(3, toplevel_tag), (2, interface_tag_top), (2, interface_tag_bottom)], removeObject=True, removeTool=False))

    print(f'Fragmenting airbox ({airbox}) with {toplevel_tag=} {substrate=} {interface_tag_top=} {interface_tag_bottom=}')
    print(occ.cut([(3, airbox)], [(3, toplevel_tag)], removeObject=True, removeTool=False))
    print(occ.fragment([(3, airbox)], [(3, toplevel_tag), (3, substrate), (2, interface_tag_top), (2, interface_tag_bottom)], removeObject=True, removeTool=False))

    #occ.fragment([(3, substrate)], [(2, interface_tag_top), (2, interface_tag_bottom)])
    #occ.fragment([(3, airbox)], [(3, substrate), (3, toplevel_tag)])

    print('Synchronizing')
    occ.synchronize()

    substrate_physical = gmsh.model.add_physical_group(3, [substrate], name='substrate')
    airbox_physical = gmsh.model.add_physical_group(3, [airbox], name='airbox')
    trace_physical = gmsh.model.add_physical_group(3, [toplevel_tag], name='trace')
    interface_top_physical = gmsh.model.add_physical_group(2, [interface_tag_top], name='interface_top')
    interface_bottom_physical = gmsh.model.add_physical_group(2, [interface_tag_bottom], name='interface_bottom')

    print('first disk', first_disk)
    print('bbox', occ.getBoundingBox(2, interface_tag_top))
    print('last disk', last_disk)
    print('bbox', occ.getBoundingBox(2, interface_tag_bottom))
    
    airbox_adjacent = set(gmsh.model.getAdjacencies(3, airbox)[1])
    in_bbox = {tag for _dim, tag in gmsh.model.getEntitiesInBoundingBox(x1+eps, y1+eps, z0+eps, x2-eps, y2-eps, z0+ab_h-eps, dim=2)}
    airbox_physical_surface = gmsh.model.add_physical_group(2, list(airbox_adjacent - in_bbox), name='airbox_surface')
    
    points_airbox_adjacent = {tag for _dim, tag in gmsh.model.getBoundary([(3, airbox)], recursive=True, oriented=False)}
    print(f'{points_airbox_adjacent=}')
    points_inside = {tag for _dim, tag in gmsh.model.getEntitiesInBoundingBox(x1+eps, y1+eps, z0+eps, x1+w-eps, y1+d-eps, z0+ab_h-eps, dim=0)}
    #gmsh.model.mesh.setSize([(0, tag) for tag in points_airbox_adjacent - points_inside], 300e-3)

    gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 32)
    gmsh.option.setNumber('Mesh.Smoothing', 10)
    gmsh.option.setNumber('Mesh.Algorithm3D', 10)
    gmsh.option.setNumber('Mesh.MeshSizeMax', 10)
    gmsh.option.setNumber('Mesh.MeshSizeMin', 0.08)
    gmsh.option.setNumber('General.NumThreads', multiprocessing.cpu_count())

    print('Meshing')
    gmsh.model.mesh.generate(dim=3)
    print('Writing to', str(mesh_out))
    gmsh.write(str(mesh_out))


def traces_to_magneticalc(traces, out, pcb_thickness=0.8):
    coords = []
    last_x, last_y, last_z = None, None, None
    def coord(x, y, z):
        nonlocal coords, last_x, last_y, last_z
        if (x, y, z) != (last_x, last_y, last_z):
            coords.append((x, y, z))

    render_cache = {}
    for tr in traces:
        z = pcb_thickness if tr[1].layer == 'F.Cu' else 0
        objs = [obj
                 for elem in tr
                 for obj in elem.render(cache=render_cache)
                 if isinstance(elem, (kicad_pcb.TrackSegment, kicad_pcb.TrackArc))]

        # start / switch layer
        coord(objs[0].x1, objs[0].y1, z)

        for ob in objs:
            coord(ob.x2, ob.y2, z)

    np.savetxt(out, np.array(coords) / 10) # magneticalc expects centimeters, not millimeters.


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


# https://en.wikipedia.org/wiki/Farey_sequence#Next_term
def farey_sequence(n: int, descending: bool = False) -> None:
    """Print the n'th Farey sequence. Allow for either ascending or descending."""
    a, b, c, d = 0, 1, 1, n
    if descending:
        a, c = 1, n - 1
    #print(f"{a}/{b}")
    yield a, b

    while c <= n and not descending or a > 0 and descending:
        k = (n + b) // d
        a, b, c, d = c, d, k * c - a, k * d - b
        #print(f"{a}/{b}")
        yield a, b


def divisors(n, max_b=10):
    for a, b in farey_sequence(n):
        if a == n and b < max_b:
            yield b
        if b == n and a < max_b:
            yield a


def print_valid_twists(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return

    print(f'Valid twist counts for {value} turns:', file=sys.stderr)
    for d in divisors(value, value):
        print(f'  {d}', file=sys.stderr)

    click.echo()
    ctx.exit()


@click.command()
@click.argument('outfile', required=False, type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--footprint-name', help="Name for the generated footprint. Default: Output file name sans extension.")
@click.option('--layer-pair', default='F.Cu,B.Cu', help="Target KiCad layer pair for the generated footprint, comma-separated. Default: F.Cu/B.Cu.")
@click.option('--turns', type=int, default=5, help='Number of turns')
@click.option('--pcb/--footprint', default=False, help='Generate a KiCad PCB instead of a footprint')
@click.option('--outer-diameter', type=float, default=50, help='Outer diameter [mm]')
@click.option('--inner-diameter', type=float, default=25, help='Inner diameter [mm]')
@click.option('--trace-width', type=float, default=None)
@click.option('--via-diameter', type=float, default=0.6)
@click.option('--via-drill', type=float, default=0.3)
@click.option('--via-offset', type=float, default=None, help='Radially offset vias from trace endpoints [mm]')
@click.option('--keepout-zone/--no-keepout-zone', default=True, help='Add a keepout are to the footprint (default: yes)')
@click.option('--keepout-margin', type=float, default=5, help='Margin between outside of coil and keepout area (mm, default: 5)')
@click.option('--twists', type=int, default=1, help='Number of twists per revolution. Note that this number must be co-prime to the number of turns. Run with --show-twists to list valid values. (default: 1)')
@click.option('--circle-segments', type=int, default=64, help='When not using arcs, the number of points to use for arc interpolation per 360 degrees.')
@click.option('--show-twists', callback=print_valid_twists, expose_value=False, type=int, is_eager=True, help='Calculate and show valid --twists counts for the given number of turns. Takes the number of turns as a value.')
@click.option('--clearance', type=float, default=None)
@click.option('--arc-tolerance', type=float, default=0.02)
@click.option('--mesh-out', type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--mag-mesh-out', type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--magneticalc-out', type=click.Path(writable=True, dir_okay=False, path_type=Path))
@click.option('--clipboard/--no-clipboard', help='Use clipboard integration (requires wl-clipboard)')
@click.option('--counter-clockwise/--clockwise', help='Direction of generated spiral. Default: clockwise when wound from the inside.')
@click.version_option()
def generate(outfile, turns, outer_diameter, inner_diameter, via_diameter, via_drill, via_offset, trace_width, clearance,
             footprint_name, layer_pair, twists, clipboard, counter_clockwise, keepout_zone, keepout_margin,
             arc_tolerance, pcb, mesh_out, magneticalc_out, circle_segments, mag_mesh_out):
    if 'WAYLAND_DISPLAY' in os.environ:
        copy, paste, cliputil = ['wl-copy'], ['wl-paste'], 'xclip'
    else:
        copy, paste, cliputil = ['xclip', '-i', '-sel', 'clipboard'], ['xclip', '-o', '-sel' 'clipboard'], 'wl-clipboard'

    if gcd(twists, turns) != 1:
        raise click.ClickException('For the geometry to work out, the --twists parameter must be co-prime to --turns, i.e. the two must have 1 as their greatest common divisor. You can print valid values for --twists by running this command with --show-twists [turns number].')

    if mesh_out and not pcb:
        raise click.ClickException('--pcb is required when --mesh-out is used.')

    if magneticalc_out and not pcb:
        raise click.ClickException('--pcb is required when --magneticalc-out is used.')

    outer_radius = outer_diameter/2
    inner_radius = inner_diameter/2
    turns_per_layer = turns/2

    sweeping_angle = 2*pi * turns_per_layer / twists
    spiral_pitch = (outer_radius-inner_radius) / turns_per_layer
    c1 = inner_radius
    c2 = inner_radius + spiral_pitch
    alpha1 = atan((outer_radius - inner_radius) / sweeping_angle / c1)
    alpha2 = atan((outer_radius - inner_radius) / sweeping_angle / c2)
    alpha = (alpha1+alpha2)/2
    projected_spiral_pitch = spiral_pitch*cos(alpha)

    if trace_width is None and clearance is None:
        trace_width = 0.15
        print(f'Warning: Defaulting to {trace_width:.2f} mm trace width.', file=sys.stderr)

    if trace_width is None:
        if clearance > projected_spiral_pitch:
            raise click.ClickException(f'Error: Given clearance of {clearance:.2f} mm is larger than the projected spiral pitch of {projected_spiral_pitch:.2f} mm. Reduce clearance or increase the size of the coil.')
        trace_width = projected_spiral_pitch - clearance
        print(f'Calculated trace width for {clearance:.2f} mm clearance is {trace_width:.2f} mm.', file=sys.stderr)

    elif clearance is None:
        if trace_width > projected_spiral_pitch:
            raise click.ClickException(f'Error: Given trace width of {trace_width:.2f} mm is larger than the projected spiral pitch of {projected_spiral_pitch:.2f} mm. Reduce clearance or increase the size of the coil.')
        clearance = projected_spiral_pitch - trace_width
        print(f'Calculated clearance for {trace_width:.2f} mm trace width is {clearance:.2f} mm.', file=sys.stderr)

    else:
        if trace_width > projected_spiral_pitch:
            raise click.ClickException(f'Error: Given trace width of {trace_width:.2f} mm is larger than the projected spiral pitch of {projected_spiral_pitch:.2f} mm. Reduce clearance or increase the size of the coil.')
        clearance_actual = projected_spiral_pitch - trace_width
        if clearance_actual < clearance:
            raise click.ClickException(f'Error: Actual clearance for {trace_width:.2f} mm trace is {clearance_actual:.2f} mm, which is lower than the given clearance of {clearance:.2f} mm.')

    if via_diameter < trace_width:
        print(f'Clipping via diameter from {via_diameter:.2f} mm to trace width of {trace_width:.2f} mm.', file=sys.stderr)
        via_diameter = trace_width

    if via_offset is None:
        via_offset = max(0, (via_diameter-trace_width)/2)
        print(f'Autocalculated via offset {via_offset:.2f} mm', file=sys.stderr)

    inner_via_ring_radius = inner_radius - via_offset
    #print(f'{inner_radius=} {via_offset=} {via_diameter=}', file=sys.stderr)
    inner_via_angle = 2*asin((via_diameter + clearance)/2 / inner_via_ring_radius)

    outer_via_ring_radius = outer_radius + via_offset
    outer_via_angle = 2*asin((via_diameter + clearance)/2 / outer_via_ring_radius)

    print(f'Inner via ring @r={inner_via_ring_radius:.2f} mm (from {inner_radius:.2f} mm)', file=sys.stderr)
    print(f'    {degrees(inner_via_angle):.1f} deg / via', file=sys.stderr)
    print(f'Outer via ring @r={outer_via_ring_radius:.2f} mm (from {outer_radius:.2f} mm)', file=sys.stderr)
    print(f'    {degrees(outer_via_angle):.1f} deg / via', file=sys.stderr)

    if inner_via_angle*twists > 2*pi:
        min_dia = 2*((via_diameter + clearance) / (2*sin(pi / twists)) + via_offset)
        raise click.ClickException(f'Error: Overlapping vias in inner via ring. Calculated minimum inner diameter is {min_dia:.2f} mm.')

    pitch = clearance + trace_width
    t, _, b = layer_pair.partition(',')
    layer_pair = (t.strip(), b.strip())
    rainbow = '#817 #a35 #c66 #e94 #ed0 #9d5 #4d8 #2cb #0bc #09c #36b #639'.split()
    rainbow = rainbow[2::3] + rainbow[1::3] + rainbow[0::3]
    n = 5
    rainbow = rainbow[n:] + rainbow[:n]
    out_paths = []
    svg_stuff = [*out_paths]


    # See https://coil32.net/pcb-coil.html for details

    d_avg = (outer_diameter + inner_diameter)/2
    phi = (outer_diameter - inner_diameter) / (outer_diameter + inner_diameter)
    c1, c2, c3, c4 = 1.00, 2.46, 0.00, 0.20
    L = mu_0 * turns**2 * d_avg*1e3 * c1 / 2 * (log(c2/phi) + c3*phi + c4*phi**2)
    print(f'Outer diameter: {outer_diameter:g} mm', file=sys.stderr)
    print(f'Average diameter: {d_avg:g} mm', file=sys.stderr)
    print(f'Inner diameter: {inner_diameter:g} mm', file=sys.stderr)
    print(f'Fill factor: {phi:g}', file=sys.stderr)
    print(f'Approximate inductance: {L:g} µH', file=sys.stderr)


    make_pad = lambda num, layer, x, y: kicad_fp.Pad(
            number=str(num),
            type=kicad_fp.Atom.smd,
            shape=kicad_fp.Atom.circle,
            at=kicad_fp.AtPos(x=x, y=y),
            size=kicad_fp.XYCoord(x=trace_width, y=trace_width),
            layers=layer,
            clearance=clearance,
            zone_connect=0)

    make_line = lambda x1, y1, x2, y2, layer: kicad_fp.Line(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                end=kicad_fp.XYCoord(x=x2, y=y2),
                layer=layer, 
                stroke=kicad_fp.Stroke(width=trace_width))

    make_arc = lambda x1, y1, x2, y2, xm, ym, layer: kicad_fp.Arc(
                start=kicad_fp.XYCoord(x=x1, y=y1),
                mid=kicad_fp.XYCoord(x=xm, y=ym),
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

    use_arcs = not pcb
    pads = []
    lines = []
    arcs = []

    def arc_approximate(points, layer, tolerance=0.02, level=0):
        indent = '    ' * level
        #print(f'{indent}arc_approximate {len(points)=}', file=sys.stderr)
        if len(points) < 3:
            raise ValueError()

        i_mid = len(points)//2

        x0, y0 = points[0]
        x1, y1 = points[i_mid]
        x2, y2 = points[-1]

        if len(points) < 5:
            #print(f'{indent} -> interp last points', file=sys.stderr)
            yield make_arc(x0, y0, x2, y2, x1, y1, layer)

        # https://stackoverflow.com/questions/56224824/how-do-i-find-the-circumcenter-of-the-triangle-using-python-without-external-lib
        d = 2 * (x0 * (y2 - y1) + x2 * (y1 - y0) + x1 * (y0 - y2))
        cx = ((x0 * x0 + y0 * y0) * (y2 - y1) + (x2 * x2 + y2 * y2) * (y1 - y0) + (x1 * x1 + y1 * y1) * (y0 - y2)) / d
        cy = ((x0 * x0 + y0 * y0) * (x1 - x2) + (x2 * x2 + y2 * y2) * (x0 - x1) + (x1 * x1 + y1 * y1) * (x2 - x0)) / d
        r = dist((cx, cy), (x1, y1))
        if any(abs(dist((px, py), (cx, cy)) - r) > tolerance for px, py in points):
            #print(f'{indent} -> split', file=sys.stderr)
            yield from arc_approximate(points[:i_mid+1], layer, tolerance, level+1)
            yield from arc_approximate(points[i_mid:], layer, tolerance, level+1)

        else:
            yield make_arc(x0, y0, x2, y2, x1, y1, layer)
            #print(f'{indent} -> good fit', file=sys.stderr)

    def do_spiral(layer, r1, r2, a1, a2, start_frac, end_frac, fn=64):
        fn = ceil(fn * (a2-a1)/(2*pi))
        x0, y0 = cos(a1)*r1, sin(a1)*r1
        direction = '↓' if r2 < r1 else '↑'
        dr = 3 if r2 < r1 else -3
        label = f'{direction} {degrees(a1):.0f}'
        svg_stuff.append(Tag('text',
                             [label],
                             x=str(x0 + cos(a1)*dr),
                             y=str(y0 + sin(a1)*dr),
                             text_anchor='middle',
                             style=f'font: 1px bold sans-serif; fill: {rainbow[layer%len(rainbow)]}'))

        xn, yn = x0, y0
        points = [(x0, y0)]
        dists = []
        for i in range(fn):
            r, g, b, _a = mpl.cm.plasma(start_frac + (end_frac - start_frac)/fn * (i + 0.5))
            path = SVGPath(fill='none', stroke=f'#{round(r*255):02x}{round(g*255):02x}{round(b*255):02x}', stroke_width=trace_width, stroke_linejoin='round', stroke_linecap='round')
            svg_stuff.append(path)
            xp, yp = xn, yn
            r = r1 + (i+1)*(r2-r1)/fn
            a = a1 + (i+1)*(a2-a1)/fn
            xn, yn = cos(a)*r, sin(a)*r
            path.move(xp, yp)
            path.line(xn, yn)
            points.append((xn, yn))
            dists.append(dist((xp, yp), (xn, yn)))
            if not use_arcs:
                lines.append(make_line(xp, yp, xn, yn, layer_pair[layer]))

        if use_arcs:
            arcs.extend(arc_approximate(points, layer_pair[layer], arc_tolerance))

        svg_stuff.append(Tag('text',
                             [label],
                             x=str(xn + cos(a2)*-dr),
                             y=str(yn + sin(a2)*-dr + 1.2),
                             text_anchor='middle',
                             style=f'font: 1px bold sans-serif; fill: {rainbow[layer%len(rainbow)]}'))

        return (x0, y0), (xn, yn), sum(dists)

    sector_angle = 2*pi / twists
    total_angle = twists*2*sweeping_angle

    inverse = {}
    for i in range(twists):
        inverse[i*turns%twists] = i

    svg_vias = []
    for i in range(twists):
        start_angle = i*sector_angle
        fold_angle = start_angle + sweeping_angle
        end_angle = fold_angle + sweeping_angle

        x = inverse[i]*floor(2*sweeping_angle / (2*pi)) * 2*pi
        (x0, y0), (xn, yn), clen = do_spiral(0, outer_radius, inner_radius, start_angle, fold_angle, (x + start_angle)/total_angle, (x + fold_angle)/total_angle, circle_segments)
        do_spiral(1, inner_radius, outer_radius, fold_angle, end_angle, (x + fold_angle)/total_angle, (x + end_angle)/total_angle)

        xv, yv = inner_via_ring_radius*cos(fold_angle), inner_via_ring_radius*sin(fold_angle)
        pads.append(make_via(xv, yv, layer_pair))
        if not isclose(via_offset, 0, abs_tol=1e-6):
            lines.append(make_line(xn, yn, xv, yv, layer_pair[0]))
            lines.append(make_line(xn, yn, xv, yv, layer_pair[1]))
        svg_vias.append(Tag('circle', cx=xv, cy=yv, r=via_diameter/2, stroke='none', fill='white'))
        svg_vias.append(Tag('circle', cx=xv, cy=yv, r=via_drill/2, stroke='none', fill='black'))

        if i > 0:
            xv, yv = outer_via_ring_radius*cos(start_angle), outer_via_ring_radius*sin(start_angle)
            pads.append(make_via(xv, yv, layer_pair))
            if not isclose(via_offset, 0, abs_tol=1e-6):
                lines.append(make_line(x0, y0, xv, yv, layer_pair[0]))
                lines.append(make_line(x0, y0, xv, yv, layer_pair[1]))
            svg_vias.append(Tag('circle', cx=xv, cy=yv, r=via_diameter/2, stroke='none', fill='white'))
            svg_vias.append(Tag('circle', cx=xv, cy=yv, r=via_drill/2, stroke='none', fill='black'))

    print(f'Approximate track length: {clen*twists*2:.2f} mm', file=sys.stderr)

    top_pad = make_pad(1, [layer_pair[0]], outer_radius, 0)
    pads.append(top_pad)
    bottom_pad = make_pad(2, [layer_pair[1]], outer_radius, 0)
    pads.append(bottom_pad)

    svg_stuff += svg_vias

    svg_stuff.append(Tag('path', d=f'M {inner_radius} 0 L {outer_radius} 0', stroke=rainbow[n+1], fill='none',
                         stroke_width='0.05mm', stroke_linecap='round'))
    ntraces = int(turns_per_layer)+1
    alpha = [0] * ntraces
    for i in range(ntraces):
        c = inner_radius + (outer_radius-inner_radius) / turns_per_layer * i
        #dalpha = dy / c
        #dx / dalpha = (outer_radius - inner_radius) / sweeping_angle
        #c * (dx / dy) = (outer_radius - inner_radius) / sweeping_angle
        #dx / dy = (outer_radius - inner_radius) / sweeping_angle / c
        dx = (outer_radius - inner_radius) / sweeping_angle / c
        alpha[i] = atan(dx)
        dy = 0.3
        dx *= dy
        r = trace_width/2 / cos(alpha[i])
        svg_stuff.append(Tag('path', d=f'M {c-r+dx} {-dy} L {c-r-dx} {dy}', stroke=rainbow[n+1], fill='none',
                             stroke_width='0.05mm', stroke_linecap='round'))
        svg_stuff.append(Tag('path', d=f'M {c+r+dx} {-dy} L {c+r-dx} {dy}', stroke=rainbow[n+1], fill='none',
                             stroke_width='0.05mm', stroke_linecap='round'))

        #print(f'spiral angle {degrees(alpha[i]):.2f}', file=sys.stderr)

    for i, (a1, a2) in enumerate(zip(alpha[::-1], alpha[1::])):
        amean = (a2+a1)/2
        pitch = (outer_radius - inner_radius) / turns_per_layer
        clearance = pitch - trace_width
        clearance *= cos(amean)

        x, y = inner_radius + (i + 1/2)*pitch, -0.5
        svg_stuff.append(Tag('text',
                             [f'{clearance:.5f}mm'],
                             x=x,
                             y=y,
                             text_anchor='start',
                             transform=f'rotate(-45 {x} {y})',
                             style=f'font: 1px bold sans-serif; fill: {rainbow[n+1]}'))

    svg_file('/tmp/test.svg', svg_stuff, 100, 100, -50, -50)

    if footprint_name:
        name = footprint_name
    elif outfile:
        name = outfile.stem,
    else:
        name = 'generated_coil'

    if keepout_zone:
        r = outer_diameter/2 + keepout_margin
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

    if pcb:
        obj = kicad_pcb.Board.empty_board(
                zones=zones,
                track_segments=[kicad_pcb.TrackSegment.from_footprint_line(line) for line in lines],
                vias=[kicad_pcb.Via.from_pad(pad) for pad in pads if pad.type == kicad_pcb.Atom.thru_hole])
        obj.rebuild_trace_index()
        seg = obj.track_segments[-1]
        traces = []
        end = top_pad
        layer = 'F.Cu'
        while True:
            tr = list(obj.find_connected_traces(end, layers=[layer]))
            traces.append(tr)
            if not isinstance(tr[-1], kicad_pcb.Via):
                break
            layer = 'B.Cu' if layer == 'F.Cu' else 'F.Cu'
            end = tr[-1]
        # remove start pad
        traces[0] = traces[0][1:]

        r = outer_diameter/2 + 20
        if mesh_out:
            traces_to_gmsh(traces, mesh_out, ((-r, -r), (r, r)))

        if mag_mesh_out:
            traces_to_gmsh_mag(traces, mag_mesh_out, ((-r, -r), (r, r)))

        if magneticalc_out:
            traces_to_magneticalc(traces, magneticalc_out)

#        for trace in traces:
#            print(f'Trace {i}', file=sys.stderr)
#            print(f'  Length: {len(trace)}', file=sys.stderr)
#            print(f'  Start: {trace[0]}', file=sys.stderr)
#            print(f'  End: {trace[-1]}', file=sys.stderr)
#            print(f'  Layer: {trace[1].layer}', file=sys.stderr)

        #for e in obj.find_connected_traces(seg, layers=seg.layer_mask):
        #    print(getattr(e, 'layer', ''), str(e)[:80], file=sys.stderr)
        #nodes, edges = obj.track_skeleton(pads[-1])
        #for node, node_edges in edges.items():
        #    print(f'Node {node} with {len(node_edges)} edges', file=sys.stderr)
        #    for i, e in enumerate(node_edges):
        #        print(f'    Edge {i}', file=sys.stderr)
        #        for elem in e:
        #            print('       ', elem, file=sys.stderr)

    else:
        obj = kicad_fp.Footprint(
                name=name,
                generator=kicad_fp.Atom('GerbonaraTwistedCoilGenV1'),
                layer='F.Cu',
                descr=f"{turns} turn {outer_diameter:.2f} mm diameter twisted coil footprint, inductance approximately {L:.6f} µH. Generated by gerbonara'c Twisted Coil generator, version {__version__}.",
                clearance=clearance,
                zone_connect=0,
                lines=lines,
                arcs=arcs,
                pads=pads,
                zones=zones,
                )

    if clipboard:
        try:
            data = obj.serialize()
            print(f'Running {copy[0]}.', file=sys.stderr)
            proc = subprocess.Popen(copy, stdin=subprocess.PIPE, text=True)
            proc.communicate(data)
            print('passed to wl-clip:', data)
        except FileNotFoundError:
            print(f'Error: --clipboard requires the {copy[0]} and {paste[0]} utilities from {cliputil} to be installed.', file=sys.stderr)
    elif not outfile:
        print(obj.serialize())
    else:
        obj.write(outfile)

if __name__ == '__main__':
    generate()
