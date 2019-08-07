#!/usr/bin/env python

# -*- coding: utf-8 -*-

from collections import defaultdict
import logging

import numpy as np
from lxml import etree
# lxml does XSD validation too but has problems with the MusicXML 3.1 XSD, so we use
# the xmlschema package for validating MusicXML against the definition
import xmlschema
import pkg_resources
from partitura.directions import parse_words
import partitura.score as score

LOGGER = logging.getLogger(__name__)
_MUSICXML_SCHEMA = pkg_resources.resource_filename('partitura', 'musicxml.xsd')
_XML_VALIDATOR = None
DYN_DIRECTIONS = {
    'f': score.ConstantLoudnessDirection,
    'ff': score.ConstantLoudnessDirection,
    'fff': score.ConstantLoudnessDirection,
    'ffff': score.ConstantLoudnessDirection,
    'fffff': score.ConstantLoudnessDirection,
    'ffffff': score.ConstantLoudnessDirection,
    'n': score.ConstantLoudnessDirection,
    'mf': score.ConstantLoudnessDirection,
    'mp': score.ConstantLoudnessDirection,
    'p': score.ConstantLoudnessDirection,
    'pp': score.ConstantLoudnessDirection,
    'ppp': score.ConstantLoudnessDirection,
    'pppp': score.ConstantLoudnessDirection,
    'ppppp': score.ConstantLoudnessDirection,
    'pppppp': score.ConstantLoudnessDirection,
    'fp': score.ImpulsiveLoudnessDirection,
    'pf': score.ImpulsiveLoudnessDirection,
    'rf': score.ImpulsiveLoudnessDirection,
    'rfz': score.ImpulsiveLoudnessDirection,
    'fz': score.ImpulsiveLoudnessDirection,
    'sf': score.ImpulsiveLoudnessDirection,
    'sffz': score.ImpulsiveLoudnessDirection,
    'sfp': score.ImpulsiveLoudnessDirection,
    'sfzp': score.ImpulsiveLoudnessDirection,
    'sfpp': score.ImpulsiveLoudnessDirection,
    'sfz': score.ImpulsiveLoudnessDirection,
}

def validate_musicxml(xml, debug=False):
    """
    Validate an XML file against an XSD. 
    
    Parameters
    ----------
    xml: str
        Path to XML file
    debug: bool, optional
        If True, raise an exception when the xml is invalid, and print out the
        cause. Otherwise just return True when the XML is valid and False otherwise
    
    Returns
    -------
    bool or None
        None if debug=True, True or False otherwise, signalling validity

    """
    global _XML_VALIDATOR
    if not _XML_VALIDATOR:
        _XML_VALIDATOR = xmlschema.XMLSchema(_MUSICXML_SCHEMA)
    if debug:
        return _XML_VALIDATOR.validate(xml)
    else:
        return _XML_VALIDATOR.is_valid(xml)


def parse_partlist(partlist):
    """
    This parses the <part-list> ... </part-list> element in the beginning
    of the MusicXML file where each instrument is declared, instruments and
    their staves are grouped (braces, brackets), etc.

    Parameters
    ----------
    partlist : etree element
        The part-list etree element

    Returns
    -------
    list:
        list of PartGroup objects
    dict:
        Dictionary of pairs (partid, Part) where the Part objects are
        instantiated with part-name and part-abbreviation if these are specified in
        the part list definition.
    """

    structure = []
    current_group = None
    part_dict = {}

    for e in partlist:
        if e.tag == 'part-group':
            if e.attrib['type'] == 'start':

                gr_name = get_value_from_tag(e, 'group-name', str)
                gr_type = get_value_from_tag(e, 'group-symbol', str)

                new_group = score.PartGroup(gr_type, gr_name)

                if 'number' in e.attrib:
                    new_group.number = int(e.attrib['number'])

                if current_group is None:
                    current_group = new_group
                else:
                    current_group.constituents.append(new_group)
                    new_group.parent = current_group
                    current_group = new_group

            elif e.attrib['type'] == 'stop':
                if current_group.parent is None:
                    structure.append(current_group)
                    current_group = None
                else:
                    current_group = current_group.parent

        elif e.tag == 'score-part':
            part_id = e.attrib['id']
            part = score.Part(part_id)

            # set part name and abbreviation if available
            part.part_name = next(iter(e.xpath('part-name/text()')), None)
            part.part_abbreviation = next(iter(e.xpath('part-abbreviation/text()')), None)

            part_dict[part_id] = part

            if current_group is None:
                structure.append(part)
            else:
                current_group.constituents.append(part)
                sp.parent = current_group

    if current_group:
        LOGGER.warning(
            'part-group {0} was not ended'.format(current_group.number))
        structure.append(current_group)

    return structure, part_dict
    

