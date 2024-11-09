"""
This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

            Installer for PolarWindPlot Image Generator Extension

Version: 0.1.2                                          Date: 9 November 2024

Revision History
    9 November 2024     v0.1.2
        -   removed all reference to PolarWindPlotDemo skin
        -   remove distutils.StrictVersion dependency
    24 December 2023    v0.1.1
        -   bump version only
    16 June 2022        v0.1.0
        -   Initial implementation
"""

# WeeWX imports
import weewx
from setup import ExtensionInstaller

REQUIRED_WEEWX_VERSION = "3.2.0"
POLARWINDPLOT_VERSION = "0.1.2"


def version_compare(v1, v2):
    """Basic 'distutils' and 'packaging' free version comparison.

    v1 and v2 are WeeWX version numbers in string format.

    Returns:
        0 if v1 and v2 are the same
        -1 if v1 is less than v2
        +1 if v1 is greater than v2
    """

    import itertools
    mash = itertools.zip_longest(v1.split('.'), v2.split('.'), fillvalue='0')
    for x1, x2 in mash:
        if x1 > x2:
            return 1
        if x1 < x2:
            return -1
    return 0


def loader():
    return PolarWindPlotInstaller()


class PolarWindPlotInstaller(ExtensionInstaller):

    def __init__(self):
        if version_compare(weewx.__version__, REQUIRED_WEEWX_VERSION) < 0:
            msg = "%s requires WeeWX %s or greater, found %s" % (''.join(('PolarWindPlot ', POLARWINDPLOT_VERSION)),
                                                                 REQUIRED_WEEWX_VERSION,
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
