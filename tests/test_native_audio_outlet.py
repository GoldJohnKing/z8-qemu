# SPDX-License-Identifier: GPL-2.0-or-later
"""Native serial5 audio outlet wiring stays explicit, fresh and single-sink."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import movie_playback

class NativeAudioOutlet(unittest.TestCase):
    def guest(self, machine='nikon-z8-full-lab'):
        return SimpleNamespace(command=['qemu','-M',machine],data={})

    def test_wav_outlet_appends_audio_models_and_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'native.wav'
            g=self.guest()
            movie_playback.attach_serial5_output(g,str(dest))
            self.assertIn('serial5-audio-config-model=on',g.command[2])
            self.assertIn('serial5-audio-idle-drain-model=on',g.command[2])
            self.assertIn('serial5-playback-ram-aperture-fixture=on',g.command[2])
            self.assertIn('serial5-tx-drain-model=on',g.command[2])
            self.assertIn('serial5-audio-output=z8native',g.command[2])
            self.assertEqual(g.command[g.command.index('-audiodev')+1],
                             'wav,id=z8native,path='+str(dest)+',out.frequency=48000,out.channels=2,out.format=s16')
            self.assertFalse(dest.exists())
            record=g.data['serial5_audio_outlet']
            self.assertEqual(record['audio_output'],str(dest))
            self.assertFalse(record['audio_tx_qualified'])

    def test_auto_uses_default_backend_and_none_is_silent(self):
        g=self.guest();movie_playback.attach_serial5_output(g,'auto')
        self.assertIn('serial5-audio-output=auto',g.command[2])
        self.assertNotIn('serial5-audio-output=z8native',g.command[2])
        self.assertNotIn('-audiodev',g.command)
        g=self.guest();movie_playback.attach_serial5_output(g,'none')
        self.assertNotIn('serial5-audio-output=',g.command[2])
        self.assertNotIn('-audiodev',g.command)
        self.assertNotIn('serial5_audio_outlet',g.data)

    def test_profile_supplied_tx_drain_is_not_duplicated(self):
        g=self.guest('nikon-z8-full-lab,serial5-tx-drain-model=on')
        movie_playback.attach_serial5_output(g,'auto')
        self.assertEqual(g.command[2].count('serial5-tx-drain-model='),1)

    def test_movie_none_plus_outlet_keeps_a_single_property_set(self):
        g=self.guest()
        movie_playback.attach(g,'none')
        movie_playback.attach_serial5_output(g,'auto')
        for name in ('serial5-audio-config-model','serial5-audio-idle-drain-model',
                     'serial5-playback-ram-aperture-fixture','serial5-tx-drain-model',
                     'serial5-audio-output'):
            self.assertEqual(g.command[2].count(name+'='),1,name)
        self.assertNotIn('-audiodev',g.command)

    def test_rejected_destinations_reuse_movie_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);existing=root/'keep.wav';existing.write_bytes(b'keep')
            for value in (str(existing),str(root/'bad,output.wav'),str(root/'bad.log'),''):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    movie_playback.validate_audio_output(value)
            self.assertEqual(existing.read_bytes(),b'keep')

if __name__=='__main__':unittest.main()
