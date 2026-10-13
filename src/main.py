import sounddevice as sd
import wave

# Configuration parameters
FILENAME = "recording.wav"
CHANNELS = 1  # Mono audio (use 2 for stereo)
SAMPLERATE = 44100  # 44.1 kHz standard audio
SUBTYPE = "PCM_16"  # 16-bit PCM format

print(f"Recording to {FILENAME}... Press Ctrl+C to stop.")

# Open the WAV file for writing
with wave.open(FILENAME, "wb") as wav_file:
  wav_file.setnchannels(CHANNELS)
  wav_file.setsampwidth(2)  # 2 bytes for 16-bit audio (PCM_16)
  wav_file.setframerate(SAMPLERATE)

  # Define a callback function that writes each audio block straight to the file
  def callback(indata, frames, time, status):
    if status:
      print(status)
    # Convert numpy float32 data (-1.0 to 1.0) into 16-bit PCM integers bytes
    wav_file.writeframes((indata * 32767).astype("int16").tobytes())

  try:
    # Open an input stream that feeds data continuously into the callback
    with sd.InputStream(
        samplerate=SAMPLERATE,
        channels=CHANNELS,
        dtype="float32",
        callback=callback,
    ):
      # Keep the script running until interrupted
      while True:
        sd.sleep(1000)

  except KeyboardInterrupt:
    print(f"\nRecording stopped. File saved as {FILENAME}")