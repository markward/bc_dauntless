"""SpeakQueue -- CharacterClass's owned faithful facade over crew_speech.

Mirrors BC's per-character speak surface (SpeakHelper/SpeakLine/SayLine +
IsSpeaking/IsReadyToSpeak/AddSoundToQueue, tier-0 reference sec 4.11) in front
of the single-channel crew_speech bus, which stays the execution backend. BC
gives each character its own queue and lets two officers overlap; that
divergence is tracked separately and does not change this facade.
"""
from __future__ import annotations

import time

from engine.appc import crew_speech


class SpeakQueue:
    def __init__(self, owner):
        self._owner = owner
        self._pending: list = []   # AddSoundToQueue enqueue (BC +queue); usually empty

    def _name(self) -> str:
        return self._owner.GetCharacterName()

    # -- SpeakHelper: clear the interruptable anim set, then route to the funnel.
    def _speak_helper(self, db, line, priority) -> float:
        try:
            self._owner.ClearExtraAnimations()     # cats 0,1,5,6 (tier-0 sec 4.11)
        except Exception:
            pass
        return crew_speech.emit(self._name(), db, line, int(priority))

    def speak_line(self, db, line, priority) -> float:
        return self._speak_helper(db, line, priority)

    def say_line(self, db, line, addressee=None, flag=None, priority=0) -> float:
        # addressee/flag are meaningless headless; real priority is the 5th arg.
        return self._speak_helper(db, line, priority)

    def is_speaking(self) -> int:
        return 1 if crew_speech.is_speaking(self._name()) else 0

    def is_ready_to_speak(self) -> int:
        # BC: a sound is queued and ready but not yet playing. Our only enqueuer
        # is add_sound_to_queue (no SDK caller), so this is 0 in practice --
        # which is exactly what unblocks the ScienceCharacterHandlers guard.
        return 1 if self._pending else 0

    def add_sound_to_queue(self, pSound, sound_type=0, data=0) -> None:
        # BC 0x0066CB90 (tier-0 reference sec 4.11): no-op unless a sound is
        # present. type==2 while the character is ready (a sound already queued)
        # or already speaking plays immediately, over the top (vtable +0x50);
        # a fully idle character's sound is enqueued for normal draining.
        if pSound is None:
            return
        if int(sound_type) == 2 and (self.is_ready_to_speak() or self.is_speaking()):
            try:
                pSound.Play()
            except Exception:
                pass
            return
        self._pending.append(pSound)


def someone_speaking() -> int:
    """BC CharacterClass_IsSomeoneSpeaking (0x00666F00): active-speaker count > 0.
    The crew_speech bus serialises, so the count is 0 or 1."""
    b = crew_speech.bus()
    return 1 if (b._active_speaker and time.monotonic() < b._active_expiry) else 0
