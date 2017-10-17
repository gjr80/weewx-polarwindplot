# polarWindPlot.py
#
# A weeWX generator to generate a various polar wind plots.
#
#   Copyright (c) 2017  Gary Roderick           gjroderick<at>gmail.com
#                       Neil Trimboy            <at>gmail.com
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see http://www.gnu.org/licenses/.
#
# Version: 0.1.0                                    Date: ?? ???????ber 2017
#
# Revision History
#   ?? ???????ber 2017  v0.1.0
#       -   initial release
#
"""
legend - used for some plots and not others, presence or absence affects plot size/location calcs. Fixed by defaulting width to 0 and setting/rendering it in render method or just leving it out if not required.

set_plot method must set self.max_ring_value

chnaged delta in trail setuplot


"""

import datetime
import math
import os.path
import syslog
import time
# first try to import from PIL then revert to python-imaging if an error
try:
    from PIL import Image, ImageColor, ImageDraw
except ImportError:
    import Image, ImageColor, ImageDraw

import weewx.reportengine

# from datetime import datetime as dt
from weeplot.utilities import get_font_handle, tobgr
from weeutil.weeutil import accumulateLeaves, option_as_list, TimeSpan, tobool, to_unicode, to_int
from weewx.units import Converter

POLAR_WIND_PLOT_VERSION = '0.1.0'

DEFAULT_PLOT_COLORS = ['lightblue', 'blue', 'midnightblue', 'forestgreen',
                        'limegreen', 'green', 'greenyellow']

DISTANCE_LOOKUP = {'km_per_hour': 'km',
                   'mile_per_hour': 'mile',
                   'meter_per_second': 'km',
                   'knot': 'Nm'}

SPEED_LOOKUP = {'km_per_hour': 'km/h',
                'mile_per_hour': 'mph',
                'meter_per_second': 'm/s',
                'knot': 'kn'}


def logmsg(lvl, msg):
    syslog.syslog(lvl, 'polarwindplot: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)

def logcrt(msg):
    logmsg(syslog.LOG_CRIT, msg)


#=============================================================================
#                        Class PolarWindPlotGenerator
#=============================================================================


class PolarWindPlotGenerator(weewx.reportengine.ReportGenerator):
    """Class to manage the polar wind plot generator.

    The ImageStackedWindRoseGenerator class is a customised report generator
    that produces polar wind rose plots based upon weewx archive data. The
    generator produces image files that may be used included in a web page, a
    weewx web page template or elsewhere as required.

    The wind rose plot charatcteristics may be controlled through option
    settings in the [Stdreport] [[StackedWindRose]] section of weewx.conf.
    """

    def __init__(self, config_dict, skin_dict, gen_ts, first_run, stn_info,
                 record=None):

        # initialise my superclass
        super(PolarWindPlotGenerator, self).__init__(config_dict,
                                                     skin_dict,
                                                     gen_ts,
                                                     first_run,
                                                     stn_info,
                                                     record)

        # get a db manager for our archive
        _binding = self.config_dict['StdArchive'].get('data_binding',
                                                      'wx_binding')
        self.dbmanager = self.db_binder.get_manager(_binding)

    def run(self):
        """Main entry point for generator."""

        # do some setup so we may generate plots
        self.setup()
        # generate the plots
        self.genPlots(self.gen_ts)

    def setup(self):
        """Setup for a plot run."""

        # get the config options for our plots
        self.polar_dict = self.skin_dict['PolarWindPlotGenerator']
        # get the formatter and converter to be used
        self.formatter  = weewx.units.Formatter.fromSkinDict(self.skin_dict)
        self.converter  = weewx.units.Converter.fromSkinDict(self.skin_dict)
        # determine how much logging is desired
        self.log_success = tobool(self.polar_dict.get('log_success', True))
        # ensure that we are in a consistent (and correct) location
        os.chdir(os.path.join(self.config_dict['WEEWX_ROOT'],
                              self.skin_dict['SKIN_ROOT'],
                              self.skin_dict['skin']))

    def genPlots(self, gen_ts):
        """Generate the plots.

        Iterate over each stanza under [PolarWindPlotGenerator] and generate
        plots as required.
        """

        # time period taken to generate plots
        t1 = time.time()
        # set plot count to 0
        ngen = 0
        # loop over each 'time span' section (eg day, week, month, etc)
        for span in self.polar_dict.sections:
            # now loop over all plot names in this 'time span' section
            for plot in self.polar_dict[span].sections:
                # accumulate all options from parent nodes:
                plot_options = accumulateLeaves(self.polar_dict[span][plot])
                # get a polar wind plot object from the factory
                plot_obj = self._polar_plot_factory(plot_options)

                # Get the end time for plot. In order try gen_ts, last known
                # good archive time stamp and then finally current time
                plotgen_ts = gen_ts
                if not plotgen_ts:
                    plotgen_ts = self.dbmanager.lastGoodStamp()
                    if not plotgen_ts:
                        plotgen_ts = time.time()
                # get the period for the plot, default to 24 hours if no period
                # set
                self.period = int(plot_options.get('period', 86400))

                # get the path of the image file we will save
                image_root = os.path.join(self.config_dict['WEEWX_ROOT'],
                                          plot_options['HTML_ROOT'])
                # Get image file format. Can use any format PIL can write,
                # default to png
                format = self.polar_dict.get('format', 'png')
                # get full file name and path for plot
                img_file = os.path.join(image_root, '%s.%s' % (plot,
                                                               format))

                # check whether this plot needs to be done at all
                if self.skipThisPlot(plotgen_ts, img_file, plot):
                    continue

                # create the directory in which the image will be saved, wrap
                # in a try block in case it already exists
                try:
                    os.makedirs(os.path.dirname(img_file))
                except OSError:
                    # directory already exists (or perhaps some other error)
                    pass

                # loop over each 'source' to be added to the plot
                for source in self.polar_dict[span][plot].sections:

                    # accumulate options from parent nodes
                    source_options = accumulateLeaves(self.polar_dict[span][plot][source])

                    # Set plot title if explicitly requested, default to no
                    # title. Config option 'label' used for consistency with
                    # skin.conf ImageGenerator sections.
                    plot_obj.set_title(source_options.get('label', ''))

                    # set timestamp
                    plot_obj.set_timestamp(plotgen_ts, source_options)

                    # Determine the speed and direction archive fields to be
                    # used. Can really only plot windSpeed and windGust, if
                    # anything else default to windSpeed, windDir.
                    speed_field = source_options.get('data_type', source)
                    if speed_field == 'windSpeed':
                        dir_field = 'windDir'
                    elif speed_field == 'windGust':
                        dir_field = 'windGustDir'
                    elif speed_field == 'windrun':
                        speed_field = 'windSpeed'
                        dir_field = 'windDir'
                    else:
                        speed_field == 'windSpeed'
                        dir_field = 'windDir'
                    # hit the archive to get speed and direction plot data
                    _span = TimeSpan(plotgen_ts - self.period + 1, plotgen_ts)
                    (_, speed_time_vec, speed_vec_raw) = self.dbmanager.getSqlVectors(_span,
                                                                                      speed_field)
                    (_, dir_time_vec, dir_vec) = self.dbmanager.getSqlVectors(_span,
                                                                              dir_field)
                    # convert the speed values to the units to be used in the
                    # plot
                    speed_vec = self.converter.convert(speed_vec_raw)
                    # get the units label for our speed data
                    units = self.skin_dict['Units']['Labels'][speed_vec[1]].strip()

                    # add the source data to be plotted to our plot object
                    plot_obj.add_data(speed_field,
                                      speed_vec,
                                      dir_vec,
                                      speed_time_vec,
                                      len(speed_time_vec[0]),
                                      units)

                # call the render() method of the polar plot object to
                # render the entire plot and produce an image
                image = plot_obj.render()

                # now save the file, wrap in a try..except in case we have
                # a problem saving
                try:
                    image.save(img_file)
                    ngen += 1
                except IOError, e:
                    loginf("Unable to save to file '%s': %s" % (img_file, e))
        if self.log_success:
            loginf("Generated %d images for %s in %.2f seconds" % (ngen,
                                                                   self.skin_dict['REPORT_NAME'],
                                                                   time.time() - t1))

    def _polar_plot_factory(self, plot_dict):
        """Factory method to produce a polar plot object."""

        # what type of plot is it
        plot_type = plot_dict.get('plot_type', 'rose').lower()
        # create and return the relevant polar plot object
        if plot_type == 'rose':
            return PolarWindRosePlot(self.skin_dict, plot_dict)
        elif plot_type == 'trail':
            return PolarWindTrailPlot(self.skin_dict, plot_dict)
        elif plot_type == 'spiral':
            return PolarWindSpiralPlot(self.skin_dict, plot_dict)
        elif plot_type == 'scatter':
            return PolarWindScatterPlot(self.skin_dict, plot_dict)
        # if we made it here we don't know about the specified plot so raise
        raise weewx.UnsupportedFeature('Unsupported polar wind plot type: %s' % plot_type)


    def skipThisPlot(self, ts, img_file, plotname):
        """Determine whether the plot is to be skipped or not.

        Successive report cyles will likely produce a windrose that,
        irrespective of period, would be different to the windrose from the
        previous report cycle. In most cases the changes are insignificant so,
        as with the weewx graphical plots, long period plots are generated
        less frequently than shorter period plots. Windrose plots will be
        skipped if:
            (1) no period was specified (need to put entry in syslog)
            (2) plot length is greater than 30 days and the plot file is less
                than 24 hours old
            (3) plot length is greater than 7 but less than 30 day and the plot
                file is less than 1 hour old

        On the other hand, a windrose must be generated if:
            (1) it does not exist
            (2) it is 24 hours old (or older)

        These rules result in windrose plots being generated:
            (1) if an existing plot does not exist
            (2) an existing plot exists but it is older than 24 hours
            (3) every 24 hours when period > 30 days (2592000 sec)
            (4) every 1 hour when period is > 7 days (604800 sec) but
                <= 30 days (2592000 sec)
            (5) every report cycle when period < 7 days (604800 sec)

        Input Parameters:

            img_file: full path and filename of plot file
            plotname: name of plot

        Returns:
            True if plot is to be generated, False if plot is to be skipped.
        """
### For testing only, delete before release
        return False

        # Images without a period must be skipped every time and a syslog
        # entry added. This should never occur, but....
        if self.period is None:
            loginf("Plot '%s' ignored, no period specified" % plotname)
            return True

        # The image definitely has to be generated if it doesn't exist.
        if not os.path.exists(img_file):
            return False

        # If the image is older than 24 hours then regenerate
        if ts - os.stat(img_file).st_mtime >= 86400:
            return False

        # If period > 30 days and the image is less than 24 hours old then skip
        if self.period > 2592000 and ts - os.stat(img_file).st_mtime < 86400:
            return True

        # If period > 7 days and the image is less than 1 hour old then skip
        if self.period >= 604800 and ts - os.stat(img_file).st_mtime < 3600:
            return True

        # Otherwise we must regenerate
        return False


#=============================================================================
#                             Class PolarWindPlot
#=============================================================================


class PolarWindPlot(object):
    """Base class for creating a polar wind plot.

    This class should be specialised for each type of plot."""

    def __init__(self, skin_dict, plot_dict):
        """Initialise an instance of PolarWindPlot."""

        # get config dict for polar plots
        self.plot_dict = plot_dict
        # do we display a legend, default to True
        self.legend = tobool(self.plot_dict.get('legend', True))

        # Set image attributes
        self.image_width = int(self.plot_dict['image_width'])
        self.image_height = int(self.plot_dict['image_height'])
        self.image_back_box_color = int(self.plot_dict['image_background_box_color'], 0)
        self.image_back_circle_color = int(self.plot_dict['image_background_circle_color'], 0)
        self.image_back_range_ring_color = int(self.plot_dict['image_background_range_ring_color'], 0)
        self.image_back_image = self.plot_dict['image_background_image']

        # plot attributes
        self.plot_border = int(self.plot_dict['plot_border'])
        self.font_path = self.plot_dict['font_path']
        self.plot_font_size  = int(self.plot_dict['plot_font_size'])
        self.plot_font_color = int(self.plot_dict['plot_font_color'], 0)
        # colours to be used in the plot
        _colors = option_as_list(self.plot_dict.get('plot_colors',
                                                     DEFAULT_PLOT_COLORS))
        self.plot_colors = []
        for _color in _colors:
            if parse_color(_color, None) is not None:
                # we have a valid color so add it to our list
                self.plot_colors.append(_color)
        # do we have at least 7 colors, if not go through DEFAULT_PLOT_COLORS
        # and add any that are not already in self.plot_colors
        if len(self.plot_colors) < 7:
            for _color in DEFAULT_PLOT_COLORS:
                if _color not in self.plot_colors:
                    self.plot_colors.append(_color)
                # break if we have at least 7 colors
                if len(self.plot_colors) >= 7:
                    break

        # legend attributes
        self.legend_bar_width = int(self.plot_dict['legend_bar_width'])
        self.legend_font_size  = int(self.plot_dict['legend_font_size'])
        self.legend_font_color = int(self.plot_dict['legend_font_color'], 0)
        self.legend_width = 0

        # title/plot label attributes
        self.label_font_size  = int(self.plot_dict['label_font_size'])
        self.label_font_color = int(self.plot_dict['label_font_color'], 0)

        # compass point abbreviations
        compass = option_as_list(skin_dict['Labels'].get('compass_points',
                                                          'N, S, E, W'))
        self.north = compass[0]
        self.south = compass[1]
        self.east = compass[2]
        self.west = compass[3]

        # Boundaries for speed range bands, these mark the colour boundaries
        # on the stacked bar in the legend. 7 elements only (ie 0, 10% of max,
        # 20% of max...100% of max)
        self.speed_factors = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]

    def add_data(self, speed_field, speed_vec, dir_vec, time_vec, samples, units):
        """Add source data to the plot.

        Inputs:
            speed_field: weeWX archive field being used as the source for speed
                         data
            speed_vec:   vector of speed data to be plotted
            dir_vec:     vector of direction data corresponding to speed_vec
            samples:     number of possible vector sample points, this may be
                         greater than or equal to the number of speed_vec or
                         dir_vec elements
            units:       unit label for speed_vec units
        """

        # weeWX archive field that was used for our speed data
        self.speed_field = speed_field
        # find maximum speed from our data
        max_speed = max(speed_vec[0])
        # set upper speed range for our plot, set to a multiple of 10 for a
        # neater display
        self.max_speed_range = (int(max_speed / 10.0) + 1) * 10
        # save the speed and dir data vectors
        self.speed_vec = speed_vec
        self.dir_vec = dir_vec
        self.time_vec = time_vec
        # how many samples in our data
        self.samples = samples
        # set the speed units label
        self.units = units

