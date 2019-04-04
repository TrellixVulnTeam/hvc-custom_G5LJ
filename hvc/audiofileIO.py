import warnings

import numpy as np
from scipy.io import wavfile
import scipy.signal
from matplotlib.mlab import specgram

import matplotlib.pyplot as plt

from . import evfuncs, koumura, wav_txt, txt
from .parse.ref_spect_params import refs_dict


class WindowError(Exception):
    pass


class SegmentParametersMismatchError(Exception):
    pass


def butter_bandpass(freq_cutoffs, samp_freq, order=8):
    """returns filter coefficients for Butterworth bandpass filter

    Parameters
    ----------
    freq_cutoffs: list
        low and high frequencies of pass band, e.g. [500, 10000]
    samp_freq: int
        sampling frequency
    order: int
        of filter, default is 8

    Returns
    -------
    b, a: ndarray, ndarray

    adopted from the SciPy cookbook:
    http://scipy-cookbook.readthedocs.io/items/ButterworthBandpass.html
    """

    nyquist = 0.5 * samp_freq
    freq_cutoffs = np.asarray(freq_cutoffs) / nyquist
    b, a = scipy.signal.butter(order, freq_cutoffs, btype='bandpass')
    return b, a


def butter_bandpass_filter(data, samp_freq, freq_cutoffs, order=8):
    """applies Butterworth bandpass filter to data

    Parameters
    ----------
    data: ndarray
        1-d array of raw audio data
    samp_freq: int
        sampling frequency
    freq_cutoffs: list
        low and high frequencies of pass band, e.g. [500, 10000]
    order: int
        of filter, default is 8

    Returns
    -------
    data: ndarray
        data after filtering

    adopted from the SciPy cookbook:
    http://scipy-cookbook.readthedocs.io/items/ButterworthBandpass.html
    """

    b, a = butter_bandpass(freq_cutoffs, samp_freq, order=order)
    return scipy.signal.lfilter(b, a, data)