def load_musicxml(xml, validate=False):
    """
    Parse a MusicXML file and build a composite score ontology
    structure from it (see also scoreontology.py).

    Parameters
    ----------
    xml : str or file-like  object
        Path to the MusicXML file to be parsed, or a file-like object
    validate : bool (optional, default=False)
        When True, the validity of the MusicXML is checked against the MusicXML
        3.1 specification before loading the file. An exception will be raised 
        when the MusicXML is invalid.

    Returns
    -------
    partlist : list
        A list of either Part or PartGroup objects
    """
    if validate:
        validate_musicxml(xml, debug=True)
        # if xml is a file-like object we need to set the read pointer to the
        # start of the file for parsing
        if hasattr(xml, 'seek'):
            xml.seek(0)
    
    parser = etree.XMLParser(resolve_entities=False, huge_tree=False,
                             remove_comments=True, remove_blank_text=True)
    document = etree.parse(xml, parser)
    
    if document.getroot().tag != 'score-partwise':
        raise Exception('Currently only score-partwise structure is supported')

    partlist_el = document.find('part-list')
    
    if partlist_el is not None:
        # parse the (hierarchical) structure of score parts
        # (instruments) that are listed in the part-list element
        partlist, part_dict = parse_partlist(partlist_el)
        # Go through each <part> to obtain the content of the parts.
        # The Part instances will be modified in place
        parse_parts(document, part_dict)
    else:
        partlist = []
    

    return partlist


def parse_parts(document, part_dict):
    """
    Populate the Part instances that are the values of `part_dict` with the musical content in document.

    Parameters
    ----------
    document : lxml.etree.ElementTree
        The ElementTree representation of the MusicXML document
    part_dict : dict
        A dictionary with key--value pairs (part_id, Part instance), as returned
        by the parse_partlist() function.
    """

    for part_el in document.findall('part'):

        part_id = part_el.get('id', 'P1')
        part = part_dict.get(part_id, score.Part(part_id))

        position = 0
        ongoing = {}
    
        # add new page and system at start of part
        handle_new_page(position, part.timeline, ongoing)
        handle_new_system(position, part.timeline, ongoing)
        
        for measure_el in part_el.xpath('measure'):
            position = handle_measure(measure_el, position, part.timeline, ongoing)


