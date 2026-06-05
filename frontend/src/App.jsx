import { useState, useRef, useEffect } from 'react'
import { floatToWavBlob } from "./utils/audioUtils"
import { myCatalog } from './A2UICatalog';
import { MessageProcessor } from '@a2ui/web_core/v0_9';
import { A2uiSurface } from '@a2ui/react/v0_9';
import { supabase } from './supabaseClient';
import Auth from './Auth';
import { sarvamFillers } from './fillersData';

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

const fillerPhrases = [
  "Hmm...",
  "Let me think about that...",
  "Looking that up...",
  "Just a second...",
  "Processing...",
  "Reading through the documents...",
  "Fetching details...",
  "Searching the database...",
  "One moment please...",
  "Analyzing...",
  "Checking the latest information...",
  "Retrieving data...",
  "Scanning FAQs..."
];

function LoadingFiller() {
  const [phraseIndex, setPhraseIndex] = useState(() => Math.floor(Math.random() * fillerPhrases.length));

  useEffect(() => {
    const interval = setInterval(() => {
      setPhraseIndex(prev => (prev + 1) % fillerPhrases.length);
    }, 1200);
    return () => clearInterval(interval);
  }, []);

  return <span style={{ fontStyle: 'italic', color: 'var(--text-secondary)', fontSize: '0.95em' }}>{fillerPhrases[phraseIndex]}</span>;
}