class Spectrogram:
    """class for making spectrograms.
    Abstracts out function calls so user just has to put spectrogram parameters
    in YAML config file.
    """

    def __init__(self,
                 nperseg=None,
                 noverlap=None,
                 freq_cutoffs=(500, 10000),
                 window=None,
                 filter_func=None,
                 spect_func=None,
                 log_transform_spect=True,
                 thresh=-4.0,
                 remove_dc=True):
        """Spectrogram.__init__ function

        Parameters
        ----------
        nperseg : int
            numper of samples per segment for FFT, e.g. 512
        noverlap : int
            number of overlapping samples in each segment

        nperseg and noverlap are required for __init__

        Other Parameters
        ----------------
        freq_cutoffs : two-element list of integers
            limits of frequency band to keep, e.g. [1000,8000]
            Spectrogram.make keeps the band:
                freq_cutoffs[0] >= spectrogram > freq_cutoffs[1]
            Default is [500, 10000].
        window : str
            window to apply to segments
            valid strings are 'Hann', 'dpss', None
            Hann -- Uses np.Hanning with parameter M (window width) set to value of nperseg
            dpss -- Discrete prolate spheroidal sequence AKA Slepian.
                Uses scipy.signal.slepian with M parameter equal to nperseg and
                width parameter equal to 4/nperseg, as in [2]_.
            Default is None.
        filter_func : str
            filter to apply to raw audio. valid strings are 'diff' or None
            'diff' -- differential filter, literally np.diff applied to signal as in [1]_.
            Default is None.
            Note this is different from filters applied to isolate frequency band.
        spect_func : str
            which function to use for spectrogram.
            valid strings are 'scipy' or 'mpl'.
            'scipy' uses scipy.signal.spectrogram,
            'mpl' uses matplotlib.matlab.specgram.
            Default is 'scipy'.
        log_transform_spect : bool
            if True, applies np.log10 to spectrogram to increase range.
            Default is True.
        thresh : float
            threshold for spectrogram.
            All values below thresh are set to thresh;
            increases contrast when visualizing spectrogram with a colormap.
            Default is -4 (assumes log_transform_spect==True)
        remove_dc : bool
            if True, remove the zero-frequency component of the spectrogram,
            i.e. the DC offset, which in a sound recording should be zero.
            Default is True. Calculation of some features (e.g. cepstrum)
            requires the DC component however.
            
        References
        ----------
        .. [1] Tachibana, Ryosuke O., Naoya Oosugi, and Kazuo Okanoya. "Semi-
        automatic classification of birdsong elements using a linear support vector
         machine." PloS one 9.3 (2014): e92584.

        .. [2] Koumura, Takuya, and Kazuo Okanoya. "Automatic recognition of element
        classes and boundaries in the birdsong with variable sequences."
        PloS one 11.7 (2016): e0159188.
        """

        if nperseg is None:
            raise ValueError('nperseg requires a value for Spectrogram.__init__')
        if noverlap is None:
            raise ValueError('noverlap requires a value for Spectrogram.__init__')
        if spect_func is None:
            # switch to default
            # can't have in args list because need to check above for
            # conflict with default spectrogram functions for each ref
            spect_func = 'scipy'
        if type(nperseg) != int:
            raise TypeError('type of nperseg must be int, but is {}'.
                             format(type(nperseg)))
        else:
            self.nperseg = nperseg

        if type(noverlap) != int:
            raise TypeError('type of noverlap must be int, but is {}'.
                             format(type(noverlap)))
        else:
            self.noverlap = noverlap

        if window is None:
            self.window = None
        else:
            if type(window) != str:
                raise TypeError('type of window must be str, but is {}'.
                                 format(type(window)))
            else:
                if window not in ['Hann', 'dpss']:
                    raise ValueError('{} is not a valid specification for window'.
                                     format(window))
                else:
                    if window == 'Hann':
                        self.window = np.hanning(self.nperseg)
                    elif window == 'dpss':
                        self.window = scipy.signal.slepian(self.nperseg, 4 / self.nperseg)

        if freq_cutoffs is None:
            self.freqCutoffs = None
        else:
            if freq_cutoffs == (500, 10000):
                # if default, convert to list
                # don't want to have a mutable list as the default
                # because mutable defaults can give rise to nasty bugs
                freq_cutoffs = list(freq_cutoffs)
    
            if type(freq_cutoffs) != list:
                raise TypeError('type of freq_cutoffs must be list, but is {}'.
                                 format(type(freq_cutoffs)))
            elif len(freq_cutoffs) != 2:
                raise ValueError('freq_cutoffs list should have length 2, but length is {}'.
                                 format(len(freq_cutoffs)))
            elif not all([type(val) == int for val in freq_cutoffs]):
                raise ValueError('all values in freq_cutoffs list must be ints')
            else:
                self.freqCutoffs = freq_cutoffs

        if freq_cutoffs is not None and filter_func is None:
            self.filterFunc = 'butter_bandpass'  # default

        if filter_func is not None and type(filter_func) != str:
            raise TypeError('type of filter_func must be str, but is {}'.
                             format(type(filter_func)))
        elif filter_func not in ['diff','bandpass_filtfilt','butter_bandpass',None]:
            raise ValueError('string \'{}\' is not valid for filter_func. '
                             'Valid values are: \'diff\' or None.'.
                             format(filter_func))
        else:
            self.filterFunc = filter_func

        if type(spect_func) != str:
            raise TypeError('type of spect_func must be str, but is {}'.
                             format(type(spect_func)))
        elif spect_func not in ['scipy', 'mpl']:
            raise ValueError('string \'{}\' is not valid for filter_func. '
                             'Valid values are: \'scipy\' or \'mpl\'.'.
                             format(spect_func))
        else:
            self.spectFunc = spect_func

        if type(log_transform_spect) is not bool:
            raise ValueError('Value for log_transform_spect is {}, but'
                             ' it must be bool.'
                             .format(type(log_transform_spect)))
        else:
            self.logTransformSpect = log_transform_spect

        if type(thresh) is not float and thresh is not None:
            try:
                thresh = float(thresh)
                self.tresh = thresh
            except:
                raise ValueError('Value for thresh is {}, but'
                                 ' it must be float.'
                                 .format(type(thresh)))
        else:
            self.thresh = thresh
        
        if type(remove_dc) is not bool:
            raise TypeError('Value for remove_dc should be boolean, not {}'
                            .format(type(remove_dc)))
        else:
            self.remove_dc = remove_dc

    def make(self,
             raw_audio,
             samp_freq):
        """makes spectrogram using assigned properties

        Parameters
        ----------
        raw_audio : 1-d numpy array
            raw audio waveform
        samp_freq : integer scalar
            sampling frequency in Hz

        Returns
        -------
        spect : 2-d numpy array
        freq_bins : 1-d numpy array
        time_bins : 1-d numpy array
        """

        if self.filterFunc == 'diff':
            raw_audio = np.diff(raw_audio)  # differential filter_func, as applied in Tachibana Okanoya 2014
        elif self.filterFunc == 'bandpass_filtfilt':
            raw_audio = evfuncs.bandpass_filtfilt(raw_audio,
                                                  samp_freq,
                                                  self.freqCutoffs)
        elif self.filterFunc == 'butter_bandpass':
            raw_audio = butter_bandpass_filter(raw_audio,
                                               samp_freq,
                                               self.freqCutoffs)

        try:  # try to make spectrogram
            if self.spectFunc == 'scipy':
                if self.window is not None:
                        freq_bins, time_bins, spect = scipy.signal.spectrogram(raw_audio,
                                                                               samp_freq,
                                                                               window=self.window,
                                                                               nperseg=self.nperseg,
                                                                               noverlap=self.noverlap)
                else:
                    freq_bins, time_bins, spect = scipy.signal.spectrogram(raw_audio,
                                                                           samp_freq,
                                                                           nperseg=self.nperseg,
                                                                           noverlap=self.noverlap)

            elif self.spectFunc == 'mpl':
                # note that the matlab specgram function returns the STFT by default
                # whereas the default for the matplotlib.mlab version of specgram
                # returns the PSD. So to get the behavior of matplotlib.mlab.specgram
                # to match, mode must be set to 'complex'

                # I think I determined empirically at one point (by staring at single
                # cases) that mlab.specgram gave me values that were closer to Matlab's
                # specgram function than scipy.signal.spectrogram
                # Matlab's specgram is what Tachibana used in his original feature
                # extraction code. So I'm maintaining the option to use it here.

                # 'mpl' is set to return complex frequency spectrum,
                # not power spectral density,
                # because some tachibana features (based on CUIDADO feature set)
                # need to use the freq. spectrum before taking np.abs or np.log10
                if self.window is not None:
                    spect, freq_bins, time_bins = specgram(raw_audio,
                                                           NFFT=self.nperseg,
                                                           Fs=samp_freq,
                                                           window=self.window,
                                                           noverlap=self.noverlap,
                                                           mode='complex')
                else:
                    spect, freq_bins, time_bins = specgram(raw_audio,
                                                           NFFT=self.nperseg,
                                                           Fs=samp_freq,
                                                           noverlap=self.noverlap,
                                                           mode='complex')
        except ValueError as err:  # if `try` to make spectrogram raised error
            if str(err) == 'window is longer than input signal':
                raise WindowError()
            else:  # unrecognized error
                raise

        if self.remove_dc:
            # remove zero-frequency component
            freq_bins = freq_bins[1:]
            spect = spect[1:,:]
        
        # we take the absolute magnitude
        # because we almost always want just that for our purposes
        spect = np.abs(spect)

        if self.logTransformSpect:
            spect = np.log10(spect)  # log transform to increase range

        if self.thresh is not None:
            spect[spect < self.thresh] = self.thresh

        # below, I set freq_bins to >= freq_cutoffs
        # so that Koumura default of [1000,8000] returns 112 freq. bins
        if self.freqCutoffs is not None:
            f_inds = np.nonzero((freq_bins >= self.freqCutoffs[0]) &
                                (freq_bins <= self.freqCutoffs[1]))[0]  # returns tuple
            freq_bins = freq_bins[f_inds]
            spect = spect[f_inds, :]

        return spect, freq_bins, time_bins