def handle_measure(measure_el, position, timeline, ongoing):
    """
    Parse a <measure>...</measure> element, adding it and its contents to the
    timeline.
    """
    # make a measure object
    measure = make_measure(measure_el)

    # add the start of the measure to the time line
    timeline.add_starting_object(position, measure)

    # keep track of the position within the measure
    # measure_pos = 0
    measure_start = position
    # keep track of the previous note (in case of <chord>)
    prev_note = None
    # used to keep track of the duration of the measure
    measure_maxtime = measure_start

    for i, e in enumerate(measure_el):

        if e.tag == 'backup':
    	# <xs:documentation>The backup and forward elements are required
    	# to coordinate multiple voices in one part, including music on
    	# multiple staves. The backup type is generally used to move
    	# between voices and staves. Thus the backup element does not
    	# include voice or staff elements. Duration values should always
    	# be positive, and should not cross measure boundaries or
    	# mid-measure changes in the divisions value.</xs:documentation>

            duration = get_value_from_tag(e, 'duration', int) or 0
            position -= duration
            # <backup> tags trigger an update of the measure
            # duration up to the measure position (after the
            # <backup> has been processed); This has been found to
            # account for implicit measure durations in
            # Baerenreiter MusicXML files.
            measure_maxtime = max(measure_maxtime, position)

        elif e.tag == 'forward':
            duration = get_value_from_tag(e, 'duration', int) or 0
            position += duration
            measure_maxtime = max(measure_maxtime, position)

        elif e.tag == 'attributes':
            handle_attributes(e, position, timeline)

        elif e.tag == 'direction':
            handle_direction(e, position, timeline, ongoing)

        elif e.tag == 'print':
            # new-page/new-system occurring anywhere in the measure take effect
            # at the start of the measure, so we pass measure_start rather than
            # position
            handle_print(e, measure_start, timeline, ongoing)

        elif e.tag == 'sound':
            handle_sound(e, position, timeline)

        elif e.tag == 'note':
            (position, prev_note) = handle_note(e, position, timeline, ongoing, prev_note)
            measure_maxtime = max(measure_maxtime, position)

        elif e.tag == 'barline':
            repeat = e.find('repeat')
            if repeat:
                handle_repeat(repeat, position, timeline, ongoing)

            ending = e.find('ending')
            if ending:
                handle_ending(ending, position, timeline, ongoing)

        else:
            LOGGER.debug('ignoring tag {0}'.format(e.tag))

    timeline.add_ending_object(measure_maxtime, measure)

    return measure_maxtime


def handle_repeat(e, position, timeline, ongoing):
    key = 'repeat'

    if e.get('direction') == 'forward':

        o = score.Repeat()
        ongoing[key] = o
        timeline.add_starting_object(position, o)

    elif e.get('direction') == 'backward':

        o = ongoing.pop(key, None)

        if o is None:
            # implicit repeat start: create Repeat
            # object and add it at the beginning of
            # the self.timeline retroactively
            o = score.Repeat()
            timeline.add_starting_object(0, o)

        timeline.add_ending_object(position, o)


def handle_ending(e, position, timeline, ongoing):
    key = 'ending'
    
    if e.get('type') == 'start':

        o = score.Ending(ending.get('number'))
        ongoing[key] = o
        timeline.add_starting_object(position, o)

    elif e.get('type') in ('stop', 'discontinue'):

        o = ongoing.pop(key, None)

        if o is None:

            LOGGER.warning('Found ending[stop] without a preceding ending[start]')

        else:

            timeline.add_ending_object(position, o)


def handle_new_page(position, timeline, ongoing):
    if 'page' in ongoing:
        if position == 0:
            # ignore non-informative new-page at start of score
            return

        timeline.add_ending_object(position,
                                   ongoing['page'])
        page_nr = ongoing['page'].nr + 1
    else:
        page_nr = 1

    page = score.Page(page_nr)
    timeline.add_starting_object(position, page)
    ongoing['page'] = page


def handle_new_system(position, timeline, ongoing):
    if 'system' in ongoing:

        if position == 0:
            # ignore non-informative new-system at start of score
            return

        # end current page
        timeline.add_ending_object(position, ongoing['system'])
        system_nr = ongoing['system'].nr + 1
    else:
        system_nr = 1

    system = score.System(system_nr)
    timeline.add_starting_object(position, system)
    ongoing['system'] = system


def make_measure(xml_measure):
    measure = score.Measure()
    try:
        measure.number = int(xml_measure.attrib['number'])
    except:
        LOGGER.warn('No number attribute found for measure')
    return measure


def handle_attributes(e, position, timeline):
    """

    """

    ts_num = get_value_from_tag(e, 'time/beats', int)
    ts_den = get_value_from_tag(e, 'time/beat-type', int)
    if ts_num and ts_den:
        timeline.add_starting_object(position, score.TimeSignature(ts_num, ts_den))

    fifths = get_value_from_tag(e, 'key/fifths', int)
    mode = get_value_from_tag(e, 'key/mode', str)
    if fifths is not None or mode is not None:
        timeline.add_starting_object(position, score.KeySignature(fifths, mode))

    diat = get_value_from_tag(e, 'transpose/diatonic', int)
    chrom = get_value_from_tag(e, 'transpose/chromatic', int)
    if diat is not None or chrom is not None:
        timeline.add_starting_object(position, score.Transposition(diat, chrom))
        
    divs = get_value_from_tag(e, 'divisions', int)
    if divs:
        timeline.add_starting_object(position, score.Divisions(divs))

    clefs = get_clefs(e)
    for clef in clefs:
        timeline.add_starting_object(position, score.Clef(**clef))