#### Where should this 'function' reside, does not seem to sit well here as
#### it is very wind rose specific
        # setup a list with speed range boundaries
        speed_list = [0 for x in range(7)]
        # Loop though each speed range boundary and store in speed_list[0]
        i = 1
        while i < 7:
            speed_list[i] = self.speed_factors[i] * self.max_speed_range
            i += 1
        # save speed_list
        self.speed_list = speed_list
####

    def set_title(self, title):
        """Set the plot title.

        Input:
            title: the title text to be displayed on the plot
        """

        self.title = to_unicode(title)

    def set_timestamp(self, ts, options):
        """Set the timestamp to be displayed on the plot.

        Set the format and location of the timestamp to be displayed on the
        plot.

        Inputs:
            ts:      the timestamp to be displayed on th eplot
            options: a 'source' plot options dict
        """

        # set the actual timestamp to be used
        self.timestamp = ts
        # get the timestamp format, use a sane default that should display
        # sensibly for all locales
        self.timestamp_format = options.get('time_stamp', '%x %X')
        # get the timestamp location, if not set then don't display at all
        _location = options.get('time_stamp_location', None)
        self.timestamp_location = _location if _location is not None else None

    def set_polar_grid(self):
        """Setup the polar plot/taget.

        Determine size and location of the polar grid on which the plot is to
        be displayed.
        """

        # Calculate the diameter of the circular plot space in pixels. Two
        # diameters are calculated, one based on image height and one based on
        # image width. We will take the smallest one. To prevent optical
        # distortion for small plots diameter will be divisible by 22
        self.max_plot_dia = min(int((self.image_height - 2 * self.plot_border - self.title_height / 2) / 22.0) * 22,
                                int((self.image_width - (2 * self.plot_border + self.legend_width)) / 22.0) * 22)
        if self.image_width > self.image_height:
            # if the plot is wider than its height
            width, height = self.draw.textsize("W", font=self.plot_font)
            # x coord of polar plot origin(0,0) top left corner
            self.origin_x = self.plot_border + width + 2 + self.max_plot_dia / 2
            # y coord of polar plot origin(0,0) is top left corner
            self.origin_y = int(self.image_height / 2)
        else:
            # if the plot is square or higher than its width
            # x coord of polar plot origin(0,0) top left corner
            self.origin_x = 2 * self.plot_border + self.max_plot_dia / 2
            # y coord of polar plot origin(0,0) is top left corner
            self.origin_y = 2 * self.plot_border + self.max_plot_dia / 2

    def set_legend(self, percentage=False):
        """Setup the legend for a plot.

        Determine the legend width and title.
        """

        # do we display % values against each legend speed label
        self.legend_percentage = percentage
        # create some worst case (width) text to use in estimating the legend
        # width
        if percentage:
            _text = '0 (100%)'
        else:
            _text = '999'
        # estimate width of the legend
        width, height = self.draw.textsize(_text, font=self.legend_font)
        self.legend_width = int(width + 2 * self.legend_bar_width + 1.5 * self.plot_border)
        # get legend title
        self.legend_title = self.get_legend_title(self.speed_field)

    def render(self, speed_vec, dir_vec):
        """Main entry point to render a plot.

        Child classes should define their own render() method.
        """

        pass

    def render_legend(self):
        """Render a polar plot legend."""

        # org_x and org_y = x,y coords of bottom left of legend stacked bar,
        # everything else is relative to this point

        # first get the space required between the polar plot and the legend
        _width, _height = self.draw.textsize('E', font=self.plot_font)
        org_x = self.origin_x + self.max_plot_dia / 2 + _width + 10
        org_y = self.origin_y + self.max_plot_dia / 2 - self.max_plot_dia / 22
        # bulb diameter
        bulb_d = int(round(1.2 * self.legend_bar_width, 0))
        # draw stacked bar and label with values
        i = 6
        while i > 0:
            # draw the rectangle for the stacked bar
            x0 = org_x
            y0 = org_y - (0.85 * self.max_plot_dia * self.speed_factors[i])
            x1 = org_x + self.legend_bar_width
            y1 = org_y
            self.draw.rectangle([(x0, y0), (x1,y1)],
                                fill=self.plot_colors[i],
                                outline='black')
            # add the label
            # first, position the label
            label_width, label_height = self.draw.textsize(str(self.speed_list[i]),
                                                           font=self.legend_font)
            x = org_x + 1.5 * self.legend_bar_width
            y = org_y - label_height / 2 - (0.85 * self.max_plot_dia * self.speed_factors[i])
            # get the basic label text
            snippets = (str(int(round(self.speed_list[i], 0))), )
            # if required add a bracketed percentage
            if self.legend_percentage:
                snippets += (' (',
                             str(int(round(100 * self.speed_bin[i]/sum(self.speed_bin), 0))),
                             '%)')
            # create the final label text
            text = ''.join(snippets)
            # render the label text
            self.draw.text((x, y),
                           text,
                           fill=self.legend_font_color,
                           font=self.legend_font)
            # do the next rectangle down
            i -= 1

        # draw 'Calm' label and '0' speed label/percentage
        # position the 'Calm' label
        t_width, t_height = self.draw.textsize('Calm', font=self.legend_font)
        x = org_x - t_width - 2
        y = org_y - t_height / 2 - (0.85 * self.max_plot_dia * self.speed_factors[0])
        # render the 'Calm' label
        self.draw.text((x , y),
                       'Calm',
                       fill=self.legend_font_color,
                       font=self.legend_font)
        # position the '0' speed label/percentage
        t_width, t_height = self.draw.textsize(str(self.speed_list[0]),
                                               font=self.legend_font)
        x = org_x + 1.5 * self.legend_bar_width
        y = org_y - t_height / 2 - (0.85 * self.max_plot_dia * self.speed_factors[0])
        # get the basic label text
        snippets = (str(self.speed_list[0]), )
        # if required add a bracketed percentage
        if self.legend_percentage:
            snippets += (' (',
                         str(int(round(100.0 * self.speed_bin[0] / sum(self.speed_bin), 0))),
                         '%)')
        # create the final label text
        text = ''.join(snippets)
        # render the label
        self.draw.text((x, y),
                       text,
                       fill=self.legend_font_color,
                       font=self.legend_font)

        # draw 'calm' bulb on bottom of stacked bar
        bounding_box = (org_x - bulb_d / 2 + self.legend_bar_width / 2,
                        org_y - self.legend_bar_width / 6,
                        org_x + bulb_d / 2 + self.legend_bar_width / 2,
                        org_y - self.legend_bar_width / 6 + bulb_d)
        self.draw.ellipse(bounding_box, outline='black', fill=self.plot_colors[0])

        # draw legend title
        # position the legend title
        t_width, tHeight = self.draw.textsize(self.legend_title,
                                              font=self.legend_font)
        x = org_x + self.legend_bar_width / 2 - t_width / 2
        y = org_y - 5 * tHeight / 2 - (0.85 * self.max_plot_dia)
        # render the title
        self.draw.text((x, y),
                       self.legend_title,
                       fill=self.legend_font_color,
                       font=self.legend_font)

        # draw legend units label
        # position the units label
        t_width, tHeight = self.draw.textsize('(' + self.units + ')',
                                              font=self.legend_font)
        x = org_x + self.legend_bar_width / 2 - t_width / 2
        y = org_y - 3 * tHeight / 2 - (0.85 * self.max_plot_dia)
        text = ''.join(('(', self.units, ')'))
        # render the units label
        self.draw.text((x, y),
                       text,
                       fill=self.legend_font_color,
                       font=self.legend_font)

    def render_polar_grid(self, plot_type):
        """Render polar plot grid.

        Render the axes, speed circles and labels.
        """

        # speed circles

        # set some parameters that define the location/size of the speed rings