def compute_amp(spect):
    """
    compute amplitude of spectrogram
    Assumes the values for frequencies are power spectral density (PSD).
    Sums PSD for each time bin, i.e. in each column.
    Inputs:
        spect -- output from spect_from_song
    Returns:
        amp -- amplitude
    """

    return np.sum(spect, axis=0)


def segment_song(amp,
                 segment_params={'threshold': 5000, 'min_syl_dur': 0.2, 'min_silent_dur': 0.02},
                 time_bins=None,
                 samp_freq=None):
    """Divides songs into segments based on threshold crossings of amplitude.
    Returns onsets and offsets of segments, corresponding (hopefully) to syllables in a song.
    Parameters
    ----------
    amp : 1-d numpy array
        Either amplitude of power spectral density, returned by compute_amp,
        or smoothed amplitude of filtered audio, returned by evfuncs.smooth_data
    segment_params : dict
        with the following keys
            threshold : int
                value above which amplitude is considered part of a segment. default is 5000.
            min_syl_dur : float
                minimum duration of a segment. default is 0.02, i.e. 20 ms.
            min_silent_dur : float
                minimum duration of silent gap between segment. default is 0.002, i.e. 2 ms.
    time_bins : 1-d numpy array
        time in s, must be same length as log amp. Returned by Spectrogram.make.
    samp_freq : int
        sampling frequency

    Returns
    -------
    onsets : 1-d numpy array
    offsets : 1-d numpy array
        arrays of onsets and offsets of segments.

    So for syllable 1 of a song, its onset is onsets[0] and its offset is offsets[0].
    To get that segment of the spectrogram, you'd take spect[:,onsets[0]:offsets[0]]
    """

    if time_bins is None and samp_freq is None:
        raise ValueError('Values needed for either time_bins or samp_freq parameters '
                         'needed to segment song.')
    if time_bins is not None and samp_freq is not None:
        raise ValueError('Can only use one of time_bins or samp_freq to segment song, '
                         'but values were passed for both parameters')

    if time_bins is not None:
        if amp.shape[-1] != time_bins.shape[-1]:
            raise ValueError('if using time_bins, '
                             'amp and time_bins must have same length')

    above_th = amp > segment_params['threshold']
    h = [1, -1]
    # convolving with h causes:
    # +1 whenever above_th changes from 0 to 1
    # and -1 whenever above_th changes from 1 to 0
    above_th_convoluted = np.convolve(h, above_th)

    if time_bins is not None:
        # if amp was taken from time_bins using compute_amp
        # note that np.where calls np.nonzero which returns a tuple
        # but numpy "knows" to use this tuple to index into time_bins
        onsets = time_bins[np.where(above_th_convoluted > 0)]
        offsets = time_bins[np.where(above_th_convoluted < 0)]
    elif samp_freq is not None:
        # if amp was taken from smoothed audio using smooth_data
        # here, need to get the array out of the tuple returned by np.where
        # **also note we avoid converting from samples to s
        # until *after* we find segments** 
        onsets = np.where(above_th_convoluted > 0)[0]
        offsets = np.where(above_th_convoluted < 0)[0]

    if onsets.shape[0] < 1 or offsets.shape[0] < 1:
        return None, None  # because no onsets or offsets in this file

    # get rid of silent intervals that are shorter than min_silent_dur
    silent_gap_durs = onsets[1:] - offsets[:-1]  # duration of silent gaps
    if samp_freq is not None:
        # need to convert to s
        silent_gap_durs = silent_gap_durs / samp_freq
    keep_these = np.nonzero(silent_gap_durs > segment_params['min_silent_dur'])
    onsets = np.concatenate(
        (onsets[0, np.newaxis], onsets[1:][keep_these]))
    offsets = np.concatenate(
        (offsets[:-1][keep_these], offsets[-1, np.newaxis]))

    # eliminate syllables with duration shorter than min_syl_dur
    syl_durs = offsets - onsets
    if samp_freq is not None:
        syl_durs = syl_durs / samp_freq
    keep_these = np.nonzero(syl_durs > segment_params['min_syl_dur'])
    onsets = onsets[keep_these]
    offsets = offsets[keep_these]

    if samp_freq is not None:
        onsets = onsets / samp_freq
        offsets = offsets / samp_freq

    return onsets, offsets

