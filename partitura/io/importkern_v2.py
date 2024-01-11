#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This module contains methods for importing Humdrum Kern files.
"""
import re
import warnings

from typing import Union, Optional

import numpy as np

import partitura.score as spt
from partitura.utils import PathLike


SIGN_TO_ACC = {
    "n": 0,
    "#": 1,
    "s": 1,
    "ss": 2,
    "x": 2,
    "##": 2,
    "###": 3,
    "b": -1,
    "f": -1,
    "bb": -2,
    "ff": -2,
    "bbb": -3,
    "-": None,
}

KERN_NOTES = {
    "C": ("C", 3),
    "D": ("D", 3),
    "E": ("E", 3),
    "F": ("F", 3),
    "G": ("G", 3),
    "A": ("A", 3),
    "B": ("B", 3),
    "c": ("C", 4),
    "d": ("D", 4),
    "e": ("E", 4),
    "f": ("F", 4),
    "g": ("G", 4),
    "a": ("A", 4),
    "b": ("B", 4),
}

KERN_DURS = {
    "000": "maxima",
    "00": "long",
    "0": "breve",
    "1": "whole",
    "2": "half",
    "4": "quarter",
    "8": "eighth",
    "16": "16th",
    "32": "32nd",
    "64": "64th",
    "128": "128th",
    "256": "256th",
}


def add_durations(a, b):
    return a*b / (a + b)


def dot_function(duration, dots):
    if dots == 0:
        return duration
    else:
        return add_durations((2**dots)*duration, dot_function(duration, dots - 1))

def parse_by_voice(file, dtype=np.object_):
    indices_to_remove = []
    voices = 1
    for i, line in enumerate(file):
        try:
            if any([line[v] == "*^" for v in range(voices)]):
                voices += 1
            elif sum([(line[v] == "*v") for v in range(voices)]):
                voices -= sum([line[v] == "*v" for v in range(voices)]) // 2
            else:
                for v in range(voices):
                    indices_to_remove.append([i, v])
        except IndexError:
            pass


    voice_indices = np.array(indices_to_remove)
    num_voices = voice_indices[:, 1].max() + 1
    data = np.empty((len(file), num_voices), dtype=dtype)
    for line, voice in voice_indices:
        data[line, voice] = file[line][voice]
    data = data.T
    if num_voices > 1:
        # Copy global lines from the first voice to all other voices
        cp_idx = np.char.startswith(data[0], "*")
        for i in range(1, num_voices):
            data[i][cp_idx] = data[0][cp_idx]
        # Copy Measure Lines from the first voice to all other voices
        cp_idx = np.char.startswith(data[0], "=")
        for i in range(1, num_voices):
            data[i][cp_idx] = data[0][cp_idx]
    return data, voice_indices


def _handle_kern_with_spine_splitting(kern_path):
    file = np.loadtxt(kern_path, dtype=str, delimiter="\n", comments="!", encoding="utf-8")
    # Get Main Number of parts and Spline Types
    spline_types = file[0].split("\t")
    dtype = file.dtype
    data = []
    file = file.tolist()
    file = [line.split("\t") for line in file]
    continue_parsing = True
    for i in range(len(spline_types)):
        # Parse by voice
        d, voice_indices = parse_by_voice(file, dtype=dtype)
        data.append(d)
        # Remove all parsed cells from the file
        voice_indices = voice_indices[np.lexsort((voice_indices[:, 1]*-1, voice_indices[:, 0]))]
        for line, voice in voice_indices:
            file[line].pop(voice)

    data = np.vstack(data).T
    return data
    #
    #
    # # Find all expansions points
    # expansion_indices = np.where(np.char.find(file, "*^") != -1)[0]
    # # For all expansion points find which stream is being expanded
    # expansion_streams_per_index = [np.argwhere(np.array(line.split("\t")) == "*^")[0] for line in
    #                                file[expansion_indices]]
    #
    # # Find all Spline Reduction points
    # reduction_indices = np.where(np.char.find(file, "*v\t*v") != -1)[0]
    # # For all reduction points find which stream is being reduced
    # reduction_streams_per_index = [
    #     np.argwhere(np.char.add(np.array(line.split("\t")[:-1]), np.array(line.split("\t")[1:])) == "*v*v")[0] for line
    #     in file[reduction_indices]]
    #
    # # Find all pairs of expansion and reduction points
    # expansion_reduction_pairs = []
    # last_exhaustive_reduction = 0
    # for expansion_index in expansion_indices:
    #     for expansion_stream in expansion_index:
    #         # Find the first reduction index that is after the expansion index and has the same index.
    #         for i, reduction_index in enumerate(reduction_indices[last_exhaustive_reduction:]):
    #             for reduction_stream in reduction_streams_per_index[i]:
    #                 if expansion_stream == reduction_stream:
    #                     expansion_reduction_pairs.append((expansion_index, reduction_index))
    #                     last_exhaustive_reduction = i if i == last_exhaustive_reduction + 1 else last_exhaustive_reduction
    #                     break


# functions to initialize the kern parser
def parse_kern(kern_path: PathLike, num_workers=0) -> np.ndarray:
    """
    Parses an KERN file from path to Part.

    Parameters
    ----------
    kern_path : PathLike
        The path of the KERN document.
    Returns
    -------
    continuous_parts : numpy character array
    non_continuous_parts : list
    """
    try:
        # This version of the parser is faster but does not support spine splitting.
        file = np.loadtxt(kern_path, dtype=str, delimiter="\t", comments="!", encoding="utf-8")
        # Decide Parts
        parts = []
    except ValueError:
        # This version of the parser supports spine splitting but is slower.
        file = _handle_kern_with_spine_splitting(kern_path)
        parts = []


    # Get Main Number of parts and Spline Types
    spline_types = file[0]

    # Find parsable parts if they start with "**kern" or "**notes"
    note_parts = np.char.startswith(spline_types, "**kern") | np.char.startswith(spline_types, "**notes")

    # Get Splines
    splines = file[1:].T[note_parts]
    for spline in splines:
        parser = SplineParser(size=spline.shape[-1])
        same_part = False
        if parser.id in [p.id for p in parts]:
            same_part = True
            warnings.warn("Part {} already exists. Adding to previous Part.".format(parser.id))
            parser.voice += 1
            part = [p for p in parts if p.id == parser.id][0]
            has_staff = np.char.startswith(spline, "*staff")
            staff = int(spline[has_staff][0][6:]) if np.count_nonzero(has_staff) else 1
            if parser.staff != staff:
                parser.staff = staff
            else:
                parser.voice += 1
            elements = parser.parse(spline)
            unique_durs = np.unique(parser.total_duration_values).astype(int)
            divs_pq = np.lcm.reduce(unique_durs)
            divs_pq = divs_pq if divs_pq > 4 else 4
            part.set_quarter_duration(0, divs_pq)
        else:
            elements = parser.parse(spline)
            unique_durs = np.unique(parser.total_duration_values).astype(int)
            divs_pq = np.lcm.reduce(unique_durs)
            divs_pq = divs_pq if divs_pq > 4 else 4
            # Initialize Part
            part = spt.Part(id=parser.id, quarter_duration=divs_pq, part_name=parser.name)
        current_tl_pos = 0

        for i in range(elements.shape[0]):
            element = elements[i]
            if element is None:
                continue
            if isinstance(element, spt.GenericNote):
                quarter_duration = 4 / parser.total_duration_values[i]
                duration_divs = int(quarter_duration*divs_pq)
                el_end = current_tl_pos + duration_divs
                part.add(element, start=current_tl_pos, end=el_end)
                current_tl_pos = el_end
            elif isinstance(element, tuple):
                # Chord
                quarter_duration = 4 / parser.total_duration_values[i]
                duration_divs = int(part.inv_quarter_map(quarter_duration))
                el_end = current_tl_pos + duration_divs
                for note in element[1]:
                    part.add(note, start=current_tl_pos, end=el_end)
                current_tl_pos = el_end
            else:
                # Do not repeat structural elements if they are being added to the same part.
                if not same_part:
                    part.add(element, start=current_tl_pos)

        # For all measures add end time as beginning time of next measure
        measures = part.measures
        for i in range(len(measures) - 1):
            measures[i].end = measures[i + 1].start
            measures[-1].end = part.last_point

        if parser.id not in [p.id for p in parts]:
            parts.append(part)
    return spt.Score(parts)


class SplineParser(object):
    def __init__(self, id="P1", staff=1, voice=1, size=1, name=""):
        self.id = id
        self.name = name
        self.staff = staff
        self.voice = voice
        self.total_duration_values = []
        self.size = size
        self.total_parsed_elements = 0
        self.tie_prev = None
        self.tie_next = None

    def parse(self, spline):
        # Remove "-" lines
        spline = spline[spline != "-"]
        # Remove "." lines
        spline = spline[spline != "."]
        # Remove Empty lines
        spline = spline[spline != ""]
        # Empty Numpy array with objects
        elements = np.empty(len(spline), dtype=object)
        self.total_duration_values = np.ones(len(spline))
        # Find Global indices, i.e. where spline cells start with "*" and process
        tandem_mask = np.char.find(spline, "*") != -1
        elements[tandem_mask] = np.vectorize(self.meta_tandem_line, otypes=[object])(spline[tandem_mask])
        # Find Barline indices, i.e. where spline cells start with "="
        bar_mask = np.char.find(spline, "=") != -1
        elements[bar_mask] = np.vectorize(self.meta_barline_line, otypes=[object])(spline[bar_mask])
        # Find Chord indices, i.e. where spline cells contain " "
        chord_mask = np.char.find(spline, " ") != -1
        self.total_parsed_elements = -1
        self.note_duration_values = np.ones(len(spline[chord_mask]))
        chord_num = np.count_nonzero(chord_mask)
        self.tie_next = np.zeros(chord_num, dtype=bool)
        self.tie_prev = np.zeros(chord_num, dtype=bool)
        elements[chord_mask] = np.vectorize(self.meta_chord_line, otypes=[object])(spline[chord_mask])
        self.total_duration_values[chord_mask] = self.note_duration_values
        # TODO: figure out slurs for chords

        # All the rest are note indices
        note_mask = np.logical_and(~tandem_mask, np.logical_and(~bar_mask, ~chord_mask))
        self.total_parsed_elements = -1
        self.note_duration_values = np.ones(len(spline[note_mask]))
        note_num = np.count_nonzero(note_mask)
        self.tie_next = np.zeros(note_num, dtype=bool)
        self.tie_prev = np.zeros(note_num, dtype=bool)
        notes = np.vectorize(self.meta_note_line, otypes=[object])(spline[note_mask])
        self.total_duration_values[note_mask] = self.note_duration_values
        # shift tie_next by one to the right
        for note, to_tie in np.c_[notes[self.tie_next], notes[np.roll(self.tie_next, -1)]]:
            to_tie.tie_next = note
            # note.tie_prev = to_tie
        for note, to_tie in np.c_[notes[self.tie_prev], notes[np.roll(self.tie_prev, 1)]]:
            note.tie_prev = to_tie
            # to_tie.tie_next = note

        elements[note_mask] = notes
        return elements

    def meta_tandem_line(self, line):
        """
        Find all tandem lines
        """
        # find number and keep its index.
        self.total_parsed_elements += 1
        if line.startswith("*MM"):
            rest = line[3:]
            return self.process_tempo_line(rest)
        elif line.startswith("*I"):
            rest = line[2:]
            return self.process_istrument_line(rest)
        elif line.startswith("*clef"):
            rest = line[5:]
            return self.process_clef_line(rest)
        elif line.startswith("*M"):
            rest = line[2:]
            return self.process_meter_line(rest)
        elif line.startswith("*k"):
            rest = line[2:]
            return self.process_key_signature_line(rest)
        elif line.startswith("*IC"):
            rest = line[3:]
            return self.process_istrument_class_line(rest)
        elif line.startswith("*IG"):
            rest = line[3:]
            return self.process_istrument_group_line(rest)
        elif line.startswith("*tb"):
            rest = line[3:]
            return self.process_timebase_line(rest)
        elif line.startswith("*ITr"):
            rest = line[4:]
            return self.process_istrument_transpose_line(rest)
        elif line.startswith("*staff"):
            rest = line[6:]
            return self.process_staff_line(rest)
        elif line.endswith(":"):
            rest = line[1:]
            return self.process_key_line(rest)
        elif line.startswith("*-"):
            return self.process_fine()

    def process_tempo_line(self, line):
        return spt.Tempo(float(line))

    def process_fine(self):
        return spt.Fine()

    def process_istrument_line(self, line):
        #TODO: add support for instrument lines
        return

    def process_istrument_class_line(self, line):
        # TODO: add support for instrument class lines
        return

    def process_istrument_group_line(self, line):
        # TODO: add support for instrument group lines
        return

    def process_timebase_line(self, line):
        # TODO: add support for timebase lines
        return

    def process_istrument_transpose_line(self, line):
        # TODO: add support for instrument transpose lines
        return

    def process_key_line(self, line):
        find = re.search(r"([a-gA-G])", line).group(0)
        # check if the key is major or minor by checking if the key is in lower or upper case.
        self.mode = "minor" if find.islower() else "major"
        return

    def process_staff_line(self, line):
        self.staff = int(line)
        return spt.Staff(self.staff)

    def process_clef_line(self, line):
        # if the cleff line does not contain any of the following characters, ["G", "F", "C"], raise a ValueError.
        if not any(c in line for c in ["G", "F", "C"]):
            raise ValueError("Unrecognized clef line: {}".format(line))
        # find the clef
        clef = re.search(r"([GFC])", line).group(0)
        # find the octave
        line = re.search(r"([0-9])", line).group(0)
        return spt.Clef(sign=clef, staff=self.staff, line=int(line), octave_change=0)

    def process_key_signature_line(self, line):
        fifths = line.count("#") - line.count("-")
        # TODO retrieve the key mode
        mode = "major"
        return spt.KeySignature(fifths, mode)

    def process_meter_line(self, line):
        if " " in line:
            line = line.split(" ")[0]
        numerator, denominator = map(eval, line.split("/"))
        return spt.TimeSignature(numerator, denominator)

    def _process_kern_pitch(self, pitch):
        # find accidentals
        alter = re.search(r"([n#\-]+)", pitch)
        # remove alter from pitch
        pitch = pitch.replace(alter.group(0), "") if alter else pitch
        step, octave = KERN_NOTES[pitch[0]]
        if octave == 4:
            octave = octave + pitch.count(pitch[0]) - 1
        elif octave == 3:
            octave = octave - pitch.count(pitch[0]) + 1
        alter = SIGN_TO_ACC[alter.group(0)] if alter else None
        return step, octave, alter

    def _process_kern_duration(self, duration):
        dur = duration.replace(".", "")
        if dur in KERN_DURS.keys():
            symbolic_duration = {"type": KERN_DURS[dur]}
        else:
            dur = eval(dur)
            diff = dict(
                (
                    map(
                        lambda x: (str(dur - int(x)), str(int(x))) if dur > int(x) else (str(dur + int(x)), str(int(x))),
                        KERN_DURS.keys(),
                    )
                )
            )

            symbolic_duration = {
                "type": KERN_DURS[diff[min(list(diff.keys()))]],
                "actual_notes": dur / 4,
                "normal_notes": int(diff[min(list(diff.keys()))]) / 4,
            }
        symbolic_duration["dots"] = duration.count(".")
        self.note_duration_values[self.total_parsed_elements] = dot_function(float(dur), symbolic_duration["dots"])
        return symbolic_duration

    def process_symbol(self, note, symbols):
        """
        Process the symbols of a note.

        Parameters
        ----------
        note
        symbol

        Returns
        -------

        """
        if "[" in symbols:
            self.tie_prev[self.total_parsed_elements] = True
            # pop symbol and call again
            symbols.pop(symbols.index("["))
            self.process_symbol(note, symbols)
        if "]" in symbols:
            self.tie_next[self.total_parsed_elements] = True
            symbols.pop(symbols.index("]"))
            self.process_symbol(note, symbols)
        if "_" in symbols:
            # continuing tie
            self.tie_prev[self.total_parsed_elements] = True
            self.tie_next[self.total_parsed_elements] = True
            symbols.pop(symbols.index("_"))
            self.process_symbol(note, symbols)
        return

    def meta_note_line(self, line, voice=None, add=True):
        """
        Grammar Defining a note line.

        A note line is specified by the following grammar:
        note_line = symbol | duration | pitch | symbol

        Parameters
        ----------
        line

        Returns
        -------

        """
        self.total_parsed_elements += 1 if add else 0
        voice = self.voice if voice is None else voice
        # extract first occurence of one of the following: a-g A-G r # - n
        pitch = re.search(r"([a-gA-Gr\-n#]+)", line).group(0)
        # extract duration can be any of the following: 0-9 .
        duration = re.search(r"([0-9]+|\.)", line).group(0)
        # extract symbol can be any of the following: _()[]{}<>|:
        symbols = re.findall(r"([_()\[\]{}<>|:])", line)
        symbolic_duration = self._process_kern_duration(duration)
        el_id = "{}-s{}-v{}-el{}".format(self.id, self.staff, voice, self.total_parsed_elements)
        if pitch.startswith("r"):
            return spt.Rest(symbolic_duration=symbolic_duration, staff=self.staff, voice=voice, id=el_id)
        step, octave, alter = self._process_kern_pitch(pitch)
        note = spt.Note(step, octave, alter, symbolic_duration=symbolic_duration, staff=self.staff, voice=voice, id=el_id)
        if symbols:
            self.process_symbol(note, symbols)
        return note

    def meta_barline_line(self, line):
        """
        Grammar Defining a barline line.

        A barline line is specified by the following grammar:
        barline_line = repeat | barline | number | repeat

        Parameters
        ----------
        line

        Returns
        -------

        """
        # find number and keep its index.
        self.total_parsed_elements += 1
        number = re.findall(r"([0-9]+)", line)
        number_index = line.index(number[0]) if number else line.index("=")
        closing_repeat = re.findall(r"[:|]", line[:number_index])
        opening_repeat = re.findall(r"[|:]", line[number_index:])
        return spt.Measure(number=int(number[0]) if number else None)

    def meta_chord_line(self, line):
        """
        Grammar Defining a chord line.

        A chord line is specified by the following grammar:
        chord_line = note | chord

        Parameters
        ----------
        line

        Returns
        -------

        """
        self.total_parsed_elements += 1
        chord = ("c", [self.meta_note_line(n, add=False) for n in line.split(" ")])
        return chord


if __name__ == "__main__":
    kern_path = "/home/manos/Desktop/test.krn"
    x = parse_kern(kern_path)
    import partitura as pt
    pt.save_musicxml(x, "/home/manos/Desktop/test_kern.musicxml")