#        if self.plot_type == "scatter" or self.plot_type == "spiral" or self.plot_type == "trail" :
#            bbMinRad = self.max_plot_dia/10.0 # Calc distance between windrose
#                                           # range rings.
#            delta = 0
#            d2 = 0
#        else :
#            # a Windrose
#            bbMinRad = self.max_plot_dia/11 # Calc distance between windrose
#                                           # range rings. Note that 'calm'
#                                           # bulleye is at centre of plot
#                                           # with diameter equal to bbMinRad
#                                           # TODO may need 11.0 here also, I needed to make 10.0 for #spiral/scatter to avoid integer rounding problems
#            delta = 0.5
#            d2 = 1
        # Calc distance between windrose range rings. Note that 'calm' bulleye
        # is at centre of plot with diameter equal to bbMinRad.
        #
        # TODO Suggested improvement .... too many magic numbers in here
        # in essence they are
        # no_of_rings, which is 5 in all our cases
        # centre_ring (0.5 for rose, 0 otherwise)
        #
        # bbMinRad = self.max_plot_dia/2.0*(no_of_rings + centre_ring)
        # delta = centre_ring
        # d2 = 2* delta (do we even need to define it or is it somethign else that happens to be 2*delta)
        if plot_type == "scatter" or plot_type == "spiral" or plot_type == "trail" :
            no_of_rings = 5
            centre_ring = 0
        else :
            no_of_rings = 5
            centre_ring = 0.5
        bbMinRad = self.max_plot_dia/(2.0*(no_of_rings + centre_ring))
        delta = centre_ring
        #d2 = 2 * centre_ring
        # locate/size then render each speed ring starting from the outside
        i = no_of_rings # TODO Magic number 5 is related to the 10 and 11 above, changed here, pending testing
        while i > 0: # TODO make for range loop ?
            # create a bound box for the ring
            bbox = (self.origin_x - bbMinRad * (i + delta),
                    self.origin_y - bbMinRad * (i + delta),
                    self.origin_x + bbMinRad * (i + delta),
                    self.origin_y + bbMinRad * (i + delta))
            # render the ring
            self.draw.ellipse(bbox,
                              outline=self.image_back_range_ring_color,
                              fill=self.image_back_circle_color)
            # next ring
            i -= 1

        # render vertical centre line
        x0 = self.origin_x
        y0 = self.origin_y - self.max_plot_dia / 2 - 2
        x1 = self.origin_x
        y1 = self.origin_y + self.max_plot_dia / 2 + 2
        self.draw.line([(x0, y0), (x1, y1)],
                       fill=self.image_back_range_ring_color)

        # render horizontal centre line
        x0 = self.origin_x - self.max_plot_dia / 2 - 2
        y0 = self.origin_y
        x1 = self.origin_x + self.max_plot_dia / 2 + 2
        y1 = self.origin_y
        self.draw.line([(x0, y0), (x1, y1)],
                       fill=self.image_back_range_ring_color)

        # render N,S,E,W markers
        # North
        width, height = self.draw.textsize(self.north, font=self.plot_font)
        x = self.origin_x - width /2
        y = self.origin_y - self.max_plot_dia / 2 - 1 - height
        self.draw.text((x, y),
                       self.north,
                       fill=self.plot_font_color,
                       font=self.plot_font)
        # South
        width, height = self.draw.textsize(self.south, font=self.plot_font)
        x = self.origin_x - width /2
        y = self.origin_y + self.max_plot_dia / 2 + 3
        self.draw.text((x, y),
                       self.south,
                       fill=self.plot_font_color,
                       font=self.plot_font)
        # West
        width, height = self.draw.textsize(self.west, font=self.plot_font)
        x = self.origin_x - self.max_plot_dia / 2 - 1 - width
        y = self.origin_y - height / 2
        self.draw.text((x, y),
                       self.west,
                       fill=self.plot_font_color,
                       font=self.plot_font)
        # East
        width, height = self.draw.textsize(self.east, font=self.plot_font)
        x = self.origin_x + self.max_plot_dia / 2 + 1
        y = self.origin_y - height / 2
        self.draw.text((x, y),
                       self.east,
                       fill=self.plot_font_color,
                       font=self.plot_font)

        # render labels on rings
        labels = list((None, None, None, None, None))   # list to hold ring labels
        i = 1
        while i < 6: # TODO make for range
            # get the label to be used for this ring
            labels[i - 1] = self.get_ring_label(i)
            # next ring
            i += 1
        # calculate location of ring labels
        # offset_x/y is the x/y offset for a label in half ring steps
        angle = 7 * math.pi / 4 + int(self.label_dir / 4.0) * math.pi / 2
        #if plot_type == "scatter" or plot_type == "spiral" or plot_type == "trail":
        offset_x = int(round(self.max_plot_dia / (4 * (no_of_rings + centre_ring)) * math.cos(angle), 0))
        offset_y = int(round(self.max_plot_dia / (4 * (no_of_rings + centre_ring)) * math.sin(angle), 0))
        #else:
        #    offset_x = int(round(self.max_plot_dia / 22 * math.cos(angle), 0))
        #    offset_y = int(round(self.max_plot_dia / 22 * math.sin(angle), 0))
        # Draw ring labels. Note leave inner ring blank due to lack of space.
        # For clarity each label (except for outside ring) is drawn on a
        # rectangle with background colour set to that of the circular plot.