function App() {
  const [session, setSession] = useState(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
    })

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
    })

    return () => subscription.unsubscribe()
  }, [])

  const [mode, setMode] = useState('text');

  const [activeSessionId, setActiveSessionId] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(window.innerWidth >= 768);

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

  const [liveMode, setLiveMode] = useState(false);
  const [ws, setWs] = useState(null);
  const [cameraStream, setCameraStream] = useState(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const liveAudioContextRef = useRef(null);
  const frameIntervalRef = useRef(null);

  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioPlayerRef = useRef(null);
  const fillerAudioRef = useRef(null);
  const [isPlusMenuOpen, setIsPlusMenuOpen] = useState(false);
  const plusMenuRef = useRef(null);

  const ttsQueueRef = useRef([]);
  const isPlayingTTSRef = useRef(false);

  const processTTSQueue = () => {
    if (isPlayingTTSRef.current || ttsQueueRef.current.length === 0) return;
    isPlayingTTSRef.current = true;
    const b64 = ttsQueueRef.current.shift();
    if (!audioPlayerRef.current) return;
    
    audioPlayerRef.current.src = `data:audio/wav;base64,${b64}`;
    audioPlayerRef.current.onended = () => {
      isPlayingTTSRef.current = false;
      processTTSQueue();
    };
    audioPlayerRef.current.onerror = () => {
      isPlayingTTSRef.current = false;
      processTTSQueue();
    };
    audioPlayerRef.current.play().catch(e => {
      isPlayingTTSRef.current = false;
      processTTSQueue();
    });
  };

  const appendTTSChunk = (b64) => {
    ttsQueueRef.current.push(b64);
    processTTSQueue();
  };

  const startLiveMode = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: 640, height: 360 }
      });
      setCameraStream(stream);
      if (videoRef.current) videoRef.current.srcObject = stream;

      const socket = new WebSocket('ws://localhost:8000/api/live/ws');
      socket.onopen = () => {
        socket.send(JSON.stringify({
          type: "auth",
          payload: { token: session?.access_token, session_id: activeSessionId }
        }));
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "assistant_response") {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'bot', text: data.payload }]);
        } else if (data.type === "tts_chunk") {
          appendTTSChunk(data.payload);
        } else if (data.type === "visual_summary") {
          console.log("AI sees:", data.payload);
        } else if (data.type === "error") {
          console.error("Live error:", data.payload);
        }
      };
      setWs(socket);

      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      liveAudioContextRef.current = audioContext;
      const source = audioContext.createMediaStreamSource(audioStream);
      const processorNode = audioContext.createScriptProcessor(4096, 1, 1);

      const encodePCM = (pcmData) => {
        const bytes = new Uint8Array(pcmData.buffer);
        let binary = '';
        const chunkSize = 8192;
        for (let i = 0; i < bytes.length; i += chunkSize) {
          binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
        }
        return btoa(binary);
      };

      processorNode.onaudioprocess = (event) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const input = event.inputBuffer.getChannelData(0);
        const pcmData = new Int16Array(input.length);
        for (let i = 0; i < input.length; i++) {
          pcmData[i] = Math.max(-32768, Math.min(32767, input[i] * 32768));
        }
        
        socket.send(JSON.stringify({ type: "audio_chunk", payload: encodePCM(pcmData) }));
      };
      source.connect(processorNode);
      processorNode.connect(audioContext.destination);

      const captureFrame = async () => {
        if (!videoRef.current || socket.readyState !== WebSocket.OPEN) return;
        try {
          const track = videoRef.current.srcObject?.getVideoTracks()[0];
          if (track && 'ImageCapture' in window) {
            const capture = new ImageCapture(track);
            const bitmap = await capture.grabFrame();
            const canvas = canvasRef.current;
            if (!canvas) return;
            canvas.width = 640;
            canvas.height = 360;
            const ctx = canvas.getContext('bitmaprenderer') || canvas.getContext('2d');
            if (typeof ctx.transferFromImageBitmap === 'function') {
              ctx.transferFromImageBitmap(bitmap);
            } else {
              ctx.drawImage(bitmap, 0, 0, 640, 360);
              bitmap.close();
            }
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.6));
            if (!blob) return;
            const buffer = await blob.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            let binary = '';
            const chunkSize = 16384;
            for (let i = 0; i < bytes.length; i += chunkSize) {
              binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
            }
            socket.send(JSON.stringify({ type: "video_frame", payload: btoa(binary) }));
          } else {
            const canvas = canvasRef.current;
            if (!canvas) return;
            canvas.width = 640;
            canvas.height = 360;
            canvas.getContext('2d').drawImage(videoRef.current, 0, 0, 640, 360);
            canvas.toBlob((blob) => {
              if (!blob) return;
              const reader = new FileReader();
              reader.onload = () => {
                const jpeg = reader.result.split(',')[1];
                socket.send(JSON.stringify({ type: "video_frame", payload: jpeg }));
              };
              reader.readAsDataURL(blob);
            }, 'image/jpeg', 0.6);
          }
        } catch (err) {
          const canvas = canvasRef.current;
          if (!canvas) return;
          canvas.width = 640;
          canvas.height = 360;
          canvas.getContext('2d').drawImage(videoRef.current, 0, 0, 640, 360);
          const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
          socket.send(JSON.stringify({ type: "video_frame", payload: dataUrl.split(',')[1] }));
        }
      };
      frameIntervalRef.current = setInterval(captureFrame, 1000);

      setLiveMode(true);
      setMode('live');
    } catch (err) {
      console.error("Live mode error:", err);
      alert("Failed to start live mode (check camera/mic permissions).");
    }
  };

  const stopLiveMode = () => {
    if (ws) {
      ws.close();
      setWs(null);
    }
    if (cameraStream) {
      cameraStream.getTracks().forEach(t => t.stop());
      setCameraStream(null);
    }
    if (liveAudioContextRef.current) {
      liveAudioContextRef.current.close();
      liveAudioContextRef.current = null;
    }
    if (frameIntervalRef.current) {
      clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setLiveMode(false);
    setMode('text');
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (plusMenuRef.current && !plusMenuRef.current.contains(event.target)) {
        setIsPlusMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const fetchSessions = async () => {
    if (!session?.access_token) return;
    try {
      const res = await fetch('http://localhost:8000/api/sessions', {
        headers: { 'Authorization': `Bearer ${session.access_token}` }
      });
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    }
  };

  useEffect(() => {
    if (session) {
      fetchSessions();
      if (!activeSessionId) {
        handleNewChat();
      }
    }
  }, [session]);

  const handleNewChat = () => {
    const newSessionId = crypto.randomUUID();
    setActiveSessionId(newSessionId);
    setMessages([{ id: crypto.randomUUID(), role: 'bot', text: 'Hello! How can I help you today?' }]);
    setMode('text');
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  };

  const loadSessionHistory = async (sessionId) => {
    setActiveSessionId(sessionId);
    setMode('text');
    if (window.innerWidth < 768) setIsSidebarOpen(false);
    setMessages([{ id: crypto.randomUUID(), role: 'bot', text: 'Loading history...' }]);
    if (!session?.access_token) return;
    try {
      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/history`, {
        headers: { 'Authorization': `Bearer ${session.access_token}` }
      });
      const data = await res.json();
      if (data.history) {
         const historyMsgs = data.history.map(msg => ({
           id: crypto.randomUUID(),
           role: msg.type === 'user' ? 'user' : 'bot',
           text: msg.content
         }));
         if (historyMsgs.length === 0) {
             historyMsgs.push({ id: crypto.randomUUID(), role: 'bot', text: 'Hello! How can I help you today?' });
         }
         setMessages(historyMsgs);
      }
    } catch (e) {
      console.error(e);
      setMessages([{ id: crypto.randomUUID(), role: 'bot', text: 'Failed to load history.' }]);
    }
  };

  useEffect(() => {
    if (mode === 'file') setUploadResult(null);
    if (mode === 'image') { setGeneratedImage(null); setImagePrompt(''); }
    if (mode !== 'live' && liveMode) stopLiveMode();
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
    ttsQueueRef.current = [];
    isPlayingTTSRef.current = false;
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    if (fillerAudioRef.current && !fillerAudioRef.current.paused) {
      fillerAudioRef.current.pause();
    }
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

  const playVoiceFiller = () => {
    if (!sarvamFillers || sarvamFillers.length === 0) return;
    const b64 = sarvamFillers[Math.floor(Math.random() * sarvamFillers.length)];
    if (!fillerAudioRef.current) {
      fillerAudioRef.current = new Audio();
    }
    // Cancel previous filler if playing
    if (!fillerAudioRef.current.paused) {
      fillerAudioRef.current.pause();
    }
    fillerAudioRef.current.src = `data:audio/wav;base64,${b64}`;
    fillerAudioRef.current.volume = 0.5;
    fillerAudioRef.current.play().catch(e => console.error("Filler audio failed", e));
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
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session?.access_token}`
        },
        body: JSON.stringify({ message: userMsg.text, session_id: activeSessionId })
      });
      fetchSessions(); // Refresh sidebar titles
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
    playVoiceFiller();
    const tempId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: tempId, role: 'user', text: '\uD83C\uDFA4 [Transcribing...]' }]);
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.wav');
    if (activeSessionId) {
      formData.append('session_id', activeSessionId);
    }
    try {
      const response = await fetch('http://localhost:8000/api/chat/audio', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session?.access_token}`
        },
        body: formData
      });
      fetchSessions(); // Refresh sidebar titles
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

  if (!session) {
    return <div className="chat-container"><Auth setSession={setSession} /></div>
  }

  return (
    <div className="app-layout">
      {/* SIDEBAR UI */}
      <div className={`sidebar ${isSidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={handleNewChat}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            New Chat
          </button>
          <button className="close-sidebar-btn" onClick={() => setIsSidebarOpen(false)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
        <div className="sidebar-sessions">
          {activeSessionId && !sessions.find(s => s.id === activeSessionId) && (
            <div className="session-item active">
              <ChatIcon />
              <span className="session-title">New Chat</span>
            </div>
          )}
          {sessions.map(s => (
            <div 
              key={s.id} 
              className={`session-item ${activeSessionId === s.id ? 'active' : ''}`}
              onClick={() => loadSessionHistory(s.id)}
            >
              <ChatIcon />
              <span className="session-title">{s.title || 'New Chat'}</span>
            </div>
          ))}
          {sessions.length === 0 && !activeSessionId && <div className="no-sessions">No previous chats</div>}
        </div>
        <div className="sidebar-footer">
          <button className="logout-btn" onClick={() => supabase.auth.signOut()}>Sign Out</button>
        </div>
      </div>

      <div className="chat-container">
        {!isSidebarOpen && (
           <button className="open-sidebar-btn" onClick={() => setIsSidebarOpen(true)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
           </button>
        )}
      {mode === 'live' ? (
        <div className="live-view">
          <div className="live-header">
            <button className="back-button" onClick={stopLiveMode}>
              <ArrowLeftIcon />
            </button>
            <span className="live-title">Live Camera</span>
            <span className="live-dot" />
          </div>

          <div className="live-video-container">
            <video ref={videoRef} autoPlay playsInline muted className="live-video" />
            <canvas ref={canvasRef} style={{ display: 'none' }} />
          </div>

          <div className="live-conversation">
            {messages.slice(-3).map(m => (
              <div key={m.id} className={`live-msg ${m.role}`}>
                <span className="live-msg-label">
                  {m.role === 'user' ? 'You' : 'AI'}
                </span>
                <span className="live-msg-text">{m.text}</span>
              </div>
            ))}
          </div>
        </div>
      ) : mode === 'text' ? (
        <>
          <div className="messages-area">
            {messages.map((m) => {
                let a2uiContent = null;
              if (m.role === 'bot' && m.surfaceId) {
                const surface = processor.model.getSurface(m.surfaceId);
                if (surface) a2uiContent = <A2uiSurface surface={surface} />;
              }
              return (
                <div key={m.id} className={`message-wrapper ${m.role}`}>
                  {m.role === 'bot' && (
                    <div className="message-icon bot-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                    </div>
                  )}
                  <div className="message-bubble">
                    {m.text && <div>{m.text}</div>}
                    {m.image && (
                      <img src={m.image} alt="AI Generated" style={{ maxWidth: '100%', borderRadius: '12px', marginTop: '8px' }} />
                    )}
                    {a2uiContent && <div style={{ marginTop: '8px', maxWidth: '100%' }}>{a2uiContent}</div>}
                  </div>
                  {m.role === 'user' && (
                    <div className="message-icon user-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    </div>
                  )}
                </div>
              );
            })}
            {isLoading && (
              <div className="message-wrapper bot">
                <div className="message-icon bot-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                </div>
                <div className="message-bubble" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div className="loading-dots" style={{ margin: 0 }}><span></span><span></span><span></span></div>
                  <LoadingFiller />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <input type="file" accept=".pdf" style={{ display: 'none' }} ref={fileInputRef} onChange={handleFileUpload} />
          <input type="file" accept="image/*" style={{ display: 'none' }} ref={imageInputRef} onChange={handleImageUpload} />
          <div className="input-area">
            <div>
              <div className="plus-menu-container" ref={plusMenuRef}>
                <button className="icon-button" onClick={() => setIsPlusMenuOpen(!isPlusMenuOpen)}
                  disabled={isLoading || isRecording || vadLoading || isUploading || isImageUploading} title="More options">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                </button>
                {isPlusMenuOpen && (
                  <div className="plus-menu-dropdown">
                    <button className="plus-menu-item" onClick={() => { fileInputRef.current?.click(); setIsPlusMenuOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>
                      Upload PDF
                    </button>
                    <button className="plus-menu-item" onClick={() => { imageInputRef.current?.click(); setIsPlusMenuOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>
                      Upload Image
                    </button>
                    <button className="plus-menu-item" onClick={() => { setMode('audio'); setIsPlusMenuOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" /><path d="M19 10v2a7 7 0 01-14 0v-2" /><line x1="12" y1="19" x2="12" y2="23" /><line x1="8" y1="23" x2="16" y2="23" /></svg>
                      Voice Chat
                    </button>
                    <button className="plus-menu-item" onClick={() => { setMode('image'); setIsPlusMenuOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><line x1="21.17" y1="8" x2="12" y2="8"/><line x1="3.95" y1="6.06" x2="8.54" y2="14"/><line x1="10.88" y1="21.94" x2="15.46" y2="14"/></svg>
                      Create Image
                    </button>
                    <button className="plus-menu-item" onClick={() => { startLiveMode(); setIsPlusMenuOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
                      Live Video Chat
                    </button>
                  </div>
                )}
              </div>
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
    </div>
  );
}

export default App
