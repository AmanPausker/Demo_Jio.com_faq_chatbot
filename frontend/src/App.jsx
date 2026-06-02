import { useState, useRef, useEffect } from 'react'
import { floatToWavBlob } from "./utils/audioUtils"
import { myCatalog } from './A2UICatalog';
import { MessageProcessor } from '@a2ui/web_core/v0_9';
import { A2uiSurface } from '@a2ui/react/v0_9';

const processor = new MessageProcessor([myCatalog]);

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

function ArrowLeftIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

function ViewHeader({ title, onBack }) {
  return (
    <div className="view-header">
      <button className="back-button" onClick={onBack}><ArrowLeftIcon /></button>
      <span className="view-header-title">{title}</span>
    </div>
  );
}

function App() {
  const sessionIdRef = useRef(crypto.randomUUID());

  const [mode, setMode] = useState(null);

  const [messages, setMessages] = useState([
    { id: 1, role: 'bot', text: 'Hello! How can I help you today?' }
  ]);
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const [isImageUploading, setIsImageUploading] = useState(false);
  const [isUploading, setIsUpLoading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [inputText, setInputText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [vadLoading, setVadLoading] = useState(false);
  const [generatedImage, setGeneratedImage] = useState(null);
  const [imageGenLoading, setImageGenLoading] = useState(false);
  const [imagePrompt, setImagePrompt] = useState('');

  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioPlayerRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (mode === 'file') setUploadResult(null);
    if (mode === 'image') { setGeneratedImage(null); setImagePrompt(''); }
  }, [mode]);

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
    setUploadResult(null);
    const tempId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: tempId, role: 'bot', text: `\uD83D\uDCC1 Uploading and processing ${file.name}...` }]);
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
          setUploadResult(data.message);
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `\u2705 ${data.message}` }];
        } else {
          setUploadResult(`Upload failed: ${data.error}`);
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `\u274C Upload failed: ${data.error}` }];
        }
      });
    } catch (error) {
      console.error("Upload error", error);
      const errMsg = 'Failed to connect to server during upload.';
      setUploadResult(errMsg);
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `\u274C ${errMsg}` }];
      });
    } finally {
      setIsUpLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleImageUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    setIsImageUploading(true);
    const tempId = crypto.randomUUID();
    setMessages(prev => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', text: `\uD83D\uDDBC\uFE0F Uploaded Image: ${file.name}` },
      { id: tempId, role: 'bot', text: '\uD83D\uDC41\uFE0F Analyzing image...' }
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
          return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: `\u274C Vision failed: ${data.error}` }];
        }
      });
    } catch (error) {
      console.error("Image upload error", error);
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== tempId);
        return [...filtered, { id: crypto.randomUUID(), role: 'bot', text: '\u274C Failed to connect to vision server.' }];
      });
    } finally {
      setIsImageUploading(false);
      if (imageInputRef.current) imageInputRef.current.value = '';
    }
  };

  const playAudio = (base64Audio) => {
    if (!base64Audio || !audioPlayerRef.current) return;
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

  const handleGenerateImage = async (prompt) => {
    if (!prompt.trim()) return;
    unlockAudio();
    setImageGenLoading(true);
    setImagePrompt(prompt);
    setGeneratedImage(null);
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', text: `\uD83C\uDFA8 Create image: ${prompt}` }]);
    try {
      const response = await fetch('http://localhost:8000/api/generate_image', {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
      });
      const data = await response.json();
      if (data.success) {
        const imgBase64 = `data:image/jpeg;base64,${data.image_base64}`;
        setGeneratedImage(imgBase64);
        setMessages(prev => [...prev, {
          id: crypto.randomUUID(),
          role: 'bot',
          text: `\u2728 Here is your image for: "${prompt}"`,
          image: imgBase64
        }]);
      } else {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: `\u274C Image failed: ${data.error}` }]);
      }
    } catch (error) {
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: '\u274C Failed to connect to server.' }]);
    } finally {
      setImageGenLoading(false);
    }
  };

  const handleSendText = async () => {
    if (!inputText.trim()) return;
    unlockAudio();
    const userMsg = { id: crypto.randomUUID(), role: 'user', text: inputText };
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setIsLoading(true);
    if (userMsg.text.startsWith('/imagine ')) {
      const prompt = userMsg.text.replace('/imagine ', '');
      try {
        const response = await fetch('http://localhost:8000/api/generate_image', {
          method: "POST",
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt })
        });
        const data = await response.json();
        if (data.success) {
          setMessages(prev => [...prev, {
            id: crypto.randomUUID(),
            role: 'bot',
            text: `\u2728 Here is your image for: "${prompt}"`,
            image: `data:image/jpeg;base64,${data.image_base64}`
          }]);
        } else {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: `\u274C Image failed: ${data.error}` }]);
        }
      } catch (error) {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: '\u274C Failed to connect to server.' }]);
      } finally {
        setIsLoading(false);
      }
      return;
    }
    try {
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg.text, thread_id: sessionIdRef.current })
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
    const tempId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: tempId, role: 'user', text: '\uD83C\uDFA4 [Transcribing...]' }]);
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.wav');
    formData.append('thread_id', sessionIdRef.current);
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
        const filtered = prev.filter(m => m.id !== tempId);
        const newMessages = [...filtered];
        if (data.user_message) {
          newMessages.push({ id: crypto.randomUUID(), role: 'user', text: `\uD83C\uDFA4 ${data.user_message}` });
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

  const startRecording = async () => {
    try {
      unlockAudio();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        await sendAudioMessage(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };
      mediaRecorder.start();
      setIsRecording(true);
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
        const VOLUME_THRESHOLD = 50;
        const SILENCE_MS_TO_STOP = 1500;
        setVadLoading(false);

        const checkVolume = () => {
          if (!active) return;
          analyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          const averageVolume = sum / dataArray.length;
          if (averageVolume > VOLUME_THRESHOLD) {
            if (silenceTimer) {
              clearTimeout(silenceTimer);
              silenceTimer = null;
            }
            if (!isSpeakingState) {
              isSpeakingState = true;
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
            if (isSpeakingState && !silenceTimer) {
              silenceTimer = setTimeout(() => {
                isSpeakingState = false;
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

    if (mode === 'audio') {
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
  }, [mode]);

  return (
    <div className="chat-container">
      {mode === null ? (
        <div className="home-screen">
          <div className="home-header">
            <h1>AI Assistant</h1>
            <p>How would you like to interact?</p>
          </div>
          <div className="option-grid">
            <button className="option-card" onClick={() => setMode('text')}>
              <ChatIcon />
              <span className="option-title">Text Chat</span>
              <span className="option-desc">Ask questions and get answers</span>
            </button>
            <button className="option-card" onClick={() => setMode('audio')}>
              <MicIcon />
              <span className="option-title">Voice Chat</span>
              <span className="option-desc">Speak and get spoken responses</span>
            </button>
            <button className="option-card" onClick={() => setMode('file')}>
              <UploadIcon />
              <span className="option-title">Upload File</span>
              <span className="option-desc">Upload PDFs for analysis</span>
            </button>
            <button className="option-card" onClick={() => setMode('image')}>
              <ImageIcon />
              <span className="option-title">Create Image</span>
              <span className="option-desc">Generate images from text</span>
            </button>
          </div>
        </div>
      ) : mode === 'text' ? (
        <>
          <ViewHeader title="Text Chat" onBack={() => setMode(null)} />
          <div className="messages-area">
            {messages.map((msg) => {
              let a2uiContent = null;
              if (msg.role === 'bot' && msg.surfaceId) {
                const surface = processor.model.getSurface(msg.surfaceId);
                if (surface) a2uiContent = <A2uiSurface surface={surface} />;
              }
              return (
                <div key={msg.id} className={`message-wrapper ${msg.role}`}>
                  {msg.text && <div className="message-bubble">{msg.text}</div>}
                  {msg.image && (
                    <img src={msg.image} alt="AI Generated" style={{ maxWidth: '100%', borderRadius: '12px', marginTop: '8px' }} />
                  )}
                  {a2uiContent && <div style={{ marginTop: '8px', maxWidth: '80%' }}>{a2uiContent}</div>}
                </div>
              );
            })}
            {isLoading && (
              <div className="message-wrapper bot">
                <div className="message-bubble loading-dots"><span></span><span></span><span></span></div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <input type="file" accept=".pdf" style={{ display: 'none' }} ref={fileInputRef} onChange={handleFileUpload} />
          <input type="file" accept="image/*" style={{ display: 'none' }} ref={imageInputRef} onChange={handleImageUpload} />
          <div className="input-area">
            <div>
              <button className="icon-button" onClick={() => imageInputRef.current?.click()}
                disabled={isLoading || isRecording || vadLoading || isUploading || isImageUploading} title="Upload Image">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
              </button>
              <button className="icon-button" onClick={() => fileInputRef.current?.click()}
                disabled={isLoading || isRecording || vadLoading || isUploading} title="Upload PDF">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
              </button>
              <input
                type="text" className="chat-input" placeholder="Type your question here..."
                value={inputText} onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendText()}
                disabled={isLoading || isRecording || vadLoading}
              />
              {inputText ? (
                <button className="icon-button" onClick={handleSendText} disabled={isLoading || vadLoading} title="Send">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </button>
              ) : (
                <button className={`icon-button ${isRecording ? 'recording' : ''}`}
                  onMouseDown={startRecording} onMouseUp={stopRecording} onMouseLeave={stopRecording}
                  onTouchStart={startRecording} onTouchEnd={stopRecording}
                  disabled={isLoading || vadLoading} title="Hold to talk">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
                    <path d="M19 10v2a7 7 0 01-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </>
      ) : mode === 'audio' ? (
        <>
          <ViewHeader title="Voice Chat" onBack={() => setMode(null)} />
          <div className="voice-mode-container">
            <div className="voice-circles-container">
              <div className="voice-circle-wrapper">
                <div className="circle-label">You</div>
                <div className={`circle-outer user-outer ${isRecording ? 'animate-pulse-slow' : ''}`} />
                <div className={`circle-middle user-middle ${isRecording ? 'animate-pulse-med' : ''}`} />
                <div className={`circle-inner user-inner ${isRecording ? 'scale-up' : ''}`} />
                <div className={`voice-mic-btn ${isRecording ? 'recording ring-active' : ''}`} title="Auto-listening">
                  {isRecording ? '⏹' : '🎤'}
                </div>
              </div>
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
              {vadLoading ? 'Loading...' : isPlaying ? 'AI is speaking...' : isLoading ? 'AI is thinking...' : isRecording ? 'Listening...' : 'Speak freely, I am listening...'}
            </div>
            <div className="voice-messages">
              {messages.map((msg) => {
                let textContent = msg.text.replace('\uD83C\uDFA4 ', '');
                let a2uiContent = null;
                if (msg.role === 'bot' && msg.surfaceId) {
                  const surface = processor.model.getSurface(msg.surfaceId);
                  if (surface) a2uiContent = <A2uiSurface surface={surface} />;
                }
                return (
                  <div key={msg.id} className={`voice-msg ${msg.role}`}>
                    <span className="voice-msg-author">{msg.role === 'user' ? 'You' : 'AI'}:</span>
                    <span className="voice-msg-text">{textContent}{a2uiContent && <div style={{ marginTop: '8px' }}>{a2uiContent}</div>}</span>
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          </div>
        </>
      ) : mode === 'file' ? (
        <>
          <ViewHeader title="Upload File" onBack={() => setMode(null)} />
          <div className="file-upload-view">
            <input type="file" accept=".pdf" style={{ display: 'none' }} ref={fileInputRef} onChange={handleFileUpload} />
            <div className="drop-zone" onClick={() => !isUploading && fileInputRef.current?.click()}>
              <div className="drop-zone-icon">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </div>
              <div className="drop-zone-text">
                {isUploading ? 'Uploading...' : 'Click to upload a PDF file'}
              </div>
              <div className="drop-zone-hint">Supported format: PDF</div>
            </div>
            {uploadResult && (
              <div className={`upload-result ${uploadResult.startsWith('\u2705') || !uploadResult.startsWith('\u274C') ? 'success' : 'error'}`}>
                {uploadResult}
              </div>
            )}
            <button className="secondary-button" onClick={() => setMode('text')} style={{ marginTop: '16px' }}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              </svg>
              Chat about this file
            </button>
          </div>
        </>
      ) : mode === 'image' ? (
        <>
          <ViewHeader title="Create Image" onBack={() => setMode(null)} />
          <div className="image-creation-view">
            <div className="image-prompt-area">
              <input
                type="text" className="image-prompt-input" placeholder="Describe the image you want to create..."
                value={imagePrompt} onChange={(e) => setImagePrompt(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !imageGenLoading && handleGenerateImage(imagePrompt)}
                disabled={imageGenLoading}
              />
              <button className="generate-button" onClick={() => handleGenerateImage(imagePrompt)} disabled={imageGenLoading || !imagePrompt.trim()}>
                {imageGenLoading ? 'Generating...' : 'Generate'}
              </button>
            </div>
            {imageGenLoading && (
              <div className="loading-dots" style={{ padding: '24px' }}>
                <span></span><span></span><span></span>
              </div>
            )}
            {generatedImage && (
              <div className="image-result">
                <img src={generatedImage} alt="Generated" />
                <button className="secondary-button" style={{ marginTop: '16px' }} onClick={() => { setGeneratedImage(null); setImagePrompt(''); }}>
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="1 4 1 10 7 10" />
                    <path d="M3.51 15a9 9 0 102.13-9.36L1 10" />
                  </svg>
                  Create Another
                </button>
              </div>
            )}
            {!generatedImage && !imageGenLoading && (
              <div className="image-result-placeholder">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.3 }}>
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
                <span>Your image will appear here</span>
              </div>
            )}
          </div>
        </>
      ) : null}
      <audio ref={audioPlayerRef} style={{ display: 'none' }} />
    </div>
  );
}

export default App