#### TODO Spiral has this as 2 : NT COMMENT I THINK THIS IS AN OLD DEAD COMMENT THAT CAN BE REMOVED
        # Draw ring labels, 1 is inner and 5 is outer
        i = 1
        while i < 6: # TODO make for range
            if labels[i-1] is not None:
                width, height = self.draw.textsize(labels[i-1],
                                                   font=self.plot_font)
                x0 = self.origin_x + (2 * (i + centre_ring)) * offset_x - width / 2
                y0 = self.origin_y + (2 * (i + centre_ring)) * offset_y - height / 2
                if i < 5:
                    # The inner most labels have a white box painted first
                    x1 = self.origin_x + (2 * (i + centre_ring)) * offset_x + width / 2
                    y1 = self.origin_y + (2 * (i + centre_ring)) * offset_y + height / 2
                    self.draw.rectangle([(x0, y0), (x1, y1)],
                                        fill=self.image_back_circle_color)
                self.draw.text((x0, y0),
                               labels[i - 1],
                               fill=self.plot_font_color,
                               font=self.plot_font)
            i += 1

        # # draw outside ring label
        # if labels[i - 1] is not None:
            # width, height = self.draw.textsize(labels[i-1], font=self.plot_font)
            # x0 = self.origin_x + (2 * i + d2) * offset_x - width / 2
            # y0 = self.origin_y + (2 * i + d2) * offset_y - height / 2
            # self.draw.text((x0, y0),
                           # labels[i - 1],
                           # fill=self.plot_font_color,
                           # font=self.plot_font)

    def render_title(self):
        """Render polar plot title."""

        # draw plot title (label) if any
        if self.title:
            width, height = self.draw.textsize(self.title, font=self.label_font)
            self.title_height = height
            try:
                self.draw.text((self.origin_x-width / 2, height / 2),
                               self.title,
                               fill=self.label_font_color,
                               font=self.label_font)
            except UnicodeEncodeError:
                self.draw.text((self.origin_x - width / 2, height / 2),
                               self.title.encode("utf-8"),
                               fill=self.label_font_color,
                               font=self.label_font)
        else:
            self.title_height = 0

    def render_timestamp(self):
        """Render plot timestamp."""

        # we only render if we have a location to put the timestamp otherwise
        # we have nothing to do
        if self.timestamp_location:
            _dt = datetime.datetime.fromtimestamp(self.timestamp)
            text = _dt.strftime(self.timestamp_format)
            width, height = self.draw.textsize(text, font=self.label_font)
            if 'TOP' in self.timestamp_location:
                y = self.plot_border + height
            else:
                y = self.image_height - self.plot_border - height
            if 'LEFT' in self.timestamp_location:
                x = self.plot_border
            elif ('CENTER' in self.timestamp_location) or ('CENTRE' in self.timestamp_location):
                x = self.origin_x - width / 2
            else:
                x = self.image_width - self.plot_border - width
#### Should this be using legendFont or labelFont?
            self.draw.text((x, y), text,
                           fill=self.legend_font_color,
                           font=self.legend_font)

    def get_image(self):
        """Get an image object on which to render the plot."""

        try:
            _image = Image.open(self.image_back_image)
        except IOError:
            _image = Image.new("RGB",
                               (self.image_width, self.image_height),
                               self.image_back_box_color)
        return _image

    def get_font_handles(self):
        """Get font handles for the fonts to be used."""

        # font used on the plot area
        self.plot_font = get_font_handle(self.font_path,
                                         self.plot_font_size)
        # font used for the legend
        self.legend_font = get_font_handle(self.font_path,
                                           self.legend_font_size)
        # font used for labels/title
        self.label_font = get_font_handle(self.font_path,
                                          self.label_font_size)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        This method should be overridden in each PolarWindPlot child object.

        Each polar plot ring is labelled. This label can be a percentage, a
        value or some other text. The get_ring_label() method returns the label
        to be used on a given ring. There are 5 equally spaced rings numbered
        from 1 (inside) to 5 (outside). A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a lalbel is required, will be from
                  1 (inside) to 5 (outside) inclusive

        Returns:
            label text for the given ring number
        """

        return None

    def joinCurve(self, start_x, start_y, start_r, start_a, end_x, end_y, end_r, end_a, color):
        """Join two points with a curve.

        Draw a smooth curve between two points by joing them with straight line
        segments covering 1 degree of arc.

        Inputs:
            start_x: start point plot x coordinate
            start_y: start point plot y coordinate
            start_r: start point vector radius
            start_a: start point vector direction
            end_x:   end point plot x coordinate
            end_y:   end point plot y coordinate
            end_r:   end point vector radius
            end_a:   end point vector direction
            color:   color to be used
        """

        # calculate the angle in degrees between the start and end vectors and
        # the 'direction of plotting'
        if (end_a - start_a) % 360 <= 180:
            start = start_a
            end = end_a
            dir = 1
        else:
            start = end_a
            end = start_a
            dir = -1
        angle_span = (end - start) % 360
        # initialise our start plot points
        last_x = start_x
        last_y = start_y
        a = 1
        # while statement to allow us to draw in 1 degree increments
        while a < angle_span:
            # calculate the radius of the vector of next point we will draw to
            radius = start_r + (end_r - start_r) * a / angle_span
            # get the x and y plot coords of the next point
            x = int(self.origin_x + radius * math.sin(math.radians(start + (a * dir))))
            y = int(self.origin_y - radius * math.cos(math.radians(start + (a * dir))))
            # define the start and end points of the line between the current
            # point to the last
            xy = (last_x, last_y, x, y)
            # draw a straight line
            self.draw.line(xy, fill=color, width=1)
            # save our current point as the last point
            last_x = x
            last_y = y
            # increment the angle
            a += 1
        # once we have finished we need to draw the last incremental point to
        # our orignal end point
        # define the line to be drawn
        xy = (last_x, last_y, end_x, end_y)
        # draw the line
        self.draw.line(xy, fill=color, width=1)

    def get_legend_title(self, source=None):
        """Produce a title for the legend."""

        if source == 'windSpeed':
            return 'Wind Speed'
        elif source == 'windGust':
            return 'Wind Gust'
        else:
            return 'Legend'

    def get_speed_color(self, source, speed):
        """Determine the speed based colour to be used."""

        if source == "speed" :
            # colour is a function of speed
            lookup = 5
            while lookup >= 0: # TODO Yuk, 7 colours is hard coded
                if speed > self.speed_list[lookup] :
                    result = self.plot_colors[lookup + 1]
                    break
                lookup -= 1
        else:
            # constant colour
            result = source
        return result

#=============================================================================
#                          Class PolarWindRosePlot
#=============================================================================


class PolarWindRosePlot(PolarWindPlot):
    """Specialised class to generate a polar wind rose plot."""

    def __init__(self, skin_dict, plot_dict):
        """Initialise a PolarWindRosePlot object."""

        # initialise my superclass
        super(PolarWindRosePlot, self).__init__(skin_dict, plot_dict)

        # get petal width, if not defined then set default to 16
        self.petal_width = int(self.plot_dict.get('windrose_plot_petal_width', 16))

    def render(self):
        """Main entry point to generate a polar wind rose plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # setup the legend
        self.set_legend(percentage=True)
