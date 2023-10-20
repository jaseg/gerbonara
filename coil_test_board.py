#!/usr/bin/env python3

import math
import hashlib
import re
import itertools
import datetime
import tempfile
import subprocess
import sqlite3
import json
from pathlib import Path

import tqdm

import gerbonara.cad.kicad.pcb as pcb
import gerbonara.cad.kicad.footprints as fp
import gerbonara.cad.primitives as cad_pr
import gerbonara.cad.kicad.graphical_primitives as kc_gr


cols = 5
rows = 5

coil_specs = [
        {'n':  1, 's':  True, 't': 1, 'c': 0.20, 'w': 5.00, 'd': 3.00, 'v': 5.00},
        {'n':  2, 's':  True, 't': 1, 'c': 0.20, 'w': 3.00, 'd': 1.50, 'v': 3.00},
        {'n':  3, 's':  True, 't': 1, 'c': 0.20, 'w': 1.50, 'd': 1.20, 'v': 2.00},
        {'n':  5, 's':  True, 't': 1, 'c': 0.20, 'w': 0.80, 'd': 0.40, 'v': 0.80},
        {'n': 10, 's':  True, 't': 1, 'c': 0.20, 'w': 0.50, 'd': 0.30, 'v': 0.60},
        {'n': 25, 's':  True, 't': 1, 'c': 0.15, 'w': 0.25, 'd': 0.30, 'v': 0.60},

        {'n':  1, 's': False, 't': 3, 'c': 0.20, 'w': 5.00, 'd': 3.00, 'v': 5.00},
        {'n':  2, 's': False, 't': 1, 'c': 0.20, 'w': 3.00, 'd': 1.50, 'v': 3.00},
        {'n':  3, 's': False, 't': 1, 'c': 0.20, 'w': 2.50, 'd': 1.20, 'v': 2.00},
        {'n':  5, 's': False, 't': 1, 'c': 0.20, 'w': 2.50, 'd': 1.20, 'v': 0.80},
        {'n': 10, 's': False, 't': 1, 'c': 0.20, 'w': 1.50, 'd': 0.80, 'v': 0.60},
        {'n': 25, 's': False, 't': 1, 'c': 0.15, 'w': 0.50, 'd': 0.30, 'v': 0.60},

        {'n':  1, 's': False, 't': 4, 'c': 0.20, 'w': 5.00, 'd': 3.00, 'v': 5.00},
        {'n':  2, 's': False, 't': 3, 'c': 0.20, 'w': 3.00, 'd': 1.50, 'v': 3.00},
        {'n':  3, 's': False, 't': 4, 'c': 0.20, 'w': 2.50, 'd': 1.20, 'v': 2.00},
        {'n':  5, 's': False, 't': 3, 'c': 0.20, 'w': 2.50, 'd': 1.20, 'v': 0.80},
        {'n': 10, 's': False, 't': 3, 'c': 0.20, 'w': 1.50, 'd': 0.80, 'v': 0.60},
        {'n': 25, 's': False, 't': 3, 'c': 0.15, 'w': 0.50, 'd': 0.30, 'v': 0.60},

        {'n':  1, 's': False, 't': 5, 'c': 0.20, 'w': 5.00, 'd': 3.00, 'v': 5.00},
        {'n':  2, 's': False, 't': 5, 'c': 0.20, 'w': 3.00, 'd': 1.50, 'v': 3.00},
        {'n':  3, 's': False, 't': 4, 'c': 0.20, 'w': 2.50, 'd': 1.20, 'v': 2.00},
        {'n':  5, 's': False, 't': 7, 'c': 0.20, 'w': 2.50, 'd': 1.20, 'v': 0.80},
        {'n': 10, 's': False, 't': 7, 'c': 0.20, 'w': 1.50, 'd': 0.80, 'v': 0.60},
        {'n': 25, 's': False, 't': 13, 'c': 0.15, 'w': 0.50, 'd': 0.30, 'v': 0.60},

        {'n': 25, 's': False, 't': 37, 'c': 0.15, 'w': 0.50, 'd': 0.30, 'v': 0.60},
]