def get_offset(e):
    offset = e.find('offset')

    if offset:

        sounding = offset.attrib.get('sound', 'no')
        return int(offset.text) if sounding == 'yes' else 0

    else:

        return None


def handle_direction(e, position, timeline, ongoing):

    # <!--
    #     A direction is a musical indication that is not attached
    #     to a specific note. Two or more may be combined to
    #     indicate starts and stops of wedges, dashes, etc.

    #     By default, a series of direction-type elements and a
    #     series of child elements of a direction-type within a
    #     single direction element follow one another in sequence
    #     visually. For a series of direction-type children, non-
    #     positional formatting attributes are carried over from
    #     the previous element by default.
    # -->
    # <!ELEMENT direction (direction-type+, offset?,
    #     %editorial-voice;, staff?, sound?)>
    # <!ATTLIST direction
    #     %placement;
    #     %direction;
    # >

    staff = get_value_from_tag(e, 'staff', int) or 1

    if get_value_from_attribute(e, 'sound/fine', str) == 'yes':
        timeline.add_starting_object(position, Fine())
    if get_value_from_attribute(e, 'sound/dacapo', str) == 'yes':
        timeline.add_starting_object(position, DaCapo())

    # <direction-type> ... </...>
    direction_types = e.findall('direction-type')
    # <!ELEMENT direction-type (rehearsal+ | segno+ | words+ |
    #     coda+ | wedge | dynamics+ | dashes | bracket | pedal |
    #     metronome | octave-shift | harp-pedals | damp | damp-all |
    #     eyeglasses | string-mute | scordatura | image |
    #     principal-voice | accordion-registration | percussion+ |
    #     other-direction)>

    # direction-types supported here:
    # * words
    # * wedge
    # * dynamics
    # * dashes
    # * coda
    # * TODO: pedal
    # * TODO: damp
    
    # here we gather all starting and ending directions, to be added to the timeline afterwards
    starting_directions = []
    ending_directions = []

    # keep track of starting and stopping dashes
    dashes_keys = {}

    for direction_type in direction_types:
        # direction_type 
        dt = next(iter(direction_type))

        if dt.tag == 'dynamics':
            # first child of direction-type is dynamics, there may be subsequent
            # dynamics items, so we loop:
            for child in direction_type:
                # interpret as score.Direction, fall back to score.Words
                dyn_el = next(iter(child))
                if dyn_el is not None:
                    direction = DYN_DIRECTIONS.get(dyn_el.tag, score.Words)(dyn_el.tag, staff=staff)
                    starting_directions.append(direction)
            
        elif dt.tag == 'words':
            # first child of direction-type is words, there may be subsequent
            # words items, so we loop:
            for child in direction_type:

                # try to make a direction out of words
                parse_result = parse_words(child.text)

                if parse_result is not None:

                    if isinstance(parse_result, (list, tuple)):
                        starting_directions.extend(parse_result)
                    else:
                        starting_directions.append(parse_result)

        elif dt.tag == 'wedge':

            number = get_value_from_attribute(dt, 'number', int) or 1
            key = ('wedge', number)
            wedge_type = get_value_from_attribute(dt, 'type', str)

            if wedge_type in ('crescendo', 'diminuendo'):

                o = score.DynamicLoudnessDirection(wedge_type)
                starting_directions.append(o)
                ongoing[key] = o

            elif wedge_type == 'stop':

                o = ongoing.get(key)
                if o is not None:
                    ending_directions.append(o)
                    del ongoing[key]
                else:
                    LOGGER.warning(
                        'Did not find a wedge start element for wedge stop!')

        elif dt.tag == 'dashes':

            # start/stop/continue
            dashes_type = get_value_from_attribute(dt, 'type', str)
            number = get_value_from_attribute(dt, 'number', int) or 1
            dashes_keys[('dashes', number)] = dashes_type
            # TODO: for now we ignore dashes_type == continue, because it exists
            # only as a function of the visual appearance. However, if dashes
            # that are continued over a system are stopped at the end of the
            # system before they are continued at the start of the next, this
            # will not be treated correctly. I'm not sure how dashes spanning
            # systems are encoded in practice (need examples).

        else:
            LOGGER.warning('ignoring direction type: {} {}'.format(
                dt.tag, dt.attrib))

    for dashes_key, dashes_type in dashes_keys.items():

        if dashes_type == 'start':

            ongoing[dashes_key] = starting_directions

        elif dashes_type == 'stop':

            oo = ongoing.get(dashes_key)
            if oo is None:
                LOGGER.warning('Dashes end without dashes start')
            else:
                ending_directions.extend(oo)
                del ongoing[dashes_key]

    for o in starting_directions:
        timeline.add_starting_object(position, o)

    for o in ending_directions:
        timeline.add_ending_object(position, o)