#### This needs to be fixed, should not render until setup complete
        if self.title:
            width, height = self.draw.textsize(self.title, font=self.label_font)
            self.title_height = height
        else:
            self.title_height = 0

        # set up the background polar grid
        self.set_polar_grid()
        self.set_plot()

        self.render_title()
        self.render_legend()

        self.render_polar_grid("rose")
        # finally render the plot
        self.render_plot()
        self.render_timestamp()
        # return the completed plot image
        return image

    def set_plot(self):
        """Setup the rose plot rnder."""

        # Setup 2D list for wind direction. wind_bin[0] represents each of
        # 16 compass directions ([0] is N, [1] is ENE etc). wind_bin[1] holds
        # count of obs in a partiuclr speed range for given direction
        wind_bin = [[0 for x in range(7)] for x in range(17)]
        # setup list to hold obs counts for each speed range
        speed_bin = [0 for x in range(7)]
        # Loop through each sample and increment direction counts and speed
        # ranges for each direction as necessary. 'None' direction is counted
        # as 'calm' (or 0 speed) and (by definition) no direction and are
        # plotted in the 'bullseye' on the plot.
        i = 0
        while i < self.samples:
            this_speed_vec = self.speed_vec[0][i]
            this_dir_vec = self.dir_vec[0][i]
            if (this_speed_vec is None) or (this_dir_vec is None):
                wind_bin[16][6] += 1
            else:
                bin = int((this_dir_vec + 11.25) / 22.5) % 16 # TODO 16 is a magic number
                if this_speed_vec > self.speed_list[5]:
                    wind_bin[bin][6] += 1
                elif this_speed_vec > self.speed_list[4]:
                    wind_bin[bin][5] += 1
                elif this_speed_vec > self.speed_list[3]:
                    wind_bin[bin][4] += 1
                elif this_speed_vec > self.speed_list[2]:
                    wind_bin[bin][3] += 1
                elif this_speed_vec > self.speed_list[1]:
                    wind_bin[bin][2] += 1
                elif this_speed_vec > 0:
                    wind_bin[bin][1] += 1
                else:
                    wind_bin[bin][0] += 1
            i += 1
        # add 'None' obs to 0 speed count
        speed_bin[0] += wind_bin[16][6]
        # don't need the 'None' counts so we can delete them
        del wind_bin[-1]
        # Now set total (direction independent) speed counts. Loop through
        # each petal speed range and increment direction independent speed
        # ranges as necessary.
        j = 0
        while j < 7:
            i = 0
            while i < 16:
                speed_bin[j] += wind_bin[i][j]
                i += 1
            j += 1
        # Calc the value to represented by outer ring (range 0 to 1). Value to
        # rounded up to next multiple of 0.05 (ie next 5%)
        self.maxRingValue = (int(max(sum(b) for b in wind_bin)/(0.05 * self.samples)) + 1) * 0.05
        # Find which wind rose arm to use to display ring range labels - look
        # for one that is relatively clear. Only consider NE, SE, SW and NW;
        # preference in order is SE, SW, NE and NW. label_dir stored as an
        # integer corresponding to the windrose arms, 2=NE, 6=SE, 10=SW, 14=NW.
        # Is SE clear, if < 30% of the max value is in use its clear.
        if sum(wind_bin[6]) / float(self.samples) <= 0.3 * self.maxRingValue:
            # SE is clear so take it
            label_dir = 6
        else:
            # SE not clear so look at the others in turn
            for i in [10, 2, 14]:
                # is SW, NE or NW clear
                if sum(wind_bin[i])/float(self.samples) <= 0.3 * self.maxRingValue:
                    # it's clear so take it
                    label_dir = i
                    # we have finished looking so exit the for loop
                    break
            else:
                # none are free so take the smallest of the four
                # set max possible number of readings + 1
                labelCount = self.samples + 1
                # start at NE
                i = 2
                # iterate over the possible directions
                for i in [2, 6, 10, 14]:
                    # if this direction has fewer obs than previous best then
                    # remember it
                    if sum(wind_bin[i]) < labelCount:
                        # set min count so far to this bin
                        labelCount = sum(wind_bin[i])
                        # set label_dir to this direction
                        label_dir = i
        self.label_dir = label_dir
        # save wind_bin, we need it later to render the rose plot
        self.wind_bin = wind_bin
        self.speed_bin = speed_bin
        # 'units' to use on ring labels
        self.ring_units = '%'
        self.max_ring_value = self.maxRingValue

    def render_plot(self):
        """Render the rose plot data."""

        # Plot wind rose petals. Each petal is constructed from overlapping
        # pie slices starting from outside (biggest) and working in (smallest)
        # start at 'North' windrose petal
        a = 0
        # loop through each wind rose arm
        while a < len(self.wind_bin):
            s = len(self.speed_list) - 1
            cumRadius = sum(self.wind_bin[a])
            if cumRadius > 0:
                armRadius = int((10 * self.max_plot_dia * sum(self.wind_bin[a])) / (11 * 2.0 * self.maxRingValue * self.samples))
                while s > 0:
                    # calc radius of current arm
                    pieRadius = int(round(armRadius * cumRadius/sum(self.wind_bin[a]) + self.max_plot_dia / 22,0))
                    # set bound box for pie slice
                    bbox = (self.origin_x-pieRadius,
                            self.origin_y-pieRadius,
                            self.origin_x+pieRadius,
                            self.origin_y+pieRadius)
                    # draw pie slice
                    self.draw.pieslice(bbox,
                                       int(a * 22.5 - 90 - self.petal_width / 2),
                                       int(a * 22.5 - 90 + self.petal_width / 2),
                                       fill=self.plot_colors[s], outline='black')
                    cumRadius -= self.wind_bin[a][s]
                    # move 'in' for next pieslice
                    s -= 1
            # next arm
            a += 1
        # draw 'bullseye' to represent windSpeed=0 or calm
        # produce the label
        label0 = str(int(round(100.0 * self.speed_bin[0] / sum(self.speed_bin), 0))) + '%'
        # work out its size, particularly its width
        textWidth, textHeight = self.draw.textsize(label0, font=self.plot_font)
        # size the bound box
        bbox = (int(self.origin_x - self.max_plot_dia / 22),
                int(self.origin_y - self.max_plot_dia / 22),
                int(self.origin_x + self.max_plot_dia / 22),
                int(self.origin_y + self.max_plot_dia / 22))
        # draw the circle
        self.draw.ellipse(bbox,
                          outline='black',
                          fill=self.plot_colors[0])
        # display the value
        self.draw.text((int(self.origin_x-textWidth / 2), int(self.origin_y - textHeight / 2)),
                       label0,
                       fill=self.plot_font_color,
                       font=self.plot_font)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled, usually with a number followed by
        unit string. The get_ring_label() method returns the label to be used
        on a given ring. There are 5 equally spaced rings numbered from
        1 (inside) to 5 (outside). A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a lalbel is required, will be from
                  1 (inside) to 5 (outside) inclusive

        Returns:
            label text for the given ring number
        """

        label_inc = self.max_ring_value / 5
        return ''.join([str(int(round(label_inc * ring * 100, 0))),
                        self.ring_units])


#=============================================================================
#                          Class PolarWindTrailPlot
#=============================================================================


class PolarWindTrailPlot(PolarWindPlot):
    """Specialise class to generate a trail plot."""

    def __init__(self, skin_dict, plot_dict):
        """Initialise a PolarWindTrailPlot object."""

        # initialise my superclass
        super(PolarWindTrailPlot, self).__init__(skin_dict, plot_dict)

        # get marker_style, default to 'circle'
        self.marker_style = plot_dict.get('marker_style', 'circle')
        # get line_style, default to radial
        self.line_style = self.plot_dict.get('line_style', 'none')

        # Get line_color, can be 'speed', 'age' or a valid color. Default to
        # 'speed'.
        self.line_color = plot_dict.get('line_color', 'speed')
        if self.line_color not in ['speed', 'age']:
            self.line_color = parse_color(self.line_color, 'speed')

        # Get marker_color, can be 'speed' or a valid color. Default to 'speed'.
        self.marker_color = plot_dict.get('marker_color', 'speed')
        if self.marker_color != 'speed':
            self.marker_color = parse_color(self.marker_color, 'speed')

        # get vector_color, default to red
        _color = self.plot_dict.get('vector_color', 'red')
        # check that it is a valid color
        self.vector_color = parse_color(self.plot_dict.get('vector_color', 'red'),
                                        'red')

#### not sure about the 'rest of the points comment, does this mean marker_color? (which is not default None)
#### This should make more sense now
        # get end_point_color, default to "none" which is points coloured as per the rest of the points as defined by marker_color
        # can be 'none' or a valid color.
        # TODO inconsistent use of None or "none" in code/skin for these colours.modes that can take different values inlcuding none
        self.end_point_color = parse_color(self.plot_dict.get('end_point_color', None),
                                     None)

        # set some properties to startup defaults
        self.max_vector_radius = None

    def render(self):
        """Main entry point to generate a polar wind rose plot."""
        """         # Setup windrose plot. Plot circles, range rings, range
                    # labels, N-S and E-W centre lines and compass pont labels
                    if self.plot_type != "trail":
                        self.windRosePlotSetup() # We cant call this straight away for trails, we have to make a pass through the data first
        """

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # setup the legend
        self.set_legend()
#### This needs to be fixed, should not render until setup complete
        if self.title:
            width, height = self.draw.textsize(self.title, font=self.label_font)
            self.title_height = height
        else:
            self.title_height = 0

        # set up the background polar grid
        self.set_polar_grid()
        self.set_plot()

        self.render_title()
        self.render_legend()

        self.render_polar_grid("trail")
        # finally render the plot
        self.render_plot()
        self.render_timestamp()
        # return the completed plot image
        return image

    def set_plot(self):
        """Setup the trail plot render.

        Perform any calculations or set any properties required to render the
        polar trail plot.
        """

        # To scale the wind trail to fit the plot area we need to know how big
        # the vector will be. We do this by doing a dry run just calculating
        # the overall vector.
        self.max_vector_radius = 0
        vec_x = 0
        vec_y = 0
        # how we calculate distance depends on the wpeed units in use
        if self.speed_vec[1] == 'meter_per_second' or self.speed_vec[1] == 'meter_per_second':
            factor = 1000.0
        else:
            factor = 3600.0
        # iterate over the samples, ignore the first since we don't know what
        # period (delta) it applies to
        for i in range(1, self.samples):
            this_dir_vec = self.dir_vec[0][i]
            this_speed_vec = self.speed_vec[0][i]
            # ignore any speeds that are 0 or None and any directions that are
            # None
            if this_speed_vec is None or this_dir_vec is None or this_speed_vec == 0.0:
                continue
            # the period in sec the current speed applies to
            delta = self.time_vec[0][i] - self.time_vec[0][i-1]
            # the corresponding distance
            dist = this_speed_vec * delta / factor
            # calculate new vector from centre for this point
            vec_x += dist * math.sin(math.radians((this_dir_vec + 180) % 360))
            vec_y += dist * math.cos(math.radians((this_dir_vec + 180) % 360))
            vec_radius = math.sqrt(vec_x**2  + vec_y**2)
            if vec_radius > self.max_vector_radius:
                self.max_vector_radius = vec_radius

        # set the location of the ring labels, in this case SE
        self.label_dir = 6
        # determine the 'unit' label to use on ring labels
        self.ring_units = DISTANCE_LOOKUP[self.speed_vec[1]]

    def render_plot(self):
        """Render the trail plot data."""

        # radius of plot area in pixels
        plot_radius =  self.max_plot_dia / 2
        # scaling to be applied to calculated vectors
        scale = plot_radius / self.max_vector_radius
        # how we calculate distance depends on the wpeed units in use
        if self.speed_vec[1] == 'meter_per_second' or self.speed_vec[1] == 'meter_per_second':
            factor = 1000.0
        else:
            factor = 3600.0
        # Unfortunately PIL does not allow us to work with layers so we need to
        # process our data twice; once to plot the 'trail' and a second time to
        # plot any markers

        # plot the markers
        if self.marker_style is not None:
            vec_x = 0
            vec_y = 0
            # iterate over the samples, ignore the first since we don't know what
            # period (delta) it applies to
            for i in range(1, self.samples): # TODO NT Check this, its been changed
                this_dir_vec = self.dir_vec[0][i]
                this_speed_vec = self.speed_vec[0][i]
                # ignore any speeds that are 0 or None and any directions that
                # are None
                if this_speed_vec is None or this_dir_vec is None or this_speed_vec == 0.0:
                    continue
                # the period in sec the current speed applies to
                delta = self.time_vec[0][i] - self.time_vec[0][i-1]
                # the corresponding distance
                dist = this_speed_vec * delta / factor
                # calculate new vector from centre for this point
                vec_x += dist * math.sin(math.radians((this_dir_vec + 180) % 360))
                vec_y += dist * math.cos(math.radians((this_dir_vec + 180) % 360))
                # scale the vector to our polar plot area
                x = self.origin_x + vec_x * scale
                y = self.origin_y - (vec_y * scale)
#### TODO next bit deciding colour is duplicated code, push to function
                if self.marker_color == "speed" :
                    # makes lines function of speed
                    lookup = 5
                    while lookup >= 0: # TODO Yuk, 7 colours is hard coded
                        if this_speed_vec > self.speed_list[lookup] :
                            markercolor = self.plot_colors[lookup + 1]
                            break
                        lookup -= 1
                else:
                    # constant colour
                    markercolor = self.marker_color
                # if this is the last point make it different colour if needed
                if i == self.samples - 1:
                    if self.end_point_color:
                        markercolor = self.end_point_color
                # now draw the markers
                if self.marker_style == "dot":
                    point = (int(x), int(y))
                    self.draw.point(point, fill=markercolor)
                elif self.marker_style == "circle":
                    bbox = (int(x - 1), int(y - 1), int(x + 1), int(y + 1))
                    self.draw.ellipse(bbox, outline=markercolor,
                                      fill=markercolor)
                elif self.marker_style == "cross":
                    horline = (int(x - 1), int(y), int(x + 1), int(y))
                    verline = (int(x), int(y - 1), int(x), int(y + 1))
                    self.draw.line(horline, fill=markercolor, width=1)
                    self.draw.line(verline, fill=markercolor, width=1)

        # now plot the lines
        lastx = self.origin_x
        lasty = self.origin_y
        vec_x = 0
        vec_y = 0
        # iterate over the samples, ignore the first since we don't know what
        # period (delta) it applies to
        for i in range(1, self.samples):
            this_dir_vec = self.dir_vec[0][i]
            this_speed_vec = self.speed_vec[0][i]
            # ignore any speeds that are 0 or None and any directions that
            # are None
            if this_speed_vec is None or this_dir_vec is None or this_speed_vec == 0.0:
                continue
            # the period in sec the current speed applies to
            delta = self.time_vec[0][i] - self.time_vec[0][i-1]
            # the corresponding distance
            dist = this_speed_vec * delta / factor
            # calculate new vector from centre for this point
            vec_x += dist * math.sin(math.radians((this_dir_vec + 180) % 360))
            vec_y += dist * math.cos(math.radians((this_dir_vec + 180) % 360))
            # scale the vector to our polar plot area
            x = self.origin_x + vec_x * scale
            y = self.origin_y - (vec_y * scale)
            thisa = int(this_dir_vec)
#### TODO next bit deciding colour is duplicated code, push to function
            if self.line_color == "speed":
                # makes lines function of speed
                lookup = 5
#### TODO Yuk, 7 colours is hard coded
                while lookup >= 0:
                    if self.speed_vec[0][i] > self.speed_list[lookup]:
                        linecolor = self.plot_colors[lookup + 1]
                        break
                    lookup -= 1
            else:
                # constant colour
                linecolor = self.line_color
            # draw the line, line style can be 'straight', 'radial' or no line
            if self.line_style == 'straight':
                vector = (int(lastx), int(lasty), int(x), int(y))
                self.draw.line(vector, fill=linecolor, width=1)
            elif self.line_style == "radial":
                self.joinCurve(lasta, lastr, lastx, lasty, thisa, linecolor)
            lastx = x
            lasty = y
            # Thats the last samlple done ,Now we draw final vector, if required
            # if self.vector_color != "none" :
                # vector = (int(self.origin_x), int(self.origin_y), int(x), int(y))
                # self.draw.line(vector, fill=self.vector_color, width=1)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled, usually with a number followed by
        unit string. The get_ring_label() method returns the label to be used
        on a given ring. There are 5 equally spaced rings numbered from
        1 (inside) to 5 (outside). A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a lalbel is required, will be from
                  1 (inside) to 5 (outside) inclusive

        Returns:
            label text for the given ring number
        """

        label_inc = self.max_vector_radius / 5
        return ''.join([str(int(round(label_inc * ring, 0))), self.ring_units])


