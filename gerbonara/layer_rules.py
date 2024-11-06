#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Based on https://github.com/tracespace/tracespace
#

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
    'mechanical outline':    r'.*\.(gko|gm[0-9]+)',
    # this rule is slightly generic to catch the drill files of things like geda and pcb-rnd that otherwise use altium's
    # layer names.
    'drill unknown':    r'.*\.(txt|drl|xln)',
    'other netlist':    r'.*\.ipc',
    },

'kicad': {
    'top copper':       r'.*\.gtl|.*f.cu.(gbr|gtl)',
    'top mask':         r'.*\.gts|.*f.mask.(gbr|gts)',
    'top silk':         r'.*\.gto|.*f.silks(creen)?.(gbr|gto)',
    'top paste':        r'.*\.gtp|.*f.paste.(gbr|gtp)',
    'bottom copper':    r'.*\.gbl|.*b.cu.(gbr|gbl)',
    'bottom mask':      r'.*\.gbs|.*b.mask.(gbr|gbs)',
    'bottom silk':      r'.*\.gbo|.*b.silks(creen)?.(gbr|gbo)',
    'bottom paste':     r'.*\.gbp|.*b.paste.(gbr|gbp)',
    'inner copper':     r'.*\.gp?([0-9]+)|.*inn?e?r?([0-9]+).cu.(?:gbr|g[0-9]+)',
    'mechanical outline':    r'.*\.(gm[0-9]+)|.*edge.cuts.(gbr|gm1)',
    'drill nonplated':  r'.*\-NPTH.(drl)',
    'drill plated':     r'.*\-PTH.(drl)',
    'drill unknown':    r'.*\.(drl)',
    'other netlist':    r'.*\.d356',
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
    'mechanical outline':    r'.*\.outline\.gbr',
    'drill plated':     r'.*\.plated-drill.cnc',
    'drill nonplated':  r'.*\.unplated-drill.cnc',
    'other netlist':    r'.*\.ipc', # default rule due to lack of tool-specific examples
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
    'other netlist':    r'.*\.ipc', # default rule due to lack of tool-specific examples
    'header regex':     [['sufficient', r'top .*|bottom .*', r'G04 DipTrace [.-0-9a-z]*\*']],
    },

'target': {
    'top copper':       r'.*\.Top',
    'top mask':         r'.*\.StopTop',
    'top silk':         r'.*\.PosiTop',
    'top paste':        r'.*\.PasteTop',
    'bottom copper':    r'.*\.Bot',
    'bottom mask':      r'.*\.StopBot',
    'bottom silk':      r'.*\.PosiBot',
    'bottom paste':     r'.*\.PasteBot',
    'mechanical outline':    r'.*\.Outline',
    'drill plated':     r'.*\.Drill',
    'other netlist':    r'.*\.ipc', # default rule due to lack of tool-specific examples
    },

'orcad': {
    'top copper':       r'.*\.top',
    'top mask':         r'.*\.smt',
    'top silk':         r'.*\.sst',
    'top paste':        r'.*\.spt',
    'bottom copper':    r'.*\.bot',
    'bottom mask':      r'.*\.smb',
    'bottom silk':      r'.*\.ssb',
    'bottom paste':     r'.*\.spb',
    'inner copper':     r'.*\.in([0-9]+)',
    'mechanical outline':    r'.*\.(fab|drd)',
    'drill plated':     r'.*\.tap',
    'drill nonplated':  r'.*\.npt',
    'other netlist':    r'.*\.ipc', # default rule due to lack of tool-specific examples
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
    'mechanical outline':    r'.*(\.dim|\.mil|\.gml)|.*\.(?:board)?outline\.ger|profile\.gbr',
    'drill plated':     r'.*\.(txt|exc|drd|xln)',
    'other netlist':    r'.*\.ipc',
    },

'siemens': {
    'mechanical outline':    r'.*ContourPlated.ncd',
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
    #'drill plated':     r'.*DrillDrawingThrough.gdo',
    # match these last to avoid shadowing other layers via substring match
    'top copper':       r'.*[^enk]Top.gdo',
    'bottom copper':    r'.*[^enk]Bottom.gdo',
    'other netlist':    r'.*\.ipc', # default rule due to lack of tool-specific examples
    },

'allegro': {
    # Allegro doesn't have any widespread convention, so we rely heavily on the layer name auto-guesser here.
    'drill plated':     r'.*\.(drl)',
    'drill nonplated':  r'.*\.(rou)',
    'other unknown':    r'.*(place|assembly|keep.?in|keep.?out).*\.art',
    'autoguess':        r'.*\.art',
    'excellon params':  r'nc_param\.txt|ncdrill\.log|ncroute\.log',
    'other netlist':    r'.*\.ipc', # default rule due to lack of tool-specific examples
    'header regex':     [['required,sufficient', r'.*\.art', r'G04 File Origin:\s+Cadence Allegro [0-9]+\.[0-9]+[-a-zA-Z0-9]*']],
    },

'pads': {
    # Pads also does not seem to have a factory-default naming schema. Or it has one but everyone ignores it.
    'autoguess':        r'.*\.pho',
    'drill plated':     r'.*\.drl',
    },

'zuken': {
    'autoguess': r'.*\.fph',
    'gerber params': r'.*\.fpl',
    'drill unknown': r'.*\.fdr',
    'excellon params': r'.*\.fdl',
    'other netlist': r'.*\.ipc',
    'ipc-2581': r'.*\.xml',
    },
}
