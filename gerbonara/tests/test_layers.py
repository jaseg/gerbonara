#! /usr/bin/env python
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

from pathlib import Path

import pytest

from .utils import *
from ..layers import LayerStack
from ..rs274x import GerberFile
from ..excellon import ExcellonFile

# hand-classified
REFERENCE_DIRS = {
    'Target3001': {
        'IRNASIoTbank1.2.Apr': None,
        'IRNASIoTbank1.2.Bot': 'bottom copper',
        'IRNASIoTbank1.2.Drill': 'drill plated',
        'IRNASIoTbank1.2.Info': None,
        'IRNASIoTbank1.2.Outline': 'mechanical outline',
        'IRNASIoTbank1.2.PasteBot': 'bottom paste',
        'IRNASIoTbank1.2.PasteTop': 'top paste',
        'IRNASIoTbank1.2.PosiBot': 'bottom silk',
        'IRNASIoTbank1.2.PosiTop': 'top silk',
        'IRNASIoTbank1.2.StopBot': 'bottom mask',
        'IRNASIoTbank1.2.StopTop': 'top mask',
        'IRNASIoTbank1.2.Tool': None,
        'IRNASIoTbank1.2.Top': 'top copper',
        'IRNASIoTbank1.2.Whl': None,
        },

    'allegro': {
        '08_057494d-ipc356.ipc': 'other netlist',
        '08_057494d.rou': 'drill nonplated',
        'Read_Me.1': None,
        'art_param.txt': None,
        'assy1.art': None,
        'assy2.art': None,
        'fab1.art': None,
        'l1_primary.art': 'top copper',
        'l2_gnd.art': 'inner_2 copper',
        'l3_vcc.art': 'inner_3 copper',
        'l4_secondary.art': 'bottom copper',
        'mask_prm.art': 'top mask',
        'mask_sec.art': 'bottom mask',
        'nc_param.txt': None,
        'ncdrill-1-4.drl': 'drill unknown',
        'ncdrill.log': None,
        'netlist.err': None,
        'paste_prm.art': 'top paste',
        'paste_sec.art': 'bottom paste',
        'photo.log': None,
        'silk_prm.art': 'top silk',
        'silk_sec.art': 'bottom silk',
        },

    'allegro-2': {
        'MINNOWMAX_REVA2_PUBLIC_BOTTOMSIDE.pdf': None,
        'MINNOWMAX_REVA2_PUBLIC_TOPSIDE.pdf': None,
        'MinnowMax_RevA1_IPC356A.ipc': 'other netlist',
        'MinnowMax_RevA1_DRILL/MinnowMax_RevA1_NCDRILL.drl': 'drill unknown',
        'MinnowMax_RevA1_DRILL/MinnowMax_RevA1_NCROUTE.rou': 'drill unknown',
        'MinnowMax_RevA1_DRILL/nc_param.txt': None,
        'MinnowMax_RevA1_DRILL/ncdrill.log': None,
        'MinnowMax_RevA1_DRILL/ncroute.log': None,
        'MinnowMax_assy.art': None,
        'MinnowMax_bslk.art': 'bottom silk',
        'MinnowMax_fab.art': None,
        'MinnowMax_lyr10_GAF.art': 'bottom copper',
        'MinnowMax_lyr1_GAF.art': 'top copper',
        'MinnowMax_lyr2.art': 'inner_2 copper',
        'MinnowMax_lyr3.art': 'inner_3 copper',
        'MinnowMax_lyr4.art': 'inner_4 copper',
        'MinnowMax_lyr5.art': 'inner_5 copper',
        'MinnowMax_lyr6.art': 'inner_6 copper',
        'MinnowMax_lyr7.art': 'inner_7 copper',
        'MinnowMax_lyr8.art': 'inner_8 copper',
        'MinnowMax_lyr9.art': 'inner_9 copper',
        'MinnowMax_smc_GAF.art': 'top mask',
        'MinnowMax_sms_GAF.art': 'bottom mask',
        'MinnowMax_spc.art': 'top paste',
        'MinnowMax_sps.art': 'bottom paste',
        'MinnowMax_tslk_GAF.art': 'top silk',
        },

    'altium-composite-drill': {
        'Gerber/LimeSDR-QPCIe_1v2-macro.APR_LIB': None,
        'Gerber/LimeSDR-QPCIe_1v2.EXTREP': None,
        'Gerber/LimeSDR-QPCIe_1v2.G1': 'inner_1 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G10': 'inner_10 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G11': 'inner_11 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G12': 'inner_12 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G2': 'inner_2 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G3': 'inner_3 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G4': 'inner_4 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G5': 'inner_5 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G6': 'inner_6 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G7': 'inner_7 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G8': 'inner_8 copper',
        'Gerber/LimeSDR-QPCIe_1v2.G9': 'inner_9 copper',
        'Gerber/LimeSDR-QPCIe_1v2.GBL': 'bottom copper',
        'Gerber/LimeSDR-QPCIe_1v2.GBO': 'bottom silk',
        'Gerber/LimeSDR-QPCIe_1v2.GBP': 'bottom paste',
        'Gerber/LimeSDR-QPCIe_1v2.GBS': 'bottom mask',
        'Gerber/LimeSDR-QPCIe_1v2.GM1': 'mechanical outline',
        'Gerber/LimeSDR-QPCIe_1v2.GM14': None,
        'Gerber/LimeSDR-QPCIe_1v2.GM15': None,
        'Gerber/LimeSDR-QPCIe_1v2.GPB': None,
        'Gerber/LimeSDR-QPCIe_1v2.GPT': None,
        'Gerber/LimeSDR-QPCIe_1v2.GTL': 'top copper',
        'Gerber/LimeSDR-QPCIe_1v2.GTO': 'top silk',
        'Gerber/LimeSDR-QPCIe_1v2.GTP': 'top paste',
        'Gerber/LimeSDR-QPCIe_1v2.GTS': 'top mask',
        'Gerber/LimeSDR-QPCIe_1v2.REP': None,
        'Gerber/LimeSDR-QPCIe_1v2.RUL': None,
        'Gerber/LimeSDR-QPCIe_1v2.apr': None,
        'NC Drill/LimeSDR-QPCIe_1v2-RoundHoles.TXT': 'drill unknown',
        'NC Drill/LimeSDR-QPCIe_1v2-SlotHoles.TXT': 'drill unknown',
        'NC Drill/LimeSDR-QPCIe_1v2.DRR': None,
        'NC Drill/LimeSDR-QPCIe_1v2.LDP': None,
        },

# TODO there are three designs in this folder. make test work with that. 
#     'diptrace': {
#         'mainboard.drl': 'drill plated',
#         'mainboard_BoardOutline.gbr': 'mechanical outline',
#         'mainboard_Bottom.gbr': 'bottom copper',
#         'mainboard_BottomMask.gbr': 'bottom mask',
#         'mainboard_Top.gbr': 'top copper',
#         'mainboard_TopMask.gbr': 'top mask',
#         'mainboard_TopSilk.gbr': 'top silk',
#         },

    'eagle-newer': {
        'copper_bottom.gbr': 'bottom copper',
        'copper_top.gbr': 'top copper',
        'drills.xln': 'drill unknown',
        'gerber_job.gbrjob': None,
        'profile.gbr': 'mechanical outline',
        'silkscreen_bottom.gbr': 'bottom silk',
        'silkscreen_top.gbr': 'top silk',
        'soldermask_bottom.gbr': 'bottom mask',
        'soldermask_top.gbr': 'top mask',
        'solderpaste_bottom.gbr': 'bottom paste',
        'solderpaste_top.gbr': 'top paste',
        },

    'eagle_files': {
        'copper_bottom_l4.gbr': 'bottom copper',
        'copper_inner_l2.gbr': 'inner_2 copper',
        'copper_inner_l3.gbr': 'inner_3 copper',
        'copper_top_l1.gbr': 'top copper',
        'profile.gbr': 'mechanical outline',
        'silkscreen_bottom.gbr': 'bottom silk',
        'silkscreen_top.gbr': 'top silk',
        'soldermask_bottom.gbr': 'bottom mask',
        'soldermask_top.gbr': 'top mask',
        'solderpaste_bottom.gbr': 'bottom paste',
        'solderpaste_top.gbr': 'top paste',
        },

    'easyeda': {
        'Gerber_BoardOutline.GKO': 'mechanical outline',
        'Gerber_BottomLayer.GBL': 'bottom copper',
        'Gerber_BottomSolderMaskLayer.GBS': 'bottom mask',
        'Gerber_Drill_NPTH.DRL': 'drill nonplated',
        'Gerber_Drill_PTH.DRL': 'drill plated',
        'Gerber_TopLayer.GTL': 'top copper',
        'Gerber_TopPasteMaskLayer.GTP': 'top paste',
        'Gerber_TopPasteMaskLayer.bottom.svg': None,
        'Gerber_TopPasteMaskLayer.gtp.top.solderpaste.svg': None,
        'Gerber_TopPasteMaskLayer.gtp.top.solderpaste_2.svg': None,
        'Gerber_TopPasteMaskLayer.top.svg': None,
        'Gerber_TopSilkLayer.GTO': 'top silk',
        'Gerber_TopSolderMaskLayer.GTS': 'top mask',
        'How-to-order-PCB.txt': None,
        },

    'fritzing': {
        'combined.GKO': 'mechanical outline',
        'combined.gbl': 'bottom copper',
        'combined.gbo': 'bottom silk',
        'combined.gbs': 'bottom mask',
        'combined.gm1': None,
        'combined.gtl': 'top copper',
        'combined.gto': 'top silk',
        'combined.gts': 'top mask',
        'combined.txt': 'drill unknown',
        'gyro_328p_6050_2021_panelize.gerberset': None,
        },

# same as above, two designs in one folder
#    'geda': {
#        'controller.bottom.gbr': 'bottom copper',
#        'controller.bottommask.gbr': 'bottom mask',
#        'controller.fab.gbr': None,
#        'controller.group3.gbr': None,
#        'controller.plated-drill.cnc': 'drill plated',
#        'controller.top.gbr': 'top copper',
#        'controller.topmask.gbr': 'top mask',
#        'controller.topsilk.gbr': 'top silk',
#        'controller.unplated-drill.cnc': 'drill nonplated',
#        },

    'pcb-rnd': {
        'power-art.asb': None,
        'power-art.ast': None,
        'power-art.fab': None,
        'power-art.gbl': 'bottom copper',
        'power-art.gbo': 'bottom silk',
        'power-art.gbp': 'bottom paste',
        'power-art.gbs': 'bottom mask',
        'power-art.gko': 'mechanical outline',
        'power-art.gtl': 'top copper',
        'power-art.gto': 'top silk',
        'power-art.gtp': 'top paste',
        'power-art.gts': 'top mask',
        'power-art.lht': None,
        'power-art.xln': 'drill unknown',
        },

    'siemens': {
        '80101_0125_F200_ContourPlated.ncd': 'mechanical outline',
        '80101_0125_F200_DrillDrawingThrough.gdo': None,
        '80101_0125_F200_L01_Top.gdo': 'top copper',
        '80101_0125_F200_L02.gdo': 'inner_2 copper',
        '80101_0125_F200_L03.gdo': 'inner_3 copper',
        '80101_0125_F200_L04.gdo': 'inner_4 copper',
        '80101_0125_F200_L05.gdo': 'inner_5 copper',
        '80101_0125_F200_L06.gdo': 'inner_6 copper',
        '80101_0125_F200_L07.gdo': 'inner_7 copper',
        '80101_0125_F200_L08.gdo': 'inner_8 copper',
        '80101_0125_F200_L09.gdo': 'inner_9 copper',
        '80101_0125_F200_L10.gdo': 'inner_10 copper',
        '80101_0125_F200_L11.gdo': 'inner_11 copper',
        '80101_0125_F200_L12_Bottom.gdo': 'bottom copper',
        '80101_0125_F200_SilkscreenBottom.gdo': 'bottom silk',
        '80101_0125_F200_SilkscreenTop.gdo': 'top silk',
        '80101_0125_F200_SolderPasteBottom.gdo': 'bottom paste',
        '80101_0125_F200_SolderPasteTop.gdo': 'top paste',
        '80101_0125_F200_SoldermaskBottom.gdo': 'bottom mask',
        '80101_0125_F200_SoldermaskTop.gdo': 'top mask',
        '80101_0125_F200_ThruHoleNonPlated.ncd': 'drill nonplated',
        '80101_0125_F200_ThruHolePlated.ncd': 'drill plated',
        },

    'siemens-2': {
        'Gerber/BoardOutlline.gdo': 'mechanical outline',
        'Gerber/DrillDrawingThrough.gdo': None,
        'Gerber/EtchLayerBottom.gdo': 'bottom copper',
        'Gerber/EtchLayerTop.gdo': 'top copper',
        'Gerber/GerberPlot.gpf': None,
        'Gerber/PCB.dsn': None,
        'Gerber/SolderPasteBottom.gdo': 'bottom paste',
        'Gerber/SolderPasteTop.gdo': 'top paste',
        'Gerber/SoldermaskBottom.gdo': 'bottom mask',
        'Gerber/SoldermaskTop.gdo': 'top mask',
        'NCDrill/ContourPlated.ncd': 'mechanical outline',
        'NCDrill/ThruHoleNonPlated.ncd': 'drill nonplated',
        'NCDrill/ThruHolePlated.ncd': 'drill plated',
        },

    'upverter': {
        'design_export.drl': 'drill unknown',
        'design_export.gbl': 'bottom copper',
        'design_export.gbo': 'bottom silk',
        'design_export.gbp': 'bottom paste',
        'design_export.gbs': 'bottom mask',
        'design_export.gko': 'mechanical outline',
        'design_export.gtl': 'top copper',
        'design_export.gto': 'top silk',
        'design_export.gtp': 'top paste',
        'design_export.gts': 'top mask',
        'design_export.xln': 'drill unknown',
        'layers.cfg': None,
        },

    'zuken-emulated': {
        'Gerber/MetalMask-A.fph': 'top paste',
        'Gerber/MetalMask-B.fph': 'bottom paste',
        'Gerber/Symbol-A.fph': 'top silk',
        'Gerber/Symbol-B.fph': 'bottom silk',
        'Gerber/Resist-A.fph': 'top mask',
        'Gerber/Resist-B.fph': 'bottom mask',
        'Gerber/Conductive-1.fph': 'top copper',
        'Gerber/Conductive-2.fph': 'bottom copper',
        'Drill/8seg_Driver__routed_Drill_thru_plt.fdr/8seg_Driver__routed_Drill_thru_plt.fdl': None,
        'Drill/8seg_Driver__routed_Drill_thru_plt.fdr/8seg_Driver__routed_Drill_thru_plt.fdr': 'drill plated',
        'Drill/8seg_Driver__routed_Drill_thru_nplt.fdr': 'drill nonplated',
        },
    'orcad': {
        'Assembly.art': None,
        'BOTTOM.art': 'bottom copper',
        'GND2.art': 'inner_3 copper',
        'LAYER_1.art': 'inner_2 copper',
        'LAYER_2.art': 'inner_4 copper',
        'PWR.art': 'inner_2 copper',
        'Solder_Mask_Bottom.art': 'bottom mask',
        'Solder_Mask_Top.art': 'top mask',
        'TOP.art': 'top copper',
        'arena_12-12_v6_L1-L6.drl': 'drill plated',
        'silk_screen_bottom.art': 'bottom silk',
        'silk_screen_top.art': 'top silk',
        },
    }

