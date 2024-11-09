"""
polarwindplot.py

A WeeWX generator to generate various polar wind plots.

The Polar Wind Plot Image Generator generates polar plots of wind related
observations from WeeWX archive data. The polar plots are generated as image
files suitable for publishing on a web page, inclusion in a WeeWX template or
for use elsewhere. The Polar Wind Plot Image Generator can generate the
following polar wind plots:

-   Wind rose. Traditional wind rose showing dominant wind directions and speed
               ranges.
-   Scatter.   Plot showing variation in wind speed and direction over time.
-   Spiral.    Plot showing wind direction over time with colour coded wind
               speed.
-   Trail.     Plot showing vector wind run over time.

Various parameters including the plot type, period, source data field, units
of measure and colours can be controlled by the user through various
configuration options similar to other image generators.

Copyright (c) 2017-2024   Gary Roderick           gjroderick<at>gmail.com
                          Neil Trimboy            neil.trimboy<at>gmail.com

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program.  If not, see https://www.gnu.org/licenses/.

Version: 0.1.2                                      Date: 9 November 2024

Revision History
    9 November 2024     v0.1.2
        -   generator version string can now be optionally included on each plot
        -   fix error in processing of timestamp location config option
        -   fix error when all wind speed values are None
        -   handle TypeError raised when parse_color() is asked to parse the
            value None as a colour
    24 December 2023    v0.1.1
        -   fix issue when wind source speed vector contains one or more None values
        -   fix error when setting max_speed_range property
    16 June 2022        v0.1.0
        -   initial release
"""
# TODO: Testing. Test trail plot net vector positioning for various timestamp positions
# TODO: Testing. Test use of data_binding config option

# python imports
import datetime
import math
import os.path
import time
# first try to import from PIL then revert to python-imaging if an error
try:
    from PIL import Image, ImageColor, ImageDraw
except ImportError:
    import Image
    import ImageColor
    import ImageDraw

# compatibility shims
import six

# WeeWX imports
import weewx
import weewx.units
import weeplot.utilities
import weeutil.weeutil
import weewx.reportengine

# import/setup logging, WeeWX v3 is syslog based but WeeWX v4 is logging based,
# try v4 logging and if it fails use v3 logging
try:
    # WeeWX4 logging
    import logging

    log = logging.getLogger(__name__)

    def logdbg(msg):
        log.debug(msg)

    def loginf(msg):
        log.info(msg)

    def logerr(msg):
        log.error(msg)

except ImportError:
    # WeeWX legacy (v3) logging via syslog
    import syslog

    def logmsg(level, msg):
        syslog.syslog(level, 'polarwindplot: %s' % msg)

    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)

    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)

    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)


POLAR_WIND_PLOT_VERSION = '0.1.2'
DEFAULT_PLOT_COLORS = ['lightblue', 'blue', 'midnightblue', 'forestgreen',
                       'limegreen', 'green', 'greenyellow']
DEFAULT_NUM_RINGS = 5
DEFAULT_NO_PETALS = 16
DEFAULT_PETAL_WIDTH = 0.8
DEFAULT_BULLSEYE = 0.1
DEFAULT_LINE_WIDTH = 1
DEFAULT_MARKER_SIZE = 2
DEFAULT_PLOT_FONT_COLOR = 'black'
DEFAULT_RING_LABEL_TIME_FORMAT = '%H:%M'
DEFAULT_MAX_SPEED = 30
DISTANCE_LOOKUP = {'km_per_hour': 'km',
                   'mile_per_hour': 'mile',
                   'meter_per_second': 'km',
                   'knot': 'Nm'}
SPEED_LOOKUP = {'km_per_hour': 'km/h',
                'mile_per_hour': 'mph',
                'meter_per_second': 'm/s',
                'knot': 'kn'}
DEGREE_SYMBOL = u'\N{DEGREE SIGN}'
PREFERRED_LABEL_QUADRANTS = [1, 2, 0, 3]


# =============================================================================
#                        Class PolarWindPlotGenerator
# =============================================================================

