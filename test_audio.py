import av
import numpy as np
# create dummy frame
frame = av.AudioFrame(format='s16', layout='mono', samples=1024)
# populate with 1
frame.planes[0].update(b'\x01' * 2048)
arr = frame.to_ndarray()
print("Shape:", arr.shape)
bytes_data = arr.tobytes()
print("Length:", len(bytes_data))
# compare to bytes()
