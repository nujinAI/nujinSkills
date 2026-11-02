import { ref } from 'vue';
import { isAudioEnabled, toggleAudioEnabled, playSignalTone, testSignalTone } from '../utils/audio';

const soundEnabled = ref(isAudioEnabled());

export function useAudio() {
  const toggleSound = () => {
    soundEnabled.value = toggleAudioEnabled();
  };

  const playTone = (action?: string) => {
    playSignalTone(action);
  };

  const testTone = () => {
    testSignalTone();
  };

  return {
    soundEnabled,
    toggleSound,
    playTone,
    testTone,
  };
}