class PolarWindPlotGenerator(weewx.reportengine.ReportGenerator):
    """Class used to control generation of polar wind plots.

    The PolarWindPlotGenerator class is a customised image generator that
    produces polar wind plots based upon WeeWX archive data. The generator
    produces image files that may be included in a web page, a WeeWX web page
    template or elsewhere as required.

    The polar wind plot characteristics may be controlled through option
    settings in the relevant skin.conf or under the relevant report stanza in
    the [StdReport] section of weewx.conf.
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

        # get the config options for our plots
        self.polar_dict = self.skin_dict['PolarWindPlotGenerator']
        # get the formatter and converter to be used
        self.formatter = weewx.units.Formatter.fromSkinDict(self.skin_dict)
        self.converter = weewx.units.Converter.fromSkinDict(self.skin_dict)
        # determine how much logging is desired
        self.log_success = weeutil.weeutil.tobool(self.polar_dict.get('log_success',
                                                                      True))
        # initialise the plot period
        self.period = None

    def run(self):
        """Main entry point for generator."""

        # do any setup required before we generate the plots
        self.setup()
        # generate the plots
        self.genPlots(self.gen_ts)

    def setup(self):
        """Setup for a plot run."""

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
        # loop over each 'time span' section (eg day, week, month etc)
        for span in self.polar_dict.sections:
            # now loop over all plot names in this 'time span' section
            for plot in self.polar_dict[span].sections:
                # accumulate all options from parent nodes:
                plot_options = weeutil.weeutil.accumulateLeaves(self.polar_dict[span][plot])
                # get a polar wind plot object from the factory
                plot_obj = self._polar_plot_factory(plot_options)

                # obtain a dbmanager so we can access the database
                binding = plot_options['data_binding']
                dbmanager = self.db_binder.get_manager(binding)

                # Get the end time for plot. In order try gen_ts, last known
                # good archive time stamp and then finally current time
                plotgen_ts = gen_ts
                if not plotgen_ts:
                    plotgen_ts = dbmanager.lastGoodStamp()
                    if not plotgen_ts:
                        plotgen_ts = time.time()

                # set the plot timestamp
                plot_obj.timestamp = plotgen_ts

                # get the period for the plot, default to 24 hours if no period
                # set
                self.period = int(plot_options.get('period', 86400))

                # give the polar wind plot object a formatter to use
                plot_obj.formatter = self.formatter

                # get the path of the image file we will save
                image_root = os.path.join(self.config_dict['WEEWX_ROOT'],
                                          plot_options['HTML_ROOT'])
                # Get image file format. Can use any format PIL can write,
                # default to png
                image_format = self.polar_dict.get('format', 'png')
                # get full file name and path for plot
                img_file = os.path.join(image_root, '%s.%s' % (plot,
                                                               image_format))

                # check whether this plot needs to be done at all, if not move
                # onto the next plot
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
                    source_options = weeutil.weeutil.accumulateLeaves(self.polar_dict[span][plot][source])

                    # Get plot title if explicitly requested, default to no
                    # title. Config option 'label' used for consistency with
                    # skin.conf ImageGenerator sections.
                    title = source_options.get('label', '')

                    # Determine the speed and direction archive fields to be
                    # used. Can really only plot windSpeed, windDir and
                    # windGust, windGustDir. If anything else default to
                    # windSpeed, windDir.`
                    sp_field = source_options.get('data_type', source)
                    if sp_field == 'windSpeed':
                        dir_field = 'windDir'
                    elif sp_field == 'windGust':
                        dir_field = 'windGustDir'
                    else:
                        sp_field = 'windSpeed'
                        dir_field = 'windDir'
                    # hit the archive to get speed and direction plot data
                    t_span = weeutil.weeutil.TimeSpan(plotgen_ts - self.period + 1,
                                                      plotgen_ts)
                    (_, sp_t_vec, sp_vec_raw) = dbmanager.getSqlVectors(t_span,
                                                                        sp_field)
                    (_, dir_t_vec, dir_vec) = dbmanager.getSqlVectors(t_span,
                                                                      dir_field)
                    # convert the speed values to the units to be used in the
                    # plot
                    speed_vec = self.converter.convert(sp_vec_raw)
                    # get the units label for our speed data
                    units = self.skin_dict['Units']['Labels'][speed_vec.unit].strip()

                    # add the source data to be plotted to our plot object
                    plot_obj.add_data(sp_field,
                                      speed_vec,
                                      dir_vec,
                                      sp_t_vec,
                                      len(sp_t_vec.value),
                                      units)

                    # call the render() method of the polar plot object to
                    # render the entire plot and produce an image
                    image = plot_obj.render(title)

                    # now save the file, wrap in a try ... except in case we have
                    # a problem saving
                    try:
                        image.save(img_file)
                        ngen += 1
                    except IOError as e:
                        loginf("Unable to save to file '%s': %s" % (img_file, e))
        if self.log_success:
            loginf("Generated %d images for %s in %.2f seconds" % (ngen,
                                                                   self.skin_dict['REPORT_NAME'],
                                                                   time.time() - t1))

    def _polar_plot_factory(self, plot_dict):
        """Factory method to produce a polar plot object."""

        # what type of plot is it, default to wind rose
        plot_type = plot_dict.get('plot_type', 'rose').lower()
        # create and return the relevant polar plot object
        if plot_type == 'rose':
            return PolarWindRosePlot(self.skin_dict, plot_dict, self.formatter)
        elif plot_type == 'trail':
            return PolarWindTrailPlot(self.skin_dict, plot_dict, self.formatter)
        elif plot_type == 'spiral':
            return PolarWindSpiralPlot(self.skin_dict, plot_dict, self.formatter)
        elif plot_type == 'scatter':
            return PolarWindScatterPlot(self.skin_dict, plot_dict, self.formatter)
        # if we made it here we don't know about the specified plot so raise
        raise weewx.UnsupportedFeature('Unsupported polar wind plot type: %s' % plot_type)

    def skipThisPlot(self, ts, img_file, plot_name):
        """Determine whether the plot is to be skipped or not.

        Successive report cycles will likely produce a windrose that,
        irrespective of period, would be different to the windrose from the
        previous report cycle. In most cases the changes are insignificant so,
        as with the WeeWX graphical plots, long period plots are generated
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
            (2) an existing plot exists, but it is older than 24 hours
            (3) every 24 hours when period > 30 days (2592000 sec)
            (4) every 1-hour when period is > 7 days (604800 sec) but
                <= 30 days (2592000 sec)
            (5) every report cycle when period < 7 days (604800 sec)

        Input Parameters:

            img_file: full path and filename of plot file
            plot_name: name of plot

        Returns:
            True if plot is to be generated, False if plot is to be skipped.
        """

        # Images without a period must be skipped every time and a syslog
        # entry added. This should never occur, but....
        if self.period is None:
            loginf("Plot '%s' ignored, no period specified" % plot_name)
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

        # otherwise, we must regenerate
        return False


# =============================================================================
#                             Class PolarWindPlot
# =============================================================================

class PolarWindPlot(object):
    """Base class for creating a polar wind plot.

    This class should be specialised for each type of plot. As a minimum a
    render() method must be defined for each type of plot.
    """

    def __init__(self, skin_dict, plot_dict, formatter):
        """Initialise an instance of PolarWindPlot."""

        # save the formatter
        self.formatter = formatter

        # set image attributes
        # overall image width and height
        self.image_width = int(plot_dict.get('image_width', 300))
        self.image_height = int(plot_dict.get('image_height', 180))
        # background colour of the image
        _image_back_box_color = plot_dict.get('image_background_color')
        self.image_background_color = parse_color(_image_back_box_color, '#96C6F5')
        # background colour of the polar plot area
        _image_back_circle_color = plot_dict.get('image_background_circle_color')
        self.image_back_circle_color = parse_color(_image_back_circle_color, '#F5F5F5')
        # colour of the polar plot area range rings
        _image_back_range_ring_color = plot_dict.get('image_background_range_ring_color')
        self.image_back_range_ring_color = parse_color(_image_back_range_ring_color, '#DDD9C3')
        # background image to be used for the overall image background
        self.image_back_image = plot_dict.get('image_background_image')
        # resample filter
        _resample_filter = plot_dict.get('resample_filter', 'NEAREST').upper()
        try:
            self.resample_filter = getattr(Image, _resample_filter)
        except AttributeError:
            self.resample_filter = Image.NEAREST

        # plot attributes
        self.plot_border = int(plot_dict.get('plot_border', 5))
        self.font_path = plot_dict.get('font_path')
        self.plot_font_size = int(plot_dict.get('plot_font_size', 10))
        _plot_font_color = plot_dict.get('plot_font_color')
        self.plot_font_color = parse_color(_plot_font_color,
                                           DEFAULT_PLOT_FONT_COLOR)
        # colours to be used in the plot
        _colors = weeutil.weeutil.option_as_list(plot_dict.get('plot_colors',
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
        # do we display a legend, default to True
        self.legend = weeutil.weeutil.tobool(plot_dict.get('legend',
                                                           True))
        self.legend_bar_width = int(plot_dict.get('legend_bar_width', 10))
        self.legend_font_size = int(plot_dict.get('legend_font_size', 10))
        _legend_font_color = plot_dict.get('legend_font_color')
        self.legend_font_color = parse_color(_legend_font_color, '#000000')
        self.legend_width = 0

        # title/plot label attributes
        self.label_font_size = int(plot_dict.get('label_font_size', 12))
        _label_font_color = plot_dict.get('label_font_color')
        self.label_font_color = parse_color(_label_font_color, '#000000')

        # compass point abbreviations
        compass = weeutil.weeutil.option_as_list(skin_dict['Labels'].get('compass_points',
                                                                         'N, S, E, W'))

        self.north = compass[0]
        self.south = compass[1]
        self.east = compass[2]
        self.west = compass[3]

        # number of rings on the polar plot
        self.rings = int(plot_dict.get('polar_rings', DEFAULT_NUM_RINGS))

        # Boundaries for speed range bands, these mark the colour boundaries
        # on the stacked bar in the legend. 7 elements only (ie 0, 10% of max,
        # 20% of max...100% of max)
        self.speed_factors = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
        # set up a list with speed range boundaries
        self.speed_list = []

        # get the timestamp format, use a sane default that should display
        # sensibly for all locales
        self.timestamp_format = plot_dict.get('timestamp_format', '%x %X')
        # get the timestamp location.
        # First get the option, if the option includes a comma we will have a
        # list otherwise it will be a string. The default will return a list
        # ['bottom', 'right'].
        _ts_loc = plot_dict.get('timestamp_location', 'bottom, right')
        # If we have the string 'None' in any case combination take that as no
        # timestamp label is to be shown. Try to convert the option to lower
        # case, if it is a list we will get an AttributeError.
        try:
            _ts_loc = _ts_loc.lower()
        except AttributeError:
            # _ts_loc is not a string, do nothing, we will pick this up shortly
            pass
        # do we have the string 'None' in any case combination
        if _ts_loc == 'none':
            # we have the string 'None', so we don't display the timestamp
            self.timestamp_location = None
        else:
            # we have something other than the string 'None', so we will be
            # displaying a timestamp label, but where?
            # get our option as a set
            _ts_loc = set(weeutil.weeutil.option_as_list(_ts_loc))
            # if we don't have a valid vertical position specified default to
            # 'bottom'
            if not _ts_loc & {'top', 'bottom'}:
                _ts_loc.add('bottom')
            # if we don't have a valid horizontal position specified default to
            # 'right'
            if not _ts_loc & {'left', 'centre', 'center', 'right'}:
                _ts_loc.add('right')
            # assign the resulting set to the timestamp_location property
            self.timestamp_location = _ts_loc

        # Get the version string location, the default is {top left}, but we
        # need to de-conflict with the timestamp location. Also, unless the
        # version string display has been explicitly disabled with the string
        # 'None' (in any case combination), display the version string whenever
        # debug >= 1.
        # first get the option, if the options does not exist None will be
        # returned
        _v_loc_opt = plot_dict.get('version_location')
        if _v_loc_opt is None:
            # version_location was not set, so unless debug >= 1 we will not
            # display the version string
            if weewx.debug >= 1:
                # debug is >= 1 so check if we can use our default location of
                # {top, left}, we will be fine unless the timestamp is there
                if {'top', 'left'} == self.timestamp_location:
                    # the timestamp has {top, left} so we will use {top, right}
                    self.version_location = {'top', 'right'}
                else:
                    # we are clear to use {top, left}
                    self.version_location = {'top', 'left'}
            else:
                # version_location was not set and debug == 0 so don't display
                # the version string
                self.version_location = None
        else:
            # version_location was set, but was it explicitly disabled by use
            # of the string 'None' (in any variation of case)? Try to convert
            # the option to lower case, if it is a list we will get an
            # AttributeError.
            try:
                _v_loc_opt = _v_loc_opt.lower()
            except AttributeError:
                # _v_loc_opt is not a string, do nothing, we will pick this up
                # shortly
                pass
            if _v_loc_opt == 'none':
                # version string display has been explicitly disabled
                self.version_location = None
            else:
                # obtain the version_location option as a set of strings
                _v_loc = set(weeutil.weeutil.option_as_list(_v_loc_opt))
                # if we don't have a valid vertical position specified default
                # to 'top'
                if not _v_loc & {'top', 'bottom'}:
                    _v_loc.add('top')
                # if we don't have a valid horizontal position specified
                # default to 'right' but only if timestamp is not using
                # 'right', in that case use 'left'
                if not _v_loc & {'left', 'centre', 'center', 'right'}:
                    # there is no horizontal position specified so de-conflict
                    # with timestamp location
                    _temp_loc = _v_loc | {'left'}
                    if _temp_loc not in self.timestamp_location:
                        _v_loc.add('left')
                    else:
                        _v_loc.add('right')
                # assign the resulting set to the version_location property
                self.version_location = _v_loc

        # get size of the arc to be kept clear for ring labels
        self.ring_label_clear_arc = plot_dict.get('ring_label_clear_arc', 30)

        # initialise a number of properties to be used later
        self.speed_field = None
        self.max_speed_range = None
        self.speed_vec = None
        self.dir_vec = None
        self.time_vec = None
        self.samples = None
        self.units = None

        self.title = None
        self.title_width = None
        self.title_height = None

        self.max_plot_dia = None
        self.origin_x = None
        self.origin_y = None
        self.plot_font = None
        self.legend_font = None
        self.label_font = None

        self.draw = None

        self.legend_percentage = None
        self.legend_title = None

        self.speed_bin = None
        self.label_dir = None

        self.timestamp = None

    def add_data(self, speed_field, speed_vec, dir_vec, time_vec, samples, units):
        """Add source data to the plot.

        Inputs:
            speed_field: WeeWX archive field being used as the source for speed
                         data
            speed_vec:   ValueTuple containing vector of speed data to be
                         plotted
            dir_vec:     ValueTuple containing vector of direction data
                         corresponding to speed_vec
            samples:     number of possible vector sample points, this may be
                         greater than or equal to the number of speed_vec or
                         dir_vec elements
            units:       unit label for speed_vec units
        """

        # WeeWX archive field that was used for our speed data
        self.speed_field = speed_field
        # find maximum speed from our data, be careful as some or all values
        # could be None
        try:
            max_speed = weeutil.weeutil.max_with_none(speed_vec.value)
        except TypeError:
            # likely all our speed_vec values are None
            max_speed = None
        # set upper speed range for our plot, set to a multiple of 10 for a
        # neater display
        if max_speed is not None:
            self.max_speed_range = (int(max_speed / 10.0) + 1) * 10
        else:
            self.max_speed_range = DEFAULT_MAX_SPEED
        # save the speed and dir data vectors
        self.speed_vec = speed_vec
        self.dir_vec = dir_vec
        self.time_vec = time_vec
        # how many samples in our data
        self.samples = samples
        # set the speed units label
        self.units = units

    def set_speed_list(self):
        """Set a list of speed range values

        Given the factors for each boundary point and a maximum speed value
        calculate the boundary points as actual speeds. Used primarily in the
        legend or wherever speeds are categorised by a speed range.
        """

        self.speed_list = [0, 0, 0, 0, 0, 0, 0]
        # loop though each speed range boundary
        for i in range(7):
            # calculate the actual boundary speed value
            self.speed_list[i] = self.speed_factors[i] * self.max_speed_range

    def set_title(self, title):
        """Set the plot title.

        Input:
            title: the title text to be displayed on the plot
        """

        self.title = six.ensure_text(title)
        if title:
            self.title_width, self.title_height = self.draw.textsize(self.title,
                                                                     font=self.label_font)
        else:
            self.title_width = 0
            self.title_height = 0

    def set_polar_grid(self):
        """Set up the polar plot grid.

        Determine size and location of the polar grid on which the plot is to
        be displayed.
        """

        # calculate plot diameter
        # first calculate the size of the cardinal compass direction labels
        _w, _n_height = self.draw.textsize(self.north, font=self.plot_font)
        _w, _s_height = self.draw.textsize(self.south, font=self.plot_font)
        _w_width, _h = self.draw.textsize(self.west, font=self.plot_font)
        _e_width, _h = self.draw.textsize(self.east, font=self.plot_font)

        # now calculate the plot area diameter in pixels, two diameters are
        # calculated, one based on image height and one based on image width
        _height_based = self.image_height - 2 * self.plot_border - self.title_height - (_n_height + 1) - (_s_height + 3)
        _width_based = self.image_width - 2 * self.plot_border - self.legend_width
        # take the smallest so that we have a guaranteed fit
        _diameter = min(_height_based, _width_based)
        # to prevent optical distortion for small plots make diameter a multiple
        # of 22
        self.max_plot_dia = int(_diameter / 22.0) * 22

        # determine plot origin
        self.origin_x = int((self.image_width - self.legend_width - _e_width + _w_width) / 2)
        self.origin_y = 1 + int((self.image_height + self.title_height + _n_height - _s_height) / 2.0)

    def set_legend(self, percentage=False):
        """Set up the legend for a plot.

        Determine the legend width and title.
        """

        if self.legend:
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
        else:
            self.legend_width = 0

    def render(self, title):
        """Main entry point to render a plot.

        Child classes should define their own render() method.
        """

        pass

    def render_legend(self):
        """Render a polar plot legend."""

        # do we need to render a legend?
        if self.legend:
            # org_x and org_y = x,y coords of bottom left of legend stacked bar,
            # everything else is relative to this point

            # first get the space required between the polar plot and the legend
            _width, _height = self.draw.textsize('E', font=self.plot_font)
            org_x = self.origin_x + self.max_plot_dia / 2 + _width + 10
            org_y = self.origin_y + self.max_plot_dia / 2 - self.max_plot_dia / 22
            # bulb diameter
            bulb_d = int(round(1.2 * self.legend_bar_width, 0))
            # draw stacked bar and label with values
            for i in range(6, 0, -1):
                # draw the rectangle for the stacked bar
                x0 = org_x
                y0 = org_y - (0.85 * self.max_plot_dia * self.speed_factors[i])
                x1 = org_x + self.legend_bar_width
                y1 = org_y
                self.draw.rectangle([(x0, y0), (x1, y1)],
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

            # draw 'Calm' label and '0' speed label/percentage
            # position the 'Calm' label
            t_width, t_height = self.draw.textsize('Calm', font=self.legend_font)
            x = org_x - t_width - 2
            y = org_y - t_height / 2 - (0.85 * self.max_plot_dia * self.speed_factors[0])
            # render the 'Calm' label
            self.draw.text((x, y),
                           'Calm',
                           fill=self.legend_font_color,
                           font=self.legend_font)
            # position the '0' speed label/percentage
            t_width, t_height = self.draw.textsize(str(self.speed_list[0]),
                                                   font=self.legend_font)
            x = org_x + 1.5 * self.legend_bar_width
            y = org_y - t_height / 2 - (0.85 * self.max_plot_dia * self.speed_factors[0])
            # get the basic label text
            snippets = (str(int(self.speed_list[0])), )
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
            self.draw.ellipse(bounding_box, outline='black',
                              fill=self.plot_colors[0])

            # draw legend title
            # position the legend title
            t_width, t_height = self.draw.textsize(self.legend_title,
                                                   font=self.legend_font)
            x = org_x + self.legend_bar_width / 2 - t_width / 2
            y = org_y - 5 * t_height / 2 - (0.85 * self.max_plot_dia)
            # render the title
            self.draw.text((x, y),
                           self.legend_title,
                           fill=self.legend_font_color,
                           font=self.legend_font)

            # draw legend units label
            # position the units label
            t_width, t_height = self.draw.textsize('(' + self.units + ')',
                                                   font=self.legend_font)
            x = org_x + self.legend_bar_width / 2 - t_width / 2
            y = org_y - 3 * t_height / 2 - (0.85 * self.max_plot_dia)
            text = ''.join(('(', self.units, ')'))
            # render the units label
            self.draw.text((x, y),
                           text,
                           fill=self.legend_font_color,
                           font=self.legend_font)

    def render_polar_grid(self, bullseye=0):
        """Render polar plot grid.

        Render the polar grid on which the plot will be displayed. This
        includes the axes, axes labels, rings and ring labels.

        Inputs:
            bullseye: radius of the bullseye to be displayed on the polar grid
                      as a proportion of the polar grid radius
        """

        # render the rings

        # calculate the space in pixels between each ring
        ring_space = (1 - bullseye) * self.max_plot_dia/(2.0 * self.rings)
        # calculate the radius of the bullseye in pixels
        bullseye_radius = bullseye * self.max_plot_dia / 2.0
        # locate/size then render each ring starting from the outside
        for i in range(self.rings, 0, -1):
            # create a bound box for the ring
            bbox = (self.origin_x - ring_space * i - bullseye_radius,
                    self.origin_y - ring_space * i - bullseye_radius,
                    self.origin_x + ring_space * i + bullseye_radius,
                    self.origin_y + ring_space * i + bullseye_radius)
            # render the ring
            self.draw.ellipse(bbox,
                              outline=self.image_back_range_ring_color,
                              fill=self.image_back_circle_color)

        # render the ring labels

        # first, initialise a list to hold the labels
        labels = list((None for x in range(self.rings)))
        # loop over the rings getting the label for each ring
        for i in range(self.rings):
            labels[i] = self.get_ring_label(i + 1)
        # Calculate location of ring labels. First we need the angle to use,
        # remember the angle is in radians.
        angle = (3.5 + int(self.label_dir / 4.0)) * math.pi / 2
        # Now draw ring labels. For clarity each label (except for outside
        # label) is drawn on a rectangle with background colour set to that of
        # the polar plot background.
        # iterate over each of the rings
        for i in range(self.rings):
            # we only need do anything if we have a label for this ring
            if labels[i] is not None:
                # calculate the width and height of the label text
                width, height = self.draw.textsize(labels[i],
                                                   font=self.plot_font)
                # find the distance of the midpoint of the text box from the
                # plot origin
                radius = bullseye_radius + (i + 1) * ring_space
                # calculate x and y coords (top left corner) for the text
                x0 = self.origin_x + int(radius * math.cos(angle) - width / 2.0)
                y0 = self.origin_y + int(radius * math.sin(angle) - height / 2.0)
                # the innermost labels have a background box painted first
                if i < self.rings - 1:
                    # calculate the bottom right corner of the background box
                    x1 = self.origin_x + int(radius * math.cos(angle) + width / 2.0)
                    y1 = self.origin_y + int(radius * math.sin(angle) + height / 2.0)
                    # draw the background box
                    self.draw.rectangle([(x0, y0), (x1, y1)],
                                        fill=self.image_back_circle_color)
                # now draw the label text
                self.draw.text((x0, y0),
                               labels[i],
                               fill=self.plot_font_color,
                               font=self.plot_font)

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
        x = self.origin_x - width / 2
        y = self.origin_y - self.max_plot_dia / 2 - 1 - height
        self.draw.text((x, y),
                       self.north,
                       fill=self.plot_font_color,
                       font=self.plot_font)
        # South
        width, height = self.draw.textsize(self.south, font=self.plot_font)
        x = self.origin_x - width / 2
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

    def render_title(self):
        """Render polar plot title."""

        # draw plot title (label) if any
        if self.title:
            try:
                self.draw.text((self.origin_x-self.title_width / 2, self.title_height / 2),
                               self.title,
                               fill=self.label_font_color,
                               font=self.label_font)
            except UnicodeEncodeError:
                self.draw.text((self.origin_x - self.title_width / 2, self.title_height / 2),
                               self.title.encode("utf-8"),
                               fill=self.label_font_color,
                               font=self.label_font)

    def render_timestamp(self):
        """Render plot timestamp."""

        # we only render if we have a location to put the timestamp otherwise
        # we have nothing to do
        if self.timestamp_location:
            _dt = datetime.datetime.fromtimestamp(self.timestamp)
            text = _dt.strftime(self.timestamp_format)
            width, height = self.draw.textsize(text, font=self.label_font)
            if 'top' in self.timestamp_location:
                y = self.plot_border + height
            else:
                y = self.image_height - self.plot_border - height
            if 'left' in self.timestamp_location:
                x = self.plot_border
            elif ('center' in self.timestamp_location) or ('centre' in self.timestamp_location):
                x = self.origin_x - width / 2
            else:
                x = self.image_width - self.plot_border - width
            self.draw.text((x, y), text,
                           fill=self.label_font_color,
                           font=self.label_font)

    def render_version(self):
        """Render the polarwindplot generator version string."""

        # we only render if we have a location to put the version string
        # otherwise we have nothing to do
        if self.version_location:
            text = 'v%s' % POLAR_WIND_PLOT_VERSION
            width, height = self.draw.textsize(text, font=self.label_font)
            if 'top' in self.version_location:
                y = self.plot_border + height
            else:
                y = self.image_height - self.plot_border - height
            if 'left' in self.version_location:
                x = self.plot_border
            elif ('center' in self.version_location) or ('centre' in self.version_location):
                x = self.origin_x - width / 2
            else:
                x = self.image_width - self.plot_border - width
            self.draw.text((x, y),
                           text,
                           fill=self.label_font_color,
                           font=self.label_font)

    def get_image(self):
        """Get an image object on which to render the plot."""

        if self.image_back_image is None:
            _image = Image.new("RGB",
                               (self.image_width, self.image_height),
                               self.image_background_color)
        else:
            try:
                _b_image = Image.open(self.image_back_image)
                _image = self.resize_image(_b_image,
                                           self.image_width,
                                           self.image_height)
            except (IOError, AttributeError):
                _image = Image.new("RGB",
                                   (self.image_width, self.image_height),
                                   self.image_background_color)
        return _image

    def resize_image(self, image, tw, th):
        """Resize an image given one or more target dimensions"""

        (w, h) = image.size
        if tw is None and th is None:
            # no target sizes so leave as is
            return image
        elif th is None:
            # scale by width only
            # we will keep the aspect ratio so need to calc a target height
            th = h * float(tw/w)
        elif tw is None:
            # scale by height only
            # we will keep the aspect ratio so need to calc a target width
            tw = w * float(th/h)
        return image.resize((tw, th), resample=self.resample_filter)

    def get_font_handles(self):
        """Get font handles for the fonts to be used."""

        # font used on the plot area
        self.plot_font = weeplot.utilities.get_font_handle(self.font_path,
                                                           self.plot_font_size)
        # font used for the legend
        self.legend_font = weeplot.utilities.get_font_handle(self.font_path,
                                                             self.legend_font_size)
        # font used for labels/title
        self.label_font = weeplot.utilities.get_font_handle(self.font_path,
                                                            self.label_font_size)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        This method should be overridden in each PolarWindPlot child object.

        Each polar plot ring is labelled. This label can be a percentage, a
        value or some other text. The get_ring_label() method returns the label
        to be used on a given ring. Rings are equally spaced and numbered from 1
        (inside) to outside. A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a label is required, will be from
                  1 to the number of rings used inclusive

        Returns:
            label text for the given ring number
        """

        return None

    def render_marker(self, x, y, size, marker_type, marker_color):
        """Render a marker.

        Inputs:
            x:            Start point plot x coordinate
            y:            Start point plot y coordinate
            size: start   Point vector radius
            marker_type:  Type of marker to be used, can be cross, x, box, dot
                          or circle. Default is circle.
            marker_color: Color to be used
        """

        if marker_type == "cross":
            line = (int(x - size), int(y), int(x + size), int(y))
            self.draw.line(line, fill=marker_color, width=1)
            line = (int(x), int(y - size), int(x), int(y + size))
            self.draw.line(line, fill=marker_color, width=1)
        elif marker_type == "x":
            line = (int(x - size), int(y - size), int(x + size), int(y + size))
            self.draw.line(line, fill=marker_color, width=1)
            line = (int(x + size), int(y - size), int(x - size), int(y + size))
            self.draw.line(line, fill=marker_color, width=1)
        elif marker_type == "box":
            line = (int(x - size), int(y - size), int(x + size), int(y - size))
            self.draw.line(line, fill=marker_color, width=1)
            line = (int(x + size), int(y - size), int(x+size), int(y + size))
            self.draw.line(line, fill=marker_color, width=1)
            line = (int(x - size), int(y - size), int(x - size), int(y + size))
            self.draw.line(line, fill=marker_color, width=1)
            line = (int(x - size), int(y + size), int(x + size), int(y + size))
            self.draw.line(line, fill=marker_color, width=1)
        else:
            # dot or circle, use circle if it's an unsupported marker type
            bbox = (int(x - size), int(y - size),
                    int(x + size), int(y + size))
            if marker_type == "dot":
                # a dot is just a filled circle
                self.draw.ellipse(bbox, outline=marker_color, fill=marker_color)
            else:
                # either circle was specified or it is an unsupported marker
                # type, either way use circle
                self.draw.ellipse(bbox, outline=marker_color)

    def join_curve(self, start_x, start_y, start_r, start_a,
                   end_x, end_y, end_r, end_a, color, line_width):
        """Join two points with a curve.

        Draw a smooth curve between two points by joining them with straight
        line segments each covering 1 degree of arc.

        Inputs:
            start_x:     start point plot x coordinate
            start_y:     start point plot y coordinate
            start_r:     start point vector radius (in pixels)
            start_a:     start point vector direction (degrees True)
            end_x:       end point plot x coordinate
            end_y:       end point plot y coordinate
            end_r:       end point vector radius (in pixels)
            end_a:       end point vector direction (degrees True)
            color:       color to be used
            line_width : line width (pixels)
        """

        # calculate the angle in degrees between the start and end vectors and
        # the 'direction of plotting'
        if (end_a - start_a) % 360 <= 180:
            start = start_a
            end = end_a
            direction = 1
        else:
            start = end_a
            end = start_a
            direction = -1
        angle_span = (end - start) % 360
        # initialise our start plot points
        last_x = start_x
        last_y = start_y
        a = 1
        # while statement to allow us to draw curve in 1 degree increments
        # if angle to cover is < 2 degrees we draw NO segments
        while a < angle_span:
            # calculate the radius of the vector of next point we will draw to
            radius = start_r + (end_r - start_r) * a / angle_span
            # get the x and y plot coords of the next point
            x = int(self.origin_x + radius * math.sin(math.radians(start_a + (a * direction))))
            y = int(self.origin_y - radius * math.cos(math.radians(start_a + (a * direction))))
            # define the start and end points of the line between the current
            # point to the last
            xy = (last_x, last_y, x, y)
            # draw a straight line
            self.draw.line(xy, fill=color, width=line_width)
            # save our current point as the last point
            last_x = x
            last_y = y
            # increment the angle
            a += 1
        # once we have finished the curve (if any was plotted at all) we need
        # to draw the last incremental point to our original end point. In
        # instances when the angle_span is < 2 degrees this will be the only
        # segment drawn
        xy = (last_x, last_y, end_x, end_y)
        self.draw.line(xy, fill=color, width=line_width)

    @staticmethod
    def get_legend_title(source=None):
        """Produce a title for the legend."""

        if source == 'windSpeed':
            return 'Wind Speed'
        elif source == 'windGust':
            return 'Wind Gust'
        else:
            return 'Legend'

    def get_speed_color(self, source, speed):
        """Determine the speed based colour to be used."""

        result = None
        if source == "speed":
            # colour is a function of speed
            for lookup in range(5, -1, -1):
                if speed > self.speed_list[lookup]:
                    result = self.plot_colors[lookup + 1]
                    break
        else:
            # constant colour
            result = source
        return result


