
def item_colors(colorscheme):
    return getattr(colorscheme, 'item_colors', True)


def black_and_white_fill(color, stroked, colorscheme, fg=None, bg=None):
    # A fill of a color of its own like KiCad's black and white export draws it: not at all (like a background fill)
    # if the shape has an outline, else in black, or in white if the color is white.
    if stroked:
        return bg or colorscheme.fill
    if color is not None and (color.r, color.g, color.b, color.a) == (255, 255, 255, 1):
        return 'white'
    return fg or colorscheme.lines


class Colorscheme:
    class KiCad:
        wire = 'black'
        bus = 'black'
        lines = 'black'
        no_connect = 'black'
        text = 'black'
        values = 'black'
        labels = 'black'
        pin_names = 'black'
        pin_numbers = 'black'
        fill = '#cccccc'
        background = 'white'
        # Whether items are drawn with the stroke and fill colors they give themselves. KiCad's black and white export
        # ignores them, and does not fill shapes with a fill color if they have an outline.
        item_colors = True
        # Whether pins with alternate functions get KiCad's icon for them, which KiCad's schematic editor shows, but not
        # its exports
        alternate_icons = True

