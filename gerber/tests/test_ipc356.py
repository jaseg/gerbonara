#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Hamilton Kibbe <ham@hamiltonkib.be>
import pytest
from ..ipc356 import *
from ..cam import FileSettings

import os

IPC_D_356_FILE = os.path.join(os.path.dirname(__file__), "resources/ipc-d-356.ipc")


def test_read():
    ipcfile = read(IPC_D_356_FILE)
    assert isinstance(ipcfile, IPCNetlist)


def test_parser():
    ipcfile = read(IPC_D_356_FILE)
    assert ipcfile.settings.units == "inch"
    assert ipcfile.settings.angle_units == "degrees"
    assert len(ipcfile.comments) == 3
    assert len(ipcfile.parameters) == 4
    assert len(ipcfile.test_records) == 105
    assert len(ipcfile.components) == 21
    assert len(ipcfile.vias) == 14
    assert ipcfile.test_records[-1].net_name == "A_REALLY_LONG_NET_NAME"
    assert ipcfile.outlines[0].type == "BOARD_EDGE"
    assert set(ipcfile.outlines[0].points) == {
        (0.0, 0.0),
        (2.25, 0.0),
        (2.25, 1.5),
        (0.0, 1.5),
        (0.13, 0.024),
    }


def test_comment():
    c = IPC356_Comment("Layer Stackup:")
    assert c.comment == "Layer Stackup:"
    c = IPC356_Comment.from_line("C  Layer Stackup:   ")
    assert c.comment == "Layer Stackup:"
    pytest.raises(ValueError, IPC356_Comment.from_line, "P  JOB")
    assert str(c) == "<IPC-D-356 Comment: Layer Stackup:>"


def test_parameter():
    p = IPC356_Parameter("VER", "IPC-D-356A")
    assert p.parameter == "VER"
    assert p.value == "IPC-D-356A"
    p = IPC356_Parameter.from_line("P  VER IPC-D-356A    ")
    assert p.parameter == "VER"
    assert p.value == "IPC-D-356A"
    pytest.raises(ValueError, IPC356_Parameter.from_line, "C  Layer Stackup:   ")
    assert str(p) == "<IPC-D-356 Parameter: VER=IPC-D-356A>"


def test_eof():
    e = IPC356_EndOfFile()
    assert e.to_netlist() == "999"
    assert str(e) == "<IPC-D-356 EOF>"


def test_outline():
    type = "BOARD_EDGE"
    points = [(0.01, 0.01), (2.0, 2.0), (4.0, 2.0), (4.0, 6.0)]
    b = IPC356_Outline(type, points)
    assert b.type == type
    assert b.points == points
    b = IPC356_Outline.from_line(
        "389BOARD_EDGE         X100Y100 X20000Y20000 X40000 Y60000",
        FileSettings(units="inch"),
    )
    assert b.type == "BOARD_EDGE"
    assert b.points == points


def test_test_record():
    pytest.raises(ValueError, IPC356_TestRecord.from_line, "P  JOB", FileSettings())
    record_string = (
        "317+5VDC            VIA   -     D0150PA00X 006647Y 012900X0000          S3"
    )
    r = IPC356_TestRecord.from_line(record_string, FileSettings(units="inch"))
    assert r.feature_type == "through-hole"
    assert r.net_name == "+5VDC"
    assert r.id == "VIA"
    pytest.approx(r.hole_diameter, 0.015)
    assert r.plated
    assert r.access == "both"
    pytest.approx(r.x_coord, 0.6647)
    pytest.approx(r.y_coord, 1.29)
    assert r.rect_x == 0.0
    assert r.soldermask_info == "both"
    r = IPC356_TestRecord.from_line(record_string, FileSettings(units="metric"))
    pytest.approx(r.hole_diameter, 0.15)
    pytest.approx(r.x_coord, 6.647)
    pytest.approx(r.y_coord, 12.9)
    assert r.rect_x == 0.0
    assert str(r) == "<IPC-D-356 +5VDC Test Record: through-hole>"

    record_string = (
        "327+3.3VDC          R40   -1         PA01X 032100Y 007124X0236Y0315R180 S0"
    )
    r = IPC356_TestRecord.from_line(record_string, FileSettings(units="inch"))
    assert r.feature_type == "smt"
    assert r.net_name == "+3.3VDC"
    assert r.id == "R40"
    assert r.pin == "1"
    assert r.plated
    assert r.access == "top"
    pytest.approx(r.x_coord, 3.21)
    pytest.approx(r.y_coord, 0.7124)
    pytest.approx(r.rect_x, 0.0236)
    pytest.approx(r.rect_y, 0.0315)
    assert r.rect_rotation == 180
    assert r.soldermask_info == "none"
    r = IPC356_TestRecord.from_line(record_string, FileSettings(units="metric"))
    pytest.approx(r.x_coord, 32.1)
    pytest.approx(r.y_coord, 7.124)
    pytest.approx(r.rect_x, 0.236)
    pytest.approx(r.rect_y, 0.315)

    record_string = (
        "317                 J4    -M2   D0330PA00X 012447Y 008030X0000          S1"
    )
    r = IPC356_TestRecord.from_line(record_string, FileSettings(units="inch"))
    assert r.feature_type == "through-hole"
    assert r.id == "J4"
    assert r.pin == "M2"
    pytest.approx(r.hole_diameter, 0.033)
    assert r.plated
    assert r.access == "both"
    pytest.approx(r.x_coord, 1.2447)
    pytest.approx(r.y_coord, 0.8030)
    pytest.approx(r.rect_x, 0.0)
    assert r.soldermask_info == "primary side"

    record_string = "317SCL              COMMUNICATION-1    D  40PA00X  34000Y  20000X 600Y1200R270 "
    r = IPC356_TestRecord.from_line(record_string, FileSettings(units="inch"))
    assert r.feature_type == "through-hole"
    assert r.net_name == "SCL"
    assert r.id == "COMMUNICATION"
    assert r.pin == "1"
    pytest.approx(r.hole_diameter, 0.004)
    assert r.plated
    pytest.approx(r.x_coord, 3.4)
    pytest.approx(r.y_coord, 2.0)