#=============================================================================
#                         Class PolarWindSpiralPlot
#=============================================================================


class PolarWindSpiralPlot(PolarWindPlot):
    """Specialise class to generate a spiral wind plot."""

    def __init__(self, skin_dict, plot_dict):
        """Initialise a PolarWindSpiralPlot object."""

        # initialise my superclass
        super(PolarWindSpiralPlot, self).__init__(skin_dict, plot_dict)

        # Display oldest or newest data at centre? Default to oldest.
        self.centre = self.plot_dict.get('centre', 'oldest')

        # get marker_style, default to 'circle'
        self.marker_style = self.plot_dict.get('marker_style', 'circle')
        # get line_style, default to radial
        self.line_style = self.plot_dict.get('line_style', 'radial')
        # Get line_color, can be 'speed', 'age' or a valid color. Default to
        # 'speed'.
        self.line_color = plot_dict.get('line_color', 'speed')
        if self.line_color not in ['speed', 'age']:
            self.line_color = parse_color(self.line_color, 'speed')
        # Get marker_color, can be 'speed' or a valid color. Default to 'speed'.
        self.marker_color = plot_dict.get('marker_color', 'speed')
        if self.marker_color != 'speed':
            self.marker_color = parse_color(self.marker_color, 'speed')
        # get axis label format
        self.axis_label = self.plot_dict.get('axis_label', '%H:%M')

    def render(self):
        """Main entry point to generate a spiral polar wind plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # setup the legend
        self.set_legend()
#### This needs to be fixed, should not render until setup complete
        if self.title:
            width, height = self.draw.textsize(self.title, font=self.label_font)
            self.title_height = height
        else:
            self.title_height = 0

        # set up the background polar grid
        self.set_polar_grid()
        # setup the spiral plot
        self.set_plot()

        # render the title
        self.render_title()
        # render the legend
        self.render_legend()

        # render the polar grid
        self.render_polar_grid("spiral")
        # render the timestamp label
        self.render_timestamp()
        # render the spial direction label
        self.render_spiral_direction_label()
        # finally render the plot
        self.render_plot()
        # return the completed plot image
        return image

    def set_plot(self):
        """Setup the spiral plot render.

        Perform any calculations or set any properties required to render the
        polar spiral plot.
        """

#### setting time_labels probably belongs in set_polar_grid but we do not define our own set_polar_grid
        # calculate which samples will fall on the circular axis marks and
        # extract their timestamps
        _label = []
        for n in range(6):
            # sample number
            sample = int(round((self.samples - 1) * n/5))
            # get the sample ts as a datetime object
            _dt = datetime.datetime.fromtimestamp(self.time_vec[0][sample])
            # format the and save to our list of labels
            _label.append(_dt.strftime(self.axis_label).strip())
        self.time_labels = _label

        # set the location of the ring labels, in this case SE
        self.label_dir = 6

    def render_plot(self):
        """Render the spiral plot data."""

        # radius of plot area in pixels
        plot_radius =  self.max_plot_dia / 2

        # unfortunately PIL does not allow us to work with layers so we need to
        # process our data twice; once to plot the 'trail' and a second time to
        # plot any markers

        # plot the spiral line
        lastx = self.origin_x
        lasty = self.origin_y
        lasta = int(0)
        lastr = int(0)
        # work out our first and last samples based on the direction of the
        # spiral
        if self.centre == "newest":
            start, stop, step = self.samples-1, -1, -1
        else:
            start, stop, step = 0, self.samples, 1
        # iterate over the samples starting from the centre of the spiral
        for i in range(start, stop, step):
            this_dir_vec = self.dir_vec[0][i]
            this_speed_vec = self.speed_vec[0][i]
            # Calculate radius for this sample. Note assumes equal time periods
            # between samples
#### TODO handle case where self.samples==1
#### TODO actually radius should be a function of time, this will then cope with nones/gaps and short set of samples
#### NOTE2GR You modified my outer foor loop, but we still need the if below to calculate radius correctly
            if self.centre == "newest" :
                i2 = self.samples - 1 - i
            else :
                i2 = i
            self.radius = i2 * plot_radius/(self.samples - 1)
            # if the current direction sample is not None then plot it
            # otherwise skip it
            if this_dir_vec is not None:
                # bearing for this sample
                thisa = int(this_dir_vec)
                # calculate plot coords for this sample
                self.x = self.origin_x + self.radius * math.sin(math.radians(this_dir_vec))
                self.y = self.origin_y - self.radius * math.cos(math.radians(this_dir_vec))
                # if this is the first sample then the last point must be set
                # to this point
                if i == start:
                    lastx = self.x
                    lasty = self.y
                    lasta = thisa
                    lastr = self.radius
                # determine line color to be used
                line_color = self.get_speed_color(self.line_color,
                                                  this_speed_vec)
                # draw the line, line style can be 'straight', 'radial' or no
                # line
                if self.line_style == "straight" :
                    vector = (int(lastx), int(lasty), int(self.x), int(self.y))
                    self.draw.line(vector, fill=line_color, width=1)
                elif self.line_style == "radial" :
                    self.joinCurve(lasta, lastr, lastx, lasty, thisa, line_color)
                # this sample is complete, save it as the 'last' sample
                lastx = self.x
                lasty = self.y
                lasta = thisa
                lastr = self.radius

        # plot the markers if required
        if self.marker_style is not None:
            lastx = self.origin_x
            lasty = self.origin_y
            lasta = int(0)
            lastr = int(0)
            # iterate over the samples starting from the centre of the spiral
            for i in range(start, stop, step):
                this_dir_vec = self.dir_vec[0][i]
                this_speed_vec = self.speed_vec[0][i]
                # Calculate radius for this sample. Note assumes equal time periods
                # between samples
#### TODO handle case where self.samples==1
#### TODO actually radius should be a function of time, this will then cope with nones/gaps and short set of samples
#### NOTE2GR You modified my outer foor loop, but we still need the if below to calculate radius correctly
                if self.centre == "newest" :
                    i2 = self.samples - 1 - i
                else :
                    i2 = i
                self.radius = i2 * plot_radius/(self.samples - 1) # TODO trap sample = 0 or 1
                # if the current direction sample is not None then plot it
                # otherwise skip it
                if this_dir_vec is not None:
                    # bearing for this sample
                    thisa = int(this_dir_vec)
                    # calculate plot coords for this sample
                    self.x = self.origin_x + self.radius * math.sin(math.radians(this_dir_vec))
                    self.y = self.origin_y - self.radius * math.cos(math.radians(this_dir_vec))
                    # if this is the first sample then the last point must be set
                    # to this point
                    if i == start:
                        lastx = self.x
                        lasty = self.y
                        lasta = thisa
                        lastr = self.radius
                    # determine line color to be used
                    marker_color = self.get_speed_color(self.line_color,
                                                        this_speed_vec)
                    # now draw the markers
                    if self.marker_style == "dot" :
                        point = (int(self.x), int(self.y))
                        self.draw.point(point, fill=marker_color)
                    elif self.marker_style == "circle" :
                        bbox = (int(self.x - 1), int(self.y - 1),
                                int(self.x + 1), int(self.y + 1))
                        self.draw.ellipse(bbox, outline=marker_color, fill=marker_color)
                    elif self.marker_style == "cross" :
                        horline = (int(self.x - 1), int(self.y),
                                   int(self.x + 1), int(self.y))
                        verline = (int(self.x), int(self.y - 1),
                                   int(self.x), int(self.y + 1))
                        self.draw.line(horline, fill=marker_color, width=1)
                        self.draw.line(verline, fill=marker_color, width=1)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled, usually with a number followed by
        unit string. The get_ring_label() method returns the label to be used
        on a given ring. There are 5 equally spaced rings numbered from
        1 (inside) to 5 (outside). A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a lalbel is required, will be from
                  1 (inside) to 5 (outside) inclusive

        Returns:
            label text for the given ring number
        """

        return self.time_labels[ring]

    def render_spiral_direction_label(self):
        """Render label indicating direction of the spiral"""

        # the text depnds on whether the newest or oldest samples are in the
        # center
        if self.centre == "newest" :
            # newest in the center
            _label_text = "Newest in Center"
        else :
            # oldest in the center, include the date of the oldest
            _label_text = "Oldest in Center " + self.time_labels[0]
        # get the size of the label
        width, height = self.draw.textsize(_label_text, font=self.label_font)
