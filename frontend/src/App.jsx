import { useState, useRef, useEffect } from 'react'
import { floatToWavBlob } from "./utils/audioUtils"
import { myCatalog } from './A2UICatalog';

function App() {
  const [messages, setMessages] = useState([
    { id: 1, role: 'bot', text: 'Hello! Ask me anything about Jio Plans, 5G, or services.' }
  ]);
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

  const handleSendText = async () => {
    if (!inputText.trim()) return;

    unlockAudio();

      const userMsg = { id: crypto.randomUUID(), role: 'user', text: inputText };
      setMessages(prev => [...prev, userMsg]);
      setInputText('');
      setIsLoading(true);

      try {
        const response = await fetch('http://localhost:8000/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: userMsg.text })
        });

        const data = await response.json();
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: data.text }]);
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

        setMessages(prev => {
          // Remove the temporary message
          const filtered = prev.filter(m => m.id !== tempId);

          // Add the real transcribed user message and the bot's response
          const newMessages = [...filtered];
          if (data.user_message) {
            newMessages.push({ id: crypto.randomUUID(), role: 'user', text: `🎤 ${data.user_message}` });
          }
          newMessages.push({ id: crypto.randomUUID(), role: 'bot', text: data.text });
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
              let content = msg.text.replace('🎤 ', '');
              if (msg.role === 'bot') {
                try {
                  const parsed = JSON.parse(msg.text);
                  if (parsed.type && myCatalog[parsed.type]) {
                    const Component = myCatalog[parsed.type];
                    content = <Component {...parsed.props} />;
                  }
                } catch (e) {
                  // Not JSON, render as text
                }
              }

              return (
                <div key={msg.id} className={`voice-msg ${msg.role}`}>
                  <span className="voice-msg-author">{msg.role === 'user' ? 'You' : 'AI'}:</span>
                  <span className="voice-msg-text">{content}</span>
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
              let content = msg.text;
              if (msg.role === 'bot') {
                try {
                  const parsed = JSON.parse(msg.text);
                  if (parsed.type && myCatalog[parsed.type]) {
                    const Component = myCatalog[parsed.type];
                    content = <Component {...parsed.props} />;
                  }
                } catch (e) {
                  // Not JSON, render as text
                }
              }

              return (
                <div key={msg.id} className={`message-wrapper ${msg.role}`}>
                  {typeof content === 'string' ? (
                    <div className="message-bubble">
                      {content}
                    </div>
                  ) : (
                    content
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
