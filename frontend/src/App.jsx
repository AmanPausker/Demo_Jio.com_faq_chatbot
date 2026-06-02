import { useState, useRef, useEffect } from 'react'
import { floatToWavBlob } from "./utils/audioUtils"
import { myCatalog } from './A2UICatalog';
import { MessageProcessor } from '@a2ui/web_core/v0_9';
import { A2uiSurface } from '@a2ui/react/v0_9';

const processor = new MessageProcessor([myCatalog]);


function App() {
  const [messages, setMessages] = useState([
    { id: 1, role: 'bot', text: 'Hello! Ask me anything about Jio Plans, 5G, or services.' }
  ]);
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const [isImageUploading, setIsImageUploading] = useState(false);
  const [isUploading, setIsUpLoading] = useState(false);
  const [inputText, setInputText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [chatMode, setChatMode] = useState('text'); // 'text' or 'voice'
  const [vadLoading, setVadLoading] = useState(false);

  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioPlayerRef = useRef(null);
  const vadRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Unlock audio on first interaction
  const unlockAudio = () => {
    if (audioPlayerRef.current) {
      audioPlayerRef.current.play().then(() => {
        audioPlayerRef.current.pause();
      }).catch(() => { });
    }
  };
  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    setIsUpLoading(true);
    const tempId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: tempId, role: 'bot', text: `📁 Uploading and processing ${file.name}...` }]);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch('http://localhost:8000/api/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();

      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        if (data.success) {
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `✅ ${data.message}` }];

        } else {
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `❌ Upload failed: ${data.error}` }];
        }
      });
    } catch (error) {
      console.error("Upload error", error);
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: '❌ Failed to connect to server during upload.' }]
      });
    } finally {
      setIsUpLoading(false); // reset the file input so the same file can be selected again if needed.
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };
  const handleImageUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    setIsImageUploading(true);
    const tempId = crypto.randomUUID();
    // Add two messages: one showing the user uploaded an image, one for the bot "thinking"
    setMessages(prev => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', text: `🖼️ Uploaded Image: ${file.name}` },
      { id: tempId, role: 'bot', text: `👁️ Analyzing image using Kimi K2.6...` }
    ]);
    const formData = new FormData();
    formData.append("image", file);
    try {
      const response = await fetch('http://localhost:8000/api/vision', {
        method: 'POST',
        body: formData
      });
      const data = await response.json();
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        if (data.success) {
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: data.text }];
        } else {
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `❌ Vision failed: ${data.error}` }];
        }
      });

    }
    catch (error) {
      console.error("Image upload error", error);
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: '❌ Failed to connect to vision server.' }];
      });
    } finally {
      setIsImageUploading(false);
      if (imageInputRef.current) imageInputRef.current.value = '';
    }

  };

  const playAudio = (base64Audio) => {
    if (!base64Audio || !audioPlayerRef.current) return;

    // Interrupt existing playback if needed
    if (!audioPlayerRef.current.paused) {
      audioPlayerRef.current.pause();
    }

    audioPlayerRef.current.src = `data:audio/wav;base64,${base64Audio}`;
    setIsPlaying(true);

    audioPlayerRef.current.onended = () => setIsPlaying(false);
    audioPlayerRef.current.onerror = () => setIsPlaying(false);

    audioPlayerRef.current.play().catch(e => {
      console.error("Audio playback failed", e);
      setIsPlaying(false);

    });
  };
  const handleGenerateImage = async () => {
    if (!inputText.trim()) return;
    const prompt = inputText;

    unlockAudio();
    // Show the user's prompt in the chat
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', text: `🎨 Create image: ${prompt}` }]);
    setInputText('');
    setIsLoading(true);

    try {
      const response = await fetch('http://localhost:8000/api/generate_image', {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt })
      });
      const data = await response.json();

      if (data.success) {
        setMessages(prev => [...prev, {
          id: crypto.randomUUID(),
          role: 'bot',
          text: `✨ Here is your image for: "${prompt}"`,
          image: `data:image/jpeg;base64,${data.image_base64}`
        }]);
      } else {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: `❌ Image failed: ${data.error}` }]);
      }
    } catch (error) {
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: '❌ Failed to connect to server.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendText = async () => {
    if (!inputText.trim()) return;

    unlockAudio();

    const userMsg = { id: crypto.randomUUID(), role: 'user', text: inputText };
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setIsLoading(true);

    // --- INTERCEPT /imagine COMMAND ---
    if (userMsg.text.startsWith('/imagine ')) {
      const prompt = userMsg.text.replace('/imagine ', '');
      try {
        const response = await fetch('http://localhost:8000/api/generate_image', {
          method: "POST",
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: prompt })
        });
        const data = await response.json();

        if (data.success) {
          setMessages(prev => [...prev, {
            id: crypto.randomUUID(),
            role: 'bot',
            text: `✨ Here is your image for: "${prompt}"`,
            image: `data:image/jpeg;base64,${data.image_base64}`
          }]);
        } else {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: `❌ Image failed: ${data.error}` }]);
        }
      } catch (error) {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: '❌ Failed to connect to server.' }]);
      } finally {
        setIsLoading(false);
      }
      return; // Stop here so it doesn't run the normal chat code!
    }

    // --- NORMAL CHAT ---
    try {
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg.text })
      });

      const data = await response.json();
      if (data.a2ui_messages && data.a2ui_messages.length > 0) {
        processor.processMessages(data.a2ui_messages);
      }
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: data.text, surfaceId: data.surface_id }]);
      playAudio(data.audio_base64);
    } catch (error) {
      console.error('Error:', error);
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: 'Sorry, I encountered an error.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const sendAudioMessage = async (audioBlob) => {
    setIsLoading(true);

    // Add a temporary placeholder so the user knows they stopped talking and it's processing
    const tempId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: tempId, role: 'user', text: `🎤 [Transcribing...]` }]);

    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.wav');

    try {
      const response = await fetch('http://localhost:8000/api/chat/audio', {
        method: 'POST',
        body: formData
      });

      const data = await response.json();
      if (data.a2ui_messages && data.a2ui_messages.length > 0) {
        processor.processMessages(data.a2ui_messages);
      }

      setMessages(prev => {
        // Remove the temporary message
        const filtered = prev.filter(m => m.id !== tempId);

        // Add the real transcribed user message and the bot's response
        const newMessages = [...filtered];
        if (data.user_message) {
          newMessages.push({ id: crypto.randomUUID(), role: 'user', text: `🎤 ${data.user_message}` });
        }
        newMessages.push({ id: crypto.randomUUID(), role: 'bot', text: data.text, surfaceId: data.surface_id });
        return newMessages;
      });

      playAudio(data.audio_base64);

    } catch (error) {
      console.error('Error:', error);
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: 'Sorry, I encountered an error processing your audio.' }];
      });
    } finally {
      setIsLoading(false);
    }
  };

  // Manual Push-to-Talk for Text Mode
  const startRecording = async () => {
    try {
      unlockAudio();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        await sendAudioMessage(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
      setChatMode('voice');
    } catch (error) {
      console.error('Error accessing microphone:', error);
      alert('Microphone access denied or not available.');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  // Initialize VAD for Voice Mode
  useEffect(() => {
    let active = true;
    let audioContext;
    let stream;
    let silenceTimer;
    let rafId;

    const startNativeVAD = async () => {
      try {
        setVadLoading(true);
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.2;
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        let isSpeakingState = false;
        const VOLUME_THRESHOLD = 50; // Increased to 50 to aggressively ignore background voices
        const SILENCE_MS_TO_STOP = 1500; // 1.5 seconds of silence stops recording

        setVadLoading(false);

        const checkVolume = () => {
          if (!active) return;

          analyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          const averageVolume = sum / dataArray.length;

          if (averageVolume > VOLUME_THRESHOLD) {
            // User is speaking
            if (silenceTimer) {
              clearTimeout(silenceTimer);
              silenceTimer = null;
            }
            if (!isSpeakingState) {
              isSpeakingState = true;
              console.log("Speech detected (volume:", Math.round(averageVolume), ")");

              if (audioPlayerRef.current && !audioPlayerRef.current.paused) {
                audioPlayerRef.current.pause();
                setIsPlaying(false);
              }
              setIsRecording(true);

              try {
                const mediaRecorder = new MediaRecorder(stream);
                mediaRecorderRef.current = mediaRecorder;
                audioChunksRef.current = [];

                mediaRecorder.ondataavailable = (event) => {
                  if (event.data.size > 0) audioChunksRef.current.push(event.data);
                };

                mediaRecorder.onstop = async () => {
                  const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
                  await sendAudioMessage(audioBlob);
                };

                mediaRecorder.start();
              } catch (err) {
                console.error("MediaRecorder start failed", err);
              }
            }
          } else {
            // Silence detected
            if (isSpeakingState && !silenceTimer) {
              silenceTimer = setTimeout(() => {
                isSpeakingState = false;
                console.log("Silence confirmed, stopping recording");

                setIsRecording(false);
                if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
                  mediaRecorderRef.current.stop();
                }
              }, SILENCE_MS_TO_STOP);
            }
          }

          rafId = requestAnimationFrame(checkVolume);
        };

        checkVolume();
      } catch (err) {
        console.error("Native VAD error:", err);
        setVadLoading(false);
      }
    };

    if (chatMode === 'voice') {
      startNativeVAD();
    } else {
      if (stream) stream.getTracks().forEach(track => track.stop());
      if (audioContext && audioContext.state !== 'closed') audioContext.close();
      if (rafId) cancelAnimationFrame(rafId);
      if (silenceTimer) clearTimeout(silenceTimer);
    }

    return () => {
      active = false;
      if (stream) stream.getTracks().forEach(track => track.stop());
      if (audioContext && audioContext.state !== 'closed') audioContext.close();
      if (rafId) cancelAnimationFrame(rafId);
      if (silenceTimer) clearTimeout(silenceTimer);
    };
  }, [chatMode]);

  return (
    <div className="chat-container">
      <div className="chat-header">
        <h1>JIO FAQ BOT</h1>
        <p>Ask me anything about Jio Plans, 5G, or services</p>
        <button
          className="mode-toggle"
          onClick={() => {
            unlockAudio();
            setChatMode(prev => prev === 'text' ? 'voice' : 'text');
          }}
        >
          {chatMode === 'text' ? '🎙️ Switch to Voice Mode' : '💬 Switch to Text Chat'}
        </button>
      </div>

      {chatMode === 'voice' ? (
        <div className="voice-mode-container">
          <div className="voice-circles-container">
            {/* User Circle */}
            <div className="voice-circle-wrapper">
              <div className="circle-label">You</div>
              <div className={`circle-outer user-outer ${isRecording ? 'animate-pulse-slow' : ''}`} />
              <div className={`circle-middle user-middle ${isRecording ? 'animate-pulse-med' : ''}`} />
              <div className={`circle-inner user-inner ${isRecording ? 'scale-up' : ''}`} />
              <div className={`voice-mic-btn ${isRecording ? 'recording ring-active' : ''}`} title="Auto-listening">
                {isRecording ? '⏹' : '🎤'}
              </div>
            </div>

            {/* AI Circle */}
            <div className="voice-circle-wrapper">
              <div className="circle-label">AI</div>
              <div className={`circle-outer ai-outer ${isPlaying ? 'animate-pulse-ai-slow' : isLoading ? 'animate-think-slow' : ''}`} />
              <div className={`circle-middle ai-middle ${isPlaying ? 'animate-pulse-ai-med' : isLoading ? 'animate-think-med' : ''}`} />
              <div className={`circle-inner ai-inner ${isPlaying ? 'scale-up-ai' : isLoading ? 'scale-up-think' : ''}`} />

              {(isPlaying || isLoading) && (
                <div className="ai-face">
                  <div className="eyes">
                    <div className="eye"></div>
                    <div className="eye"></div>
                  </div>
                  {isPlaying ? (
                    <div className="mouth speaking"></div>
                  ) : (
                    <div className="thinking-dots ai-think">
                      <span></span><span></span><span></span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="voice-status">
            {vadLoading
              ? 'Loading VAD Model...'
              : isPlaying
                ? 'AI is speaking...'
                : isLoading
                  ? 'AI is thinking...'
                  : isRecording
                    ? 'Listening for speech...'
                    : 'Speak freely, I am listening...'
            }
          </div>

          <div className="voice-messages">
            {messages.map((msg) => {
              let textContent = msg.text.replace('🎤 ', '');
              let a2uiContent = null;
              if (msg.role === 'bot' && msg.surfaceId) {
                const surface = processor.model.getSurface(msg.surfaceId);
                if (surface) {
                  a2uiContent = <A2uiSurface surface={surface} />;
                }
              }

              return (
                <div key={msg.id} className={`voice-msg ${msg.role}`}>
                  <span className="voice-msg-author">{msg.role === 'user' ? 'You' : 'AI'}:</span>
                  <span className="voice-msg-text">
                    {textContent}
                    {a2uiContent && <div style={{ marginTop: '8px' }}>{a2uiContent}</div>}
                  </span>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        </div>
      ) : (
        <>
          <div className="messages-area">
            {messages.map((msg) => {
              let a2uiContent = null;
              if (msg.role === 'bot' && msg.surfaceId) {
                const surface = processor.model.getSurface(msg.surfaceId);
                if (surface) {
                  a2uiContent = <A2uiSurface surface={surface} />;
                }
              }

              return (
                <div key={msg.id} className={`message-wrapper ${msg.role}`}>
                  {msg.text && (
                    <div className="message-bubble">
                      {msg.text}
                    </div>
                  )}
                  {msg.image && (
                    <img src={msg.image}
                      alt="AI Generated"
                      style={{ maxWidth: '100%', borderRadius: '12px', marginTop: '8px' }}
                    />
                  )}
                  {a2uiContent && (
                    <div style={{ marginTop: '8px', maxWidth: '80%' }}>
                      {a2uiContent}
                    </div>
                  )}
                </div>
              );
            })}
            {isLoading && (
              <div className="message-wrapper bot">
                <div className="message-bubble loading-dots">
                  <span></span><span></span><span></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="input-area">
            {/* Hidden file input. */}
            <input
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              ref={fileInputRef} onChange={handleFileUpload}
            />
            {/* Hidden image input */}
            <input type="file" accept="image/*" style={{ display: 'none' }}
              ref={imageInputRef} onChange={handleImageUpload}
            />
            {/*Image upload button */}
            <button className="icon-button" onClick={() => imageInputRef.current?.click()}
              disabled={isLoading || isRecording || vadLoading || isUploading || isImageUploading} title="Upload Image"
              style={{ marginRight: "8px" }}>🖼️ </button>

            {/* Upload Button */}
            <button className="icon-button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading || isRecording || vadLoading || isUploading}
              title="Upload PDF"
              style={{ marginRight: "8px" }} // tiny space
            >📁</button>
            <input
              type="text"
              className="chat-input"
              placeholder="Type your question here..."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendText()}
              disabled={isLoading || isRecording || vadLoading}
            />

            {inputText ? (
              <button className="icon-button" onClick={handleSendText} disabled={isLoading || vadLoading}>
                ↑
              </button>
            ) : (
              <button
                className={`icon-button ${isRecording ? 'recording' : ''}`}
                onMouseDown={startRecording}
                onMouseUp={stopRecording}
                onMouseLeave={stopRecording}
                onTouchStart={startRecording}
                onTouchEnd={stopRecording}
                disabled={isLoading || vadLoading}
                title="Hold to talk"
              >
                {isRecording ? '⏹' : '🎤'}
              </button>
            )}
          </div>
        </>
      )}
      {/* Hidden audio element for stable playback policy */}
      <audio ref={audioPlayerRef} style={{ display: 'none' }} />
    </div>
  )
}

export default App
