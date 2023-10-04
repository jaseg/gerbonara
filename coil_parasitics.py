#!/usr/bin/env python3

from pathlib import Path
import multiprocessing
import re
import tempfile
import subprocess
import fnmatch
import shutil
import numpy as np

from pyelmer import elmer
import click
from scipy import constants

def enumerate_mesh_bodies(msh_file):
    with open(msh_file, 'r') as f:
        for line in f:
            if line.startswith('$PhysicalNames'):
                break
        else:
            raise ValueError('No physcial bodies found in mesh file.')

        _num_names = next(f)

        for line in f:
            if line.startswith('$EndPhysicalNames'):
                break
            
            dim, _, line = line.strip().partition(' ')
            tag, _, name = line.partition(' ')
            yield name.strip().strip('"'), (int(dim), int(tag))

INPUT_EXT_MAP = {
        '.grd': 1,
        '.mesh*': 2,
        '.ep': 3,
        '.ansys': 4,
        '.inp': 5,
        '.fil': 6,
        '.FDNEUT': 7,
        '.unv': 8,
        '.mphtxt': 9,
        '.dat': 10,
        '.node': 11,
        '.ele': 11,
        '.mesh': 12,
        '.msh': 14,
        '.ep.i': 15,
        '.2dm': 16}

OUTPUT_EXT_MAP = {
        '.grd': 1,
        '.mesh*': 2,
        '.ep': 3,
        '.msh': 4,
        '.vtu': 5}

def elmer_grid(infile, outfile=None, intype=None, outtype=None, cwd=None, **kwargs):
    infile = Path(infile)
    if outfile is not None:
        outfile = Path(outfile)

    if intype is None:
        intype = str(INPUT_EXT_MAP[infile.suffix])

    if outtype is None:
        if outfile is not None and outfile.suffix:
            outtype = str(OUTPUT_EXT_MAP[outfile.suffix])
        else:
            outtype = '2'

    if outfile is not None:
        kwargs['out'] = str(outfile)

    args = ['ElmerGrid', intype, outtype, infile]
    for key, value in kwargs.items():
        args.append(f'-{key}')
        if isinstance(value, (tuple, list)):
            args.extend(str(v) for v in value)
        else:
            args.append(str(value))
    subprocess.run(args, cwd=cwd)

def elmer_solver(cwd):
    subprocess.run(['ElmerSolver'], cwd=cwd)


