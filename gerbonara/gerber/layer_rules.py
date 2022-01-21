# From https://github.com/tracespace/tracespace

MATCH_RULES = {
'altium': {
    'top copper':       r'.*\.gtl',
    'top mask':         r'.*\.gts',
    'top silk':         r'.*\.gto',
    'top paste':        r'.*\.gtp',
    'bottom copper':    r'.*\.gbl',
    'bottom mask':      r'.*\.gbs',
    'bottom silk':      r'.*\.gbo',
    'bottom paste':     r'.*\.gbp',
    'inner copper':     r'.*\.gp?([0-9]+)',
    'outline mech':     r'.*\.(gko|gm[0-9]+)',
    'drill unknown':    r'.*\.(txt)',
    },

'kicad': {
    'top copper':       r'.*\.gtl|.*f.cu.*',
    'top mask':         r'.*\.gts|.*f.mask.*',
    'top silk':         r'.*\.gto|.*f.silks.*',
    'top paste':        r'.*\.gtp|.*f.paste.*',
    'bottom copper':    r'.*\.gbl|.*b.cu.*',
    'bottom mask':      r'.*\.gbs|.*b.mask.*',
    'bottom silk':      r'.*\.gbo|.*b.silks.*',
    'bottom paste':     r'.*\.gbp|.*b.paste.*',
    'inner copper':     r'.*\.gp?([0-9]+)|.*inn?e?r?([0-9]+).cu.*',
    'outline mech':     r'.*\.(gm[0-9]+)|.*edge.cuts.*',
    'drill plated':     r'.*\.(drl)',
    },

'geda': {
    'top copper':       r'.*\.top\.\w+',
    'top mask':         r'.*\.topmask\.\w+',
    'top silk':         r'.*\.topsilk\.\w+',
    'top paste':        r'.*\.toppaste\.\w+',
    'bottom copper':    r'.*\.bottom\.\w+',
    'bottom mask':      r'.*\.bottommask\.\w+',
    'bottom silk':      r'.*\.bottomsilk\.\w+',
    'bottom paste':     r'.*\.bottompaste\.\w+',
    'inner copper':     r'.*\.inner_l([0-9]+)\.\w+', # FIXME verify this
    'outline mech':     r'.*\.outline\.gbr',
    'drill plated':     r'.*\.plated-drill.cnc',
    'drill nonplated':  r'.*\.unplated-drill.cnc',
    },

'diptrace': {
    'top copper':       r'.*_top\.\w+',
    'top mask':         r'.*_topmask\.\w+',
    'top silk':         r'.*_topsilk\.\w+',
    'top paste':        r'.*_toppaste\.\w+',
    'bottom copper':    r'.*_bottom\.\w+',
    'bottom mask':      r'.*_bottommask\.\w+',
    'bottom silk':      r'.*_bottomsilk\.\w+',
    'bottom paste':     r'.*_bottompaste\.\w+',
    'inner copper':     r'.*_inner_l([0-9]+).*',
    'bottom paste':     r'.*_boardoutline\.\w+', # FIXME verify this
    'drill plated':     r'.*\.(drl)', # diptrace has unplated drills on the outline layer
    },

'orcad': {
    'top copper':       r'.*\.top',
    'top mask':         r'.*\.smt',
    'top silk':         r'.*\.sst',
    'top paste':        r'.*\.spt',
    'top copper':       r'.*\.bot',
    'top mask':         r'.*\.smb',
    'top silk':         r'.*\.ssb',
    'top paste':        r'.*\.spb',
    'inner copper':     r'.*\.in([0-9]+)',
    'outline gerber':   r'.*\.(fab|drd)',
    'drill plated':     r'.*\.tap',
    'drill nonplated':  r'.*\.npt',
    },

'eagle': {
    None: r'.*\.(gpi|dri)|pnp_bom',
    'top copper':       r'.*(\.cmp|\.top|\.toplayer\.ger)|.*(copper_top|top_copper).*',
    'top mask':         r'.*(\.stc|\.tsm|\.topsoldermask\.ger)|.*(soldermask_top|top_mask).*',
    'top silk':         r'.*(\.plc|\.tsk|\.topsilkscreen\.ger)|.*(silkscreen_top|top_silk).*',
    'top paste':        r'.*(\.crc|\.tsp|\.tcream\.ger)|.*(solderpaste_top|top_paste).*',
    'bottom copper':    r'.*(\.sld|\.sol\|\.bottom|\.bottomlayer\.ger)|.*(copper_bottom|bottom_copper).*',
    'bottom mask':      r'.*(\.sts|\.bsm|\.bottomsoldermask\.ger)|.*(soldermask_bottom|bottom_mask).*',
    'bottom silk':      r'.*(\.pls|\.bsk|\.bottomsilkscreen\.ger)|.*(silkscreen_bottom|bottom_silk).*',
    'bottom paste':     r'.*(\.crs|\.bsp|\.bcream\.ger)|.*(solderpaste_bottom|bottom_paste).*',
    'inner copper':     r'.*\.ly([0-9]+)|.*\.internalplane([0-9]+)\.ger',
    'outline mech':     r'.*(\.dim|\.mil|\.gml)|.*\.(?:board)?outline\.ger|profile\.gbr',
    'drill plated':     r'.*\.(txt|exc|drd|xln)',
    },

'siemens': {
    'outline mech':     r'.*ContourPlated.ncd',
    'inner copper':     r'.*L([0-9]+).gdo',
    'bottom silk':      r'.*SilkscreenBottom.gdo',
    'top silk':         r'.*SilkscreenTop.gdo',
    'bottom paste':     r'.*SolderPasteBottom.gdo',
    'top paste':        r'.*SolderPasteTop.gdo',
    'bottom mask':      r'.*SoldermaskBottom.gdo',
    'top mask':         r'.*SoldermaskTop.gdo',
    'drill nonplated':  r'.*ThruHoleNonPlated.ncd',
    'drill plated':     r'.*ThruHolePlated.ncd',
    # list this last to prefer the actual excellon files
    'drill plated':     r'.*DrillDrawingThrough.gdo',
    # match these last to avoid shadowing other layers via substring match
    'top copper':       r'.*Top.gdo',
    'bottom copper':    r'.*Bottom.gdo',
    },

'allegro': {
        # Allegro doesn't have any widespread convention, so we rely heavily on the layer name auto-guesser here.
    'drill mech': r'.*\.rou',
    'drill mech': r'.*\.drl',
    'generic gerber': r'.*\.art',
    'excellon params':  'nc_param\.txt',
    # put .log file last to prefer .txt
    'excellon params':  'ncdrill\.log',
    'excellon params':  'ncroute\.log',
    },
}