def get_clefs(e):
    """
    Get the clefs

    Returns
    -------

    (fifths, mode) OR None : tuple of or None.

    """
    clefs = e.xpath('clef')
    result = []
    for clef in clefs:
        result.append(dict(number=get_value_from_attribute(clef, 'number', int),
                           sign=get_value_from_tag(clef, 'sign', str),
                           line=get_value_from_tag(clef, 'line', int),
                           octave_change=get_value_from_tag(clef, 'clef-octave-change', int)))
    return result


def get_value_from_tag(e, tag, as_type, none_on_error=True):
    """
    Return the text contents of a particular tag in element e, cast as a
    particular type. By default the function will return None if either the tag
    is not found or the value cannot be cast to the desired type.
    
    Examples
    --------

    >>> e = lxml.etree.fromstring('<note><duration>2</duration></note>') 
    >>> get_value_from_tag(e, 'duration', int)
    2
    >>> get_value_from_tag(e, 'duration', float)
    2.0

    >>> e = lxml.etree.fromstring('<note><duration>quarter</duration></note>')
    >>> get_value_from_tag(e, 'duration', float)
    None
    

    Parameters
    ----------
    e: etree.Element
        An etree Element instance
    tag: string
        Child tag to retrieve
    as_type: function
        Function that casts the string to the desired type (e.g. int, float)
    none_on_error: bool, optional (default: True)
        When False, an exception is raised when `tag` is not found in `e` or the
        text inside `tag` cannot be cast to an integer. When True, None is returned
        in such cases.
    
    Returns
    -------
    object
        The value read from `tag`, cast as `as_type`
    """
    try:
        return as_type(e.find(tag).text)
    except:
        if none_on_error:
            return None
        else:
            raise


def get_value_from_attribute(e, attr, as_type, none_on_error=True):
    """
    Return the attribute of a particular attribute of element e, cast as a
    particular type. By default the function will return None if either `e` does
    not have the attribute or the value cannot be cast to the desired type.

    Parameters
    ----------
    e: etree.Element
        An etree Element instance
    attr: string
        Attribute to retrieve
    as_type: function
        Function that casts the string to the desired type (e.g. int, float)
    none_on_error: bool, optional (default: True)
        When False, an exception is raised when `tag` is not found in `e` or the
        text inside `tag` cannot be cast to an integer. When True, None is returned
        in such cases.
    
    Returns
    -------
    object or None
        The attribute value, or None
    """

    value = e.get(attr)
    if value is None:
        return None
    else:
        try:
            return as_type(value)
        except:
            if none_on_error:
                return None
            else:
                raise


def get_pitch(e):
    """
    Check whether the element has a pitch. If so return a tuple (pitch, alter,
    octave), otherwise return None.

    Returns
    -------
    tuple : (str, int or None, int) or None
        The tuple contains (pitch, alter, octave)
    """

    pitch = e.find('pitch')
    if pitch:
        step = get_value_from_tag(pitch, 'step', str)
        alter = get_value_from_tag(pitch, 'alter', int)
        octave = get_value_from_tag(pitch, 'octave', int)
        return (step, alter, octave)
    else:
        return None