# =============================================================================
#                          Class PolarWindRosePlot
# =============================================================================

class PolarWindRosePlot(PolarWindPlot):
    """Specialised class to generate a polar wind rose plot.

    The polar wind rose shows the frequency of winds over a period of time by
    wind direction with colour bands showing wind speed ranges. The plot
    results in a number of multi-coloured spokes with the direction of the
    longest spoke showing the wind direction with the greatest frequency.
    """

    def __init__(self, skin_dict, plot_dict, formatter):
        """Initialise a PolarWindRosePlot object."""

        # initialise my superclass
        super(PolarWindRosePlot, self).__init__(skin_dict, plot_dict, formatter)

        # get petal width, if not defined then use the default
        self.petals = int(plot_dict.get('petals', DEFAULT_NO_PETALS))
        if self.petals < 2 or self.petals > 360:
            logdbg("Unsupported number of petals '%d', using default '%d' instead" % (self.petals,
                                                                                      DEFAULT_NO_PETALS))
            self.petals = DEFAULT_NO_PETALS
        # get petal width, if not defined then use the default
        self.petal_width = float(plot_dict.get('petal_width',
                                               DEFAULT_PETAL_WIDTH))
        if self.petal_width < 0.01 or self.petal_width > 1.0:
            logdbg("Unsupported petal width '%d', using default '%d' instead" % (self.petal_width,
                                                                                 DEFAULT_PETAL_WIDTH))
            self.petal_width = DEFAULT_PETAL_WIDTH
        # bullseye radius as a proportion of the plot area radius
        self.bullseye = float(plot_dict.get('bullseye', DEFAULT_BULLSEYE))
        if self.bullseye < 0.01 or self.bullseye > 1.0:
            logdbg("Unsupported bullseye size '%d', using default '%d' instead" % (self.bullseye,
                                                                                   DEFAULT_BULLSEYE))
            self.bullseye = DEFAULT_BULLSEYE
        # initialise some properties for use later
        self.max_ring_val = None
        self.wind_bin = None
        self.ring_units = None

    def render(self, title):
        """Main entry point to generate a polar wind rose plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # set up the legend
        self.set_legend(percentage=True)
        # set up the plot title
        self.set_title(title)
        # set the speed list boundary values
        self.set_speed_list()
        # set up the background polar grid
        self.set_polar_grid()
        # setup for rendering
        self.set_plot()
        # render the plot title
        self.render_title()
        # render the legend
        self.render_legend()
        # render the polar grid
        self.render_polar_grid(bullseye=self.bullseye)
        # render the timestamp label
        self.render_timestamp()
        # render the version string
        self.render_version()
        # finally, render the plot
        self.render_plot()
        # return the completed plot image
        return image

    def set_plot(self):
        """Set up the rose plot render."""

        # Setup 2D list for wind direction. wind_bin[0] represents each of
        # 'petals' compass directions ([0] is N, increasing clockwise).
        # wind_bin[1] holds count of obs in a particular speed range for given
        # direction
        wind_bin = [[0 for x in range(7)] for x in range(self.petals + 1)]
        # setup list to hold obs counts for each speed range
        speed_bin = [0 for x in range(7)]
        # Loop through each sample and increment direction counts and speed
        # ranges for each direction as necessary. 'None' direction is counted
        # as 'calm' (or 0 speed) and (by definition) no direction and are
        # plotted in the 'bullseye' on the plot.
        for i in range(self.samples):
            this_speed_vec = self.speed_vec.value[i]
            this_dir_vec = self.dir_vec.value[i]
            if (this_speed_vec is None) or (this_dir_vec is None):
                wind_bin[self.petals][6] += 1
            else:
                bin = int((this_dir_vec + (180.0 / self.petals)) / (360.0 / self.petals)) % self.petals
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
        # add 'None' obs to 0 speed count
        speed_bin[0] += wind_bin[self.petals][6]
        # don't need the 'None' counts so we can delete them
        del wind_bin[-1]
        # Now set total (direction independent) speed counts. Loop through
        # each petal speed range and increment direction independent speed
        # ranges as necessary.
        for j in range(7):
            for i in range(self.petals):
                speed_bin[j] += wind_bin[i][j]
        # Calc the value to represented by outer ring (range 0 to 1). Value to
        # rounded up to next multiple of 0.05 (ie next 5%)
        self.max_ring_val = (int(max(sum(b) for b in wind_bin) / (0.05 * self.samples)) + 1) * 0.05
        # Find which wind rose arm to use to display ring range labels - look
        # for one that is relatively clear. Only consider NE, SE, SW and NW;
        # preference in order is SE, SW, NE and NW. label_dir stored as an
        # integer corresponding to a 16 windrose arms, 2=NE, 6=SE, 10=SW, 14=NW.
        # Is SE clear, if < 30% of the max value is in use its clear.
        _se = int(self.petals * 0.375)
        _ne = int(self.petals * 0.125)
        _sw = int(self.petals * 0.625)
        _nw = int(self.petals * 0.875)
        _dir_list = [_se, _sw, _ne, _nw]
        _dict = {_ne: 2, _se: 6, _sw: 10, _nw: 14}
        label_dir = None
        for i in _dir_list:
            # is SW, NE or NW clear
            if sum(wind_bin[i])/float(self.samples) <= 0.3 * self.max_ring_val:
                # it's clear so take it
                label_dir = _dict[i]
                # we have finished looking so exit the for loop
                break
        else:
            # none are free so take the smallest of the four
            # set max possible number of readings + 1
            label_count = self.samples + 1
            # iterate over the possible directions
            for i in _dir_list:
                # if this direction has fewer obs than previous best then
                # remember it
                if sum(wind_bin[i]) < label_count:
                    # set min count so far to this bin
                    label_count = sum(wind_bin[i])
                    # set label_dir to this direction
                    label_dir = _dict[i]
        self.label_dir = label_dir
        # save wind_bin, we need it later to render the rose plot
        self.wind_bin = wind_bin
        self.speed_bin = speed_bin
        # 'units' to use on ring labels
        self.ring_units = '%'

    def render_plot(self):
        """Render the rose plot data."""

        # calculate the bullseye radius in pixels
        b_radius = self.bullseye * self.max_plot_dia / 2.0
        # calculate the space left in which to plot the rose 'petals'
        petal_space = self.max_plot_dia / 2.0 - b_radius

        _half_petal_arc = 180.0 * self.petal_width / self.petals

        # Plot wind rose petals. Each petal is constructed from overlapping
        # pie slices starting from outside (biggest) and working in (smallest)
        # start at 'North' windrose petal

        # loop through each wind rose arm
        for a in range(len(self.wind_bin)):
            # calculate the sum of all samples for this arm
            arm_sum = sum(self.wind_bin[a])
            # we only need to do something if we have data to plot
            if arm_sum > 0:
                # loop through each of the bins that make up this arm, start at
                # the outermost (highest) and work our way in
                for s in range(len(self.speed_list) - 1, 0, -1):
                    # calc radius in pixels of the pie slice that represents
                    # the current bin
                    proportion = arm_sum / (self.max_ring_val * self.samples)
                    radius = int(b_radius + proportion * petal_space)
                    # set bound box for pie slice
                    bbox = (self.origin_x - radius,
                            self.origin_y - radius,
                            self.origin_x + radius,
                            self.origin_y + radius)
                    # draw pie slice
                    self.draw.pieslice(bbox,
                                       int(a * (360.0/self.petals) - 90 - _half_petal_arc),
                                       int(a * (360.0/self.petals) - 90 + _half_petal_arc),
                                       fill=self.plot_colors[s], outline='black')
                    # finished with this bin, so reduce our arm sum by the bin
                    # we just plotted
                    arm_sum -= self.wind_bin[a][s]

        # draw 'bullseye' to represent windSpeed=0 or calm
        # produce the label
        label0 = str(int(round(100.0 * self.speed_bin[0] / sum(self.speed_bin), 0))) + '%'
        # work out its size, particularly its width
        text_width, text_height = self.draw.textsize(label0, font=self.plot_font)
        # size the bound box
        bbox = (int(self.origin_x - b_radius),
                int(self.origin_y - b_radius),
                int(self.origin_x + b_radius),
                int(self.origin_y + b_radius))
        # draw the circle
        self.draw.ellipse(bbox,
                          outline='black',
                          fill=self.plot_colors[0])
        # display the value
        self.draw.text((int(self.origin_x-text_width / 2), int(self.origin_y - text_height / 2)),
                       label0,
                       fill=self.plot_font_color,
                       font=self.plot_font)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled. This label can be a percentage, a
        value or some other text. The get_ring_label() method returns the label
        to be used on a given ring. Rings are equally spaced and numbered from 1
        (inside) to outside. A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a label is required, will be from
                  1 to the number of rings used inclusive

        Returns:
            label text for the given ring number
        """

        if ring > 1:
            label_inc = self.max_ring_val / self.rings
            return ''.join([str(int(round(label_inc * ring * 100, 0))),
                            self.ring_units])
        else:
            return None


