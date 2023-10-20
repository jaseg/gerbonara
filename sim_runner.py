#!/usr/bin/env python3

import threading
import queue
import itertools
import pathlib
import tempfile
import sys
import sqlite3
import time
import math
import json
import subprocess

import tqdm
import click
from tabulate import tabulate


def mesh_args(db, coil_id, mesh_type, mesh_file, outfile):
    mesh_type = {'split': '--mesh-split-out', 'normal': '--mesh-out', 'mutual': '--mesh-mutual-out'}[mesh_type]
    rows = db.execute('SELECT key, value FROM results WHERE coil_id=?', (coil_id,)).fetchall()
    args = ['python', '-m', 'twisted_coil_gen_twolayer', mesh_type, mesh_file, '--pcb']
    for k, v in rows:
        prefix, _, k = k.partition('.')
        if v != 'False' and prefix == 'gen':
            args.append('--' + k.replace('_', '-'))
            if v != 'True':
                args.append(str(v))
    args.append(outfile)
    return args


def get_mesh_file(db, mesh_dir, run_id, coil_id, mesh_type):
    db.execute('CREATE TABLE IF NOT EXISTS meshes(coil_id INTEGER, mesh_type TEXT, error INTEGER, filename TEXT, timestamp TEXT DEFAULT current_timestamp, FOREIGN KEY (coil_id) REFERENCES coils(coil_id))') 

    row = db.execute('SELECT * FROM meshes WHERE coil_id=? AND mesh_type=? ORDER BY timestamp DESC LIMIT 1', (coil_id, mesh_type)).fetchone()
    if row is not None:
        mesh_file = mesh_dir / row['filename']
        if mesh_file.is_file():
            return mesh_file

    timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
    return mesh_dir / f'mesh-{run_id}-{coil_id}-{mesh_type}-{timestamp}.msh'


def ensure_mesh(db, mesh_dir, log_dir, run_id, coil_id, mesh_type):
    mesh_file = get_mesh_file(db, mesh_dir, run_id, coil_id, mesh_type)

    if mesh_file.is_file():
        return mesh_file

    db.execute('INSERT INTO meshes(coil_id, mesh_type, error, filename) VALUES (?, ?, 0, ?)', (coil_id, mesh_type, mesh_file.name))
    db.commit()

    mesh_file.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix='.kicad_pcb') as f:
        args = mesh_args(db, coil_id, mesh_type, mesh_file, f.name)
        tqdm.tqdm.write(' '.join(map(str, args)))
        logfile = log_dir / mesh_file.with_suffix('.log').name
        logfile.parent.mkdir(exist_ok=True)
        try:
            res = subprocess.run(args, check=True, capture_output=True, text=True)
            logfile.write_text(res.stdout + res.stderr)

        except subprocess.CalledProcessError as e:
            print('Mesh generation failed with exit code {e.returncode}', file=sys.stderr)
            logfile.write_text(e.stdout + e.stderr)
            print(e.stdout + e.stderr)
            raise

    return mesh_file


@click.group()
@click.option('-d', '--database', default='coil_parameters.sqlite3')
@click.pass_context
def cli(ctx, database):
    ctx.ensure_object(dict)
    def connect():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        return db
    ctx.obj['db_connect'] = connect
    

@cli.command()
@click.pass_context
def list_runs(ctx):
    for row in ctx.obj['db_connect']().execute('SELECT * FROM runs ORDER BY timestamp').fetchall():
        print(row['run_id'], row['timestamp'], row['version'])


@cli.command()
@click.pass_context
def list_runs(ctx):
    for row in ctx.obj['db_connect']().execute('SELECT * FROM runs ORDER BY timestamp').fetchall():
        print(row['run_id'], row['timestamp'], row['version'])


