"""
test audiofileIO module
"""

import pytest
from scipy.io import wavfile
import numpy as np

import hvc.audiofileIO
import hvc.evfuncs
import hvc.koumura

@pytest.fixture()
def has_window_error():
    return './test_data/cbins/window_error/gy6or6_baseline_220312_0901.106.cbin'

class TestAudiofileIO:
    
    def test_Spectrogram_init(self):
        """#test whether can init a spec object
        """
        spec = hvc.audiofileIO.Spectrogram(nperseg=128,
                                           noverlap=32,
                                           window='Hann',
                                           freq_cutoffs=[1000, 5000],
                                           filter_func='diff',
                                           spect_func='scipy')

        #test whether init works with 'ref' parameter
        #instead of passing spect params
        spect_maker = hvc.audiofileIO.Spectrogram(ref='tachibana')

        spect_maker = hvc.audiofileIO.Spectrogram(ref='koumura')

        #test that specify 'ref' and specifying other params raises warning
        #(because other params specified will be ignored)
        with pytest.warns(UserWarning):
            spect_maker = hvc.audiofileIO.Spectrogram(nperseg=512,
                                                      ref='tachibana')
        with pytest.warns(UserWarning):
            spect_maker = hvc.audiofileIO.Spectrogram(nperseg=512,
                                                    ref='tachibana')

        with pytest.warns(UserWarning):
            spect_maker = hvc.audiofileIO.Spectrogram(spect_func='scipy',
                                                      ref='tachibana')

    def test_Spectrogram_make(self):
        """ test whether Spectrogram.make works
        """
        # test whether make works with .cbin
        cbin  = './test_data/cbins/032412/gy6or6_baseline_240312_0811.1165.cbin'
        dat, fs = hvc.evfuncs.load_cbin(cbin)

        spect_maker = hvc.audiofileIO.Spectrogram(ref='tachibana')
        spect,freq_bins, time_bins = spect_maker.make(dat, fs)
        assert spect.shape[0] == freq_bins.shape[0]
        assert spect.shape[1] == time_bins.shape[0]

        spect_maker = hvc.audiofileIO.Spectrogram(ref='koumura')
        spect,freq_bins, time_bins = spect_maker.make(dat, fs)
        assert spect.shape[0] == freq_bins.shape[0]
        assert spect.shape[1] == time_bins.shape[0]

        # test whether make works with .wav from Koumura dataset
        wav = './test_data/koumura/Bird0/Wave/0.wav'
        fs, dat = wavfile.read(wav)

        spect_maker = hvc.audiofileIO.Spectrogram(ref='tachibana')
        spect, freq_bins, time_bins = spect_maker.make(dat, fs)
        assert spect.shape[0] == freq_bins.shape[0]
        assert spect.shape[1] == time_bins.shape[0]

        spect_maker = hvc.audiofileIO.Spectrogram(ref='koumura')
        spect, freq_bins, time_bins = spect_maker.make(dat, fs)
        assert spect.shape[0] == freq_bins.shape[0]
        assert spect.shape[1] == time_bins.shape[0]

        # test custom exceptions!!
        # can test with syllable 19 of song 23 in gy6or6/032212
        # file is: 'gy6or6_baseline_220312_0901.106.cbin'


    def test_Song_init(self):
        """test whether Song object inits properly
        """

        segment_params = {
            'threshold': 1500,
            'min_syl_dur': 0.01,
            'min_silent_dur': 0.006
        }

        cbin  = './test_data/cbins/032412/gy6or6_baseline_240312_0811.1165.cbin'
        song = hvc.audiofileIO.Song(filename=cbin,
                                    file_format='evtaf',
                                    segment_params=segment_params)

        wav = './test_data/koumura/Bird0/Wave/0.wav'
        song = hvc.audiofileIO.Song(filename=wav,
                                    file_format='koumura')

    def test_Song_set_and_make_syls(self):
        """test that set_syls_to_use and make_syl_spects work
        """

        segment_params = {
            'threshold': 1500,
            'min_syl_dur': 0.01,
            'min_silent_dur': 0.006
        }

        cbin  = './test_data/cbins/032412/gy6or6_baseline_240312_0811.1165.cbin'
        cbin_song = hvc.audiofileIO.Song(filename=cbin,
                                         file_format='evtaf',
                                         segment_params=segment_params)
        cbin_song.set_syls_to_use('iabcdefghjk')

        wav = './test_data/koumura/Bird0/Wave/0.wav'
        wav_song = hvc.audiofileIO.Song(filename=wav,
                                        file_format='koumura')
        wav_song.set_syls_to_use('0123456')

        spect_params = {
            'nperseg': 512,
            'noverlap': 480,
            'freq_cutoffs': [1000, 8000]}
        cbin_song.make_syl_spects(spect_params)
        wav_song.make_syl_spects(spect_params)

        cbin_song.make_syl_spects(spect_params={'ref': 'tachibana'})
        wav_song.make_syl_spects(spect_params={'ref': 'tachibana'})

        cbin_song.make_syl_spects(spect_params={'ref': 'koumura'})
        wav_song.make_syl_spects(spect_params={'ref': 'koumura'})

        # test that when spect can't be made for a syl with certain params
        # it gets set to np.nan
        # can test with syllable 19 of song 23 in gy6or6/032212
        # file is: 'gy6or6_baseline_220312_0901.106.cbin'

    def check_window_error_set_to_nan(self,has_window_error):
        segment_params = {
            'threshold': 1500,
            'min_syl_dur': 0.01,
            'min_silent_dur': 0.006
        }
        cbin_song = hvc.audiofileIO.Song(filename=has_window_error,
                                         file_format='evtaf',
                                         segment_params=segment_params)
        cbin_song.set_syls_to_use('iabcdefghjk')
        cbin_song.make_syl_spects(spect_params={'ref': 'koumura'})
        assert np.nan in cbin_song.syls