# =============================================================================
#                        Class PolarWindScatterPlot
# =============================================================================

class PolarWindScatterPlot(PolarWindPlot):
    """Specialised class to generate a windrose plot.

    The wind scatter plat shows wind speed and direction over a period of time.
    Points are plotted by time with wind speed represented by the distance from
    the origin and wind direction is indicated by the polar angle. The plotted
    points can be optionally connected in order of age by a single line. The
    line may transition in colour from oldest to youngest. The plot typically
    results in a single curved line that joins all plotted points in time order.
    """

    def __init__(self, skin_dict, plot_dict, formatter):
        """Initialise a PolarWindScatterPlot object."""

        # initialise my superclass
        super(PolarWindScatterPlot, self).__init__(skin_dict, plot_dict, formatter)

        # we don't display a legend on a scatter plot so force legend to False
        self.legend = False
        #  Get marker_type, default to  None
        _marker_type = plot_dict.get('marker_type')
        self.marker_type = None if _marker_type == '' else _marker_type
        # get marker_size, default to '1'
        self.marker_size = int(plot_dict.get('marker_size',
                                             DEFAULT_MARKER_SIZE))
        # Get line_type; available options are 'straight', 'spoke', 'radial' or
        # None. Default to 'straight'.
        _line_type = plot_dict.get('line_type', 'straight').lower()
        # Handle the None case. If the string 'None' is specified (in any case
        # combination) then accept that as python None. Also use None if the
        # line_type config option has been listed but with no value.
        _line_type = None if _line_type == '' or _line_type == 'none' else _line_type
        # filter any invalid line types replacing them with 'straight'
        if _line_type not in (None, 'straight', 'spoke', 'radial'):
            # add a debug log entry
            logdbg("Invalid line type '%s' specified for spiral plot. "
                   "Defaulting to 'straight'" % (_line_type, ))
            # and default to 'straight'
            _line_type = 'straight'
        self.line_type = _line_type
        # get line_width
        self.line_width = int(plot_dict.get('line_width',
                                            DEFAULT_LINE_WIDTH))
        # Get line_color, can be 'age' or a valid color. Default to 'age'.
        _line_color = plot_dict.get('line_color', 'age')
        # we have a line color but is it valid or a type we know about
        if _line_color in ['age']:
            # it's a color style I understand
            self.line_color = _line_color
        else:
            _parsed = parse_color(_line_color, None)
            if _parsed is not None:
                # we have a valid supported color
                self.line_color = _parsed
            else:
                # it's an invalid color so use 'age' instead and log it
                self.line_color = 'age'
                logdbg("Unknown scatter plot line color '%s', using 'age' instead" % (_line_color, ))

        # get colors for oldest and newest points
        _oldest_color = plot_dict.get('oldest_color')
        self.oldest_color = parse_color(_oldest_color, '#F7FAFF')
        _newest_color = plot_dict.get('newest_color')
        self.newest_color = parse_color(_newest_color, '#00368E')

        # get axis label format
        self.ring_label_time_format = plot_dict.get('ring_label_time_format',
                                                    DEFAULT_RING_LABEL_TIME_FORMAT)

        # initialise some properties for use later
        self.ring_units = None

    def render(self, title):
        """Main entry point to generate a scatter polar wind plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # set up the plot title
        self.set_title(title)
        # set up the background polar grid
        self.set_polar_grid()
        # set up the spiral plot
        self.set_plot()
        # render the title
        self.render_title()
        # render the polar grid
        self.render_polar_grid()
        # render the timestamp label
        self.render_timestamp()
        # render the version string
        self.render_version()
        # finally, render the plot
        self.render_plot()
        # return the completed plot image
        return image

    def set_plot(self):
        """Set up the scatter plot render.

        Perform any calculations or set any properties required to render the
        polar scatter plot.
        """

        # Determine which quadrant will contain the ring labels. Ring labels
        # are displayed on a 45 degree radial in one of the 4 quadrants.
        # Preferred quadrant is SE (aka lower right or quadrant 1) but use a
        # different quadrant if there is a lot of data in SE that may be
        # obscured by the labels. Do a simple check of how many points are in
        # the SE quadrant and if more than 30% of our samples then chose
        # another quadrant that has less than 30% of the samples. Quadrants are
        # checked in order of preference according to contents of
        # PREFERRED_LABEL_QUADRANTS.

        # initialise a list to holds the sample counts for quadrant 0 to 3
        quadrant_count = [0 for x in range(4)]
        # iterate over our samples assigning each to a particular quadrant
        for i in range(0, self.samples):
            # get the direction element of the sample
            _dir = self.dir_vec.value[i]
            # increment the count for the quadrant that will contain the sample
            # but be careful as the sample's direction could be None
            if _dir is not None:
                quadrant_count[int(_dir // 90)] += 1
        # now choose the quadrant for our labels, default to SE (quadrant 1)
        label_dir = 1
        # iterate over our quadrants in preferred order of use
        for q in PREFERRED_LABEL_QUADRANTS:
            # take the first quadrant that has < 30% of the samples
            if quadrant_count[q] <= 0.3 * self.samples:
                label_dir = q
                break
        # assign the chosen quadrant to a property
        self.label_dir = label_dir

        # determine the 'unit' label to use on ring labels
        self.ring_units = SPEED_LOOKUP[self.speed_vec.unit]

    def render_plot(self):
        """Render the scatter plot."""

        # do we need to plot anything
        if self.line_type is not None or self.marker_type is not None:
            # radius of plot area in pixels
            plot_radius = self.max_plot_dia / 2
            # initialise values for the last plot point, use None as there is
            # no last point the first time around
            last_x = last_y = last_dir = last_radius = None
            # iterate over the samples
            for i in range(0, self.samples):
                this_dir_vec = self.dir_vec.value[i]
                this_speed_vec = self.speed_vec.value[i]
                # we only plot if we have values for speed and dir
                if this_speed_vec is not None and this_dir_vec is not None:
                    # calculate the 'radius' in pixels of the vector
                    # representing the sample to be plotted
                    this_radius = plot_radius * this_speed_vec / self.max_speed_range
                    # calculate the x and y coords of the sample to be plotted
                    x = int(self.origin_x + this_radius * math.sin(math.radians(this_dir_vec)))
                    y = int(self.origin_y - this_radius * math.cos(math.radians(this_dir_vec)))
                    # if this is the first sample we can skip it as we have
                    # nothing to plot from
                    if last_radius is not None:
                        # determine the line color to be used
                        if self.line_color == 'age':
                            # color is dependent on the age of the sample so
                            # calculate a transition color
                            line_color = color_trans(self.oldest_color,
                                                     self.newest_color,
                                                     i / (self.samples - 1.0))
                        else:
                            # fixed line color
                            line_color = self.line_color
                        # draw the line, line type can be 'straight', 'spoke',
                        # 'radial' or no line
                        if self.line_type == "straight":
                            xy = (last_x, last_y, x, y)
                            self.draw.line(xy, fill=line_color, width=self.line_width)
                        elif self.line_type == "spoke":
                            spoke = (self.origin_x, self.origin_y, x, y)
                            self.draw.line(spoke, fill=line_color, width=self.line_width)
                        elif self.line_type == "radial":
                            self.join_curve(last_x, last_y, last_radius, last_dir,
                                            x, y, this_radius, this_dir_vec,
                                            line_color, self.line_width)
                        # do we need to plot a marker
                        if self.marker_type is not None:
                            # we do, so get the colour, it's based on a
                            # transition or is fixed
                            if self.line_color == 'age':
                                marker_color = color_trans(self.oldest_color,
                                                           self.newest_color,
                                                           i / (self.samples - 1.0))
                            else:
                                marker_color = self.line_color
                            # now draw the marker
                            self.render_marker(x, y, self.marker_size,
                                               self.marker_type, marker_color)
                    # this sample is complete, save the plot values as the
                    # 'last' sample
                    last_x = x
                    last_y = y
                    last_dir = this_dir_vec
                    last_radius = this_radius

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled. This label can be a percentage, a
        value or some other text. The get_ring_label() method returns the label
        to be used on a given ring. Rings are equally spaced and numbered from 1
        (inside) to outside. A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a label is required, will be from
                  1 to the number of rings used inclusive

        Returns:
            label text for the given ring number
        """

        label_inc = self.max_speed_range / self.rings
        return ''.join([str(int(round(label_inc * ring, 0))), self.ring_units])