cachedir = Path('/tmp/coil_test_cache')
version_string = 'v1.0'
coil_border = 7 # mm
cut_gap = 8 # mm
tooling_border = 10 # mm
vscore_extra = 10 # mm
mouse_bite_width = 8 # mm
mouse_bite_yoff = 0.175
mouse_bite_hole_dia = 0.7
mouse_bite_hole_spacing = 0.7
hole_offset = 5
hole_dia = 3.2
coil_dia = 35 # mm
coil_inner_dia = 15 # mm
board_thickness = 0.80 # mm
pad_offset = 2 # mm
pad_dia = 2.0 # mm
pad_length = 3.5 # mm
pad_drill = 1.1 # mm
pad_pitch = 2.54 # mm
join_trace_w = 0.150 # mm
do_v_cuts = False
do_mouse_bites = False
do_cut_gaps = False

db = sqlite3.connect('coil_parameters.sqlite3')
db.execute('CREATE TABLE IF NOT EXISTS runs (run_id INTEGER PRIMARY KEY, timestamp TEXT, version TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS coils (coil_id INTEGER PRIMARY KEY, run_id INTEGER, FOREIGN KEY (run_id) REFERENCES runs(run_id))')
db.execute('CREATE TABLE IF NOT EXISTS results (result_id INTEGER PRIMARY KEY, coil_id INTEGER, key TEXT, value TEXT, FOREIGN KEY (coil_id) REFERENCES coils(coil_id))')
cur = db.cursor()
cur.execute('INSERT INTO runs(timestamp, version) VALUES (datetime("now"), ?)', (version_string,))
run_id = cur.lastrowid
db.commit()

tile_width = tile_height = coil_dia + 2*coil_border
coil_pitch_v = tile_width + cut_gap
coil_pitch_h = tile_height + cut_gap

total_width = coil_pitch_h*cols + 2*tooling_border + cut_gap
total_height = coil_pitch_v*rows + 2*tooling_border + cut_gap

drawing_text_size = 2.0

print(f'Calculated board size: {total_width:.2f} * {total_height:.2f} mm')
print(f'Tile size: {tile_height:.2f} * {tile_height:.2f} mm')

x0, y0 = 100, 100

xy = pcb.XYCoord
b = pcb.Board.empty_board(page=pcb.PageSettings(page_format='A2'))

b.add(kc_gr.Rectangle(xy(x0, y0), xy(x0+total_width, y0+total_height), layer='Edge.Cuts', stroke=pcb.Stroke(width=0.15)))

def do_line(x0, y0, x1, y1, off_x=0, off_y=0):
    b.add(kc_gr.Line(xy(x0+off_x, y0+off_y),
                     xy(x1+off_x, y1+off_y),
                     layer='Edge.Cuts', stroke=pcb.Stroke(width=0.15)))

if do_v_cuts:
    for y in range(rows):
        for off_y in [0, tile_height]:
            y_pos = y0 + tooling_border + cut_gap + off_y + y*coil_pitch_v
            do_line(x0 - vscore_extra, y_pos, x0 + total_width + vscore_extra, y_pos)
            b.add(kc_gr.Text(text='V-score',
                             at=pcb.AtPos(x0 + total_width + vscore_extra + drawing_text_size/2, y_pos, 0),
                             layer=kc_gr.TextLayer('Edge.Cuts'),
                             effects=pcb.TextEffect(
                                 font=pcb.FontSpec(size=xy(drawing_text_size, drawing_text_size),
                                                   thickness=drawing_text_size/10),
                                 justify=pcb.Justify(h=pcb.Atom.left))))


    for x in range(cols):
        for off_x in [0, tile_width]:
            x_pos = x0 + tooling_border + cut_gap + off_x + x*coil_pitch_h
            do_line(x_pos, y0 - vscore_extra, x_pos, y0 + total_height + vscore_extra)
            b.add(kc_gr.Text(text='V-score',
                             at=pcb.AtPos(x_pos, y0 + total_height + vscore_extra + drawing_text_size/2, 90),
                             layer=kc_gr.TextLayer('Edge.Cuts'),
                             effects=pcb.TextEffect(
                                 font=pcb.FontSpec(size=xy(drawing_text_size, drawing_text_size),
                                                   thickness=drawing_text_size/10),
                                 justify=pcb.Justify(h=pcb.Atom.right))))

