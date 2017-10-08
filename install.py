#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# Installer for PolarWindPlot Image Generator Extension
#
# Version: 0.1.0                                      Date: ?? ??????ber 2017
#
# Revision History
#   ?? ??????ber 2017   v0.1.0
#       -   Initial implementation
#

# python imports
from distutils.version import StrictVersion

# weeWX imports
import weewx

from setup import ExtensionInstaller

REQUIRED_VERSION = "3.2.0"
POLARWINDPLOT_VERSION = "0.1.0"

def loader():
    return PolarWindPlotInstaller()

class PolarWindPlotInstaller(ExtensionInstaller):
    def __init__(self):
        if StrictVersion(weewx.__version__) < StrictVersion(REQUIRED_VERSION):
            msg = "%s requires weeWX %s or greater, found %s" % (''.join(('PolarWindPlot ', POLARWINDPLOT_VERSION)),
                                                                 REQUIRED_VERSION,
                                                                 weewx.__version__)
            raise weewx.UnsupportedFeature(msg)
        super(PolarWindPlotInstaller, self).__init__(
            version="0.1.0",
            name='PolarWindPlot',
            description='Polar wind plot image generator for weeWX.',
            author="Gary Roderick Neil Trimboy",
            author_email="gjroderick@gmail.com",
            config={
                'StdReport': {
                    'PolarWindPlot': {
                        'skin': 'PolarWindPlot',
                        'Units': {
                            'Groups': {
                                'group_speed': 'km_per_hour'
                            },
                            'Labels': {
                                'km_per_hour': 'km/h',
                                'knot': 'knots',
                                'meter_per_second': 'm/s',
                                'mile_per_hour': 'mph'
                            },
                        },
                        'Labels': {
                            'compass_points': ['N', 'S', 'E', 'W'],
                            'Generic': {
                                'windGust': 'Gust Speed',
                                'windSpeed': 'Wind Speed'
                            }
                        },
                        'PolarWindPlotGenerator': {
                            'image_background_image': 'None',
                            'image_width': '382',
                            'image_height': '361',
                            'image_background_circle_color': '0xF5F5F5',
                            'image_background_box_color': '0xF5C696',
                            'image_background_range_ring_color': '0xC3D9DD',
                            'plot_border': '5',
                            'legend_bar_width': '10',
                            'font_path': '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
                            'plot_font_size': '10',
                            'plot_font_color': '0x000000',
                            'legend_font_size': '10',
                            'legend_font_color': '0x000000',
                            'label_font_size': '12',
                            'label_font_color': '0x000000',
                            'plot_colors': ['aqua', '0xFF9900', '0xFF3300', '0x009900', '0x00CC00', '0x33FF33', '0x00FFCC'],
                            'petal_width': '16',
                            'day_images': {
                                'period': '86400',
                                'daywindrose': {
                                    'plot_type': 'rose',
                                    'format': 'png',
                                    'windSpeed': {
                                        'label': '24 Hour Wind Rose',
                                        'time_stamp': '%H:%M %-d %b %y',
                                        'time_stamp_location': ['bottom', 'right']
                                    }
                                }
                            }
                        }
                    }
                }
            },
            files=[
                ('bin/user', ['bin/user/polarWindplot.py']),
                ('skins/PolarWindPlot', ['skins/PolarWindPlot/skin.conf'])
            ]
        )