# =============================================================================
#                         Class PolarWindSpiralPlot
# =============================================================================

class PolarWindSpiralPlot(PolarWindPlot):
    """Specialised class to generate a spiral wind plot.

    The wind spiral plot shows the wind speed and direction over a period of
    time. The plot consists of a single line starting from the origin of the
    polar plot and ending at the outer edge of the plot area. Wind speed is
    indicated by the colour of the line and wind direction by the polar plot
    angle. The plot may place the oldest entry at the origin and the most
    recent entry at the outer edge or it may place the most recent entry at the
    origin and the oldest entry at the outer edge. The plot typically results
    in a single curved line that spirals from the origin to the outer edge of
    the plot area.
    """

    def __init__(self, skin_dict, plot_dict, formatter):
        """Initialise a PolarWindSpiralPlot object."""

        # initialise my superclass
        super(PolarWindSpiralPlot, self).__init__(skin_dict, plot_dict, formatter)

        # Display oldest or newest data at centre? Default to oldest.
        _centre = plot_dict.get('center', 'oldest').lower()
        self.centre = _centre if _centre in ['oldest', 'newest'] else 'oldest'

        # get marker_type, default to None
        _marker_type = plot_dict.get('marker_type')
        self.marker_type = None if _marker_type == '' else _marker_type
        # get marker_size, default to '1'
        self.marker_size = int(plot_dict.get('marker_size',
                                             DEFAULT_MARKER_SIZE))
        # Get line_type; available options are 'straight', 'radial' or None.
        # Default to 'straight'.
        _line_type = plot_dict.get('line_type', 'straight').lower()
        # Handle the None case. If the string 'None' is specified (in any case
        # combination) then accept that as python None. Also use None if the
        # line_type config option has been listed but with no value.
        _line_type = None if _line_type == '' or _line_type == 'none' else _line_type
        # filter any invalid line types replacing them with 'straight'
        if _line_type not in (None, 'straight', 'radial'):
            # add a debug log entry
            logdbg("Invalid line type '%s' specified for spiral plot. "
                   "Defaulting to 'straight'" % (_line_type, ))
            # and default to 'straight'
            _line_type = 'straight'
        self.line_type = _line_type
        # get line_width
        self.line_width = int(plot_dict.get('line_width',
                                            DEFAULT_LINE_WIDTH))
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
        self.ring_label_time_format = plot_dict.get('ring_label_time_format',
                                                    DEFAULT_RING_LABEL_TIME_FORMAT)

    def render(self, title):
        """Main entry point to generate a spiral polar wind plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # set up the legend
        self.set_legend()
        # set up the plot title
        self.set_title(title)
        # set the speed list boundary values
        self.set_speed_list()
        # set up the background polar grid
        self.set_polar_grid()
        # set up the spiral plot
        self.set_plot()
        # render the title
        self.render_title()
        # render the legend
        self.render_legend()
        # render the polar grid
        self.render_polar_grid()
        # render the timestamp label
        self.render_timestamp()
        # render the version string
        self.render_version()
        # render the spiral direction label
        self.render_spiral_direction_label()
        # finally, render the plot
        self.render_plot()
        # return the completed plot image
        return image

    def set_plot(self):
        """Set up the spiral plot render.

        Perform any calculations or set any properties required to render the
        polar spiral plot.
        """

        # Determine which quadrant will contain the ring labels. Ring labels
        # are displayed on a 45 degree radial in one of the 4 quadrants.
        # Preferred quadrant is SE (aka lower right or quadrant 1).

        # TODO. Do we need some logic in making this choice or leave it arbitrary?
        # Use the default SE quadrant
        self.label_dir = 1

    def render_plot(self):
        """Render the spiral plot."""

        # do we need to plot anything
        if self.line_type is not None or self.marker_type is not None:
            # radius of plot area in pixels
            plot_radius = self.max_plot_dia / 2
            # we start from the origin so set our 'last' values
            last_x = self.origin_x
            last_y = self.origin_y
            last_dir = 0
            last_radius = 0
            # work out our first and last samples based on the direction of the
            # spiral
            if self.centre == "newest":
                start, stop, step = self.samples-1, -1, -1
            else:
                start, stop, step = 0, self.samples, 1
            # iterate over the samples starting from the centre of the spiral
            for i in range(start, stop, step):
                this_dir_vec = self.dir_vec.value[i]
                this_speed_vec = self.speed_vec.value[i]
                # Calculate radius for this sample. Note assumes equal time periods
                # between samples
                if self.centre == "newest":
                    scale = self.samples - 1 - i
                else:
                    scale = i
                # TODO. radius should be a function of time so as to better cope with gaps in data
                this_radius = scale * plot_radius/(self.samples - 1) if self.samples > 1 else 0.0
                # if the current direction sample is not None then plot it
                # otherwise skip it
                if this_dir_vec is not None:
                    # bearing for this sample
                    this_dir = int(this_dir_vec)
                    # calculate plot coords for this sample
                    x = self.origin_x + this_radius * math.sin(math.radians(this_dir_vec))
                    y = self.origin_y - this_radius * math.cos(math.radians(this_dir_vec))
                    # determine line color to be used
                    line_color = self.get_speed_color(self.line_color,
                                                      this_speed_vec)
                    # draw the line; line type can be 'straight', 'radial' or None
                    # for no line
                    if self.line_type == "straight":
                        vector = (int(last_x), int(last_y), int(x), int(y))
                        self.draw.line(vector, fill=line_color, width=self.line_width)
                    elif self.line_type == "radial":
                        self.join_curve(last_x, last_y, last_radius, last_dir,
                                        x, y, this_radius, this_dir,
                                        line_color, self.line_width)
                    # do we need to plot a marker
                    if self.marker_type is not None:
                        # we do, so get the colour, it's based on speed
                        marker_color = self.get_speed_color(self.line_color,
                                                            this_speed_vec)
                        # now draw the marker
                        self.render_marker(x, y, self.marker_size,
                                           self.marker_type, marker_color)
                    # this sample is complete, save it as the 'last' sample
                    last_x = x
                    last_y = y
                    last_dir = this_dir
                    last_radius = this_radius

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled. This label can be a percentage, a
        value or some other text. The get_ring_label() method returns the label
        to be used on a given ring. Rings are equally spaced and numbered from 1
        (inside) to outside. A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a label is required, will be from
                  1 to the number of rings used inclusive

        Returns:
            label text for the given ring number
        """

        # determine which sample will fall on the specified ring and extract
        # its timestamp
        if self.centre == "newest":
            sample = int(round((self.samples - 1) * (self.rings - ring) / self.rings))
        else:
            sample = int(round((self.samples - 1) * ring / self.rings))
        # get the sample ts as a datetime object
        _dt = datetime.datetime.fromtimestamp(self.time_vec.value[sample])
        # return the formatted time
        return _dt.strftime(self.ring_label_time_format).strip()

    def render_spiral_direction_label(self):
        """Render label indicating direction of the spiral."""

        # Construct the spiral direction label text. The text depends on
        # whether the newest or oldest samples are in the centre.
        if self.centre == "newest":
            # newest in the center
            _label_text = "Newest (%s) in centre" % (self.get_ring_label(0))
        else:
            # oldest in the center, include the date of the oldest
            _label_text = "Oldest (%s) in center" % (self.get_ring_label(0))
        # get the size of the label
        width, height = self.draw.textsize(_label_text, font=self.label_font)
        # Now locate the label. We follow the vertical location of the
        # timestamp label but we render on the opposite side of the plot so we
        # do not overwrite the timestamp label. If there is no timestamp label
        # then default to the bottom left.
        if self.timestamp_location is not None:
            # start off using the same vertical alignment as the timestamp
            # label
            same_vert_align = True
            if 'left' in self.timestamp_location:
                # timestamp is left so we go right
                x = self.image_width - self.plot_border - width
            elif ('center' in self.timestamp_location) or ('centre' in self.timestamp_location):
                # We cannot use the same vertical alignment as the timestamp
                # label - we can't fit. So we use the same horizontal alignment
                # (centre) but the opposite vertical alignment.
                same_vert_align = False
                x = self.origin_x - width / 2
            else:
                # it's not left or centre so it must be right, so we go left
                x = self.plot_border
            if 'top' in self.timestamp_location and same_vert_align or \
                    'bottom' in self.timestamp_location and not same_vert_align:
                # we are using the top
                y = self.plot_border + height
            else:
                # otherwise we go bottom
                y = self.image_height - self.plot_border - height
        else:
            # there is no timestamp being displayed so we are free to use
            # anywhere, default to bottom right
            x = self.image_width - self.plot_border - width
            y = self.image_height - self.plot_border - height
        # render the label
        self.draw.text((x, y), _label_text,
                       fill=self.legend_font_color,
                       font=self.label_font)


