#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Garret Fick <garret@ficksworkshop.com>

import os

from ..render.rs274x_backend import Rs274xContext
from ..rs274x import read


def test_render_two_boxes():
    """Umaco exapmle of two boxes"""
    _test_render(
        "resources/example_two_square_boxes.gbr", "golden/example_two_square_boxes.gbr"
    )

def _resolve_path(path):
    return os.path.join(os.path.dirname(__file__), path)


def _test_render(gerber_path, png_expected_path, create_output_path=None):
    """Render the gerber file and compare to the expected PNG output.

    Parameters
    ----------
    gerber_path : string
        Path to Gerber file to open
    png_expected_path : string
        Path to the PNG file to compare to
    create_output : string|None
        If not None, write the generated PNG to the specified path.
        This is primarily to help with
    """

    gerber_path = _resolve_path(gerber_path)
    png_expected_path = _resolve_path(png_expected_path)
    if create_output_path:
        create_output_path = _resolve_path(create_output_path)

    gerber = read(gerber_path)

    # Create GBR output from the input file
    ctx = Rs274xContext(gerber.settings)
    gerber.render(ctx)

    actual_contents = ctx.dump()

    # If we want to write the file bytes, do it now. This happens
    if create_output_path:
        with open(create_output_path, "wb") as out_file:
            out_file.write(actual_contents.getvalue())
        # Creating the output is dangerous - it could overwrite the expected result.
        # So if we are creating the output, we make the test fail on purpose so you
        # won't forget to disable this
        assert not True, (
            "Test created the output %s. This needs to be disabled to make sure the test behaves correctly"
            % (create_output_path,)
        )

    # Read the expected PNG file

    with open(png_expected_path, "r") as expected_file:
        expected_contents = expected_file.read()

    assert expected_contents == actual_contents.getvalue()

    return gerber
