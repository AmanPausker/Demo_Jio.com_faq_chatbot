import av
import numpy as np

resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
# Create dummy audio frame
frame = av.AudioFrame(format='fltp', layout='stereo', samples=1024)
frame.sample_rate = 44100
for r_frame in resampler.resample(frame):
    print("Method 1 (to_ndarray):", len(r_frame.to_ndarray().tobytes()))
    try:
        print("Method 2 (planes[0].to_bytes):", len(r_frame.planes[0].to_bytes()))
    except Exception as e:
        print("Method 2 error:", e)
    try:
        print("Method 3 (bytes()):", len(bytes(r_frame.planes[0])))
    except Exception as e:
        print("Method 3 error:", e)