@filter_syntax_warnings
@pytest.mark.parametrize('ref_dir,file_map', list(REFERENCE_DIRS.items()))
def test_layer_classifier(ref_dir, file_map):
    path = reference_path(ref_dir)
    print('Reference path is', path)
    file_map = { filename: role for filename, role in file_map.items() if role is not None } 
    rev_file_map = { tuple(value.split()): key for key, value in file_map.items() }
    drill_files = { filename: role for filename, role in file_map.items() if role.startswith('drill') }

    stack = LayerStack.open_dir(path)
    print('loaded layers:', ', '.join(f'{side} {use}' for side, use in stack.graphic_layers))

    for side in 'top', 'bottom':
        for layer in 'copper', 'silk', 'mask', 'paste':
            if 'allegro-2' in ref_dir and layer in ('silk', 'mask', 'paste'):
                # This particular example has very poorly named files
                continue
            if 'easyeda' in ref_dir and layer == 'paste' and side == 'bottom':
                continue

            if (side, layer) in rev_file_map:
                assert (side, layer) in stack
                found = stack[side, layer]
                assert isinstance(found, GerberFile)
                assert found.original_path.name == Path(rev_file_map[side, layer]).name

            else: # not in file_map
                assert (side, layer) not in stack

    assert len(list(stack.drill_layers)) == len(drill_files)

    for filename, role in drill_files.items():
        print('drill:', filename, role)
        print([(layer.original_path, layer.original_path == Path(filename).name) for layer in stack.drill_layers]) 
        assert any(layer.original_path.name == Path(filename).name for layer in stack.drill_layers) 

    for layer in stack.drill_layers:
        if 'upverter' not in ref_dir:
            assert isinstance(layer, ExcellonFile)

