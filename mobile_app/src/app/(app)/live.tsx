import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Audio } from 'expo-av';
import { useEffect, useRef, useState, useCallback } from 'react';
import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { RTCPeerConnection, RTCSessionDescription, mediaDevices } from 'react-native-webrtc';
import { supabase } from '../../utils/supabaseClient';
import { WaveAnimation, WaveType } from '../../components/WaveAnimation';

export default function LiveChatScreen() {
  const router = useRouter();
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const [audioPermissionResponse, requestAudioPermission] = Audio.usePermissions();

  const cameraRef = useRef<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollViewRef = useRef<ScrollView>(null);

  const [messages, setMessages] = useState<any[]>([]);
  const activeSessionIdRef = useRef(Date.now().toString());

  // Animation states
  const [fillerText, setFillerText] = useState("");
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const assistantSpeakingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const userSpeakingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // WebRTC refs
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<any>(null);
  const audioLevelIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const isPlayingRef = useRef(false);

  // VAD logic
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isSpeakingState = useRef(false);
  const VOLUME_THRESHOLD = -25;
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
            } catch (e) { }
          }, 2000);

          // Start streaming audio via WebRTC
          startWebRTC(ws);
        };

        ws.onmessage = (event) => {
          const data = JSON.parse(event.data);
          if (data.type === "filler_word") {
            setFillerText(data.payload);
          } else if (data.type === "webrtc_answer") {
            pcRef.current?.setRemoteDescription(new RTCSessionDescription(data.payload));
          } else if (data.type === "assistant_response") {
            setFillerText(""); // Clear filler text
            setMessages(prev => [...prev.slice(-2), { role: 'bot', text: data.payload }]);
            setIsAssistantSpeaking(true);
            if (assistantSpeakingTimeoutRef.current) clearTimeout(assistantSpeakingTimeoutRef.current);
            assistantSpeakingTimeoutRef.current = setTimeout(() => setIsAssistantSpeaking(false), 3000);
          } else if (data.type === "transcript") {
            setMessages(prev => [...prev.slice(-2), { role: 'user', text: data.payload }]);
          } else if (data.type === "user_speaking_start") {
            setFillerText(""); // Clear filler text on user barge-in
            setUserSpeaking(true);
          } else if (data.type === "user_speaking_end") {
            setUserSpeaking(false);
          }
        };
      };

      connectWs();

      return () => {
        mounted = false;
        if (frameInterval) clearInterval(frameInterval);
        if (assistantSpeakingTimeoutRef.current) clearTimeout(assistantSpeakingTimeoutRef.current);
        if (userSpeakingTimeoutRef.current) clearTimeout(userSpeakingTimeoutRef.current);
        stopWebRTC();
      };
    }, [])
  );

  const startWebRTC = async (ws: WebSocket) => {
    try {
      const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
      pcRef.current = pc;

      const stream = await mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      localStreamRef.current = stream;

      stream.getTracks().forEach((track: any) => pc.addTrack(track, stream));

      const offer = await pc.createOffer({});
      await pc.setLocalDescription(offer);

      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === 'complete') {
          resolve();
        } else {
          const timeout = setTimeout(() => resolve(), 2000);
          pc.onicegatheringstatechange = () => {
            if (pc.iceGatheringState === 'complete') {
              clearTimeout(timeout);
              resolve();
            }
          };
        }
      });

      ws.send(JSON.stringify({ type: "webrtc_offer", payload: pc.localDescription }));

    } catch (err) {
      console.error('Failed to start WebRTC', err);
    }
  };

  const stopWebRTC = () => {
    isSpeakingState.current = false;
    if (audioLevelIntervalRef.current) clearInterval(audioLevelIntervalRef.current);
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t: any) => t.stop());
      localStreamRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    isPlayingRef.current = false;
    setIsAssistantSpeaking(false);
  };

  const handleMetering = (db: number, ws: WebSocket) => {
    const currentThreshold = isPlayingRef.current ? -15 : VOLUME_THRESHOLD;

    if (db > currentThreshold) {
      setUserSpeaking(true);
      if (userSpeakingTimeoutRef.current) clearTimeout(userSpeakingTimeoutRef.current);
      userSpeakingTimeoutRef.current = setTimeout(() => setUserSpeaking(false), 1000);

      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }
      if (!isSpeakingState.current) {
        isSpeakingState.current = true;
        ws.send(JSON.stringify({ type: "interrupt" }));
      }
    } else {
      if (isSpeakingState.current && !silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          isSpeakingState.current = false;
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "speech_ended" }));
          }
        }, SILENCE_MS_TO_STOP);
      }
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
      <CameraView style={styles.camera} facing="back" ref={cameraRef} />
      <View style={[styles.overlay, StyleSheet.absoluteFillObject]}>
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
          {fillerText ? (
            <View style={styles.messageBox}>
              <Text style={styles.messageLabel}>AI</Text>
              <Text style={[styles.messageText, { fontStyle: 'italic', opacity: 0.7 }]}>{fillerText}</Text>
            </View>
          ) : null}
        </ScrollView>
      </View>
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
