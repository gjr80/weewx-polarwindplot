"""
This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

            Installer for PolarWindPlot Image Generator Extension

Version: 0.1.2                                          Date: 27 December 2023

Revision History
    27 December 2023    v0.1.2
        -   removed all reference to PolarWindPlotDemo skin
    24 December 2023    v0.1.1
        -   bump version only
    16 June 2022        v0.1.0
        -   Initial implementation
"""

# python imports
import configobj
from distutils.version import StrictVersion

# WeeWX imports
import weewx
from setup import ExtensionInstaller

REQUIRED_VERSION = "3.2.0"
POLARWINDPLOT_VERSION = "0.1.2"


def loader():
    return PolarWindPlotInstaller()


class PolarWindPlotInstaller(ExtensionInstaller):

    def __init__(self):
        if StrictVersion(weewx.__version__) < StrictVersion(REQUIRED_VERSION):
            msg = "%s requires WeeWX %s or greater, found %s" % (''.join(('PolarWindPlot ', POLARWINDPLOT_VERSION)),
                                                                 REQUIRED_VERSION,
                                                                 weewx.__version__)
            raise weewx.UnsupportedFeature(msg)
        super(PolarWindPlotInstaller, self).__init__(
            version=POLARWINDPLOT_VERSION,
            name='PolarWindPlot',
            description='Polar wind plot image generator for WeeWX.',
            author="Gary Roderick Neil Trimboy",
            author_email="gjroderick@gmail.com",
            files=[('bin/user', ['bin/user/polarwindplot.py'])]
        )
