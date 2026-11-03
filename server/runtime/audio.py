import logging
import os
import shutil
import subprocess
import sys
import threading

logger = logging.getLogger("NujinSkillsAudio")


def play_system_alert(action: str = "SIGNAL"):
    """
    Plays an audible system chime on Linux in a non-blocking background thread.
    Tries paplay, canberra-gtk-play, pw-play, aplay, and terminal bell fallback.
    """
    def _play():
        try:
            is_buy = "BUY" in action.upper() or "LONG" in action.upper()
            sound_theme = "complete" if is_buy else "bell"
            sound_path = f"/usr/share/sounds/freedesktop/stereo/{sound_theme}.oga"

            played = False
            # 1. Prefer paplay (direct PulseAudio/PipeWire, ultra-low latency)
            if shutil.which("paplay") and os.path.exists(sound_path):
                subprocess.Popen(
                    ["paplay", sound_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                played = True

            # 2. Canberra GTK play
            if not played and shutil.which("canberra-gtk-play"):
                subprocess.Popen(
                    ["canberra-gtk-play", "-i", sound_theme],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                played = True

            # 3. pw-play (PipeWire)
            if not played and shutil.which("pw-play") and os.path.exists(sound_path):
                subprocess.Popen(
                    ["pw-play", sound_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                played = True

            # Terminal bell fallback
            sys.stdout.write("\a")
            sys.stdout.flush()
            logger.info(f"[SystemAlert] Played desktop audio chime for action: {action} (played={played})")
        except Exception as e:
            logger.warning(f"[SystemAlert] Audio playback error: {e}")

    threading.Thread(target=_play, daemon=True).start()
