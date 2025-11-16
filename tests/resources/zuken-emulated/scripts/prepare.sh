#!/bin/sh

python3 scripts/zukenka_gerber.py < orig/driver-B_Cu    > Gerber/Conductive-2.fph
python3 scripts/zukenka_gerber.py < orig/driver-B_Mask  > Gerber/Resist-B.fph
python3 scripts/zukenka_gerber.py < orig/driver-B_Paste > Gerber/MetalMask-B.fph
python3 scripts/zukenka_gerber.py < orig/driver-B_SilkS > Gerber/Symbol-B.fph
python3 scripts/zukenka_gerber.py < orig/driver-F_Cu    > Gerber/Conductive-1.fph
python3 scripts/zukenka_gerber.py < orig/driver-F_Mask  > Gerber/Resist-A.fph
python3 scripts/zukenka_gerber.py < orig/driver-F_Paste > Gerber/MetalMask-A.fph
python3 scripts/zukenka_gerber.py < orig/driver-F_SilkS > Gerber/Symbol-A.fph

python3 scripts/zukenka_excellon.py < orig/driver-NPTH  > Drill/8seg_Driver__routed_Drill_thru_nplt.fdr
mkdir -p Drill/8seg_Driver__routed_Drill_thru_plt.fdr
python3 scripts/zukenka_excellon.py < orig/driver-PTH   > Drill/8seg_Driver__routed_Drill_thru_plt.fdr/8seg_Driver__routed_Drill_thru_plt.fdr

cp scripts/drill_log_sample Drill/8seg_Driver__routed_Drill_thru_plt.fdr/8seg_Driver__routed_Drill_thru_plt.fdl
cp scripts/drill_log_sample Drill/8seg_Driver__routed_Drill_thru_nplt.fdl