class syllable:
    """
    syllable object, returned by make_syl_spect.
    Properties
    ----------
    syl_audio : 1-d numpy array
        raw waveform from audio file
    sampfreq : integer
        sampling frequency in Hz as determined by scipy.io.wavfile function
    spect : 2-d m by n numpy array
        spectrogram as computed by Spectrogram.make(). Each of the m rows is a frequency bin,
        and each of the n columns is a time bin. Value in each bin is power at that frequency and time.
    nfft : integer
        number of samples used for each FFT
    overlap : integer
        number of samples that each consecutive FFT window overlapped
    time_bins : 1d vector
        values are times represented by each bin in s
    freq_bins : 1d vector
        values are power spectral density in each frequency bin
    index: int
        index of this syllable in song.syls.labels
    label: int
        label of this syllable from song.syls.labels
    """
    def __init__(self,
                 syl_audio,
                 samp_freq,
                 spect,
                 nfft,
                 overlap,
                 freq_cutoffs,
                 freq_bins,
                 time_bins,
                 index,
                 label):
        self.sylAudio = syl_audio
        self.sampFreq = samp_freq
        self.spect = spect
        self.nfft = nfft
        self.overlap = overlap
        self.freqCutoffs = freq_cutoffs
        self.freqBins = freq_bins
        self.timeBins = time_bins
        self.index = index
        self.label = label