# =============================================================================
#                          Class PolarWindTrailPlot
# =============================================================================

class PolarWindTrailPlot(PolarWindPlot):
    """Specialised class to generate a wind trail plot.


    The wind trail plot shows a polar representation of windrun over a period
    of time. The plot starts at the origin of the polar plot with subsequent
    points plotted based on the windrun and direction relative to the last
    point. The most recent point is plotted on outer edge of the polar plot.
    The location of the most recent point gives the overall vector windrun
    (distance and direction) during the plot period. The plotted points may be
    optionally connect by a line. The plot typically results in a single curved
    line from the origin to the outer edge of the plot.
    """

    def __init__(self, skin_dict, plot_dict, formatter):
        """Initialise a PolarWindTrailPlot object."""

        # initialise my superclass
        super(PolarWindTrailPlot, self).__init__(skin_dict, plot_dict, formatter)

        # get marker_type, default to None
        _marker_type = plot_dict.get('marker_type')
        self.marker_type = None if _marker_type == '' else _marker_type
        # get marker_size, default to '1'
        self.marker_size = int(plot_dict.get('marker_size',
                                             DEFAULT_MARKER_SIZE))
        # Get line_type; available options are 'straight', 'radial' or None.
        # Default to 'straight'.
        _line_type = plot_dict.get('line_type', 'straight').lower()
        # Handle the None case. If the string 'None' is specified (in any case
        # combination) then accept that as python None. Also use None if the
        # line_type config option has been listed but with no value.
        _line_type = None if _line_type == '' or _line_type == 'none' else _line_type
        # filter any invalid line types replacing them with 'straight'
        if _line_type not in (None, 'straight', 'radial'):
            # add a debug log entry
            logdbg("Invalid line type '%s' specified for spiral plot. "
                   "Defaulting to 'straight'" % (_line_type, ))
            # and default to 'straight'
            _line_type = 'straight'
        self.line_type = _line_type
        # get line_width
        self.line_width = int(plot_dict.get('line_width',
                                            DEFAULT_LINE_WIDTH))

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
        _color = plot_dict.get('vector_color', 'red')
        # check that it is a valid color
        self.vector_color = parse_color(plot_dict.get('vector_color', 'red'),
                                        'red')

        # get end_point_color, default to None
        self.end_point_color = parse_color(plot_dict.get('end_point_color', None),
                                           None)

        # get the vector location
        _vec_loc = set(plot_dict.get('vector_location', {}))
        _v_align = _vec_loc & {'top', 'bottom'}
        if not _v_align:
            _v_align = {'bottom'}
        _h_align = _vec_loc & {'left', 'centre', 'center', 'right'}
        if not _h_align:
            if self.timestamp_location & {'left'}:
                _h_align = {'right'}
            else:
                _h_align = {'left'}
        elif _vec_loc & {'left'} and self.timestamp_location & {'left'}:
            _h_align = {'right'}
        elif _vec_loc & {'right'} and self.timestamp_location & {'right'}:
            _h_align = {'left'}
        self.vector_location = _v_align | _h_align

        # get size of the arc to be kept clear for ring labels
        self.ring_label_clear_arc = plot_dict.get('ring_label_clear_arc', 30)
        # set some properties to startup defaults
        self.max_vector_radius = None
        self.ring_units = None
        self.factor = None
        self.vector_x = None
        self.vector_y = None

    def render(self, title):
        """Main entry point to generate a polar wind trail plot."""

        # get an Image object for our plot
        image = self.get_image()
        # get a Draw object on which to render the plot
        self.draw = ImageDraw.Draw(image)
        # get handles for the fonts we will use
        self.get_font_handles()
        # set up the legend
        self.set_legend()
        # set up the plot title
        self.set_title(title)
        # set the speed list boundary values
        self.set_speed_list()
        # set up the background polar grid
        self.set_polar_grid()
        # setup for rendering
        self.set_plot()
        # render the plot title
        self.render_title()
        # render the legend
        self.render_legend()
        # render the polar grid
        self.render_polar_grid()
        # render the timestamp
        self.render_timestamp()
        # render the version string
        self.render_version()
        # render the overall windrun vector text
        self.render_vector()
        # finally, render the plot
        self.render_plot()
        # return the completed plot image
        return image

    def set_plot(self):
        """Set up the trail plot render.

        Perform any calculations or set any properties required to render the
        polar trail plot.
        """

        # To scale the wind trail to fit the plot area we need to know how big
        # the vector will be. We do this by doing a dry run just calculating
        # the overall vector.
        self.max_vector_radius = 0
        vec_x = 0
        vec_y = 0
        # how we calculate distance depends on the speed units in use
        if self.speed_vec.unit == 'meter_per_second' or self.speed_vec.unit == 'meter_per_second':
            self.factor = 1000.0
        else:
            self.factor = 3600.0
        # iterate over the samples, ignore the first since we don't know what
        # period (delta) it applies to
        for i in range(1, self.samples):
            this_dir_vec = self.dir_vec.value[i]
            this_speed_vec = self.speed_vec.value[i]
            # ignore any speeds that are 0 or None and any directions that are
            # None
            if this_speed_vec is None or this_dir_vec is None or this_speed_vec == 0.0:
                continue
            # the period in sec the current speed applies to
            delta = self.time_vec.value[i] - self.time_vec.value[i-1]
            # the corresponding distance
            dist = this_speed_vec * delta / self.factor
            # calculate new vector from centre for this point
            vec_x += dist * math.sin(math.radians((this_dir_vec + 180) % 360))
            vec_y += dist * math.cos(math.radians((this_dir_vec + 180) % 360))
            vec_radius = math.sqrt(vec_x**2 + vec_y**2)
            if vec_radius > self.max_vector_radius:
                self.max_vector_radius = vec_radius
        # store the resulting x and y components for an overall vector statement
        self.vector_x = vec_x
        self.vector_y = vec_y

        # Determine which quadrant will contain the ring labels. Ring labels
        # are displayed on a 45 degree radial in one of the 4 quadrants.
        # Preferred quadrant is SE (aka lower right or quadrant 1) but use a
        # different quadrant if the net vector appears in the SE quadrant and
        # is too close to the 45 degree radial used for labels. Quadrants are
        # checked in order of preference according to contents of
        # PREFERRED_LABEL_QUADRANTS.

        # first calculate the angle of our vector in degrees (0-360) but
        # translate to NSEW rather than cartesian coords used by atan2
        angle = math.degrees(math.atan2(vec_x, vec_y)) % 360
        # and work out which quadrant that is
        quadrant = int(angle // 90)

        # default to SE quadrant
        label_dir = 1

        # now check each quadrant in our preferred label quadrant list and take
        # the first entry suitable entry
        for q in PREFERRED_LABEL_QUADRANTS:
            # calculate the difference in angle between the 45 degree radial in
            # the quadrant being checked and the final net vector
            label_diff = abs(45 + q * 90 - angle)
            # the current quadrant is suitable if the net vector is in another
            # quadrant or the net vector is more than ring_label_clear_arc
            # degrees away from the 45 degree radial
            if q != quadrant or label_diff >= self.ring_label_clear_arc:
                label_dir = q
                break
        self.label_dir = label_dir

        # determine the 'unit' label to use on ring labels
        self.ring_units = DISTANCE_LOOKUP[self.speed_vec.unit]

    def render_plot(self):
        """Render the trail plot."""

        # do we need to plot anything
        if (self.line_type is not None or self.marker_type is not None) \
                and self.max_vector_radius > 0.0:
            # radius of plot area in pixels
            plot_radius = self.max_plot_dia / 2
            # scaling to be applied to calculated vectors
            scale = plot_radius / self.max_vector_radius
            # for the first sample the vector components must be set to 0 and the
            # previous point must be set to the origin
            vec_x = 0
            vec_y = 0
            last_x = self.origin_x
            last_y = self.origin_y
            if self.dir_vec.value[0] is None:
                last_dir = 0
            else:
                last_dir = int((self.dir_vec.value[0] + 180) % 360)
            last_radius = 0
            # iterate over the samples, ignore the first since we don't know what
            # period (delta) it applies to
            for i in range(1, self.samples):
                this_dir_vec = self.dir_vec.value[i]
                this_speed_vec = self.speed_vec.value[i]
                # ignore any speeds that are 0 or None and any directions that are None
                if this_speed_vec is None or this_dir_vec is None or this_speed_vec == 0.0:
                    continue
                # the period in sec the current speed applies to
                delta = self.time_vec.value[i] - self.time_vec.value[i - 1]
                # the corresponding distance
                dist = this_speed_vec * delta / self.factor
                # calculate new running vector from centre for this point
                vec_x += dist * math.sin(math.radians((this_dir_vec + 180) % 360))
                vec_y += dist * math.cos(math.radians((this_dir_vec + 180) % 360))
                # scale the vector to our polar plot area
                x = self.origin_x + vec_x * scale
                y = self.origin_y - vec_y * scale
                this_radius = math.sqrt(vec_x**2 + vec_y**2) * scale
                this_dir = math.degrees(math.atan2(-vec_y, vec_x)) + 90.0
                # determine line color to be used
                line_color = self.get_speed_color(self.line_color,
                                                  this_speed_vec)
                # draw the line, line type can be 'straight', 'radial' or no line
                if self.line_type == 'straight':
                    vector = (int(last_x), int(last_y), int(x), int(y))
                    self.draw.line(vector, fill=line_color, width=self.line_width)
                elif self.line_type == "radial":
                    self.join_curve(last_x, last_y, last_radius, last_dir,
                                    x, y, this_radius, this_dir,
                                    line_color, self.line_width)
                # do we need to plot a marker
                if self.marker_type is not None:
                    # we do, so get the colour, it's based on speed
                    marker_color = self.get_speed_color(self.marker_color,
                                                        this_speed_vec)
                    # if this is the last point make it a different colour if
                    # needed
                    if i == self.samples - 1:
                        if self.end_point_color:
                            marker_color = self.end_point_color
                    # now draw the marker
                    self.render_marker(x, y, self.marker_size, self.marker_type, marker_color)
                last_x = x
                last_y = y
                last_dir = this_dir
                last_radius = this_radius
            # that's the last sample done, now we draw final vector if required
            if self.vector_color is not None:
                vector = (int(self.origin_x), int(self.origin_y), int(x), int(y))
                self.draw.line(vector,
                               fill=self.vector_color,
                               width=self.line_width)

    def render_vector(self):
        """Render a statement of the net plotted windrun vector."""

        # obtain the net windrun vector magnitude and direction
        _mag = int(round(math.sqrt(self.vector_x**2 + self.vector_y**2),
                         0))
        # we need to do a little translation to map from PIL vector coords to
        # compass vector coords
        _dir = round(math.degrees(math.atan2(self.vector_x, self.vector_y)),
                     0)
        _dir = int(_dir) if _dir >= 0 else int(_dir + 360)
        # convert to a ValueTuple and use our formatter to get the correct
        # ordinal direction
        _dir_vt = weewx.units.ValueTuple(_dir,
                                         'degree_compass',
                                         'group_direction')
        _ord_dir = self.formatter.to_ordinal_compass(_dir_vt)
        # construct the text
        _vector_text = "Net windrun %s%s from %s%s(%s)" % (_mag,
                                                           self.ring_units,
                                                           _dir,
                                                           DEGREE_SYMBOL,
                                                           _ord_dir)
        # determine the size
        _width, _height = self.draw.textsize(_vector_text,
                                             font=self.label_font)

        # now find the location we are to use, we should already be
        # deconflicted with the timestamp location
        if 'top' in self.vector_location:
            y = self.plot_border + _height
        else:
            y = self.image_height - self.plot_border - _height
        if 'left' in self.vector_location:
            x = self.plot_border
        elif ('center' in self.vector_location) or ('centre' in self.vector_location):
            x = self.origin_x - _width / 2
        else:
            x = self.image_width - self.plot_border - _width
        # draw our text, be prepared to catch a unicode encode error
        try:
            self.draw.text((x, y),
                           _vector_text,
                           fill=self.label_font_color,
                           font=self.label_font)

        except UnicodeEncodeError:
            self.draw.text((x, y),
                           _vector_text.encode("utf-8"),
                           fill=self.label_font_color,
                           font=self.label_font)

    def get_ring_label(self, ring):
        """Get the label to be displayed on the polar plot rings.

        Each polar plot ring is labelled. This label can be a percentage, a
        value or some other text. The get_ring_label() method returns the label
        to be used on a given ring. Rings are equally spaced and numbered from 1
        (inside) to outside. A value of None will result in no label
        being displayed for the ring concerned.

        Input:
            ring: ring number for which a label is required, will be from
                  1 to the number of rings used inclusive

        Returns:
            label text for the given ring number
        """

        label_inc = self.max_vector_radius / self.rings
        return ''.join([str(int(round(label_inc * ring, 0))), self.ring_units])


# =============================================================================
#                             Utility functions
# =============================================================================

def parse_color(color, default=None):
    """Parse a string representing a color.

    Parse a parameter representing a colour where the value may be a colour
    word eg 'red', a tuple representing RGB values eg (255, 0, 0) or a number
    eg 0xFF0000. If the color string cannot be parsed to a valid color a
    default value is returned.

    Inputs:
        color:   the string to be parsed
        default: the default value if color cannot be parsed to a valid colour

    Returns:
        a valid rgb tuple or the default value
    """

    # do we have a valid color or none (in any case)
    try:
        result = ImageColor.getrgb(color)
    except (ValueError, AttributeError, TypeError):
        # getrgb() cannot parse color; most likely it is not a recognised
        # color string or maybe it is None. Either way use the default.
        result = parse_color(default) if default is not None else None
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
