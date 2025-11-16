#!/usr/bin/env python

import importlib.resources
from tempfile import NamedTemporaryFile, TemporaryDirectory
from pathlib import Path

from quart import Quart, request, Response, send_file, abort

from . import protoboard as pb
from . import protoserve_data
from .primitives import SMDStack
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
                stack.append((item, item_out))

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
                    stack = SMDStack.rect(pitch_x-clearance, pitch_y-clearance, paste=False, unit=unit)
                case 'circle':
                    stack = SMDStack.circle(min(pitch_x, pitch_y)-clearance, paste=False, unit=unit)
            return pb.PatternProtoArea(pitch_x, pitch_y, obj=stack, unit=unit)

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
                    pad = pb.THTPad.rect(hole_dia, pitch_x-clearance, pitch_y-clearance, paste=False, plated=plated, unit=unit)
                case 'circle':
                    pad = pb.THTPad.circle(hole_dia, min(pitch_x, pitch_y)-clearance, paste=False, plated=plated, unit=unit)
                case 'obround':
                    pad = pb.THTPad.obround(hole_dia, pitch_x-clearance, pitch_y-clearance, paste=False, plated=plated, unit=unit)

            if oneside:
                pad.pad_bottom = None

            return pb.PatternProtoArea(pitch_x, pitch_y, obj=pad, unit=unit)

        case 'manhattan':
            return pb.PatternProtoArea(pitch_x, pitch_y, obj=pb.ManhattanPads(pitch_x, pitch_y, clearance, unit=unit), unit=unit)

        case 'powered':
            pitch = mil(float(obj.get('pitch', 2.54)))
            hole_dia = mil(float(obj['hole_dia']))
            via_drill = mil(float(obj['via_hole_dia']))
            via_dia = mil(float(obj['via_dia']))
            trace_width = mil(float(obj['trace_width']))
            # Force 1mm margin to avoid shorts when adjacent to planes such as that one in the RF THT proto.
            return pb.PatternProtoArea(pitch, pitch, pb.PoweredProto(pitch, hole_dia, clearance, via_size=via_drill, power_pad_dia=via_dia, trace_width=trace_width, unit=unit), margin=unit(1.0, MM), unit=unit)

        case 'flower':
            pitch = mil(float(obj.get('pitch', 2.54)))
            hole_dia = mil(float(obj['hole_dia']))
            pattern_dia = mil(float(obj['pattern_dia']))
            clearance = mil(float(obj['clearance']))
            return pb.PatternProtoArea(pitch, pitch, pb.THTFlowerProto(pitch, hole_dia, pattern_dia, clearance, unit=unit), unit=unit)

        case 'spiky':
            return pb.PatternProtoArea(2.54, 2.54, pb.SpikyProto(), unit=unit)

        case 'alio':
            pitch = mil(float(obj.get('pitch', 2.54)))
            drill = mil(float(obj.get('hole_dia', 0.9)))
            clearance = mil(float(obj.get('clearance', 0.3)))
            link_pad_width = mil(float(obj.get('link_pad_width', 1.1)))
            link_trace_width = mil(float(obj.get('link_trace_width', 0.5)))
            via_size = mil(float(obj.get('via_hole_dia', 0.4)))
            return pb.PatternProtoArea(pitch, pitch, pb.AlioCell(
                    pitch=pitch,
                    drill=drill,
                    clearance=clearance,
                    link_pad_width=link_pad_width,
                    link_trace_width=link_trace_width,
                    via_size=via_size
                ), margin=unit(1.5, MM), unit=unit)

        case 'breadboard':
            horizontal = obj.get('direction', 'v') == 'h'
            drill = float(obj.get('hole_dia', 0.9))
            return pb.BreadboardArea(clearance=clearance, drill=drill, horizontal=horizontal, unit=unit)

        case 'starburst':
            trace_width_x = float(obj.get('trace_width_x', 1.8))
            trace_width_y = float(obj.get('trace_width_y', 1.8))
            drill = float(obj.get('hole_dia', 0.9))
            annular_ring = float(obj.get('annular', 1.2))
            clearance = float(obj.get('clearance', 0.4))
            mask_width = float(obj.get('mask_width', 0.5))
            return pb.PatternProtoArea(pitch_x, pitch_y, pb.StarburstPad(pitch_x, pitch_y, trace_width_x, trace_width_y, clearance, mask_width, drill, annular_ring, unit=unit), unit=unit)

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
    margin = float(obj.get('margin', unit(2.0, MM)))
    holes = obj.get('mounting_holes', {})
    mounting_hole_dia = float(holes.get('diameter', unit(3.2, MM)))
    mounting_hole_offset = float(holes.get('offset', unit(5, MM)))

    if obj.get('children'):
        try:
            content = deserialize(obj['children'][0], unit)
        except ValueError:
            return abort(400)
    else:
        content = [pb.EmptyProtoArea()]

    return pb.ProtoBoard(w, h, content,
                       corner_radius=corner_radius,
                       mounting_hole_dia=mounting_hole_dia,
                       mounting_hole_offset=mounting_hole_offset,
                       margin=margin,
                       unit=unit)

@app.route('/preview_<side>.svg', methods=['POST'])
async def preview(side):
    obj = await request.get_json()
    board = to_board(obj)
    return Response(str(board.pretty_svg(side=side)), mimetype='image/svg+xml')

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