#### Does this conflict with the location of the timestamp?
        # now locate the label
        if self.timestamp_location is not None:
            if 'TOP' in self.timestamp_location:
                y = self.plot_border + height
            else:
                y = self.image_height-self.plot_border - height
            if 'LEFT' in self.timestamp_location:
                x = self.image_width - self.plot_border - width
            elif ('CENTER' in self.timestamp_location) or ('CENTRE' in self.timestamp_location):
                x = self.origin_x - width / 2
                # TODO CANT DO THIS ONE
            else:
                # Assume RIGHT
                x = self.plot_border
        else:
            x = self.image_width - self.plot_border - width
            y = self.image_height - self.plot_border - height
        # render the label
        self.draw.text((x, y), _label_text,
                       fill=self.legend_font_color,
                       font=self.legend_font)

#=============================================================================
#                        Class PolarWindScatterPlot
#=============================================================================


class PolarWindScatterPlot(PolarWindPlot):
    """Specialise class to generate a windrose plot."""

    def __init__(self, skin_dict, plot_dict):
        """Initialise a PolarWindScatterPlot object."""

        # initialise my superclass
        super(PolarWindScatterPlot, self).__init__(skin_dict, plot_dict)

        # we don't display a legend on a scatter plot so force legend to False
        self.legend = False
        # get marker_style, default to 'circle'
        self.marker_style = self.plot_dict.get('marker_style', 'circle')

        # Get line style, can be 'straight', 'spoke', 'radial' or None. Default
        # to 'straight'
        _style = self.plot_dict.get('line_style', 'straight')
        # we have a line style but is it one we know about
        if _style is not None and _style.lower() not in ['straight', 'spoke', 'radial']:
            # it's a line style I don't understand, set line_style to
            # 'straight' so that something is displayed then log it
            self.line_style = 'straight'
            logdbg("Unknown scatter plot line style '%s', using 'straight' instead" % (_style, ))
        else:
            # we have a valid line style so save it
            self.line_style = _style

        # Get line_color, can be 'speed', 'age' or a valid color. Default to
        # 'age'.
        _line_color = plot_dict.get('line_color', 'age')
        # we have a line color but is it valid or a style we know about
        if _line_color in ['age', 'speed']:
            # it's a color style I understand
            self.line_color = _line_color
        else:
            _parsed = parse_color(_line_color, None)
            if _parsed is not None:
                # we have a valid supported color
                self.line_color = _parsed
            else:
                # it's an invlaid color so use 'age' instead and log it
                self.line_color = 'age'
                logdbg("Unknown scatter plot line color '%s', using 'age' instead" % (_line_color, ))

        # get colors for oldest and newest points
        _oldest_color = self.plot_dict.get('oldest_color')
        self.oldest_color = parse_color2(_oldest_color, '#F7FAFF')
        _newest_color = self.plot_dict.get('newest_color')
        self.newest_color = parse_color2(_newest_color, '#00368E')

        # get axis label format
        self.axis_label = self.plot_dict.get('axis_label', '%H:%M')

    def render(self):
        """Main entry point to generate a scatter polar wind plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
#### This needs to be fixed, should not render until setup complete
        if self.title:
            width, height = self.draw.textsize(self.title, font=self.label_font)
            self.title_height = height
        else:
            self.title_height = 0

        # set up the background polar grid
        self.set_polar_grid()
        # setup the spiral plot
        self.set_plot()

        # render the title
        self.render_title()

        # render the polar grid
        self.render_polar_grid("scatter")
        # render the timestamp label
        self.render_timestamp()
        # finally render the plot
        self.render_plot()
        # return the completed plot image
        return image

    def set_plot(self):
        """Setup the scatter plot render.

        Perform any calculations or set any properties required to render the
        polar trail plot.
        """

        # set the location of the ring labels, in this case SE
        self.label_dir = 6
        # determine the 'unit' label to use on ring labels
        self.ring_units = SPEED_LOOKUP[self.speed_vec[1]]

    def render_plot(self):
        """Render the scatter plot data."""

        # radius of plot area in pixels
        plot_radius =  self.max_plot_dia / 2

        # unfortunately PIL does not allow us to work with layers so we need to
        # process our data twice; once to plot the 'trail' and a second time to
        # plot any markers

        # plot the scatter line if required
        if self.line_style is not None:
            # initialise values for the last plot point, use None as there is
            # no last point the first time around
            lastx = lasty = lasta = lastr = None
            # iterate over the samples
            for i in range(0, self.samples):
                this_dir_vec = self.dir_vec[0][i]
                this_speed_vec = self.speed_vec[0][i]
                # we only plot if we have values for speed and dir
                if this_speed_vec is not None and this_dir_vec is not None:
                    # calculate the 'radius' in pixels of the vector
                    # representing the sample to be plotted
                    radius = plot_radius * this_speed_vec / self.max_speed_range
                    # calculate the x and y coords of the sample to be plotted
                    x = int(self.origin_x + radius * math.sin(math.radians(this_dir_vec)))
                    y = int(self.origin_y - radius * math.cos(math.radians(this_dir_vec)))
                    # if this is the first sample we can skip it as we have
                    # nothing to plot from
                    if lastr is not None:
                        # determine the line color to be used
                        if self.line_color == "age":
                            # color is dependent on the age of the sample so
                            # calculate a transitioan color
                            line_color = color_trans(self.oldest_color,
                                                     self.newest_color,
                                                     i / (self.samples - 1.0))
                        else:
                            # fixed line color
                            line_color = self.line_color
                        # draw the line, line style can be 'straight', 'spoke',
                        # 'radial' or no line
                        if self.line_style == "straight":
                            xy = (lastx, lasty, x, y)
                            self.draw.line(xy, fill=line_color, width=1)
                        elif self.line_style == "spoke":
                            spoke = (self.origin_x, self.origin_y, x, y)
                            self.draw.line(spoke, fill=line_color, width=1)
                        elif self.line_style == "radial":
                            self.joinCurve(lastx, lasty, lastr, lasta,
                                           x, y, radius, this_dir_vec,
                                           line_color)
                    # this sample is complete, save the plot values as the
                    # 'last' sample
                    lastx = x
                    lasty = y
                    lasta = this_dir_vec
                    lastr = radius

        # plot the markers if required
        if self.marker_style is not None:
            # iterate over the samples
            for i in range(0, self.samples):
                this_dir_vec = self.dir_vec[0][i]
                this_speed_vec = self.speed_vec[0][i]
                # we only plot if we have values for speed and dir
                if this_speed_vec is not None and this_dir_vec is not None:
                    # calculate the 'radius' in pixels of the vector
                    # representing the sample to be plotted
                    radius = plot_radius * this_speed_vec / self.max_speed_range
                    # calculate the x and y coords of the sample to be plotted
                    x = self.origin_x + radius * math.sin(math.radians(this_dir_vec))
                    y = self.origin_y - radius * math.cos(math.radians(this_dir_vec))
                    # determine the marker color to be used
                    if self.line_color == "age" :
                        marker_color = color_trans(self.oldest_color,
                                                   self.newest_color,
                                                   i / (self.samples - 1.0))
                    else :
                        marker_color = self.line_color
                    # now draw the markers
                    if self.marker_style == "dot" :
                        point = (int(x), int(y))
                        self.draw.point(point, fill=marker_color)
                    elif self.marker_style == "circle" :
                        bbox = (int(x - 1), int(y - 1),
                                int(x + 1), int(y + 1))
                        self.draw.ellipse(bbox,
                                          outline=marker_color,
                                          fill=marker_color)
                    elif self.marker_style == "cross" :
                        horline = (int(x - 1), int(y), int(x + 1), int(y))
                        verline = (int(x), int(y - 1), int(x),int(y + 1))
                        self.draw.line(horline, fill=marker_color, width=1)
                        self.draw.line(verline, fill=marker_color, width=1)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled, usually with a number followed by
        unit string. The get_ring_label() method returns the label to be used
        on a given ring. There are 5 equally spaced rings numbered from
        1 (inside) to 5 (outside). A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a lalbel is required, will be from
                  1 (inside) to 5 (outside) inclusive

        Returns:
            label text for the given ring number
        """

        label_inc = self.max_speed_range / 5
        return ''.join([str(int(round(label_inc * ring, 0))), self.ring_units])


