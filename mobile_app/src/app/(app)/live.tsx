import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Audio } from 'expo-av';
import { useEffect, useRef, useState, useCallback } from 'react';
import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import * as FileSystem from 'expo-file-system/legacy';
import { supabase } from '../../utils/supabaseClient';
import { WaveAnimation, WaveType } from '../../components/WaveAnimation';

// PCM encoding buffer
const pcmEncode = (audioData: Float32Array): ArrayBuffer => {
  const pcm = new Int16Array(audioData.length);
  for (let i = 0; i < audioData.length; i++) {
    pcm[i] = Math.max(-32768, Math.min(32767, audioData[i] * 32768));
  }
  return pcm.buffer;
};

const encodeBase64 = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = Array.from(bytes.subarray(i, i + chunkSize));
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
};

export default function LiveChatScreen() {
  const router = useRouter();
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const [audioPermissionResponse, requestAudioPermission] = Audio.usePermissions();
  
  const cameraRef = useRef<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollViewRef = useRef<ScrollView>(null);
  
  const [messages, setMessages] = useState<any[]>([]);
  const isRecordingRef = useRef(false);
  const activeSessionIdRef = useRef(Date.now().toString()); 
  
  // TTS playback queue
  const ttsQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef(false);
  const soundRef = useRef<Audio.Sound | null>(null);

  // Animation states
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const userSpeakingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Audio recording refs
  const audioRecorderRef = useRef<any>(null);
  const audioStreamRef = useRef<any>(null);

  // VAD logic
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isSpeakingState = useRef(false);
  const VOLUME_THRESHOLD = -20;
  const SILENCE_MS_TO_STOP = 1500;

  // Setup permissions
  useEffect(() => {
    if (!cameraPermission?.granted) requestCameraPermission();
    if (!audioPermissionResponse?.granted) requestAudioPermission();
  }, [cameraPermission, audioPermissionResponse]);

  // Connect WebSocket and setup loops
  useFocusEffect(
    useCallback(() => {
      setMessages([]);
      activeSessionIdRef.current = Date.now().toString();

      let mounted = true;
      let frameInterval: ReturnType<typeof setInterval>;
      
      const connectWs = async () => {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;
        
        const wsUrl = process.env.EXPO_PUBLIC_API_URL?.replace('http', 'ws') + '/api/live/ws';
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        
        ws.onopen = async () => {
          ws.send(JSON.stringify({
            type: "auth",
            payload: { token: session.access_token, session_id: activeSessionIdRef.current }
          }));
          
          // Start Video Loop (0.5 FPS)
          frameInterval = setInterval(async () => {
            if (!mounted || !cameraRef.current) return;
            try {
              const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.5, shutterSound: false });
              if (photo && photo.base64 && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "video_frame", payload: photo.base64 }));
              }
            } catch (e) {}
          }, 2000);
          
          // Start streaming audio via PCM chunks through WebSocket
          isRecordingRef.current = true;
          startStreamingAudio(ws);
        };

        ws.onmessage = (event) => {
          const data = JSON.parse(event.data);
          if (data.type === "assistant_response") {
            setMessages(prev => [...prev.slice(-2), { role: 'bot', text: data.payload }]);
          } else if (data.type === "transcript") {
            setMessages(prev => [...prev.slice(-2), { role: 'user', text: data.payload }]);
          } else if (data.type === "tts_chunk") {
            ttsQueueRef.current.push(data.payload);
            playNextTTS();
          }
        };
      };
      
      connectWs();
      
      return () => {
        mounted = false;
        isRecordingRef.current = false;
        if (frameInterval) clearInterval(frameInterval);
        if (wsRef.current) wsRef.current.close();
        try {
          if (soundRef.current) soundRef.current.unloadAsync();
        } catch (e) {}
        try {
          if (audioRecorderRef.current) {
            audioRecorderRef.current.stopAndUnloadAsync();
          }
        } catch (e) {}
      };
    }, [])
  );

  const playNextTTS = async () => {
    if (isPlayingRef.current || ttsQueueRef.current.length === 0) return;
    isPlayingRef.current = true;
    setIsAssistantSpeaking(true);
    const b64 = ttsQueueRef.current.shift();
    
    if (!b64) {
        isPlayingRef.current = false;
        setIsAssistantSpeaking(false);
        playNextTTS();
        return;
    }
    
    try {
      const uri = `data:audio/wav;base64,${b64}`;
      const { sound } = await Audio.Sound.createAsync({ uri });
      soundRef.current = sound;
      
      sound.setOnPlaybackStatusUpdate((status: any) => {
        if (status.didJustFinish) {
          sound.unloadAsync();
          isPlayingRef.current = false;
          setIsAssistantSpeaking(false);
          playNextTTS();
        }
      });
      await sound.playAsync();
    } catch (e) {
      console.error("Audio playback error:", e);
      isPlayingRef.current = false;
      setIsAssistantSpeaking(false);
      playNextTTS();
    }
  };

  const startStreamingAudio = async (ws: WebSocket) => {
    if (!isRecordingRef.current) return;
    
    try {
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });
      
      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
        (status) => {
          if (status.metering) {
            handleMetering(status.metering, ws);
          }
        },
        100
      );
      audioRecorderRef.current = recording;
    } catch (err) {
      console.error("Audio start error", err);
      setTimeout(() => startStreamingAudio(ws), 1000);
    }
  };

  const handleMetering = (db: number, ws: WebSocket) => {
    if (isPlayingRef.current) return;

    if (db > VOLUME_THRESHOLD) {
      setUserSpeaking(true);
      if (userSpeakingTimeoutRef.current) clearTimeout(userSpeakingTimeoutRef.current);
      userSpeakingTimeoutRef.current = setTimeout(() => setUserSpeaking(false), 1000);

      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }
      if (!isSpeakingState.current) {
        isSpeakingState.current = true;
        if (soundRef.current && isPlayingRef.current) {
          soundRef.current.stopAsync().catch(() => {});
          isPlayingRef.current = false;
          setIsAssistantSpeaking(false);
        }
        ws.send(JSON.stringify({ type: "interrupt" }));
      }
    } else {
      if (isSpeakingState.current && !silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          isSpeakingState.current = false;
          handleSpeechEnd(ws);
        }, SILENCE_MS_TO_STOP);
      }
    }
  };

  const handleSpeechEnd = async (ws: WebSocket) => {
    if (!audioRecorderRef.current || !isRecordingRef.current) return;
    try {
      await audioRecorderRef.current.stopAndUnloadAsync();
      const uri = audioRecorderRef.current.getURI();
      audioRecorderRef.current = null;
      
      if (uri && ws.readyState === WebSocket.OPEN) {
        const base64 = await FileSystem.readAsStringAsync(uri, { encoding: 'base64' });
        ws.send(JSON.stringify({ type: "audio_file_full", payload: base64 }));
      }
      
      startStreamingAudio(ws);
    } catch (e) {
      console.error('Stop recording error', e);
      startStreamingAudio(ws);
    }
  };

  if (!cameraPermission?.granted || !audioPermissionResponse?.granted) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
            <TouchableOpacity onPress={() => router.replace('/chat')} style={styles.backBtn}>
              <Feather name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
        </View>
        <Text style={styles.text}>Requesting permissions...</Text>
      </View>
    );
  }

  const waveType: WaveType = userSpeaking ? 'user' : isAssistantSpeaking ? 'assistant' : 'idle';

  return (
    <View style={styles.container}>
      <CameraView style={styles.camera} facing="back" ref={cameraRef}>
        <View style={styles.overlay}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => router.replace('/chat')} style={styles.backBtn}>
              <Feather name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.title}>Live Camera</Text>
            <View style={styles.recordingDot} />
          </View>
          
          <WaveAnimation type={waveType} />

          <ScrollView 
            style={styles.messagesScrollView} 
            contentContainerStyle={styles.messagesContent}
            ref={scrollViewRef}
            onContentSizeChange={() => scrollViewRef.current?.scrollToEnd({ animated: true })}
          >
            {messages.map((m, i) => (
              <View key={i} style={styles.messageBox}>
                <Text style={styles.messageLabel}>{m.role === 'user' ? 'YOU' : 'AI'}</Text>
                <Text style={styles.messageText}>{m.text}</Text>
              </View>
            ))}
          </ScrollView>
        </View>
      </CameraView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
  },
  text: {
    color: '#fff',
    textAlign: 'center',
    marginTop: 50,
  },
  camera: {
    flex: 1,
  },
  overlay: {
    flex: 1,
    justifyContent: 'space-between',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: 50,
    paddingHorizontal: 20,
    paddingBottom: 16,
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  backBtn: {
    padding: 8,
  },
  title: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
    flex: 1,
    marginLeft: 10,
  },
  recordingDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#ef4444',
  },
  messagesScrollView: {
    maxHeight: '40%',
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  messagesContent: {
    padding: 24,
    paddingBottom: 40,
  },
  messageBox: {
    marginBottom: 16,
  },
  messageLabel: {
    color: '#38bdf8', // Light blue for visibility
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 6,
    textShadowColor: 'rgba(0,0,0,0.8)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 2,
  },
  messageText: {
    color: '#fff',
    fontSize: 22,
    lineHeight: 32,
    fontWeight: '500',
    textShadowColor: 'rgba(0,0,0,0.85)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 4,
  },
});
