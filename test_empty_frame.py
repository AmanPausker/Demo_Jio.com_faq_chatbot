import av
try:
    frame = av.AudioFrame(format='s16', layout='mono', samples=0)
    frame.planes[0].update(b"")
    print("Success")
except Exception as e:
    print("Error:", e)