#=============================================================================
#                             Utility functions
#=============================================================================

def parse_color(color, default):
    """Parse a string representing a color.

    Parse a parameter representing a colour where the value may be a colour
    word eg 'red', a tuple representing RGB values eg (255, 0, 0) or a number
    eg 0xFF0000. The color parameter may be None or a string representation of
    None in which case the value None will be returned. If the parameter
    cannot be interpreted as a valid colour return the default.

    Inputs:
        color:   the string to be parsed
        default: the default value if color cannot be aprsed to a valid colour

    Returns:
        a valid rgb tuple or the value None
    """

    # do we have a valid color or none (in any case)
    if color is not None and color.lower() != 'none':
        try:
            result = ImageColor.getrgb(color)
        except ValueError:
        # color is not a recognised color string, use the default
            result = default
    else:
        result = None
    return result

def parse_color2(color, default=None):
    """Parse a string representing a color.

    Parse a parameter representing a colour where the value may be a colour
    word eg 'red', a tuple representing RGB values eg (255, 0, 0) or a number
    eg 0xFF0000. If the color string cannot be parsed to a valid color a
    default value is returned.

    Inputs:
        color:   the string to be parsed
        default: the default value if color cannot be aprsed to a valid colour

    Returns:
        a valid rgb tuple or the default value
    """

    # do we have a valid color or none (in any case)
    try:
        result = ImageColor.getrgb(color)
    except ValueError:
    # color is not a recognised color string, use the default
        result = parse_color2(default)
    except AttributeError:
    # color is something (maybe None) that getrgb() cannot parse, use the
    # default
        result = parse_color2(default)
    return result

def color_trans(start_color, end_color, proportion):
    """Get a color on a linear transition between two given colors.

    Uses the algorithm from
    https://stackoverflow.com/questions/21835739/smooth-color-transition-algorithm

    Inputs:
        start_color: 3-way tuple with rgb components of start color.
        end_color:   3-way tuple with rgb components of end color.
        proportion:  Float in range 0 to 1 inclusive that determines the
                     resulting color on the linear transition from
                     start_color (0) to end_color (1).
     Returns:
        A string in the format #RRGGBB
    """

    # get rgb components of the start and end colors
    start_r, start_g, start_b = start_color
    end_r, end_g, end_b = end_color

    # calculate the transitional color rgb components
    r = int((1 - proportion) * start_r + proportion * end_r + 0.5)
    g = int((1 - proportion) * start_g + proportion * end_g + 0.5)
    b = int((1 - proportion) * start_b + proportion * end_b + 0.5)
    # return the resulting transitional color in #RRGGBB format
    return '#%02x%02x%02x' % (r, g, b)
