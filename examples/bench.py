#!/usr/bin/env python3

import time
from pathlib import Path

import tqdm

import gerbonara

if __name__ == '__main__':
    resources = Path(__file__).parent.parent / 'gerbonara' / 'tests' / 'resources'

    TEST_FILES = [
        'easyeda/Gerber_TopSilkLayer.GTO',
        'allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr3.art',
        'allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_fab.art',
        'eagle-newer/soldermask_bottom.gbr',
        'eagle-newer/copper_bottom.gbr',
# FIXME remove redundant warnings in these files
#        'siemens/80101_0125_F200_SilkscreenBottom.gdo',
#        'siemens/80101_0125_F200_SoldermaskBottom.gdo',
#        'siemens/80101_0125_F200_SolderPasteBottom.gdo',
#        'siemens/80101_0125_F200_L03.gdo',
#        'siemens/80101_0125_F200_L01_Top.gdo',
#        'zuken-emulated/Gerber/Symbol-A.fph',
        'Target3001/IRNASIoTbank1.2.StopTop',
        'Target3001/IRNASIoTbank1.2.PasteTop',
        'Target3001/IRNASIoTbank1.2.PasteBot',
        'Target3001/IRNASIoTbank1.2.StopBot',
        'Target3001/IRNASIoTbank1.2.Top',
        'pcb-rnd/power-art.gtl',
        'pcb-rnd/power-art.gto',
        'pcb-rnd/power-art.gtp',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G1',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G2',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G3',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G4',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G5',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G6',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G7',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G8',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G9',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G10',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G11',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G12',
        'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GBS',
        'eagle_files/copper_top_l1.gbr',
        'eagle_files/soldermask_top.gbr',
        'diptrace/mainboard_Bottom.gbr',
        'upverter/design_export.gtp',
        'upverter/design_export.gbl',
        ]

    start = time.perf_counter()
    for file in TEST_FILES: #tqdm.tqdm(TEST_FILES):
        gerbonara.GerberFile.open(resources / file)
    end = time.perf_counter()

    print(f'Duration: {(end - start)*1000:.3f} ms')