def draw_corner(x0, y0, spokes):
    right, top, left, bottom = [True if c.lower() in 'y1' else False for c in spokes]

    l = (tile_width - mouse_bite_width)/2 - cut_gap/2

    if right:
        do_line(cut_gap/2, -cut_gap/2, cut_gap/2 + l, -cut_gap/2, x0, y0)
        do_line(cut_gap/2, cut_gap/2, cut_gap/2 + l, cut_gap/2, x0, y0)
        b.add(kc_gr.Arc(start=xy(x0+cut_gap/2+l, y0-cut_gap/2),
                        end=xy(x0+cut_gap/2+l, y0+cut_gap/2),
                        center=xy(x0+cut_gap/2+l, y0),
                        layer='Edge.Cuts',
                        stroke=pcb.Stroke(width=0.15)))

    else:
        do_line(cut_gap/2, -cut_gap/2, cut_gap/2, cut_gap/2, x0, y0)

    if left:
        do_line(-cut_gap/2, -cut_gap/2, -cut_gap/2 - l, -cut_gap/2, x0, y0)
        do_line(-cut_gap/2, cut_gap/2, -cut_gap/2 - l, cut_gap/2, x0, y0)
        b.add(kc_gr.Arc(end=xy(x0-cut_gap/2-l, y0-cut_gap/2),
                        start=xy(x0-cut_gap/2-l, y0+cut_gap/2),
                        center=xy(x0-cut_gap/2-l, y0),
                        layer='Edge.Cuts',
                        stroke=pcb.Stroke(width=0.15)))

    else:
        do_line(-cut_gap/2, -cut_gap/2, -cut_gap/2, cut_gap/2, x0, y0)

    if bottom:
        do_line(-cut_gap/2, cut_gap/2, -cut_gap/2, cut_gap/2 + l, x0, y0)
        do_line(cut_gap/2, cut_gap/2, cut_gap/2, cut_gap/2 + l, x0, y0)
        b.add(kc_gr.Arc(end=xy(x0-cut_gap/2, y0+cut_gap/2+l),
                        start=xy(x0+cut_gap/2, y0+cut_gap/2+l),
                        center=xy(x0, y0+cut_gap/2+l),
                        layer='Edge.Cuts',
                        stroke=pcb.Stroke(width=0.15)))

    else:
        do_line(-cut_gap/2, cut_gap/2, cut_gap/2, cut_gap/2, x0, y0)

    if top:
        do_line(-cut_gap/2, -cut_gap/2, -cut_gap/2, -cut_gap/2 - l, x0, y0)
        do_line(cut_gap/2, -cut_gap/2, cut_gap/2, -cut_gap/2 - l, x0, y0)
        b.add(kc_gr.Arc(start=xy(x0-cut_gap/2, y0-cut_gap/2-l),
                        end=xy(x0+cut_gap/2, y0-cut_gap/2-l),
                        center=xy(x0, y0-cut_gap/2-l),
                        layer='Edge.Cuts',
                        stroke=pcb.Stroke(width=0.15)))
    else:

        do_line(-cut_gap/2, -cut_gap/2, cut_gap/2, -cut_gap/2, x0, y0)