def handle_print(e, position, timeline, ongoing):
    if "new-page" in e.attrib:
        handle_new_page(position, timeline, ongoing)
        handle_new_system(position, timeline, ongoing)
    if "new-system" in e.attrib:
        handle_new_system(position, timeline, ongoing)

def handle_sound(e, position, timeline):
    if "tempo" in e.attrib:
        timeline.add_starting_object(position, Tempo(int(e.attrib['tempo'])))

def handle_note(e, position, timeline, ongoing, prev_note):

    # prev_note is used when the current note has a <chord/> tag

    # get some common features of element if available
    duration = get_value_from_tag(e, 'duration', int) or 0
    # elements may have an explicit temporal offset
    offset = get_value_from_tag(e, 'offset', int) or 0
    staff = get_value_from_tag(e, 'staff', int) or 0
    voice = get_value_from_tag(e, 'voice', int) or 0

    note_id = get_value_from_attribute(e, 'id', str)

    symbolic_duration = {}
    symbolic_duration['type'] = get_value_from_tag(e, 'type', str)
    symbolic_duration['dots'] = len(e.findall('dot'))
    symbolic_duration['actual_notes'] = get_value_from_tag(e, 'time-modification/actual-notes', int)
    symbolic_duration['normal_notes'] = get_value_from_tag(e, 'time-modification/normal-notes', int)

    chord = e.find('chord') is not None
    if chord:
        # this note starts at the same position as the previous note, and has same duration
        assert prev_note is not None
        position = prev_note.start.t
        # duration = prev_note.duration
        
        # TODO: fix logic for Chord instances

        # if 'chord' in ongoing:
        #     chord = ongoing['chord']
        # else:
        #     chord = score.Chord()
        #     timeline.add_starting_object(prev_note.start.t, chord)
        #     ongoing['chord'] = chord
    else:
        # end the current chord

        # if 'chord' in ongoing:
        #     chord = ongoing['chord']
        #     self.timeline.add_ending_object(
        #         position, chord)
        #     del self.ongoing['chord']
        pass

    pitch = e.find('pitch')
    if pitch is not None:

        step = get_value_from_tag(pitch, 'step', str)
        alter = get_value_from_tag(pitch, 'alter', int)
        octave = get_value_from_tag(pitch, 'octave', int)

        grace = e.find('grace')

        if grace is not None:
            grace_type, steal_proportion = get_grace_info(grace)
            note = score.GraceNote(grace_type, step, alter, octave,
                                   note_id, voice, staff, symbolic_duration,
                                   steal_proportion=steal_proportion)
        else:

            note = score.Note(step, alter, octave, note_id, voice, staff, symbolic_duration)

    else:
        # note element is a rest
        note = score.Rest(note_id, voice, staff, symbolic_duration)

    timeline.add_starting_object(position, note)
    timeline.add_ending_object(position+duration, note)

    ties = e.findall('tie')
    if ties:

        # TODO: this fails when note is a rest
        tie_key = ('tie', note.midi_pitch)
        tie_types = set(tie.attrib['type'] for tie in ties)

        if 'stop' in tie_types:

            tie_prev = ongoing.get(tie_key, None)

            if tie_prev:

                note.tie_prev = tie_prev
                tie_prev.tie_next = note
                del ongoing[tie_key]

        if 'start' in tie_types:

            ongoing[tie_key] = note


    # staccato = e.find('notations/articulations/staccato') is not None
    # accent = e.find('notations/articulations/accent') is not None
    notations = e.find('notations')
    if notations is not None:
        if notations.find('fermata'):
            self.timeline.add_starting_object(position, score.Fermata(note))

        slurs = notations.findall('slur')

        # this sorts all found slurs by type (either 'start' or 'stop')
        # in reverse order, so all with type 'stop' will be before
        # the ones with 'start'?!.
        slurs.sort(key=lambda x: x.attrib['type'], reverse=True)

        # Now that the slurs are sorted by their type, sort them
        # by their numbers; First note that slurs do not always
        # have a number attribute, then 1 is implied.
        slurs.sort(key=lambda x: get_value_from_attribute(x, 'number', int) or 1)
        
        for slur_e in slurs:

            slur_number = get_value_from_attribute(slur_e, 'number', int)
            slur_type = get_value_from_attribute(slur_e, 'type', str)
            start_slur_key = ('start_slur', slur_number)
            stop_slur_key = ('stop_slur', slur_number)

            if slur_type == 'start':

                # check if we have a stopped_slur in ongoing that corresponds to
                # this stop
                slur = ongoing.pop(stop_slur_key, None)

                if slur is None:

                    slur = score.Slur(note)
                    ongoing[start_slur_key] = slur

                note.slur_starts.append(slur)
                timeline.add_starting_object(position, slur)

            elif slur_type == 'stop':

                slur = ongoing.pop(start_slur_key, None)
                if slur is None:
                    # slur stop occurs before slur start in document order, that
                    # is a valid scenario
                    slur = score.Slur(None, note)
                    ongoing[stop_slur_key] = slur
                else:
                    slur.end_note = note

                note.slur_stops.append(slur)
                timeline.add_ending_object(position, slur)

                
    new_position = position + duration

    return new_position, note 


