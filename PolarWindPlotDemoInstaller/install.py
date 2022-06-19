"""
This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

                      Installer for PolarWindPlotDemo skin

Version: 0.1.0                                          Date: 16 June 2022

Revision History
    16 June 2022      v0.1.0
        -   Initial implementation
"""

# python imports
import configobj
from distutils.version import StrictVersion

# import StringIO, use six.moves due to python2/python3 differences
from six.moves import StringIO

# WeeWX imports
import weewx
from setup import ExtensionInstaller

REQUIRED_VERSION = "3.2.0"
POLARWINDPLOTDEMO_VERSION = "0.1.0"
# define our config as a multiline string so we can preserve comments
polar_config = """
[StdReport]
    [[PolarWindPlotDemo]]
        skin = PolarWindPlotDemo
        enable = False
"""

# construct our config dict
polar_dict = configobj.ConfigObj(StringIO(polar_config))


def loader():
    return PolarWindPlotDemoSkinInstaller()


class PolarWindPlotDemoSkinInstaller(ExtensionInstaller):

    def __init__(self):
        if StrictVersion(weewx.__version__) < StrictVersion(REQUIRED_VERSION):
            msg = "%s requires WeeWX %s or greater, found %s" % (''.join(('PolarWindPlot ', POLARWINDPLOTDEMO_VERSION)),
                                                                 REQUIRED_VERSION,
                                                                 weewx.__version__)
            raise weewx.UnsupportedFeature(msg)
        super(PolarWindPlotDemoSkinInstaller, self).__init__(
            version="0.1.0",
            name='PolarWindPlotDemo',
            description='Demonstration skin for the WeeWX polar wind plot image generator.',
            author="Gary Roderick",
            author_email="gjroderick@gmail.com",
            config=polar_dict,
            files=[
                ('skins/PolarWindPlot', ['skins/PolarWindPlotDemo/skin.conf',
                                         'skins/PolarWindPlotDemo/polarwindplot/polarplots.html.tmpl',
                                         'skins/PolarWindPlotDemo/font/LICENSE.txt',
                                         'skins/PolarWindPlotDemo/font/OpenSans-Bold.ttf'])
            ]
        )