@cli.command()
@click.option('-r', '--run-id')
@click.option('-m', '--mesh-dir', default='meshes')
@click.pass_context
def list_coils(ctx, run_id, mesh_dir):
    db = ctx.obj['db_connect']()
    if run_id is None:
        run_id, = db.execute('SELECT run_id FROM runs ORDER BY timestamp DESC LIMIT 1').fetchone()
    timestamp, = db.execute('SELECT timestamp FROM runs WHERE run_id=?', (run_id,)).fetchone()
    mesh_dir = pathlib.Path(mesh_dir)

    print(f'Listing meshes for run {run_id} at {timestamp}')
    print()

    keys = {'gen.turns': 'N',
            'gen.twists': 'T',
            'gen.single_layer': '1L',
            'gen.inner_diameter': 'ID[mm]',
            'gen.outer_diameter': 'OD[mm]',
            'calculated_fill_factor': 'Fill factor',
            'calculated_approximate_inductance': 'L [µH]',
            'calculated_trace_length': 'track len [mm]',
            'calculated_approximate_resistance': 'R [mΩ]'}
    out = []
    for row in db.execute('SELECT *, MAX(meshes.timestamp) FROM coils LEFT JOIN meshes ON coils.coil_id=meshes.coil_id WHERE run_id=? GROUP BY coils.coil_id, mesh_type ORDER BY meshes.timestamp', (run_id,)).fetchall():
        if row['timestamp']:
            if row['error']:
                state = 'ERROR'
            elif not (mesh_dir / row['filename']).is_file():
                state = 'NOT FOUND'
            else:
                state = 'SUCCESS'
        else:
            state = 'NOT RUN'

        params = dict(db.execute('SELECT key, value FROM results WHERE coil_id=?', (row['coil_id'],)).fetchall())

        if 'calculated_approximate_inductance' in params:
            params['calculated_approximate_inductance'] = f'{float(params["calculated_approximate_inductance"])*1e6:.02f}'

        if 'calculated_trace_length' in params:
            params['calculated_trace_length'] = f'{float(params["calculated_trace_length"])*1e3:.03f}'

        if 'calculated_approximate_resistance' in params:
            params['calculated_approximate_resistance'] = f'{float(params["calculated_approximate_resistance"])*1e3:.03f}'

        if 'calculated_fill_factor' in params:
            params['calculated_fill_factor'] = f'{float(params["calculated_fill_factor"]):.03f}'

        out.append([row['coil_id'], row['mesh_type'], state, row['timestamp']] + [params.get(key, '-') for key in keys])

    print(tabulate(out, headers=['coil', 'mesh', 'state', 'time'] + list(keys.values()), disable_numparse=True, stralign='right'))

@cli.command()
@click.argument('coil_id', type=int)
@click.argument('mesh_type', type=click.Choice(['normal', 'split', 'mutual']))
@click.option('--mesh-file', default='/tmp/test.msh')
@click.option('--pcb-file', default='/tmp/test.kicad_pcb')
@click.pass_context
def cmdline(ctx, coil_id, mesh_type, mesh_file, pcb_file):
    print(' '.join(mesh_args(ctx.obj['db_connect'](), coil_id, mesh_type, mesh_file, pcb_file)))

@cli.group()
@click.option('-r', '--run-id')
@click.option('-l', '--log-dir', default='logs')
@click.option('-m', '--mesh-dir', default='meshes')
@click.pass_context
def run(ctx, run_id, log_dir, mesh_dir):
    if run_id is None:
        run_id, = ctx.obj['db_connect']().execute('SELECT run_id FROM runs ORDER BY timestamp DESC LIMIT 1').fetchone()
    ctx.obj['run_id'] = run_id
    ctx.obj['log_dir'] = pathlib.Path(log_dir)
    ctx.obj['mesh_dir'] = pathlib.Path(mesh_dir)


