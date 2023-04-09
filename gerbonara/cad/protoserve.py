#!/usr/bin/env python

import importlib.resources
from tempfile import NamedTemporaryFile, TemporaryDirectory
from pathlib import Path

from quart import Quart, request, Response, send_file

from . import protoboard as pb
from . import protoserve_data
from ..utils import MM, Inch


def extract_importlib(package):
    root = TemporaryDirectory()

    stack = [(importlib.resources.files(package), Path(root.name))]
    while stack:
        res, out = stack.pop()

        for item in res.iterdir():
            item_out = out / item.name
            if item.is_file():
                item_out.write_bytes(item.read_bytes())
            else:
                assert item.is_dir()
                item_out.mkdir()
                stack.push((item, item_out))

    return root

static_folder = extract_importlib(protoserve_data)
app = Quart(__name__, static_folder=static_folder.name)

@app.route('/')
async def index():
    return await app.send_static_file('protoserve.html')

def deserialize(obj, unit):
    pitch_x = float(obj.get('pitch_x', 1.27))
    pitch_y = float(obj.get('pitch_y', 1.27))
    clearance = float(obj.get('clearance', 0.2))

    mil = lambda x: x/1000 if unit == Inch else x

    match obj['type']:
        case 'layout':
            if not obj.get('children'):
                return pb.EmptyProtoArea()

            proportions = [float(child['layout_prop']) for child in obj['children']]
            content = [deserialize(child, unit) for child in obj['children']]
            return pb.PropLayout(content, obj['direction'], proportions)

        case 'twoside':
            top, bottom = obj['children']
            return pb.TwoSideLayout(deserialize(top, unit), deserialize(bottom, unit))

        case 'placeholder':
            return pb.EmptyProtoArea()

        case 'smd':
            match obj['pad_shape']:
                case 'rect':
                    pad = pb.SMDPad.rect(0, 0, pitch_x-clearance, pitch_y-clearance, paste=False, unit=unit)
                case 'circle':
                    pad = pb.SMDPad.circle(0, 0, min(pitch_x, pitch_y)-clearance, paste=False, unit=unit)
            return pb.PatternProtoArea(pitch_x, pitch_y, obj=pad, unit=unit)

        case 'tht':
            hole_dia = mil(float(obj['hole_dia']))
            match obj['plating']:
                case 'plated':
                    oneside, plated = False, True
                case 'nonplated':
                    oneside, plated = False, False
                case 'singleside':
                    oneside, plated = True, False

            match obj['pad_shape']:
                case 'rect':
                    pad = pb.THTPad.rect(0, 0, hole_dia, pitch_x-clearance, pitch_y-clearance, paste=False, plated=plated, unit=unit)
                case 'circle':
                    pad = pb.THTPad.circle(0, 0, hole_dia, min(pitch_x, pitch_y)-clearance, paste=False, plated=plated, unit=unit)
                case 'obround':
                    pad = pb.THTPad.obround(0, 0, hole_dia, pitch_x-clearance, pitch_y-clearance, paste=False, plated=plated, unit=unit)

            if oneside:
                pad.pad_bottom = None

            return pb.PatternProtoArea(pitch_x, pitch_y, obj=pad, unit=unit)

        case 'manhattan':
            return pb.PatternProtoArea(pitch_x, pitch_y, obj=pb.ManhattanPads(pitch_x, pitch_y, clearance, unit=unit), unit=unit)

        case 'powered':
            pitch = mil(float(obj.get('pitch', 2.54)))
            hole_dia = mil(float(obj['hole_dia']))
            via_drill = mil(float(obj['via_hole_dia']))
            trace_width = mil(float(obj['trace_width']))
            return pb.PatternProtoArea(pitch, pitch, pb.PoweredProto(pitch, hole_dia, clearance, via_size=via_drill, trace_width=trace_width, unit=unit), unit=unit)

        case 'flower':
            pitch = mil(float(obj.get('pitch', 2.54)))
            hole_dia = mil(float(obj['hole_dia']))
            pattern_dia = mil(float(obj['pattern_dia']))
            return pb.PatternProtoArea(2*pitch, 2*pitch, pb.THTFlowerProto(pitch, hole_dia, pattern_dia, unit=unit), unit=unit)

        case 'rf':
            pitch = float(obj.get('pitch', 2.54))
            hole_dia = float(obj['hole_dia'])
            via_dia = float(obj['via_dia'])
            via_drill = float(obj['via_hole_dia'])
            return pb.PatternProtoArea(pitch, pitch, pb.RFGroundProto(pitch, hole_dia, clearance, via_dia, via_drill, unit=MM), unit=MM)

def to_board(obj):
    unit = Inch if obj.get('units' == 'us') else MM
    w = float(obj.get('width', unit(100, MM)))
    h = float(obj.get('height', unit(80, MM)))
    corner_radius = float(obj.get('round_corners', {}).get('radius', unit(1.5, MM)))
    holes = obj.get('mounting_holes', {})
    mounting_hole_dia = float(holes.get('diameter', unit(3.2, MM)))
    mounting_hole_offset = float(holes.get('offset', unit(5, MM)))

    if obj.get('children'):
        content = deserialize(obj['children'][0], unit)
    else:
        content = [pb.EmptyProtoArea()]

    return pb.ProtoBoard(w, h, content,
                       corner_radius=corner_radius,
                       mounting_hole_dia=mounting_hole_dia,
                       mounting_hole_offset=mounting_hole_offset,
                       unit=unit)

@app.route('/preview.svg', methods=['POST'])
async def preview():
    obj = await request.get_json()
    board = to_board(obj)
    return Response(str(board.pretty_svg()), mimetype='image/svg+xml')

@app.route('/gerbers.zip', methods=['POST'])
async def gerbers():
    obj = await request.get_json()
    board = to_board(obj)
    with NamedTemporaryFile(suffix='.zip') as f:
        f = Path(f.name)
        board.layer_stack().save_to_zipfile(f)
        return Response(f.read_bytes(), mimetype='image/svg+xml')


if __name__ == '__main__':
    app.run()