class Song:
    """Song object
    used for feature extraction
    """

    class SegmentParametersMismatchError(SegmentParametersMismatchError):
        pass

    def __init__(self,
                 filename,
                 file_format,
                 segment_params=None,
                 use_annotation=True,
                 annote_filename=None,
                 spect_params=None):
        """__init__ function for song object

        either loads annotations, or segments song to find annotations.
        Annotations are:
            onsets_s : 1-d array
            offsets_s : 1-d array, same length as onsets_s
                onsets and offsets of segments in seconds
            onsets_Hz : 1-d array, same length as onsets_s
            offsets_Hz : 1-d array, same length as onsets_s
                onsets and offsets of segments in Hertz
                for isolating segments from raw audio instead of from spectrogram
            labels: 1-d array, same length as onsets_s

        Parameters
        ----------
        filename : str
            name of file
        file_format : str
            {'evtaf','koumura'}
            'evtaf' -- files obtained with EvTAF program [1]_, extension is '.cbin'
            'koumura' -- .wav files from repository [2]_ that accompanied paper [3]_.
        segment_params : dict
            Parameters for segmenting audio file into "syllables".
            If use_annotation is True, checks values in this dict against
            the parameters in the annotation file (if they are present, not all
            data sets include segmentation parameters).
            Default is None.
            segment_params dict has the following keys:
                threshold : int
                    value above which amplitude is considered part of a segment. default is 5000.
                min_syl_dur : float
                    minimum duration of a segment. default is 0.02, i.e. 20 ms.
                min_silent_dur : float
                    minimum duration of silent gap between segment. default is 0.002, i.e. 2 ms.
        use_annotation : bool
            if True, loads annotations from file.
            default is True.
            if False, segment song during init using spect_params and segment_params.
            if annotation file not found, raises FileNotFound error.
        annote_filename : str
            name of file that contains annotations to use for segments
            default is None.
            If None, __init__ tries to find file automatically
        spect_params : dict
            not required unless use_annotation is False
            keys should be parameters for Spectrogram.__init__,
            see the docstring for those keys.
        """

        if use_annotation is False and segment_params is None:
            raise ValueError('use_annotation set to False but no segment_params '
                             'was provided; segment_params are required to '
                             'find segments.')

        if use_annotation is False and spect_params is None:
            raise ValueError('use_annotation set to False but no spect_params '
                             'was provided; spect_params are required to '
                             'find segments.')

        self.filename = filename
        self.fileFormat = file_format

        if file_format == 'evtaf':
            raw_audio, samp_freq = evfuncs.load_cbin(filename)
        elif file_format == 'koumura':
            samp_freq, raw_audio = wavfile.read(filename)
        elif file_format == 'wav_txt':
            samp_freq, raw_audio = wavfile.read(filename)
            raw_audio = raw_audio.astype(float)
        elif file_format == 'txt':
            samp_freq, raw_audio = read_song_txt(filename)
        elif file_format == 'npy':
            samp_freq, raw_audio = read_song_npy(filename)

        self.rawAudio = raw_audio
        self.sampFreq = samp_freq

        if use_annotation:
            if file_format == 'evtaf':
                if segment_params is None:
                    ValueError('segment_params required when '
                               'use_annotation is true for '
                               'evtaf file format')
                if annote_filename:
                    song_dict = evfuncs.load_notmat(annote_filename)
                else:
                    song_dict = evfuncs.load_notmat(filename)

                # in .not.mat files saved by evsonganaly,
                # onsets and offsets are in units of ms, have to convert to s
                if segment_params['threshold'] != song_dict['threshold']:
                    raise Song.SegmentParametersMismatchError('\'threshold\' parameter for {} does not match parameter '
                                     'value for segment_params[\'threshold\'].'
                                     .format(filename))
                if segment_params['min_syl_dur'] != song_dict['min_dur']/1000:
                    raise Song.SegmentParametersMismatchError('\'min_dur\' parameter for {} does not match parameter '
                                     'value for segment_params[\'min_syl_dur\'].'
                                     .format(filename))
                if segment_params['min_silent_dur'] != song_dict['min_int']/1000:
                    raise Song.SegmentParametersMismatchError('\'min_int\' parameter for {} does not match parameter '
                                     'value for segment_params[\'min_silent_dur\'].'
                                     .format(filename))
                self.onsets_s = song_dict['onsets'] / 1000
                self.offsets_s = song_dict['offsets'] / 1000
                # subtract one because of Python's zero indexing (first sample is sample zero)
                self.onsets_Hz = np.round(self.onsets_s * self.sampFreq).astype(int) - 1
                self.offsets_Hz = np.round(self.offsets_s * self.sampFreq).astype(int)
            elif file_format == 'koumura':
                if annote_filename:
                    song_dict = koumura.load_song_annot(annote_filename)
                else:
                    try:
                        song_dict = koumura.load_song_annot(filename)
                    except FileNotFoundError:
                        print("Could not automatically find an annotation file for {}."
                              .format(filename))
                        raise
                self.onsets_Hz = song_dict['onsets']  # in Koumura annotation.xml files, onsets given in Hz
                self.offsets_Hz = song_dict['offsets']  # and offsets
                self.onsets_s = self.onsets_Hz / self.sampFreq  # so need to convert to seconds
                self.offsets_s = song_dict['offsets'] / self.sampFreq
				
            elif file_format == 'wav_txt':
                if annote_filename:
                    song_dict = wav_txt.load_song_annot(annote_filename)
                else:
                    try:
                        song_dict = wav_txt.load_song_annot(filename)
                    except FileNotFoundError:
                        print("Could not automatically find an annotation file for {}."
                              .format(filename))
                        raise
                self.onsets_Hz = song_dict['onsets']  # in Koumura annotation.xml files, onsets given in Hz
                self.offsets_Hz = song_dict['offsets']  # and offsets
                self.onsets_s = self.onsets_Hz / self.sampFreq  # so need to convert to seconds
                self.offsets_s = song_dict['offsets'] / self.sampFreq	
				
            elif file_format == 'txt':
                if annote_filename:
                    song_dict = txt.load_song_annot(annote_filename)
                else:
                    try:
                        song_dict = txt.load_song_annot(filename)
                    except FileNotFoundError:
                        print("Could not automatically find an annotation file for {}."
                              .format(filename))
                        raise
                self.onsets_Hz = song_dict['onsets']  # in Koumura annotation.xml files, onsets given in Hz
                self.offsets_Hz = song_dict['offsets']  # and offsets
                self.onsets_s = self.onsets_Hz / self.sampFreq  # so need to convert to seconds
                self.offsets_s = song_dict['offsets'] / self.sampFreq	
				
            elif file_format == 'npy':
                if annote_filename:
                    song_dict = txt.load_song_annot(annote_filename)
                else:
                    try:
                        song_dict = txt.load_song_annot(filename)
                    except FileNotFoundError:
                        print("Could not automatically find an annotation file for {}."
                              .format(filename))
                        raise
                self.onsets_Hz = song_dict['onsets']  # in Koumura annotation.xml files, onsets given in Hz
                self.offsets_Hz = song_dict['offsets']  # and offsets
                self.onsets_s = self.onsets_Hz / self.sampFreq  # so need to convert to seconds
                self.offsets_s = song_dict['offsets'] / self.sampFreq	
				

            self.labels = song_dict['labels']

        elif use_annotation is False:
            self.spectParams = spect_params
            self.segmentParams = segment_params

            # will need to add ability to segment in different ways
            # e.g. with different amplitudes
            # amp = compute_amp(spect, amplitude_type)
            # for now doing it with the way evsonganaly does
            if self.fileFormat == 'evtaf':
                # need to use same frequency cutoffs that 
                # the matlab function SmoothData.m uses
                # when applying Butterworth filter before segmenting
                amp = evfuncs.smooth_data(self.rawAudio,
                                          self.sampFreq,
                                          refs_dict['evsonganaly']['freq_cutoffs'])
            else:
                amp = evfuncs.smooth_data(self.rawAudio,
                                          self.sampFreq,
                                          self.spectParams['freq_cutoffs'])

				
            onsets, offsets = segment_song(amp,
                                           segment_params,
                                           samp_freq=self.sampFreq)

            self.onsets_s = onsets
            self.offsets_s = offsets
            self.onsets_Hz = np.round(self.onsets_s * self.sampFreq).astype(int)
            self.offsets_Hz = np.round(self.offsets_s * self.sampFreq).astype(int)
            self.labels = '-' * len(onsets)
			
			
            ###Test: plot segmented amp
            ##
            ##window =('hamming')
            ##overlap = 64
            ##nperseg = 1024
            ##noverlap = nperseg-overlap
            ##colormap = "jet"
			##
			##
            ###Plot smoothed amplitude
            ##plt.figure() 
            ##x=np.arange(len(amp))
            ##plt.plot(x,amp)
            ##shpe = len(onsets)
			##
            ##print('nb_segmented_sysl: %d' % shpe)
            ###Plot onsets and offsets
            ##for i in range(0,shpe):
            ##    plt.axvline(x=self.onsets_Hz[i])
            ##    plt.axvline(x=self.offsets_Hz[i],color='r')
            ##   
            ###Compute and plot spectrogram
            ##(f,t,sp)=scipy.signal.spectrogram(self.rawAudio, self.sampFreq, window, nperseg, noverlap, mode='complex')
            ###sp_p=np.clip(abs(sp), 0, 0.004)
            ##max_sp=np.amax(abs(sp))
            ##plt.figure()
            ##sp = sp/max_sp
            ###plt.imshow(abs(sp_p), origin="lower", aspect="auto", cmap=colormap, interpolation="none")
            ##plt.imshow(10*np.log10(np.square(abs(sp))), origin="lower", aspect="auto", cmap=colormap, interpolation="none")
            ##plt.colorbar()
            ##plt.show()
            ##
            ###End test
			
			
			
			
			

    def set_syls_to_use(self, labels_to_use='all'):
        """
        Parameters
        ----------
        labels_to_use : list or string
            List or string of all labels for which associated spectrogram should be made.
            When called by extract, this function takes a list created by the
            extract config parser. But a user can call the function with a string.
            E.g., if labels_to_use = 'iab' then syllables labeled 'i','a',or 'b'
            will be extracted and returned, but a syllable labeled 'x' would be
            ignored. If labels_to_use=='all' then all spectrograms are returned with
            empty strings for the labels. Default is 'all'.

        sets syls_to_use to a numpy boolean that can be used to index e.g. labels, onsets
        This method must be called before get_syls
        """

        if labels_to_use != 'all':
            if type(labels_to_use) != list and type(labels_to_use) != str:
                raise ValueError('labels_to_use argument should be a list or string')
            if type(labels_to_use) == str:
                labels_to_use = list(labels_to_use)

        if labels_to_use == 'all':
            self.syls_to_use = np.ones((self.onsets_s.shape),dtype=bool)
        else:
            self.syls_to_use = np.in1d(list(self.labels),
                                       labels_to_use)

    def make_syl_spects(self,
                        spect_params,
                        syl_spect_width=-1,
                        set_syl_spects=True,
                        return_spects=False):
        """Make spectrograms from syllables.
        This method isolates making spectrograms from selecting syllables
        to use so that spectrograms can be loaded 'lazily', e.g., if only
        duration features are being extracted that don't require spectrograms.

        Parameters
        ----------
        spect_params : dict
            keys should be parameters for Spectrogram.__init__,
            see the docstring for those keys.
        syl_spect_width : float
            Optional parameter to set constant duration for each spectrogram of a
            syllable, in seconds. E.g., 0.05 for an average 50 millisecond syllable. 
            Used for creating inputs to neural network where each input
            must be of a fixed size.
            Default value is -1; in this case, the width of the spectrogram will
            be the duration of the syllable as determined by the segmentation
            algorithm, i.e. the onset and offset that are stored in an annotation file.
            If a different value is given, then the duration of each spectrogram
            will be that value. Note that if any individual syllable has a duration
            greater than syl_spect_duration, the function raises an error.
        set_syl_spects : bool
            if True, creates syllable objects for each segment in song,
             as defined by onsets and offsets,
             and assigns to each syllable's `spect` property the
            spectrogram of that segment.
            Default is True.
        return_spects : bool
            if True, return spectrograms.
            Can be used without affecting syllables that have already been set
            for a song.
            Default is False.
        """

        if not hasattr(self, 'syls_to_use'):
            raise ValueError('Must set syls_to_use by calling set_syls_to_use method '
                             'before calling get_syls.')

        if not hasattr(self, 'raw_audio') and not hasattr(self, 'sampFreq'):
            if self.fileFormat == 'evtaf':
                    raw_audio, samp_freq = evfuncs.load_cbin(self.filename)
            elif self.fileFormat == 'koumura':
                samp_freq, raw_audio = wavfile.read(self.filename)
            self.rawAudio = raw_audio
            self.sampFreq = samp_freq

        if syl_spect_width > 0:
            if syl_spect_width > 1:
                warnings.warn('syl_spect_width set greater than 1; note that '
                              'this parameter is in units of seconds, so using '
                              'a value greater than one will make it hard to '
                              'center the syllable/segment of interest within'
                              'the spectrogram, and additionally consume a lot '
                              'of memory.')
            syl_spect_width_Hz = int(syl_spect_width * self.sampFreq)
            if syl_spect_width_Hz > self.rawAudio.shape[-1]:
                raise ValueError('syl_spect_width, converted to samples, '
                                 'is longer than song file {}.'
                                 .format(self.filename))

        all_syls = []

        spect_maker = Spectrogram(**spect_params)

        for ind, (label, onset, offset) in enumerate(zip(self.labels, self.onsets_Hz, self.offsets_Hz)):
            if 'syl_spect_width_Hz' in locals():
                syl_duration_in_samples = offset - onset
                if syl_duration_in_samples > syl_spect_width_Hz:
                    raise ValueError('syllable duration of syllable {} with label {} '
                                     'in file {} is greater than '
                                     'width specified for all syllable spectrograms.'
                                     .format(ind, label, self.filename))

            if self.syls_to_use[ind]:
                if 'syl_spect_width_Hz' in locals():
                    width_diff = syl_spect_width_Hz - syl_duration_in_samples
                    # take half of difference between syllable duration and spect width
                    # so one half of 'empty' area will be on one side of spect
                    # and the other half will be on other side
                    # i.e., center the spectrogram
                    left_width = int(round(width_diff / 2))
                    right_width = width_diff - left_width
                    if left_width > onset:  # if duration before onset is less than left_width
                        # (could happen with first onset)
                        syl_audio = self.rawAudio[0:syl_spect_width_Hz]
                    elif offset + right_width > self.rawAudio.shape[-1]:
                        # if right width greater than length of file
                        syl_audio = self.rawAudio[-syl_spect_width_Hz:]
                    else:
                        syl_audio = self.rawAudio[onset - left_width:offset + right_width]
                else:
                    syl_audio = self.rawAudio[onset:offset]

                try:
                    spect, freq_bins, time_bins = spect_maker.make(syl_audio,
                                                                   self.sampFreq)
                except WindowError as err:
                    warnings.warn('Segment {0} in {1} with label {2} '
                                  'not long enough for window function'
                                  ' set with current spect_params.\n'
                                  'spect will be set to nan.'
                                  .format(ind, self.filename, label))
                    spect, freq_bins, time_bins = (np.nan,
                                                   np.nan,
                                                   np.nan)

                curr_syl = syllable(syl_audio,
                                    self.sampFreq,
                                    spect,
                                    spect_maker.nperseg,
                                    spect_maker.noverlap,
                                    spect_maker.freqCutoffs,
                                    freq_bins,
                                    time_bins,
                                    ind,
                                    label)

                all_syls.append(curr_syl)
        if set_syl_spects:
            self.syls = all_syls

        if return_spects:
            # stack with dimensions (samples, height, width)
            return np.stack([syl.spect for syl in all_syls], axis=0)

def read_song_txt(filename):
    samp_freq = 30303.0
    raw_audio = []
    with open(filename) as f:
         lines = f.readlines()
		 #print(type(lines))
         #samp_freq = float(lines[0])
         for line in lines:  #lines[1:-1] considers all elements of lines except the first one 
             #line = str(lines)
             #print("line: %s" % line)
             #splt = line.split("\n")
             #print("line: %f" % float(line))
             raw_audio.append(float(line))
    
    f.close
	
    raw_audio = np.asarray(raw_audio)
    #raw_audio=rawsong_templ[:,None]
	
    return(samp_freq, raw_audio)
	
def read_song_npy(filename):
    samp_freq = 30303.0
    raw_audio = []	
    raw_audio = np.load(filename)
    #print(raw_audio.shape)
	#convert from (M,1) to (M,)
    raw_audio=np.transpose(raw_audio)
    #print(raw_audio.shape)
    raw_audio = raw_audio[0,:]
    #print(raw_audio.shape)

    return(samp_freq, raw_audio)

	