def make_mouse_bite(x, y, rot=0, width=mouse_bite_width, hole_dia=mouse_bite_hole_dia, hole_spacing=mouse_bite_hole_spacing, **kwargs):

    pitch = hole_dia + hole_spacing
    num_holes = int(math.floor((width - hole_dia) / pitch)) + 1
    
    actual_spacing = (width - num_holes*hole_dia) / (num_holes - 1)
    pitch = hole_dia + actual_spacing
    
    f = fp.Footprint(name='mouse_bite', _version=None, generator=None, at=fp.AtPos(x, y, rot), **kwargs)
    for i in range(num_holes):
        f.pads.append(fp.Pad(
            number='1',
            type=fp.Atom.np_thru_hole,
            shape=fp.Atom.circle,
            at=fp.AtPos(-width/2 + i*pitch + hole_dia/2, 0, 0),
            size=xy(hole_dia, hole_dia),
            drill=fp.Drill(diameter=hole_dia),
            footprint=f))
    return f


def make_hole(x, y, dia, **kwargs):
    f = fp.Footprint(name='hole', _version=None, generator=None, at=fp.AtPos(x, y, 0), **kwargs)
    f.pads.append(fp.Pad(
        number='1',
        type=fp.Atom.np_thru_hole,
        shape=fp.Atom.circle,
        at=fp.AtPos(0, 0, 0),
        size=xy(dia, dia),
        drill=fp.Drill(diameter=dia),
        footprint=f))
    return f


def make_pads(x, y, rot, n, pad_dia, pad_length, drill, pitch, **kwargs):
    f = fp.Footprint(name=f'conn_gen_01x{n}', _version=None, generator=None, at=fp.AtPos(x, y, rot), **kwargs)

    for i in range(n):
        f.pads.append(fp.Pad(
            number=str(i+1),
            type=fp.Atom.thru_hole,
            shape=fp.Atom.oval,
            at=fp.AtPos(-pitch*(n-1)/2 + i*pitch, 0, rot),
            size=xy(pad_dia, pad_length),
            drill=fp.Drill(diameter=drill),
            footprint=f))

    return f


corner_x0 = x0 + tooling_border + cut_gap/2
corner_y0 = y0 + tooling_border + cut_gap/2
corner_x1 = x0 + total_width - tooling_border - cut_gap/2
corner_y1 = y0 + total_height - tooling_border - cut_gap/2

if do_cut_gaps:
    # Corners
    draw_corner(corner_x0, corner_y0, 'YNNY')
    draw_corner(corner_x0, corner_y1, 'YYNN')
    draw_corner(corner_x1, corner_y0, 'NNYY')
    draw_corner(corner_x1, corner_y1, 'NYYN')

    # Top / bottom T junctions
    for x in range(1, cols):
        draw_corner(corner_x0 + x*coil_pitch_h, corner_y0, 'YYNY')
        draw_corner(corner_x0 + x*coil_pitch_h, corner_y1, 'NYYY')

    # Left / right T junctions
    for y in range(1, rows):
        draw_corner(corner_x0, corner_y0 + y*coil_pitch_v, 'YYNY')
        draw_corner(corner_x1, corner_y0 + y*coil_pitch_v, 'NYYY')

    # Middle X junctions
    for y in range(1, rows):
        for x in range(1, cols):
            draw_corner(corner_x0 + x*coil_pitch_h, corner_y0 + y*coil_pitch_v, 'YYYY')

else:
    for layer in ('F.SilkS', 'B.SilkS'):
        for x in range(0, cols+1):
            cx = x0 + tooling_border + cut_gap/2 + x*coil_pitch_h
            b.add(kc_gr.Line(xy(cx, corner_y0),
                             xy(cx, corner_y1),
                             layer=layer, stroke=pcb.Stroke(width=0.15)))

        for y in range(0, rows+1):
            cy = y0 + tooling_border + cut_gap/2 + y*coil_pitch_v
            b.add(kc_gr.Line(xy(corner_x0, cy),
                             xy(corner_x1, cy),
                             layer=layer, stroke=pcb.Stroke(width=0.15)))


