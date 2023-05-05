#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This module implement a series of mid-level descriptors of the performance expressions: asynchrony, dynamics, articulation, phrasing...
Built upon the low-level basis functions from the performance codec. 
"""

# from typing import str 
import warnings
import numpy as np
np.set_printoptions(suppress=True)
import matplotlib.pyplot as plt
from scipy import stats
from scipy.optimize import least_squares
import numpy.lib.recfunctions as rfn
from partitura.score import ScoreLike
from partitura.performance import PerformanceLike
from partitura.utils import music
from partitura.musicanalysis.performance_codec import to_matched_score, encode_performance, encode_tempo


# ordinal 
OLS = ["ppp", "pp", "p", "mp", "mf", "f", "ff", "fff"]

def get_performance_expressions(score: ScoreLike, 
                                performance: PerformanceLike,
                                alignment: list
):
    """
    Compute the performance expression attributes 

    Parameters
    ----------
    score : partitura.score.ScoreLike
        Score information, can be a part, score
    performance : partitura.performance.PerformanceLike
        Performance information, can be a ppart, performance
    alignment : list
        The score--performance alignment, a list of dictionaries

    Returns
    -------
    expressions : dict
        
    """
    m_score, snote_ids = to_matched_score(score, performance, alignment, include_score_markings=True)
    (time_params, unique_onset_idxs) = encode_tempo(
        score_onsets=m_score["onset"],
        performed_onsets=m_score["p_onset"],
        score_durations=m_score["duration"],
        performed_durations=m_score["p_duration"],
        return_u_onset_idx=True,
        tempo_smooth="average"
    )
    m_score = rfn.append_fields(m_score, "beat_period", time_params['beat_period'], "f4", usemask=False)

    async_ = async_attributes(unique_onset_idxs, m_score)
    dynamics_ = dynamics_attributes(m_score)
    articulations_ = articulation_attributes(m_score)
    phrasing_ = phrasing_attributes(m_score, 
                                    unique_onset_idxs,
                                    # plot=True
                                    )
    return {
        "asynchrony": async_,
        "dynamics": dynamics_,
        "articulations": articulations_,
        "phrasing": phrasing_
    }


### Asynchrony
def async_attributes(unique_onset_idxs: list,
                     m_score: list,
                     v=False):
    """
    Compute the asynchrony attributes from the alignment. 
        - delta: the largest time difference between onsets in this group (-inf, inf)
        - pitch_cor: correlation between timing and pitch [-1, 1]
        - vel_cor: correlation between timing and velocity [-1, 1]
        - voice_std: std of the avg timing of each voice in this group (-inf, inf)

    Parameters
    ----------
    unique_onset_idxs : list
        a list of arrays with the note indexes that have the same onset
    m_score : list
        correspondance between score and performance notes, with score markings. 
    
    Returns
    -------
    async_ : structured array
        structured array (on the onset level) with fields delta, pitch_cor, vel_cor, voice_cor
    """
    
    async_ = np.zeros(len(unique_onset_idxs), dtype=[(
        "delta", "f4"), ("pitch_cor", "f4"), ("vel_cor", "f4"), ("voice_std", "f4")])
    for i, onset_idxs in enumerate(unique_onset_idxs):

        note_group = m_score[onset_idxs]

        onset_times = note_group['p_onset']
        delta = onset_times.max() - onset_times.min()
        async_[i]['delta'] = delta 

        midi_pitch = note_group['pitch']
        midi_pitch = midi_pitch - midi_pitch.min() # min-scaling
        onset_times = onset_times - onset_times.min()
        cor = (-1) * np.corrcoef(midi_pitch, onset_times)[0, 1]
        # cor=nan if there is only one note in the group
        async_[i]['pitch_cor'] = (0 if np.isnan(cor) else cor)

        midi_vel = note_group['velocity'].astype(float)
        midi_vel = midi_vel - midi_vel.min()
        cor = (-1) * np.corrcoef(midi_vel, onset_times)[0, 1]
        async_[i]['vel_cor'] = (0 if np.isnan(cor) else cor)

        voices = np.unique(note_group['voice'])
        voices_onsets = []
        for voice in voices:
            note_in_voice = note_group[note_group['voice'] == voice]
            voices_onsets.append(note_in_voice['p_onset'].mean())
        async_[i]['voice_std'] = np.std(np.array(voices_onsets))
        
    return async_

def map_fields(note_info, fields):
    """
    map the one-hot fields of dynamics and articulation marking into one column with field.

    Args:
        note_info (np.array): a row slice from the note_array, without dtype names
        fields (list): list of tuples (index, field name)

    Returns:
        string: the name of the marking. 
    """

    for i, name in fields:
        if note_info[i] == 1:
            # hack for the return type
            return np.array([name.split(".")[-1]], dtype="U256")
    return np.array(["N/A"], dtype="U256")

### Dynamics 
def dynamics_attributes(m_score : list,
                        window : int = 3,
                        agg : str = "avg"):
    """
    Compute the dynamics attributes from the alignment.

    Parameters
    ----------
    m_score : structured array
        correspondance between score and performance notes, with score markings. 
    window : int
        Length of window to look at the range of dynamic marking coverage, default 3. 
    agg : string
        how to aggregate velocity of notes with the same marking, default avg

    Returns
    -------
    dynamics_ : structured array
        structured array on the piece level with fields agreement and consistency
    """  
    dynamics_ = np.zeros(1, dtype=[("dyn_agreement", "f4"), ("dyn_consistency_std", "f4")])    

    fields = [(i, name) for i, name in enumerate(m_score.dtype.names) if "loudness" in name]
    constant_dyn = np.apply_along_axis(map_fields, 1, rfn.structured_to_unstructured(m_score), fields).flatten()
    m_score = rfn.rec_append_fields(m_score, "constant_dyn", constant_dyn, "U256")

    # append the marking into m_score based on the time position and windowing
    beats_with_constant_dyn = np.unique(m_score[m_score['constant_dyn'] != 'N/A']['onset'])
    markings = [m_score[m_score['onset'] == b]['constant_dyn'][0] for b in beats_with_constant_dyn]
    velocity = [m_score[m_score['onset'] == b]['velocity'] for b in beats_with_constant_dyn]
    velocity_agg = [np.mean(v_group) for v_group in velocity]

    # TODO: changing dynamics

    constant_dynamics = list(zip(markings, velocity_agg))

    if len(constant_dynamics) < 2:
        return dynamics_

    # agreement: compare each adjacent pair of markings with their expected order, average
    tau_total = 0
    for marking1, marking2 in zip(constant_dynamics, constant_dynamics[1:]):
        m1, v1 = marking1
        m2, v2 = marking2
        m1_, m2_ = OLS.index(m1), OLS.index(m2)
        # preventing correlation returning nan when the values are constant
        v2 = v2 + 1e-5
        m2_ = m2_ + 1e-5        
        tau, _ = stats.kendalltau([v1, v2], [m1_, m2_])
        assert(tau == tau) # not nan
        tau_total += tau
    dynamics_['dyn_agreement'] = tau_total / (len(constant_dynamics)-1)

    # consistency: how much fluctuations does each marking have 
    velocity_std = [np.std(v_group) for v_group in velocity]
    dynamics_["dyn_consistency_std"] = np.mean(np.array(velocity_std))

    return dynamics_


### Articulation
def articulation_attributes(m_score):
    """
    Compute the articulation attributes (key overlap ratio) from the alignment.
    Key overlap ratio is the ratio between key overlap time (KOT) and IOI, result in a value between (-1, inf)
    -1 is the dummy value. 
    B.Repp: Acoustics, Perception, and Production of Legato Articulation on a Digital Piano

    Parameters
    ----------
    m_score : structured array
        correspondance between score and performance notes, with score markings. 

    Returns
    -------
    kor_ : structured array
        structured array on the onset level with fields kor, kor_legato, kor_staccato, 
        kor_repeated
    """  
    
    m_score = rfn.append_fields(m_score, "offset", m_score['onset'] + m_score['duration'], usemask=False)
    m_score = rfn.append_fields(m_score, "p_offset", m_score['p_onset'] + m_score['p_duration'], usemask=False)

    kor_ =  (-1) * np.ones((len(m_score)))
    kor_ = np.array(kor_, dtype=[("kor", "f4"), ("kor_legato", "f4"), ("kor_staccato", "f4"),  ("kor_repeated", "f4")])

    fields = [(i, name) for i, name in enumerate(m_score.dtype.names) if "articulation" in name]
    articulation = np.apply_along_axis(map_fields, 1, rfn.structured_to_unstructured(m_score), fields).flatten()
    m_score = rfn.rec_append_fields(m_score, "articulation", articulation, "U256")

    # consider the note transition by each voice
    for voice in np.unique(m_score['voice']):
        match_voiced = m_score[m_score['voice'] == voice]
        for i, note_info in enumerate(match_voiced):
            if i >= len(match_voiced) - 1:  
                break
            next_note_info = match_voiced[i + 1]
            j = np.where(m_score == note_info)[0].item()  # original position

            # KOR for general melodic transitions
            if (note_info['offset'] == next_note_info['onset']):
                kor_[j]['kor'] =  get_kor(note_info, next_note_info)

            # KOR for legato notes - needs refinement
            if (note_info['slur_feature.slur_incr'] > 0) or (note_info['slur_feature.slur_decr'] > 0): 
                kor_[j]['kor_legato'] =  get_kor(note_info, next_note_info)

            # KOR for staccato notes
            if note_info['articulation'] == 'staccato':
                kor_[j]['kor_staccato'] =  get_kor(note_info, next_note_info)

            # KOR for repeated notes 
            if (note_info['pitch'] == next_note_info['pitch']):
                kor_[j]['kor_repeated'] =  get_kor(note_info, next_note_info)

    return kor_

def get_kor(e1, e2):
    
    kot = e1['p_offset'] - e2['p_onset']
    ioi = e2['p_onset'] - e1['p_onset']

    kor = kot / ioi
    if kor <= -1:
        warnings.warn(f"Getting KOR smaller than -1 in {e1['onset']}-{e1['pitch']} and {e2['onset']}-{e2['pitch']}.")
    return kor 


### Phrasing

def freiberg_kinematic(params, xdata, ydata):
    w, q = params
    return ydata - (1 + (w ** q - 1) * xdata) ** (1/q)


def get_phrase_end(m_score, unique_onset_idxs):
    """
    Returns a list of possible phrase endings for analyzing slowing down structure. 
    (current implementation only takes last 4 beats, need for more advanced segmentation algorithm.)

    Parameters
    ----------
    m_score : structured array
        correspondance between score and performance notes, with score markings. 
    unique_onset_idxs : list
        a list of arrays with the note indexes that have the same onset

    Returns
    -------
    endings : list
        list of tuples with (beats, tempo)
    """
    beat_first_note =  [group[0] for group in unique_onset_idxs]
    m_score_beats = m_score[beat_first_note]

    # last 4 beats
    final_beat = m_score_beats['onset'][-1]
    prase_ending = m_score_beats[(m_score_beats['onset'] >= final_beat - 4)]
    xdata, ydata = prase_ending['onset'], 60 / prase_ending['beat_period']

    endings = [(xdata, ydata)]
    return endings

def phrasing_attributes(m_score, unique_onset_idxs, plot=False):
    """
    rubato:
        Model the final tempo curve (last 2 measures) using Friberg & Sundberg’s kinematic model: 
            (https://www.researchgate.net/publication/220723460_Evidence_for_Pianist-specific_Rubato_Style_in_Chopin_Nocturnes)
        v(x) = (1 + (w^q − 1) * x)^(1/q), 
        w: the final tempo (normalized between 0 and 1, assuming normalized )
        q: variation in curvature

    Parameters
    ----------
    m_score : structured array
        correspondance between score and performance notes, with score markings. 
    unique_onset_idxs : list
        a list of arrays with the note indexes that have the same onset
        
    Returns
    -------
    pharsing_ : structured array
        structured array on the (phrase?) level with fields w and q. 
    """

    endings = get_phrase_end(m_score, unique_onset_idxs)
    phrasing_ = np.zeros(len(endings), dtype=[("rubato_w", "f4"), ("rubato_q", "f4")])     

    for i, ending in enumerate(endings):
        xdata, ydata = ending

        # normalize x and y. y: initial tempo as 1
        xdata = (xdata - xdata.min()) * (1 / (xdata.max() - xdata.min()))
        ydata = (ydata - 0) * (1 / (ydata.max() - 0))

        params_init = np.array([0.5, -1])
        res = least_squares(freiberg_kinematic, params_init, args=(xdata, ydata))
        
        w, q = res.x
        phrasing_[i]['rubato_w'] = w
        phrasing_[i]['rubato_q'] = q

        if plot:
            plt.scatter(xdata, ydata, marker="+", c="red")
            xline = np.linspace(0, 1, 100)
            plt.plot(xline, (1 + (w ** q - 1) * xline) ** (1/q))
            plt.ylim(0, 1.2)
            plt.title(f"Friberg & Sundberg kinematic rubato curve with w={round(w, 2)} and q={round(q, 2)}")
            plt.show()

    return phrasing_