def get_grace_info(grace):
    # grace note handling
    grace_type = 'grace'
    steal_proportion = None

    slash_text = get_value_from_attribute(grace, 'slash', str)
    if slash_text == 'yes':
        grace_type = 'acciaccatura'

    steal_prc = get_value_from_attribute(grace, 'steal-time-following', float)
    if steal_prc is not None:
        steal_proportion = steal_prc / 100
        grace_type = 'appoggiatura'

    steal_prec = get_value_from_attribute(grace, 'steal-time-previous', float)
    if steal_prc is not None:
        steal_proportion = steal_prc / 100
        grace_type = 'acciaccatura'

    return grace_type, steal_proportion


SCORE_DTYPES = [('pitch', 'i4'), ('onset', 'f4'), ('duration', 'f4')]

def xml_to_notearray(fn, flatten_parts=True, sort_onsets=True,
                     expand_grace_notes=True, validate=False):
    """
    Get a note array from a MusicXML file

    Parameters
    ----------
    fn : str
        Path to a MusicXML file
    flatten_parts : bool
        If `True`, returns a single array containing all notes.
        Otherwise, returns a list of arrays for each part.
    expand_grace_notes : bool or 'delete'

    Returns
    -------
    score : structured array or list of structured arrays
        Structured array containing the score. The fields are
        'pitch', 'onset' and 'duration'.
    """

    if not isinstance(expand_grace_notes, (bool, str)):
        raise ValueError('`expand_grace_notes` must be a boolean or '
                         '"delete"')
    delete_grace_notes = False
    if isinstance(expand_grace_notes, str):

        if expand_grace_notes in ('omit', 'delete', 'd'):
            expand_grace_notes = False
            delete_grace_notes = True
        else:
            raise ValueError('`expand_grace_notes` must be a boolean or '
                             '"delete"')

    # Parse MusicXML
    parts = load_musicxml(fn, validate)
    score = []
    for part in parts:
        # Unfold timeline to have repetitions
        print(part.pprint())
        if expand_grace_notes:
            LOGGER.debug('Expanding grace notes...')
            part.expand_grace_notes()

        part.timeline = part.unfold_timeline()
        # get beat map
        bm = part.beat_map
        print('ja')
        # Build score from beat map
        _score = np.array(
            [(n.midi_pitch, bm(n.start.t), bm(n.end.t) - bm(n.start.t))
             for n in part.notes],
            dtype=SCORE_DTYPES)

        # Sort notes according to onset
        if sort_onsets:
            _score = _score[_score['onset'].argsort()]

        if delete_grace_notes:
            LOGGER.debug('Deleting grace notes...')
            _score = _score[_score['duration'] != 0]
        score.append(_score)

    # Return a structured array if the score has only one part
    if len(score) == 1:
        return score[0]
    elif len(score) > 1 and flatten_parts:
        score = np.vstack(score)
        if sort_onsets:
            return score[score['onset'].argsort()]
    else:
        return score