# Mouse bites
if do_mouse_bites:
    for x in range(0, cols):
        for y in range(0, rows):
            tile_x0 = x0 + tooling_border + cut_gap + x*coil_pitch_h
            tile_y0 = y0 + tooling_border + cut_gap + y*coil_pitch_v

            b.add(make_mouse_bite(tile_x0 + tile_width/2, tile_y0 - mouse_bite_hole_dia/2, 0))
            b.add(make_mouse_bite(tile_x0 + tile_width/2, tile_y0 + tile_height + mouse_bite_hole_dia/2, 0))
            b.add(make_mouse_bite(tile_x0 - mouse_bite_hole_dia/2, tile_y0 + tile_height/2, 90))
            b.add(make_mouse_bite(tile_x0 + tile_width + mouse_bite_hole_dia/2, tile_y0 + tile_height/2, 90))

# Mounting holes
for x in range(0, cols):
    for y in range(0, rows):
        tile_x0 = x0 + tooling_border + cut_gap + x*coil_pitch_h + tile_width/2
        tile_y0 = y0 + tooling_border + cut_gap + y*coil_pitch_v + tile_height/2

        dx = tile_width/2 - hole_offset
        dy = tile_height/2 - hole_offset
        b.add(make_hole(tile_x0 - dx, tile_y0 - dy, hole_dia))
        b.add(make_hole(tile_x0 - dx, tile_y0 + dy, hole_dia))
        b.add(make_hole(tile_x0 + dx, tile_y0 - dy, hole_dia))
        b.add(make_hole(tile_x0 + dx, tile_y0 + dy, hole_dia))

# border graphics
c = 3
for layer in ['F.SilkS', 'B.SilkS']:
    b.add(kc_gr.Rectangle(start=xy(x0, y0), end=xy(x0+c, y0+total_height), layer=layer, stroke=pcb.Stroke(width=0),
                          fill=kc_gr.FillMode(pcb.Atom.solid)))
    b.add(kc_gr.Rectangle(start=xy(x0, y0), end=xy(x0+total_width, y0+c), layer=layer, stroke=pcb.Stroke(width=0),
                          fill=kc_gr.FillMode(pcb.Atom.solid)))
    b.add(kc_gr.Rectangle(start=xy(x0+total_width-c, y0), end=xy(x0+total_width, y0+total_height), layer=layer, stroke=pcb.Stroke(width=0),
                          fill=kc_gr.FillMode(pcb.Atom.solid)))
    b.add(kc_gr.Rectangle(start=xy(x0, y0+total_height-c), end=xy(x0+total_width, y0+total_height), layer=layer, stroke=pcb.Stroke(width=0),
                          fill=kc_gr.FillMode(pcb.Atom.solid)))

a = 3
timestamp = datetime.datetime.now().strftime('%Y-%m-%d')
b.add(kc_gr.Text(text=f'Planar inductor test panel',
                 at=pcb.AtPos(x0 + tooling_border + cut_gap/2, y0 + c + 2*a/3),
                 layer=kc_gr.TextLayer('F.SilkS'),
                 effects=pcb.TextEffect(
                     font=pcb.FontSpec(face="Inter Semi Bold",
                                       size=xy(6*a/3, 6*a/3),
                                       thickness=a/5),
                     justify=pcb.Justify(h=pcb.Atom.left, v=pcb.Atom.top))))

b.add(kc_gr.Text(text=f'{version_string} {timestamp} © 2023 Jan Götte, FG KOM, TU Darmstadt',
                 at=pcb.AtPos(x0 + total_width - tooling_border - cut_gap/2, y0 + c + 4*a/3),
                 layer=kc_gr.TextLayer('F.SilkS'),
                 effects=pcb.TextEffect(
                     font=pcb.FontSpec(face="Inter Light",
                                       size=xy(a, a),
                                       thickness=a/5),
                     justify=pcb.Justify(h=pcb.Atom.right, v=pcb.Atom.top))))