@click.command()
@click.option('-d', '--sim-dir', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.argument('mesh_file', type=click.Path(dir_okay=False, path_type=Path))
def run_capacitance_simulation(mesh_file, sim_dir):
    physical = dict(enumerate_mesh_bodies(mesh_file))
    if sim_dir is not None:
        sim_dir = Path(sim_dir)
        sim_dir.mkdir(exist_ok=True)

    sim = elmer.load_simulation('3D_steady', 'coil_parasitics_sim.yml')
    mesh_dir = '.'
    mesh_fn = 'mesh'
    sim.header['Mesh DB'] = f'"{mesh_dir}" "{mesh_fn}"'
    sim.constants.update({
        'Permittivity of Vacuum': str(constants.epsilon_0),
        'Gravity(4)': f'0 -1 0 {constants.g}',
        'Boltzmann Constant': str(constants.Boltzmann),
        'Unit Charge': str(constants.elementary_charge)})

    air = elmer.load_material('air', sim, 'coil_parasitics_materials.yml')
    ro4003c = elmer.load_material('ro4003c', sim, 'coil_parasitics_materials.yml')

    solver_electrostatic = elmer.load_solver('Electrostatics_Capacitance', sim, 'coil_parasitics_solvers.yml')
    solver_electrostatic.data['Potential Difference'] = '1.0'
    eqn = elmer.Equation(sim, 'main', [solver_electrostatic])

    bdy_sub = elmer.Body(sim, 'substrate', [physical['substrate'][1]])
    bdy_sub.material = ro4003c
    bdy_sub.equation = eqn

    bdy_ab = elmer.Body(sim, 'airbox', [physical['airbox'][1]])
    bdy_ab.material = air
    bdy_ab.equation = eqn

    # boundaries
    for name, identity in physical.items():
        if (m := re.fullmatch(r'trace([0-9]+)', name)):
            num = int(m.group(1))

            bndry_m2 = elmer.Boundary(sim, name, [identity[1]])
            bndry_m2.data['Capacitance Body'] = str(num)

    boundary_airbox = elmer.Boundary(sim, 'FarField', [physical['airbox_surface'][1]])
    boundary_airbox.data['Electric Infinity BC'] = 'True'

    with tempfile.TemporaryDirectory() as tmpdir:
        if sim_dir:
            tmpdir = str(sim_dir)

        sim.write_startinfo(tmpdir)
        sim.write_sif(tmpdir)
        # Convert mesh from gmsh to elemer formats. Also scale it from 1 unit = 1 mm to 1 unit = 1 m (SI units)
        elmer_grid(mesh_file.name, 'mesh', cwd=tmpdir, scale=[1e-3, 1e-3, 1e-3])
        elmer_solver(tmpdir)
        
        capacitance_matrix = np.loadtxt(tmpdir / 'capacitance.txt')

@click.command()
@click.option('-d', '--sim-dir', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.argument('mesh_file', type=click.Path(dir_okay=False, path_type=Path))
def run_inductance_simulation(mesh_file, sim_dir):
    physical = dict(enumerate_mesh_bodies(mesh_file))

    if sim_dir is not None:
        sim_dir = Path(sim_dir)
        sim_dir.mkdir(exist_ok=True)

    sim = elmer.load_simulation('3D_steady', 'coil_mag_sim.yml')
    mesh_dir = '.'
    mesh_fn = 'mesh'
    sim.header['Mesh DB'] = f'"{mesh_dir}" "{mesh_fn}"'
    sim.constants.update({
        'Permittivity of Vacuum': str(constants.epsilon_0),
        'Gravity(4)': f'0 -1 0 {constants.g}',
        'Boltzmann Constant': str(constants.Boltzmann),
        'Unit Charge': str(constants.elementary_charge)})

    air = elmer.load_material('air', sim, 'coil_mag_materials.yml')
    ro4003c = elmer.load_material('ro4003c', sim, 'coil_mag_materials.yml')
    copper = elmer.load_material('copper', sim, 'coil_mag_materials.yml')

    solver_current = elmer.load_solver('Static_Current_Conduction', sim, 'coil_mag_solvers.yml')
    solver_magdyn = elmer.load_solver('Magneto_Dynamics', sim, 'coil_mag_solvers.yml')
    solver_magdyn_calc = elmer.load_solver('Magneto_Dynamics_Calculations', sim, 'coil_mag_solvers.yml')

    copper_eqn = elmer.Equation(sim, 'copperEqn', [solver_current, solver_magdyn, solver_magdyn_calc])
    air_eqn = elmer.Equation(sim, 'airEqn', [solver_magdyn, solver_magdyn_calc])

    bdy_trace = elmer.Body(sim, 'trace', [physical['trace'][1]])
    bdy_trace.material = copper
    bdy_trace.equation = copper_eqn

    bdy_sub = elmer.Body(sim, 'substrate', [physical['substrate'][1]])
    bdy_sub.material = ro4003c
    bdy_sub.equation = air_eqn

    bdy_ab = elmer.Body(sim, 'airbox', [physical['airbox'][1]])
    bdy_ab.material = air
    bdy_ab.equation = air_eqn

    bdy_if_top = elmer.Body(sim, 'interface_top', [physical['interface_top'][1]])
    bdy_if_top.material = copper
    bdy_if_top.equation = copper_eqn

    bdy_if_bottom = elmer.Body(sim, 'interface_bottom', [physical['interface_bottom'][1]])
    bdy_if_bottom.material = copper
    bdy_if_bottom.equation = copper_eqn

    # boundaries
    boundary_airbox = elmer.Boundary(sim, 'FarField', [physical['airbox_surface'][1]])
    boundary_airbox.data['Electric Infinity BC'] = 'True'

    boundary_vplus = elmer.Boundary(sim, 'Vplus', [physical['interface_top'][1]])
    boundary_vplus.data['Potential'] = 1.0
    boundary_vplus.data['Save Scalars'] = True

    boundary_vminus = elmer.Boundary(sim, 'Vminus', [physical['interface_bottom'][1]])
    boundary_vminus.data['Potential'] = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        if sim_dir:
            tmpdir = str(sim_dir)

        sim.write_startinfo(tmpdir)
        sim.write_sif(tmpdir)
        # Convert mesh from gmsh to elemer formats. Also scale it from 1 unit = 1 mm to 1 unit = 1 m (SI units)
        elmer_grid(mesh_file.name, 'mesh', cwd=tmpdir, scale=[1e-3, 1e-3, 1e-3])
        elmer_solver(tmpdir)


if __name__ == '__main__':
    run_inductance_simulation()