@run.command()
@click.option('-j', '--num-jobs', type=int, default=1, help='Number of jobs to run in parallel')
@click.pass_context
def generate_meshes(ctx, num_jobs):
    db = ctx.obj['db_connect']()
    rows = [row['coil_id'] for row in db.execute('SELECT coil_id FROM coils WHERE run_id=?', (ctx.obj['run_id'],)).fetchall()]
    mesh_types = ['split', 'normal', 'mutual']

    params = list(itertools.product(rows, mesh_types))
    all_files = {get_mesh_file(db, ctx.obj['mesh_dir'], ctx.obj['run_id'], coil_id, mesh_type): (coil_id, mesh_type) for coil_id, mesh_type in params}
    todo = [(coil_id, mesh_type) for f, (coil_id, mesh_type) in all_files.items() if not f.is_file()]

    q = queue.Queue()
    for elem in todo:
        q.put(elem)

    tq = tqdm.tqdm(total=len(todo))
    def queue_worker():
        try:
            while True:
                coil_id, mesh_type = q.get_nowait()
                try:
                    ensure_mesh(ctx.obj['db_connect'](), ctx.obj['mesh_dir'], ctx.obj['log_dir'], ctx.obj['run_id'], coil_id, mesh_type)
                except subprocess.CalledProcessError:
                    tqdm.tqdm.write(f'Error generating {mesh_type} mesh for {coil_id=}')
                tq.update(1)
                q.task_done()
        except queue.Empty:
            pass

    tqdm.tqdm.write(f'Found {len(params)-len(todo)} meshes out of a total of {len(params)}.')
    tqdm.tqdm.write(f'Processing the remaining {len(todo)} meshes on {num_jobs} workers in parallel.')
    threads = []
    for i in range(num_jobs):
        t = threading.Thread(target=queue_worker, daemon=True)
        t.start()
        threads.append(t)
    q.join()

@run.command()
@click.option('-j', '--num-jobs', type=int, default=1, help='Number of jobs to run in parallel')
@click.pass_context
def self_inductance(ctx, num_jobs):
    db = ctx.obj['db_connect']()

    q = queue.Queue()

    def queue_worker():
        try:
            while True:
                mesh_file, logfile = q.get_nowait()
                with tempfile.TemporaryDirectory() as tmpdir:
                    try:
                        tqdm.tqdm.write(f'Processing {mesh_file}')
                        res = subprocess.run(['python', '-m', 'coil_parasitics', 'inductance', '--sim-dir', tmpdir, mesh_file], check=True, capture_output=True)
                        logfile.write_text(res.stdout+res.stderr)
                    except subprocess.CalledProcessError as e:
                        print(f'Error running simulation, rc={e.returncode}')
                        logfile.write_text(e.stdout+e.stderr)
                tq.update(1)
                q.task_done()
        except queue.Empty:
            pass

    num_meshes, num_params, num_completed = 0, 0, 0
    for coil_id, in db.execute('SELECT coil_id FROM coils WHERE run_id=?', (ctx.obj['run_id'],)).fetchall():
        num_params += 1
        mesh_file = get_mesh_file(ctx.obj['db_connect'](), ctx.obj['mesh_dir'], ctx.obj['run_id'], coil_id, 'normal')
        if mesh_file.is_file():
            num_meshes += 1
            logfile = ctx.obj['log_dir']  / (mesh_file.stem + '_elmer_self_inductance.log')
            if logfile.is_file():
                num_completed += 1
            else:
                q.put((mesh_file, logfile))

    tqdm.tqdm.write(f'Found {num_meshes} meshes out of a total of {num_params} with {num_completed} completed simulations.')
    tqdm.tqdm.write(f'Processing the remaining {num_meshes-num_completed} simulations on {num_jobs} workers in parallel.')

    tq = tqdm.tqdm(total=num_meshes-num_completed)
    threads = []
    for i in range(num_jobs):
        t = threading.Thread(target=queue_worker, daemon=True)
        t.start()
        threads.append(t)
    q.join()

@run.command()
@click.pass_context
def self_capacitance(ctx):
    db = ctx.obj['db_connect']()
    for coil_id, in tqdm.tqdm(db.execute('SELECT coil_id FROM coils WHERE run_id=?', (ctx.obj['run_id'],)).fetchall()):
        mesh_file = get_mesh_file(ctx.obj['db_connect'](), ctx.obj['mesh_dir'], ctx.obj['run_id'], coil_id, 'normal')
        if mesh_file.is_file():
            logfile = ctx.obj['log_dir']  / (mesh_file.stem + '_elmer_self_capacitance.log')
            with tempfile.TemporaryDirectory() as tmpdir:
                try:
                    res = subprocess.run(['python', '-m', 'coil_parasitics', 'self-capacitance', '--sim-dir', tmpdir, mesh_file], check=True, capture_output=True)
                    logfile.write_text(res.stdout+res.stderr)
                except subprocess.CalledProcessError as e:
                    print(f'Error running simulation, rc={e.returncode}')
                    logfile.write_text(e.stdout+e.stderr)


if __name__ == '__main__':
   cli()