for index, ((y, x), spec) in tqdm.tqdm(enumerate(zip(itertools.product(range(rows), range(cols)), coil_specs), start=1)):
    pass
    with tempfile.NamedTemporaryFile(suffix='.kicad_mod') as f:
        tile_x0 = x0 + tooling_border + cut_gap + x*coil_pitch_h + tile_width/2
        tile_y0 = y0 + tooling_border + cut_gap + y*coil_pitch_v + tile_height/2

        for key, alias in {
                'gen.inner_diameter': 'id',
                'gen.outer_diameter': 'od',
                'gen.trace_width': 'w',
                'gen.turns': 'n',
                'gen.twists': 't',
                'gen.clearance': 'c',
                'gen.single_layer': 's',
                'gen.via_drill': 'd',
                'gen.via_diameter': 'v'}.items():
            if alias in spec:
                spec[key] = spec.pop(alias)

        if 'gen.via_diameter' not in spec:
            spec['gen.via_diameter'] = spec['gen.trace_width']
        
        if 'gen.inner_diameter' not in spec:
            spec['gen.inner_diameter'] = coil_inner_dia

        if 'gen.outer_diameter' not in spec:
            spec['gen.outer_diameter'] = coil_dia

        args = ['python', '-m', 'twisted_coil_gen_twolayer', '--no-keepout-zone']
        for k, v in spec.items():
            prefix, _, k = k.partition('.')
            if (not isinstance(v, bool) or v) and prefix == 'gen':
                args.append('--' + k.replace('_', '-'))
                if v is not True:
                    args.append(str(v))

        arg_digest = hashlib.sha3_256(' / '.join(map(str, args)).encode()).hexdigest()
        cachedir.mkdir(exist_ok=True)
        cache_file = cachedir / f'C-{arg_digest}.kicad_mod'
        log_file = cachedir / f'Q-{arg_digest}.kicad_mod'
        if not cache_file.is_file():
            args.append(cache_file)
            try:
                res = subprocess.run(args, check=True, capture_output=True, text=True)
                log_file.write_text(res.stdout + res.stderr)
            except subprocess.CalledProcessError as e:
                print(f'Error generating coil with command line {args}, rc={e.returncode}')
                print(e.stdout)
                print(e.stderr)

        coil = fp.Footprint.open_mod(cache_file)
        coil.at = fp.AtPos(tile_x0, tile_y0, 0)
        b.add(coil)

        t = [f'n={spec["gen.turns"]}',
             f'{spec["gen.twists"]} twists',
             f'w={spec["gen.trace_width"]:.2f}mm']
        if spec.get('gen.single_layer'):
            t.append('single layer')

        spec['gen.board_thickness'] = board_thickness
        cur.execute('INSERT INTO coils(run_id) VALUES (?)', (run_id,))
        coil_id = cur.lastrowid

        for key, value in spec.items():
            if isinstance(value, bool):
                value = str(value)
            db.execute('INSERT INTO results(coil_id, key, value) VALUES (?, ?, ?)', (coil_id, key, value))

        for l in log_file.read_text().splitlines():
            if (m := re.fullmatch(r'Approximate inductance:\s*([-+.0-9eE]+)\s*µH', l.strip())):
                val = float(m.group(1)) * 1e-6
                db.execute('INSERT INTO results(coil_id, key, value) VALUES (?, "calculated_approximate_inductance", ?)', (coil_id, val))
            if (m := re.fullmatch(r'Approximate track length:\s*([-+.0-9eE]+)\s*mm', l.strip())):
                val = float(m.group(1)) * 1e-3
                db.execute('INSERT INTO results(coil_id, key, value) VALUES (?, "calculated_trace_length", ?)', (coil_id, val))
            if (m := re.fullmatch(r'Approximate resistance:\s*([-+.0-9eE]+)\s*Ω', l.strip())):
                val = float(m.group(1))
                db.execute('INSERT INTO results(coil_id, key, value) VALUES (?, "calculated_approximate_resistance", ?)', (coil_id, val))
            if (m := re.fullmatch(r'Fill factor:\s*([-+.0-9eE]+)', l.strip())):
                val = float(m.group(1))
                db.execute('INSERT INTO results(coil_id, key, value) VALUES (?, "calculated_fill_factor", ?)', (coil_id, val))
        db.commit()

        sz = 2
        b.add(kc_gr.Text(text='\\n'.join(t),
                         at=pcb.AtPos(tile_x0, tile_y0),
                         layer=kc_gr.TextLayer('B.SilkS'),
                         effects=pcb.TextEffect(
                             font=pcb.FontSpec(face='Inter Medium',
                                               size=xy(sz, sz),
                                               thickness=sz/5),
                             justify=pcb.Justify(h=None, v=None, mirror=True))))

        b.add(kc_gr.Text(text=f'Tile {index}',
                         at=pcb.AtPos(tile_x0, tile_y0 - tile_height/2 + sz),
                         layer=kc_gr.TextLayer('B.SilkS'),
                         effects=pcb.TextEffect(
                             font=pcb.FontSpec(face='Inter Semi Bold',
                                               size=xy(sz, sz),
                                               thickness=sz/5),
                             justify=pcb.Justify(h=None, v=pcb.Atom.top, mirror=True))))

        b.add(kc_gr.Text(text=f'{version_string} {timestamp}',
                         at=pcb.AtPos(tile_x0, tile_y0 - tile_height/2 + sz*2.4),
                         layer=kc_gr.TextLayer('B.SilkS'),
                         effects=pcb.TextEffect(
                             font=pcb.FontSpec(face='Inter Light',
                                               size=xy(sz, sz),
                                               thickness=sz/5),
                             justify=pcb.Justify(h=None, v=pcb.Atom.top, mirror=True))))

        b.add(kc_gr.Text(text=f'{index}',
                         at=pcb.AtPos(tile_x0, tile_y0 - tile_height/2 + sz),
                         layer=kc_gr.TextLayer('F.SilkS'),
                         effects=pcb.TextEffect(
                             font=pcb.FontSpec(face='Inter Medium',
                                               size=xy(sz, sz),
                                               thickness=sz/5),
                             justify=pcb.Justify(h=None, v=pcb.Atom.top, mirror=False))))

        pads_x0 = tile_x0 + tile_width/2 - pad_offset
        pads = make_pads(pads_x0, tile_y0, 270, 2, pad_dia, pad_length, pad_drill, pad_pitch)
        b.add(pads)

        w = min(spec.get('gen.trace_width', pad_dia), pad_dia)
        wx, wy, _r, _f = pads.pad(2).abs_pos
        w2 = (wx - pad_length/2, wy)
        wx, wy, _r, _f = pads.pad(1).abs_pos
        w1 = (wx - pad_length/2, wy)
        b.add(cad_pr.Trace(w, coil.pad(1), pads.pad(1), waypoints=[w1], orientation=['ccw'], side='top'))
        b.add(cad_pr.Trace(w, coil.pad(2), pads.pad(2), waypoints=[w2], orientation=['cw'], side='bottom'))

        k = 3
        for layer in ['F.SilkS', 'B.SilkS']:
            b.add(kc_gr.Rectangle(start=xy(wx-k/2, wy-pad_pitch-k/2), end=xy(wx+k/2, wy-pad_pitch), layer=layer, stroke=pcb.Stroke(width=0),
                                  fill=kc_gr.FillMode(pcb.Atom.solid)))

b.write('coil_test_board.kicad_pcb')

