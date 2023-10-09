#!/usr/bin/env python3

import math
from pathlib import Path
import multiprocessing
import re
import tempfile
import fnmatch
import shutil
import numpy as np

from pyelmer import elmer
import subprocess_tee
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

# https://en.wikipedia.org/wiki/Metric_prefix
SI_PREFIX = 'QRYZEPTGMk mµnpfazyrq'

def format_si(value, unit='', fractional_digits=1):
    mag = int(math.log10(abs(value))//3)
    value /= 1000**mag
    prefix = SI_PREFIX[SI_PREFIX.find(' ') - mag].strip()
    value = f'{{:.{fractional_digits}f}}'.format(value)
    return f'{value} {prefix}{unit}'


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

def elmer_grid(infile, outfile=None, intype=None, outtype=None, cwd=None, stdout_log=None, stderr_log=None, **kwargs):
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

    args = ['ElmerGrid', intype, outtype, str(infile)]
    for key, value in kwargs.items():
        args.append(f'-{key}')
        if isinstance(value, (tuple, list)):
            args.extend(str(v) for v in value)
        else:
            args.append(str(value))

    result = subprocess_tee.run(args, cwd=cwd, check=True)
    if stdout_log:
        Path(stdout_log).write_text(result.stdout or '')
    if stderr_log:
        Path(stderr_log).write_text(result.stderr or '')

def elmer_solver(cwd, stdout_log=None, stderr_log=None):
    result = subprocess_tee.run(['ElmerSolver'], cwd=cwd, check=True)
    if stdout_log:
        Path(stdout_log).write_text(result.stdout or '')
    if stderr_log:
        Path(stderr_log).write_text(result.stderr or '')
    return result


@click.group()
def cli():
    pass


@cli.command()
@click.option('-d', '--sim-dir', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.argument('mesh_file', type=click.Path(dir_okay=False, path_type=Path))
def self_capacitance(mesh_file, sim_dir):
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
        tmpdir = sim_dir if sim_dir else Path(tmpdir)

        sim.write_startinfo(tmpdir)
        sim.write_sif(tmpdir)
        # Convert mesh from gmsh to elemer formats. Also scale it from 1 unit = 1 mm to 1 unit = 1 m (SI units)
        elmer_grid(mesh_file.absolute(), 'mesh', cwd=tmpdir, scale=[1e-3, 1e-3, 1e-3],
                   stdout_log=(tmpdir / 'ElmerGrid_stdout.log'),
                   stderr_log=(tmpdir / 'ElmerGrid_stderr.log'))
        elmer_solver(tmpdir,
                   stdout_log=(tmpdir / 'ElmerSolver_stdout.log'),
                   stderr_log=(tmpdir / 'ElmerSolver_stderr.log'))
        
        capacitance_matrix = np.loadtxt(tmpdir / 'capacitance.txt')

@cli.command()
@click.option('-d', '--sim-dir', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.argument('mesh_file', type=click.Path(dir_okay=False, path_type=Path))
def inductance(mesh_file, sim_dir):
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

    potential_force = elmer.BodyForce(sim, 'electric_potential', {'Electric Potential': 'Equals "Potential"'})
    bdy_trace.body_force = potential_force

    # boundaries
    boundary_airbox = elmer.Boundary(sim, 'FarField', [physical['airbox_surface'][1]])
    boundary_airbox.data['Electric Infinity BC'] = 'True'

    boundary_vplus = elmer.Boundary(sim, 'Vplus', [physical['interface_top'][1]])
    boundary_vplus.data['Potential'] = 1.0
    boundary_vplus.data['Save Scalars'] = True

    boundary_vminus = elmer.Boundary(sim, 'Vminus', [physical['interface_bottom'][1]])
    boundary_vminus.data['Potential'] = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = sim_dir if sim_dir else Path(tmpdir)

        sim.write_startinfo(tmpdir)
        sim.write_sif(tmpdir)
        # Convert mesh from gmsh to elemer formats. Also scale it from 1 unit = 1 mm to 1 unit = 1 m (SI units)
        elmer_grid(mesh_file.absolute(), 'mesh', cwd=tmpdir, scale=[1e-3, 1e-3, 1e-3],
                   stdout_log=(tmpdir / 'ElmerGrid_stdout.log'),
                   stderr_log=(tmpdir / 'ElmerGrid_stderr.log'))
        solver_stdout, solver_stderr = (tmpdir / 'ElmerSolver_stdout.log'), (tmpdir / 'ElmerSolver_stderr.log')
        res = elmer_solver(tmpdir,
                   stdout_log=solver_stdout,
                   stderr_log=solver_stderr)
        
        P, R, U_mag = None, None, None
        solver_error = False
        for l in res.stdout.splitlines():
            if (m := re.fullmatch(r'StatCurrentSolve:\s*Total Heating Power\s*:\s*([0-9.+-Ee]+)\s*', l)):
                P = float(m.group(1))
            elif (m := re.fullmatch(r'StatCurrentSolve:\s*Effective Resistance\s*:\s*([0-9.+-Ee]+)\s*', l)):
                R = float(m.group(1))
            elif (m := re.fullmatch(r'MagnetoDynamicsCalcFields:\s*ElectroMagnetic Field Energy\s*:\s*([0-9.+-Ee]+)\s*', l)):
                U_mag = float(m.group(1))
            elif re.fullmatch(r'IterSolve: Linear iteration did not converge to tolerance', l):
                solver_error = True

        if solver_error:
            raise click.ClickException(f'Error: One of the solvers did not converge. See log files for details:\n{solver_stdout.absolute()}\n{solver_stderr.absolute()}')
        elif P is None or R is None or U_mag is None:
            raise click.ClickException(f'Error during solver execution. Electrical parameters could not be calculated. See log files for details:\n{solver_stdout.absolute()}\n{solver_stderr.absolute()}')

        V = math.sqrt(P*R)
        I = math.sqrt(P/R)
        L = 2*U_mag / (I**2)

        assert math.isclose(V, 1.0, abs_tol=1e-3)

        print(f'Total magnetic field energy: {format_si(U_mag, "J")}')
        print(f'Reference coil current: {format_si(I, "Ω")}')
        print(f'Coil resistance calculated by solver: {format_si(R, "Ω")}')
        print(f'Inductance calucated from field: {format_si(L, "H")}')


@cli.command()
@click.option('-r', '--reference-field', type=float, required=True)
@click.option('-d', '--sim-dir', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.argument('mesh_file', type=click.Path(dir_okay=False, path_type=Path))
def mutual_inductance(mesh_file, sim_dir, reference_field):
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

    bdy_trace1 = elmer.Body(sim, 'trace1', [physical['trace1'][1]])
    bdy_trace1.material = copper
    bdy_trace1.equation = copper_eqn

    bdy_trace2 = elmer.Body(sim, 'trace2', [physical['trace2'][1]])
    bdy_trace2.material = copper
    bdy_trace2.equation = copper_eqn

    bdy_sub1 = elmer.Body(sim, 'substrate1', [physical['substrate1'][1]])
    bdy_sub1.material = ro4003c
    bdy_sub1.equation = air_eqn

    bdy_sub2 = elmer.Body(sim, 'substrate2', [physical['substrate2'][1]])
    bdy_sub2.material = ro4003c
    bdy_sub2.equation = air_eqn


    bdy_ab = elmer.Body(sim, 'airbox', [physical['airbox'][1]])
    bdy_ab.material = air
    bdy_ab.equation = air_eqn

    bdy_if_top1 = elmer.Body(sim, 'interface_top1', [physical['interface_top1'][1]])
    bdy_if_top1.material = copper
    bdy_if_top1.equation = copper_eqn

    bdy_if_bottom1 = elmer.Body(sim, 'interface_bottom1', [physical['interface_bottom1'][1]])
    bdy_if_bottom1.material = copper
    bdy_if_bottom1.equation = copper_eqn

    bdy_if_top2 = elmer.Body(sim, 'interface_top2', [physical['interface_top2'][1]])
    bdy_if_top2.material = copper
    bdy_if_top2.equation = copper_eqn

    bdy_if_bottom2 = elmer.Body(sim, 'interface_bottom2', [physical['interface_bottom2'][1]])
    bdy_if_bottom2.material = copper
    bdy_if_bottom2.equation = copper_eqn

    potential_force = elmer.BodyForce(sim, 'electric_potential', {'Electric Potential': 'Equals "Potential"'})
    bdy_trace1.body_force = potential_force
    bdy_trace2.body_force = potential_force

    # boundaries
    boundary_airbox = elmer.Boundary(sim, 'FarField', [physical['airbox_surface'][1]])
    boundary_airbox.data['Electric Infinity BC'] = 'True'

    boundary_vplus1 = elmer.Boundary(sim, 'Vplus1', [physical['interface_top1'][1]])
    boundary_vplus1.data['Potential'] = 1.0
    boundary_vplus1.data['Save Scalars'] = True

    boundary_vminus1 = elmer.Boundary(sim, 'Vminus1', [physical['interface_bottom1'][1]])
    boundary_vminus1.data['Potential'] = 0.0

    boundary_vplus2 = elmer.Boundary(sim, 'Vplus2', [physical['interface_top2'][1]])
    boundary_vplus2.data['Potential'] = 1.0
    boundary_vplus2.data['Save Scalars'] = True

    boundary_vminus2 = elmer.Boundary(sim, 'Vminus2', [physical['interface_bottom2'][1]])
    boundary_vminus2.data['Potential'] = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = sim_dir if sim_dir else Path(tmpdir)

        sim.write_startinfo(tmpdir)
        sim.write_sif(tmpdir)
        # Convert mesh from gmsh to elemer formats. Also scale it from 1 unit = 1 mm to 1 unit = 1 m (SI units)
        elmer_grid(mesh_file.absolute(), 'mesh', cwd=tmpdir, scale=[1e-3, 1e-3, 1e-3],
                   stdout_log=(tmpdir / 'ElmerGrid_stdout.log'),
                   stderr_log=(tmpdir / 'ElmerGrid_stderr.log'))
        solver_stdout, solver_stderr = (tmpdir / 'ElmerSolver_stdout.log'), (tmpdir / 'ElmerSolver_stderr.log')
        res = elmer_solver(tmpdir,
                   stdout_log=solver_stdout,
                   stderr_log=solver_stderr)
        
        P, R, U_mag = None, None, None
        solver_error = False
        for l in res.stdout.splitlines():
            if (m := re.fullmatch(r'StatCurrentSolve:\s*Total Heating Power\s*:\s*([0-9.+-Ee]+)\s*', l)):
                P = float(m.group(1))
            elif (m := re.fullmatch(r'StatCurrentSolve:\s*Effective Resistance\s*:\s*([0-9.+-Ee]+)\s*', l)):
                R = float(m.group(1))
            elif (m := re.fullmatch(r'MagnetoDynamicsCalcFields:\s*ElectroMagnetic Field Energy\s*:\s*([0-9.+-Ee]+)\s*', l)):
                U_mag = float(m.group(1))
            elif re.fullmatch(r'IterSolve: Linear iteration did not converge to tolerance', l):
                solver_error = True

        if solver_error:
            raise click.ClickException(f'Error: One of the solvers did not converge. See log files for details:\n{solver_stdout.absolute()}\n{solver_stderr.absolute()}')
        elif P is None or R is None or U_mag is None:
            raise click.ClickException(f'Error during solver execution. Electrical parameters could not be calculated. See log files for details:\n{solver_stdout.absolute()}\n{solver_stderr.absolute()}')

        V = math.sqrt(P*R)
        I = math.sqrt(P/R)
        Lm = (U_mag - 2*reference_field) / ((I/2)**2)

        assert math.isclose(V, 1.0, abs_tol=1e-3)

        print(f'Mutual inductance calucated from field: {format_si(Lm, "H")}')


if __name__ == '__main__':
    cli()

